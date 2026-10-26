"""
中国股市股票数据获取工具 - 修正版
使用可靠的数据源（新浪接口 stock_zh_a_daily 替代失效的东方财富接口）

作者: AI Assistant
日期: 2025-02-03
修正日期: 2025-02-03 (修正数据源问题)

问题说明:
- 东方财富接口 (stock_zh_a_hist, stock_zh_a_spot_em) 连接失败
- 解决方案: 使用新浪接口 (ak.stock_zh_a_daily, 新浪财经源) 作为主要数据源
  (订正: 旧文档误称"腾讯接口"; 腾讯 qt.gtimg.cn 仅用于实时行情 get_realtime_quote)

主要功能:
1. 获取股票历史行情（使用新浪接口; 实时行情另行使用腾讯 qt.gtimg.cn）
2. 获取财务指标
3. 批量获取数据
4. 数据自动存储到本地
5. 计算技术指标
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import time
from pathlib import Path

# requests 用于腾讯实时行情 (get_realtime_quote) — 守卫: 缺失时该功能
# 不可用, 其余功能 (历史行情/财务/指标) 不受影响
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None
    REQUESTS_AVAILABLE = False

from core.fetch_result import FetchResult
from core.indicator_engine import IndicatorEngine
from sina_daily import fetch_daily, format_symbol


class StockDataFetcher:
    """股票数据获取器 - 使用可靠数据源"""

    def __init__(self, data_dir="./stock_data"):
        """
        初始化数据获取器

        Args:
            data_dir: 数据存储目录
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 创建子目录
        (self.data_dir / "quotes").mkdir(exist_ok=True)
        (self.data_dir / "financial").mkdir(exist_ok=True)
        (self.data_dir / "reports").mkdir(exist_ok=True)
        (self.data_dir / "market").mkdir(exist_ok=True)

        print(f"[OK] 数据将保存到: {self.data_dir.absolute()}")

        # 最近一次 get_quote_data 的结构化结果 (审计项 11 FetchResult)
        self.last_fetch_result = None

    def _format_symbol(self, symbol):
        """
        格式化股票代码为 sh/sz/bj 前缀格式 (新浪财经接口要求)

        规则的单一真相源是 `sina_daily.format_symbol` (审计 M18): 旧实现缺
        bj 分支, 4/8/92 开头的北交所裸码原样发给新浪 → 404 且异常被吞。

        Args:
            symbol: 股票代码 (如 "600036" 或 "000001")

        Returns:
            带前缀的代码 (如 "sh600036" / "sz000001" / "bj920002")
        """
        return format_symbol(symbol)

    def _dedupe_quote_cache(self, symbol, adjust="", keep=None):
        """quotes/ 快照按 (股票, 复权口径) 去重 — 同口径只留最新 (审计 M16)

        旧实现文件名 `{symbol}_{起}_{止}.csv` 与日期区间绑定: 同一股票每次
        取数 (尤其重叠区间) 都新增一个文件, 目录无上限膨胀且内容大量重叠。
        去重后每个 (symbol, 口径) 至多 1 个文件; raw 文件名保持旧格式
        (无标签), qfq/hfq 带口径标签 —— MRC `_load_from_local_cache` 的
        `{index_code}_*.csv` glob 对两种命名都仍然命中。

        keep: 刚写入的新快照文件名 (先写后删, 写失败时旧快照仍在)。
        """
        tag = adjust if adjust in ("qfq", "hfq") else ""
        quotes_dir = self.data_dir / "quotes"
        for path in quotes_dir.glob(f"{symbol}_*.csv"):
            if keep is not None and path.name == keep:
                continue
            # rest = "{tag_}YYYYMMDD_YYYYMMDD.csv" (tag 仅 qfq/hfq)
            rest = path.name[len(str(symbol)) + 1:]
            head = rest.split("_", 1)[0]
            file_tag = "" if head.isdigit() else head
            if file_tag == tag:
                try:
                    path.unlink()
                except OSError as e:
                    print(f"[WARN] 旧快照删除失败 {path.name}: {e}")

    def get_stock_list(self, market="A股") -> pd.DataFrame:
        """
        获取股票列表

        Args:
            market: 市场类型 (A股/沪深/京市/深市)

        Returns:
            股票列表 DataFrame
        """
        print(f"[INFO] 正在获取{market}股票列表...")

        try:
            if market == "A股":
                df = ak.stock_info_a_code_name()
            elif market == "沪深":
                df = ak.stock_info_sh_name_code()
            else:
                df = ak.stock_info_a_code_name()

            if df is not None and len(df) > 0:
                # 保存到本地
                df.to_csv(self.data_dir / "stock_list.csv", index=False, encoding='utf-8-sig')
                print(f"[OK] 获取到 {len(df)} 只股票")
                return df
        except Exception as e:
            print(f"[ERROR] 获取股票列表失败: {str(e)[:100]}")

        return pd.DataFrame()

    def get_quote_data(self, symbol, start_date=None, end_date=None, days=252,
                       adjust=""):
        """
        获取历史行情数据 - 使用新浪接口 (ak.stock_zh_a_daily)

        Args:
            symbol: 股票代码 (例如: "000001" 或 "600036")
            start_date: 开始日期 (格式: "20200101" 或 datetime对象)
            end_date: 结束日期 (格式: "20231231" 或 datetime对象)，默认为今天
            days: 获取天数，默认252个交易日（约1年）
            adjust: 复权口径 — ''=不复权 (默认, 与落库主口径一致) / 'qfq' /
                'hfq'。**复权是数据维度**: 不同口径的序列混用会在除权日产生
                虚假跳空, 收益率与全部指标随之失真 (审计 P0-4)。

        Returns:
            行情数据 DataFrame
        """
        print(f"[INFO] 获取 {symbol} 行情数据...")

        # 格式化股票代码
        sina_symbol = self._format_symbol(symbol)

        # 计算日期范围
        if end_date is None:
            end_date = datetime.now()
        elif isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y%m%d")

        if start_date is None:
            start_date = end_date - timedelta(days=days * 2)  # 多申请一些，过滤非交易日
        elif isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y%m%d")

        try:
            # 新浪接口 (sh/sz 透传 ak.stock_zh_a_daily; bj 走 klc 直连,
            # akshare 对 bj 在 amount 步骤崩溃 — 审计 M18, 见 sina_daily)
            df = fetch_daily(
                symbol=sina_symbol,
                start_date=start_date.date(),
                end_date=end_date.date(),
                adjust=adjust
            )

            if df is not None and len(df) > 0:
                # 标准化列名（新浪接口返回英文列名）
                column_mapping = {
                    'date': '日期',
                    'open': '开盘',
                    'high': '最高',
                    'low': '最低',
                    'close': '收盘',
                    'volume': '成交量',
                    'amount': '成交额'
                }
                df = df.rename(columns=column_mapping)

                # 确保日期是datetime类型
                if '日期' in df.columns:
                    df['日期'] = pd.to_datetime(df['日期'])

                # 按日期排序
                df = df.sort_values('日期').reset_index(drop=True)

                # 计算涨跌幅
                if '涨跌幅' not in df.columns:
                    df['涨跌幅'] = df['收盘'].pct_change() * 100

                # 保存到本地 (同 (股票, 口径) 只留最新快照 — 审计 M16)
                # 复权口径进文件名 (raw 保持旧名兼容; 审计 P0-4 同构)
                tag_part = f"_{adjust}" if adjust in ("qfq", "hfq") else ""
                filename = (f"{symbol}{tag_part}_"
                            f"{start_date.strftime('%Y%m%d')}_"
                            f"{end_date.strftime('%Y%m%d')}.csv")
                filepath = self.data_dir / "quotes" / filename
                df.to_csv(filepath, index=False, encoding='utf-8-sig')
                # 先写后删: 写失败时旧快照仍完好
                self._dedupe_quote_cache(symbol, adjust, keep=filename)

                print(f"[OK] 获取到 {len(df)} 条记录")
                self.last_fetch_result = FetchResult.success(
                    df, source=f"stock_zh_a_daily:{symbol}:{adjust or 'raw'}",
                    adjust=adjust)
                return df
            else:
                print(f"[WARN] {symbol} 没有数据")
                self.last_fetch_result = FetchResult.failure(
                    f"{symbol} 无数据",
                    source=f"stock_zh_a_daily:{symbol}:{adjust or 'raw'}",
                    adjust=adjust)
                return pd.DataFrame()

        except Exception as e:
            print(f"[ERROR] 获取 {symbol} 数据失败: {str(e)[:100]}")
            self.last_fetch_result = FetchResult.failure(
                str(e)[:200],
                source=f"stock_zh_a_daily:{symbol}:{adjust or 'raw'}",
                adjust=adjust)
            return pd.DataFrame()

    def get_quote_result(self, symbol, start_date=None, end_date=None, days=252,
                         adjust=""):
        """
        获取历史行情并返回结构化 FetchResult (审计项 11)

        与 get_quote_data 的区别: 失败不再只体现为空 DataFrame，
        调用方应检查 result.ok / result.error。

        Args:
            adjust: 复权口径 (''/qfq/hfq) — 随结果记录在 FetchResult.adjust,
                调用方据此判断序列口径 (审计 P0-4: adjust 是数据维度)

        Returns:
            core.fetch_result.FetchResult
        """
        df = self.get_quote_data(symbol, start_date=start_date,
                                 end_date=end_date, days=days, adjust=adjust)
        if self.last_fetch_result is not None:
            return self.last_fetch_result
        if df is not None and len(df) > 0:
            return FetchResult.success(
                df, source=f"stock_zh_a_daily:{symbol}:{adjust or 'raw'}",
                adjust=adjust)
        return FetchResult.failure(
            f"{symbol} 获取失败(未知原因)",
            source=f"stock_zh_a_daily:{symbol}:{adjust or 'raw'}", adjust=adjust)

    def get_quote_data_fallback(self, symbol, start_date, end_date, period="daily", adjust=""):
        """
        获取历史行情数据 - 备用方法（尝试东方财富接口）

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: 周期
            adjust: 复权方式 — 默认 ""(不复权), 与主路径 stock_zh_a_daily 对齐
                    (审计R4: 旧默认 "qfq" 与主路径混用会产生除权跳空)

        Returns:
            行情数据 DataFrame
        """
        print(f"[INFO] 尝试备用数据源获取 {symbol}...")

        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )

            if df is not None and len(df) > 0:
                # 单位对齐 (审计R4): stock_zh_a_hist 成交量单位=手,
                # 主路径 stock_zh_a_daily 单位=股 → 统一换算为股
                if '成交量' in df.columns:
                    df['成交量'] = df['成交量'] * 100
                print(f"[OK] 备用源获取到 {len(df)} 条记录")
                return df
        except Exception as e:
            print(f"[WARN] 备用数据源也失败: {str(e)[:50]}")

        return pd.DataFrame()

    def get_financial_indicator(self, symbol, indicator="按年度"):
        """
        获取财务指标

        Args:
            symbol: 股票代码
            indicator: 统计频率 (按年度/按季度)

        Returns:
            财务指标 DataFrame
        """
        print(f"[INFO] 获取 {symbol} 财务指标...")

        try:
            df = ak.stock_financial_analysis_indicator(symbol=symbol, indicator=indicator)

            if df is not None and len(df) > 0:
                # 保存到本地
                filename = f"{symbol}_financial_indicator_{indicator}.csv"
                filepath = self.data_dir / "financial" / filename
                df.to_csv(filepath, index=False, encoding='utf-8-sig')
                print(f"[OK] 获取到 {len(df)} 条记录")
                return df
            else:
                print(f"[WARN] {symbol} 没有财务指标数据")
                return pd.DataFrame()

        except Exception as e:
            print(f"[ERROR] 获取财务指标失败: {str(e)[:100]}")
            return pd.DataFrame()

    def get_stock_money_flow(self, symbol, market="sz"):
        """
        获取个股资金流向

        Args:
            symbol: 股票代码
            market: 市场 (sh/sz)

        Returns:
            资金流向数据
        """
        print(f"[INFO] 获取 {symbol} 资金流向...")

        try:
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)

            if df is not None and len(df) > 0:
                filename = f"{symbol}_money_flow.csv"
                filepath = self.data_dir / "market" / filename
                df.to_csv(filepath, index=False, encoding='utf-8-sig')
                return df
        except Exception as e:
            print(f"[ERROR] 获取资金流向失败: {str(e)[:100]}")
            return pd.DataFrame()

    def get_realtime_quote(self, symbol):
        """
        获取实时行情 - 使用腾讯API

        Args:
            symbol: 股票代码

        Returns:
            实时行情数据字典 (requests 缺失时返回 None)
        """
        if not REQUESTS_AVAILABLE:
            print("[ERROR] requests 未安装 — 实时行情不可用 "
                  "(pip install requests)")
            return None

        print(f"[INFO] 获取 {symbol} 实时行情...")

        # 格式化股票代码
        if symbol.startswith('6'):
            symbol_prefix = f'sh{symbol}'
        else:
            symbol_prefix = f'sz{symbol}'

        url = f'http://qt.gtimg.cn/q={symbol_prefix}'

        try:
            response = requests.get(url, timeout=10)
            response.encoding = 'gbk'

            if response.status_code == 200 and '~' in response.text:
                data = response.text.strip()
                # 解析腾讯返回的实时数据
                if '~' in data:
                    parts = data.split('~')
                    if len(parts) > 40:
                        # 腾讯字段表: 30=时间(YYYYMMDDHHMMSS), 33/34=高/低,
                        # 36=成交量(手), 37=成交额(万元) — 统一到"元" (审计R10)
                        dt_str = parts[30]
                        result = {
                            '代码': symbol,
                            '名称': parts[1],
                            '当前价': float(parts[3]) if parts[3] else 0,
                            '昨收': float(parts[4]) if parts[4] else 0,
                            '开盘': float(parts[5]) if parts[5] else 0,
                            '最高': float(parts[33]) if parts[33] else 0,
                            '最低': float(parts[34]) if parts[34] else 0,
                            '成交量': int(parts[36]) if parts[36] else 0,
                            '成交额': (float(parts[37]) * 10000) if parts[37] else 0,
                            '日期': dt_str[:8] if len(dt_str) >= 8 else dt_str,
                            '时间': dt_str[8:14] if len(dt_str) >= 14 else dt_str,
                            '涨跌': float(parts[3]) - float(parts[4]) if parts[3] and parts[4] else 0,
                            '涨跌幅': ((float(parts[3]) / float(parts[4]) - 1) * 100) if parts[3] and parts[4] else 0
                        }
                        print(f"[OK] {symbol} 实时价: {result['当前价']:.2f}")
                        return result

        except Exception as e:
            print(f"[WARN] 获取实时行情失败: {str(e)[:50]}")

        return {}

    def get_realtime_quotes_batch(self, symbols, delay=0.15):
        """
        批量获取多只股票的实时行情

        Args:
            symbols: 股票代码列表
            delay: 请求间隔（秒）

        Returns:
            所有股票实时行情的字典
        """
        print(f"[INFO] 批量获取 {len(symbols)} 只股票的实时行情...")

        all_data = {}
        for symbol in symbols:
            data = self.get_realtime_quote(symbol)
            if data:
                all_data[symbol] = data

            if symbol != symbols[-1]:  # 不是最后一个
                time.sleep(delay)

        return all_data

    def batch_get_quotes(self, symbols, start_date=None, end_date=None, delay=0.5):
        """
        批量获取多只股票的行情数据

        Args:
            symbols: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            delay: 请求间隔（秒），避免频繁请求

        Returns:
            所有股票数据的字典
        """
        print(f"[INFO] 批量获取 {len(symbols)} 只股票的数据...")

        all_data = {}
        success_count = 0

        for i, symbol in enumerate(symbols, 1):
            print(f"[{i}/{len(symbols)}] 处理 {symbol}...", end=' ')

            data = self.get_quote_data(symbol, start_date, end_date)

            if not data.empty:
                all_data[symbol] = data
                success_count += 1
            else:
                print("FAILED")

            # 延迟避免请求过快
            if i < len(symbols):
                time.sleep(delay)

        print(f"\n[OK] 批量获取完成！成功: {success_count}/{len(symbols)}")
        return all_data

    def get_stock_fundamental(self, symbol):
        """
        获取股票基本面数据（综合）

        Args:
            symbol: 股票代码

        Returns:
            包含多种基本面数据的字典
        """
        print(f"[INFO] 获取 {symbol} 综合基本面数据...")

        fundamental = {
            "financial_indicator": self.get_financial_indicator(symbol),
            "money_flow": self.get_stock_money_flow(symbol),
        }

        return fundamental

    def calculate_technical_indicators(self, df):
        """
        计算常用技术指标

        Args:
            df: 包含OHLCV数据的DataFrame

        Returns:
            添加技术指标的DataFrame
        """
        if df.empty or '收盘' not in df.columns:
            return df

        # 共享指标引擎 (审计 #10)
        eng = IndicatorEngine(df)
        close = df['收盘']

        # 移动平均线
        df['MA5'] = eng.ma(5)
        df['MA10'] = eng.ma(10)
        df['MA20'] = eng.ma(20)
        df['MA60'] = eng.ma(60)

        # EMA
        df['EMA20'] = eng.ema(20)
        df['EMA50'] = eng.ema(50)

        # MACD
        dif, dea, hist = eng.macd()
        df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = dif, dea, hist

        # RSI (core 单一真相源)
        df['RSI'] = eng.rsi(14)

        # KDJ
        k, d, j = eng.kdj()
        df['K'], df['D'], df['J'] = k, d, j

        # Bollinger Bands
        upper, middle, lower, std = eng.bollinger(20, 2.0)
        df['BB_Middle'], df['BB_Std'] = middle, std
        df['BB_Upper'], df['BB_Lower'] = upper, lower

        # ATR (core Wilder 单一真相源, 旧: SMA14)
        df['TR'] = eng.true_range()
        df['ATR'] = eng.atr(14)

        # 成交量移动平均
        df['VOL_MA5'] = eng.volume_ma(5)

        # 涨跌幅（如果还没有）
        if '涨跌幅' not in df.columns:
            df['涨跌幅'] = close.pct_change() * 100

        return df

    def export_to_excel(self, symbol, start_date, end_date):
        """
        导出综合数据到Excel（便于分析）

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        """
        print(f"[INFO] 正在导出 {symbol} 的综合数据到Excel...")

        try:
            filepath = self.data_dir / f"{symbol}_综合分析_{start_date}_{end_date}.xlsx"

            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                # 行情数据
                quote = self.get_quote_data(symbol, start_date, end_date)
                if not quote.empty:
                    quote = self.calculate_technical_indicators(quote)
                    quote.to_excel(writer, sheet_name='行情数据', index=False)

                # 财务指标
                financial = self.get_financial_indicator(symbol)
                if not financial.empty:
                    financial.to_excel(writer, sheet_name='财务指标', index=False)

            print(f"[OK] Excel文件已保存: {filepath}")
        except Exception as e:
            print(f"[ERROR] 导出Excel失败: {str(e)[:100]}")


# ==================== 便捷函数 ====================

def quick_fetch(stock_code, start_date=None, end_date=None, days=252):
    """
    快速获取单只股票数据

    示例:
        quick_fetch("000001", days=180)
        quick_fetch("600519", "20230101", "20231231")
    """
    fetcher = StockDataFetcher()
    data = fetcher.get_quote_data(stock_code, start_date, end_date, days)
    return data


def batch_fetch(stock_list, start_date=None, end_date=None, delay=0.5):
    """
    批量获取多只股票数据

    示例:
        stocks = ["000001", "000002", "600000"]
        batch_fetch(stocks, days=180)
    """
    fetcher = StockDataFetcher()
    data = fetcher.batch_get_quotes(stock_list, start_date, end_date, delay)
    return data


def get_stock_overview(stock_code, start_date, end_date):
    """
    获取股票综合分析报告

    示例:
        get_stock_overview("000001", "20230101", "20231231")
    """
    fetcher = StockDataFetcher()
    fetcher.export_to_excel(stock_code, start_date, end_date)


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 创建数据获取器
    fetcher = StockDataFetcher(data_dir="./stock_data")

    # 示例1: 获取单只股票行情（使用新浪接口）
    print("\n" + "="*50)
    print("示例1: 获取平安银行(000001)历史行情 - 新浪接口")
    print("="*50)
    quote_data = fetcher.get_quote_data(
        symbol="000001",
        days=180
    )
    if not quote_data.empty:
        print(quote_data.head())
        print(f"\n数据列: {quote_data.columns.tolist()}")
        print(f"数据范围: {quote_data['日期'].min()} ~ {quote_data['日期'].max()}")

    # 示例2: 获取多只股票
    print("\n" + "="*50)
    print("示例2: 批量获取多只股票")
    print("="*50)
    stocks = ["000001", "600519", "000858"]  # 平安银行、贵州茅台、五粮液
    batch_data = fetcher.batch_get_quotes(
        symbols=stocks,
        days=180,
        delay=0.5
    )

    # 示例3: 计算技术指标
    print("\n" + "="*50)
    print("示例3: 计算技术指标")
    print("="*50)
    if not quote_data.empty:
        quote_with_indicators = fetcher.calculate_technical_indicators(quote_data)
        print(quote_with_indicators[['日期', '收盘', 'MA5', 'MA20', 'MACD', 'RSI']].tail(10))

    # 示例4: 获取实时行情
    print("\n" + "="*50)
    print("示例4: 获取实时行情")
    print("="*50)
    realtime = fetcher.get_realtime_quote("000001")
    if realtime:
        print(f"最新价: {realtime.get('收盘', 'N/A')}")
        print(f"涨跌幅: {realtime.get('涨跌幅', 'N/A')}%")

    print("\n" + "="*50)
    print("[OK] 所有示例运行完成!")
    print("="*50)
