"""
中国股市股票数据获取工具 - 修正版
使用可靠的数据源（腾讯接口替代失效的东方财富接口）

作者: AI Assistant
日期: 2025-02-03
修正日期: 2025-02-03 (修正数据源问题)

问题说明:
- 东方财富接口 (stock_zh_a_hist, stock_zh_a_spot_em) 连接失败
- 解决方案: 使用腾讯接口 (stock_zh_a_daily) 作为主要数据源

主要功能:
1. 获取股票历史行情（使用腾讯接口）
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

    def _format_symbol(self, symbol):
        """
        格式化股票代码为腾讯接口格式

        Args:
            symbol: 股票代码 (如 "600036" 或 "000001")

        Returns:
            腾讯接口格式的代码 (如 "sh600036" 或 "sz000001")
        """
        if len(symbol) == 6:
            if symbol.startswith('6'):
                return f'sh{symbol}'
            elif symbol.startswith('0') or symbol.startswith('3'):
                return f'sz{symbol}'
            else:
                return symbol
        return symbol

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

    def get_quote_data(self, symbol, start_date=None, end_date=None, days=252):
        """
        获取历史行情数据 - 使用腾讯接口

        Args:
            symbol: 股票代码 (例如: "000001" 或 "600036")
            start_date: 开始日期 (格式: "20200101" 或 datetime对象)
            end_date: 结束日期 (格式: "20231231" 或 datetime对象)，默认为今天
            days: 获取天数，默认252个交易日（约1年）

        Returns:
            行情数据 DataFrame
        """
        print(f"[INFO] 获取 {symbol} 行情数据...")

        # 格式化股票代码
        tencent_symbol = self._format_symbol(symbol)

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
            # 使用腾讯接口
            df = ak.stock_zh_a_daily(
                symbol=tencent_symbol,
                start_date=start_date.date(),
                end_date=end_date.date()
            )

            if df is not None and len(df) > 0:
                # 标准化列名（腾讯接口返回英文列名）
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

                # 保存到本地
                filename = f"{symbol}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
                filepath = self.data_dir / "quotes" / filename
                df.to_csv(filepath, index=False, encoding='utf-8-sig')

                print(f"[OK] 获取到 {len(df)} 条记录")
                return df
            else:
                print(f"[WARN] {symbol} 没有数据")
                return pd.DataFrame()

        except Exception as e:
            print(f"[ERROR] 获取 {symbol} 数据失败: {str(e)[:100]}")
            return pd.DataFrame()

    def get_quote_data_fallback(self, symbol, start_date, end_date, period="daily", adjust="qfq"):
        """
        获取历史行情数据 - 备用方法（尝试东方财富接口）

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: 周期
            adjust: 复权方式

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

    def get_cash_flow(self, symbol, indicator="按年度"):
        """获取现金流量表"""
        print(f"[INFO] 获取 {symbol} 现金流量表...")

        try:
            df = ak.stock_financial_analysis_indicator(symbol=symbol, indicator=indicator)

            if df is not None and len(df) > 0:
                filename = f"{symbol}_cash_flow_{indicator}.csv"
                filepath = self.data_dir / "reports" / filename
                df.to_csv(filepath, index=False, encoding='utf-8-sig')
                return df
        except Exception as e:
            print(f"[ERROR] 获取现金流量表失败: {str(e)[:100]}")
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
        获取实时行情 - 使用腾讯接口

        Args:
            symbol: 股票代码

        Returns:
            实时行情数据
        """
        print(f"[INFO] 获取 {symbol} 实时行情...")

        # 获取最近一天的数据作为实时行情
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)

        df = self.get_quote_data(symbol, start_date, end_date, days=5)

        if not df.empty and len(df) > 0:
            # 返回最新一天的数据
            return df.iloc[-1:].to_dict('records')[0]
        else:
            return {}

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

        close = df['收盘']
        high = df['最高']
        low = df['最低']

        # 移动平均线
        df['MA5'] = close.rolling(window=5).mean()
        df['MA10'] = close.rolling(window=10).mean()
        df['MA20'] = close.rolling(window=20).mean()
        df['MA60'] = close.rolling(window=60).mean()

        # EMA
        df['EMA20'] = close.ewm(span=20, adjust=False).mean()
        df['EMA50'] = close.ewm(span=50, adjust=False).mean()

        # MACD
        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema_fast - ema_slow
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # KDJ
        low_n = low.rolling(window=9).min()
        high_n = high.rolling(window=9).max()
        rsv = (close - low_n) / (high_n - low_n) * 100
        df['K'] = rsv.ewm(span=3, adjust=False).mean()
        df['D'] = df['K'].ewm(span=3, adjust=False).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']

        # Bollinger Bands
        df['BB_Middle'] = close.rolling(window=20).mean()
        df['BB_Std'] = close.rolling(window=20).std()
        df['BB_Upper'] = df['BB_Middle'] + 2 * df['BB_Std']
        df['BB_Lower'] = df['BB_Middle'] - 2 * df['BB_Std']

        # ATR
        df['TR'] = np.maximum(
            high - low,
            np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1)))
        )
        df['ATR'] = df['TR'].rolling(window=14).mean()

        # 成交量移动平均
        df['VOL_MA5'] = df['成交量'].rolling(window=5).mean()

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

    # 示例1: 获取单只股票行情（使用腾讯接口）
    print("\n" + "="*50)
    print("示例1: 获取平安银行(000001)历史行情 - 腾讯接口")
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
