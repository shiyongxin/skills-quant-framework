# -*- coding: utf-8 -*-
"""
持仓分析与操作策略 v2
直接使用akshare获取实时股价，不依赖项目的复杂模块
"""

import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')


class HoldingsAnalyzerV2:
    """持仓分析器 v2 - 简化版"""

    def __init__(self, holdings_file="持仓.csv"):
        """初始化分析器"""
        self.holdings_file = holdings_file
        self.holdings = self._load_holdings()

    def _load_holdings(self):
        """加载持仓数据"""
        try:
            df = pd.read_csv(self.holdings_file, encoding='utf-8')
            print(f"[OK] 成功加载 {len(df)} 只持仓股票")
            return df
        except Exception as e:
            print(f"[ERROR] 加载持仓数据失败: {e}")
            return pd.DataFrame()

    def get_stock_data(self, symbol):
        """
        获取股票历史数据
        使用akshare直接获取，更加可靠
        """
        try:
            # 确定市场
            if symbol.startswith('6'):
                market = 'sh'
            else:
                market = 'sz'

            # 计算日期范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=120)

            # 尝试多种方式获取数据
            try:
                # 方法1: 使用stock_zh_a_hist
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                    adjust="qfq"
                )
            except:
                try:
                    # 方法2: 使用stock_zh_a_daily
                    df = ak.stock_zh_a_daily(
                        symbol=f"{market}{symbol}",
                        start_date=start_date.date(),
                        end_date=end_date.date()
                    )
                except:
                    return None

            if df is None or len(df) < 20:
                return None

            # 标准化列名
            column_mapping = {
                '日期': '日期',
                '开盘': '开盘',
                '收盘': '收盘',
                '最高': '最高',
                '最低': '最低',
                '成交量': '成交量',
                '成交额': '成交额',
                '涨跌幅': '涨跌幅',
                '涨跌额': '涨跌额',
                '换手率': '换手率'
            }

            # 检查并重命名列
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns and new_col not in df.columns:
                    df = df.rename(columns={old_col: new_col})

            # 确保日期列格式正确
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期'])

            df = df.sort_values('日期').reset_index(drop=True)

            # 计算技术指标
            df = self._calculate_indicators(df)

            return df

        except Exception as e:
            print(f"    获取数据失败: {e}")
            return None

    def _calculate_indicators(self, df):
        """计算技术指标"""
        close = df['收盘']
        high = df['最高']
        low = df['最低']

        # 均线
        df['MA5'] = close.rolling(5).mean()
        df['MA10'] = close.rolling(10).mean()
        df['MA20'] = close.rolling(20).mean()
        df['MA60'] = close.rolling(60).mean()

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # KDJ
        low9 = low.rolling(9).min()
        high9 = high.rolling(9).max()
        rsv = (close - low9) / (high9 - low9) * 100
        df['K'] = rsv.ewm(span=3, adjust=False).mean()
        df['D'] = df['K'].ewm(span=3, adjust=False).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']

        # 布林带
        df['BB_Mid'] = close.rolling(20).mean()
        df['BB_Std'] = close.rolling(20).std()
        df['BB_Upper'] = df['BB_Mid'] + 2 * df['BB_Std']
        df['BB_Lower'] = df['BB_Mid'] - 2 * df['BB_Std']

        return df

    def analyze_stock(self, row):
        """分析单只股票"""
        symbol = str(row['股票代码']).zfill(6)  # 确保6位
        name = row['股票名称']
        quantity = row['持股数量']
        cost_price = row['成本价']

        print(f"\n{'─'*60}")
        print(f"分析 {name}({symbol})...")
        print(f"{'─'*60}")

        # 获取数据
        df = self.get_stock_data(symbol)
        if df is None:
            print(f"    [X] 无法获取数据")
            return None

        latest = df.iloc[-1]
        current_price = float(latest['收盘'])

        # 计算盈亏
        market_value = current_price * quantity
        cost_value = cost_price * quantity
        profit_loss = market_value - cost_value
        profit_loss_pct = (current_price / cost_price - 1) * 100

        # 技术分析
        ma_trend = self._analyze_ma(latest)
        macd_signal = self._analyze_macd(latest)
        rsi_signal = self._analyze_rsi(latest)
        kdj_signal = self._analyze_kdj(latest)
        bb_signal = self._analyze_bb(latest)

        # 计算信号强度
        signal_strength = self._calculate_signal_strength(latest)

        # 近期表现
        recent_5d = (current_price / df['收盘'].iloc[-6] - 1) * 100 if len(df) > 5 else 0
        recent_20d = (current_price / df['收盘'].iloc[-21] - 1) * 100 if len(df) > 20 else 0

        # 生成策略
        strategy = self._generate_strategy(
            profit_loss_pct, ma_trend, signal_strength, recent_20d
        )

        return {
            '股票代码': symbol,
            '股票名称': name,
            '持股数量': quantity,
            '成本价': cost_price,
            '最新价': current_price,
            '市值': market_value,
            '成本': cost_value,
            '盈亏': profit_loss,
            '盈亏比例': profit_loss_pct,
            'MA趋势': ma_trend,
            'MACD': macd_signal,
            'RSI': rsi_signal,
            'KDJ': kdj_signal,
            '布林带': bb_signal,
            '信号强度': signal_strength,
            '5日涨跌': recent_5d,
            '20日涨跌': recent_20d,
            '操作策略': strategy
        }

    def _analyze_ma(self, latest):
        """分析均线"""
        current = float(latest['收盘'])
        ma5 = float(latest['MA5']) if not pd.isna(latest['MA5']) else current
        ma10 = float(latest['MA10']) if not pd.isna(latest['MA10']) else current
        ma20 = float(latest['MA20']) if not pd.isna(latest['MA20']) else current

        if current > ma5 > ma10 > ma20:
            return "多头排列，强势"
        elif current > ma5 > ma20:
            return "上升趋势"
        elif current < ma5 < ma20:
            return "下降趋势"
        else:
            return "震荡整理"

    def _analyze_macd(self, latest):
        """分析MACD"""
        macd = float(latest['MACD']) if not pd.isna(latest['MACD']) else 0
        signal = float(latest['MACD_Signal']) if not pd.isna(latest['MACD_Signal']) else 0

        if macd > 0 and signal > 0:
            return "多头区域"
        elif macd < 0 and signal < 0:
            return "空头区域"
        elif macd > signal:
            return "即将金叉"
        else:
            return "即将死叉"

    def _analyze_rsi(self, latest):
        """分析RSI"""
        rsi = float(latest['RSI']) if not pd.isna(latest['RSI']) else 50

        if rsi > 70:
            return f"超买({rsi:.1f})"
        elif rsi < 30:
            return f"超卖({rsi:.1f})"
        elif rsi > 50:
            return f"强势({rsi:.1f})"
        else:
            return f"弱势({rsi:.1f})"

    def _analyze_kdj(self, latest):
        """分析KDJ"""
        k = float(latest['K']) if not pd.isna(latest['K']) else 50
        d = float(latest['D']) if not pd.isna(latest['D']) else 50

        if k > d and k < 80:
            return "金叉"
        elif k < d and k > 20:
            return "死叉"
        elif k > 80:
            return f"超买(k={k:.1f})"
        elif k < 20:
            return f"超卖(k={k:.1f})"
        else:
            return f"中性(k={k:.1f})"

    def _analyze_bb(self, latest):
        """分析布林带"""
        current = float(latest['收盘'])
        upper = float(latest['BB_Upper']) if not pd.isna(latest['BB_Upper']) else current
        lower = float(latest['BB_Lower']) if not pd.isna(latest['BB_Lower']) else current

        if current >= upper:
            return "突破上轨"
        elif current <= lower:
            return "触及下轨"
        else:
            return "中轨区域"

    def _calculate_signal_strength(self, latest):
        """计算综合信号强度"""
        score = 0

        # MA信号
        current = float(latest['收盘'])
        ma5 = float(latest['MA5']) if not pd.isna(latest['MA5']) else current
        ma20 = float(latest['MA20']) if not pd.isna(latest['MA20']) else current
        if current > ma5 > ma20:
            score += 2
        elif current < ma5 < ma20:
            score -= 2

        # MACD信号
        macd = float(latest['MACD']) if not pd.isna(latest['MACD']) else 0
        signal = float(latest['MACD_Signal']) if not pd.isna(latest['MACD_Signal']) else 0
        if macd > signal:
            score += 1
        else:
            score -= 1

        # RSI信号
        rsi = float(latest['RSI']) if not pd.isna(latest['RSI']) else 50
        if rsi < 30:
            score += 2
        elif rsi > 70:
            score -= 2

        # KDJ信号
        k = float(latest['K']) if not pd.isna(latest['K']) else 50
        d = float(latest['D']) if not pd.isna(latest['D']) else 50
        if k > d and k < 80:
            score += 1
        elif k < d and k > 20:
            score -= 1

        return score

    def _generate_strategy(self, profit_pct, ma_trend, signal_strength, recent_20d):
        """生成操作策略"""
        strategies = []

        # 1. 信号强度分析
        if signal_strength >= 4:
            strategies.append("【强烈买入信号】技术面强势，可加仓")
        elif signal_strength >= 2:
            strategies.append("【买入信号】技术面向好，可持有或小幅加仓")
        elif signal_strength <= -4:
            strategies.append("【强烈卖出信号】技术面疲弱，建议减仓")
        elif signal_strength <= -2:
            strategies.append("【卖出信号】技术面转弱，建议谨慎")

        # 2. 趋势分析
        if "多头" in ma_trend or "上升" in ma_trend:
            strategies.append("【趋势向上】均线多头排列，上涨趋势确立")
        elif "下降" in ma_trend:
            strategies.append("【趋势向下】均线空头排列，下跌趋势中")

        # 3. 近期表现
        if recent_20d > 10:
            strategies.append(f"【近期强势】20日涨幅{recent_20d:.1f}%，短期表现强劲")
        elif recent_20d < -10:
            strategies.append(f"【近期疲弱】20日跌幅{abs(recent_20d):.1f}%，短期表现疲弱")

        # 4. 盈亏结合策略
        if profit_pct > 10:
            strategies.append(f"【盈利较多】+{profit_pct:.1f}%，建议设置止盈位保护利润")
        elif profit_pct < -10:
            strategies.append(f"【亏损较多】{profit_pct:.1f}%，考虑止损或等待反弹")

        # 5. 综合建议
        if signal_strength >= 2 and profit_pct < 0:
            strategies.append("【综合建议】技术面好转但亏损，可考虑补仓降低成本")
        elif signal_strength <= -2 and profit_pct > 5:
            strategies.append("【综合建议】技术面转弱且有盈利，建议止盈离场")
        elif signal_strength >= 2 and profit_pct > 5:
            strategies.append("【综合建议】技术面强势且有盈利，继续持有待涨")
        elif signal_strength <= -2 and profit_pct < 0:
            strategies.append("【综合建议】技术面转弱且亏损，建议止损或等待")

        return strategies

    def run_analysis(self):
        """运行完整分析"""
        if self.holdings.empty:
            print("没有持仓数据")
            return

        print("="*80)
        print(" "*20 + "股票持仓分析报告")
        print("="*80)
        print(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"持仓数量: {len(self.holdings)} 只")

        results = []
        total_cost = 0
        total_value = 0

        for idx, row in self.holdings.iterrows():
            analysis = self.analyze_stock(row)
            if analysis:
                results.append(analysis)
                total_cost += analysis['成本']
                total_value += analysis['市值']

        # 打印详细报告
        for r in results:
            print(f"\n{'='*80}")
            print(f"  {r['股票名称']}({r['股票代码']})")
            print(f"{'='*80}")
            print(f"  持仓: {r['持股数量']}股 | 成本: {r['成本价']:.3f}元 | 最新: {r['最新价']:.3f}元")
            print(f"  市值: {r['市值']:.2f}元 | 盈亏: {r['盈亏']:+.2f}元 ({r['盈亏比例']:+.2f}%)")
            print(f"  {'─'*80}")
            print(f"  技术指标:")
            print(f"    MA趋势: {r['MA趋势']}")
            print(f"    MACD:   {r['MACD']}")
            print(f"    RSI:    {r['RSI']}")
            print(f"    KDJ:    {r['KDJ']}")
            print(f"    布林带: {r['布林带']}")
            print(f"    信号强度: {r['信号强度']:+d}")
            print(f"  {'─'*80}")
            print(f"  近期表现:")
            print(f"    5日涨跌: {r['5日涨跌']:+.2f}%")
            print(f"    20日涨跌: {r['20日涨跌']:+.2f}%")
            print(f"  {'─'*80}")
            print(f"  操作策略:")
            for s in r['操作策略']:
                print(f"    {s}")

        # 总体概况
        total_profit = total_value - total_cost
        total_profit_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

        print(f"\n{'='*80}")
        print(" "*25 + "总体概况")
        print(f"{'='*80}")
        print(f"  总成本: {total_cost:.2f}元")
        print(f"  总市值: {total_value:.2f}元")
        print(f"  总盈亏: {total_profit:+.2f}元 ({total_profit_pct:+.2f}%)")
        print(f"{'='*80}\n")

        # 保存结果
        self._save_results(results, total_cost, total_value, total_profit, total_profit_pct)

        return results

    def _save_results(self, results, total_cost, total_value, total_profit, total_profit_pct):
        """保存分析结果"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 保存CSV
        df = pd.DataFrame(results)
        csv_file = f"持仓分析结果_{timestamp}.csv"
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"[OK] CSV结果已保存: {csv_file}")

        # 保存文本报告
        report_file = f"持仓分析报告_{timestamp}.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write(" "*25 + "股票持仓分析报告\n")
            f.write("="*80 + "\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"持仓数量: {len(results)} 只\n\n")

            for r in results:
                f.write(f"\n{'='*80}\n")
                f.write(f"  {r['股票名称']}({r['股票代码']})\n")
                f.write(f"{'='*80}\n")
                f.write(f"  持仓: {r['持股数量']}股 | 成本: {r['成本价']:.3f}元 | 最新: {r['最新价']:.3f}元\n")
                f.write(f"  市值: {r['市值']:.2f}元 | 盈亏: {r['盈亏']:+.2f}元 ({r['盈亏比例']:+.2f}%)\n")
                f.write(f"  {'─'*80}\n")
                f.write(f"  技术指标:\n")
                f.write(f"    MA趋势: {r['MA趋势']}\n")
                f.write(f"    MACD:   {r['MACD']}\n")
                f.write(f"    RSI:    {r['RSI']}\n")
                f.write(f"    KDJ:    {r['KDJ']}\n")
                f.write(f"    布林带: {r['布林带']}\n")
                f.write(f"    信号强度: {r['信号强度']:+d}\n")
                f.write(f"  {'─'*80}\n")
                f.write(f"  近期表现:\n")
                f.write(f"    5日涨跌: {r['5日涨跌']:+.2f}%\n")
                f.write(f"    20日涨跌: {r['20日涨跌']:+.2f}%\n")
                f.write(f"  {'─'*80}\n")
                f.write(f"  操作策略:\n")
                for s in r['操作策略']:
                    f.write(f"    {s}\n")

            f.write(f"\n{'='*80}\n")
            f.write(" "*25 + "总体概况\n")
            f.write(f"{'='*80}\n")
            f.write(f"  总成本: {total_cost:.2f}元\n")
            f.write(f"  总市值: {total_value:.2f}元\n")
            f.write(f"  总盈亏: {total_profit:+.2f}元 ({total_profit_pct:+.2f}%)\n")
            f.write(f"{'='*80}\n")

        print(f"[OK] 文本报告已保存: {report_file}")


if __name__ == "__main__":
    analyzer = HoldingsAnalyzerV2()
    analyzer.run_analysis()
