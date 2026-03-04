# -*- coding: utf-8 -*-
"""
转折点策略回测系统
Reversal Strategy Backtest System

验证"买在低点，卖在高点"策略的回测效果
"""

import sys
sys.path.append('.claude/skills')

import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')


@dataclass
class Trade:
    """交易记录"""
    type: str  # 'BUY' / 'SELL'
    date: datetime
    price: float
    shares: int
    reason: str


@dataclass
class BacktestResult:
    """回测结果"""
    code: str
    name: str

    # 交易统计
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float

    # 收益统计
    total_return: float  # 总收益率%
    buy_hold_return: float  # 买入持有收益率%
    excess_return: float  # 超额收益%

    # 交易记录
    trades: List[Trade]

    # 详细数据
    trade_details: List[Dict]


class ReversalBacktester:
    """转折点策略回测器"""

    def __init__(self, initial_capital: float = 100000):
        self.initial_capital = initial_capital

    def get_stock_data(self, code: str, days: int = 365) -> Optional[pd.DataFrame]:
        """获取股票历史数据"""
        try:
            if len(str(code)) == 6:
                full_code = f'sh{code}' if str(code).startswith('6') else f'sz{code}'
            else:
                full_code = code

            end_date = datetime.now()
            start_date = end_date - timedelta(days=days * 2)

            df = ak.stock_zh_a_daily(
                symbol=full_code,
                start_date=start_date.date(),
                end_date=end_date.date()
            )

            if df is None or len(df) < 100:
                return None

            column_mapping = {
                'date': '日期', 'open': '开盘', 'high': '最高',
                'low': '最低', 'close': '收盘', 'volume': '成交量'
            }
            df = df.rename(columns=column_mapping)
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.sort_values('日期').reset_index(drop=True)

            # 只取最近1年
            if len(df) > days:
                df = df.tail(days).reset_index(drop=True)

            return df

        except Exception as e:
            return None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        close = df['收盘']
        high = df['最高']
        low = df['最低']

        # RSI
        for period in [6, 14]:
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            rs = gain / loss
            df[f'RSI{period}'] = 100 - (100 / (1 + rs))

        # KDJ
        low_n = low.rolling(9).min()
        high_n = high.rolling(9).max()
        rsv = (close - low_n) / (high_n - low_n) * 100
        df['K'] = rsv.ewm(3).mean()
        df['D'] = df['K'].ewm(3).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']

        # 布林带
        df['BB_Middle'] = close.rolling(20).mean()
        df['BB_Std'] = close.rolling(20).std()
        df['BB_Upper'] = df['BB_Middle'] + 2 * df['BB_Std']
        df['BB_Lower'] = df['BB_Middle'] - 2 * df['BB_Std']

        # 均线
        df['MA5'] = close.rolling(5).mean()
        df['MA20'] = close.rolling(20).mean()

        # 成交量
        df['Vol_MA5'] = df['成交量'].rolling(5).mean()

        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成买卖信号"""
        df = df.copy()
        df['buy_signal'] = 0
        df['sell_signal'] = 0
        df['buy_reason'] = ''
        df['sell_reason'] = ''

        for i in range(30, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i-1]

            buy_score = 0
            buy_reasons = []
            sell_score = 0
            sell_reasons = []

            # === 买入信号 ===

            # 1. RSI超卖
            rsi14 = row['RSI14']
            if pd.notna(rsi14):
                if rsi14 < 25:
                    buy_score += 30
                    buy_reasons.append(f'RSI超卖({rsi14:.0f})')
                elif rsi14 < 30:
                    buy_score += 20
                    buy_reasons.append(f'RSI偏低({rsi14:.0f})')

            # 2. KDJ超卖
            j = row['J']
            if pd.notna(j) and j < 10:
                buy_score += 20
                buy_reasons.append(f'KDJ超卖(J={j:.0f})')

            # 3. 触及布林下轨
            if row['收盘'] <= row['BB_Lower'] * 1.02:
                buy_score += 15
                buy_reasons.append('触及下轨')

            # 4. 连续下跌后放量
            if i >= 3:
                down_days = sum(1 for j in range(i-2, i) if df['收盘'].iloc[j-1] < df['收盘'].iloc[j-1])
                if down_days >= 2 and row['成交量'] > row['Vol_MA5'] * 1.2:
                    buy_score += 15
                    buy_reasons.append('下跌后放量')

            # 4. 连续下跌后放量
            if i >= 3:
                down_days = sum(1 for j in range(1, 4) if df['收盘'].iloc[i-j] < df['收盘'].iloc[i-j-1])
                if down_days >= 2 and row['成交量'] > row['Vol_MA5'] * 1.2:
                    buy_score += 15
                    buy_reasons.append('下跌后放量')

            # 5. 底背离检测
            if i >= 20:
                recent = df.iloc[i-20:i+1].reset_index(drop=True)
                price_min_idx = recent['收盘'].idxmin()
                rsi_min_idx = recent['RSI14'].idxmin()
                if price_min_idx == len(recent) - 1 and rsi_min_idx < len(recent) - 5:
                    if pd.notna(recent['RSI14'].iloc[-1]) and pd.notna(recent['RSI14'].iloc[rsi_min_idx]):
                        if recent['RSI14'].iloc[-1] > recent['RSI14'].iloc[rsi_min_idx]:
                            buy_score += 25
                            buy_reasons.append('底背离')

            # === 卖出信号 ===

            # 1. RSI超买
            if pd.notna(rsi14):
                if rsi14 > 80:
                    sell_score += 30
                    sell_reasons.append(f'RSI超买({rsi14:.0f})')
                elif rsi14 > 75:
                    sell_score += 20
                    sell_reasons.append(f'RSI偏高({rsi14:.0f})')

            # 2. KDJ超买
            if pd.notna(j) and j > 100:
                sell_score += 20
                sell_reasons.append(f'KDJ超买(J={j:.0f})')

            # 3. 触及布林上轨
            if row['收盘'] >= row['BB_Upper'] * 0.98:
                sell_score += 15
                sell_reasons.append('触及上轨')

            # 4. 连续上涨后缩量
            if i >= 3:
                up_days = sum(1 for j in range(1, 4) if df['收盘'].iloc[i-j] > df['收盘'].iloc[i-j-1])
                if up_days >= 2 and row['成交量'] < row['Vol_MA5'] * 0.7:
                    sell_score += 15
                    sell_reasons.append('上涨后缩量')

            # 5. 顶背离检测
            if i >= 20:
                recent = df.iloc[i-20:i+1]
                price_max_idx = recent['收盘'].idxmax()
                rsi_max_idx = recent['RSI14'].idxmax()
                if price_max_idx == i and rsi_max_idx < i - 5:
                    if recent['RSI14'].iloc[-1] < recent['RSI14'].iloc[rsi_max_idx]:
                        sell_score += 25
                        sell_reasons.append('顶背离')

            # 设置信号
            if buy_score >= 40:
                df.loc[df.index[i], 'buy_signal'] = buy_score
                df.loc[df.index[i], 'buy_reason'] = ', '.join(buy_reasons[:2])

            if sell_score >= 40:
                df.loc[df.index[i], 'sell_signal'] = sell_score
                df.loc[df.index[i], 'sell_reason'] = ', '.join(sell_reasons[:2])

        return df

    def backtest_single(self, code: str, name: str = '') -> Optional[BacktestResult]:
        """回测单只股票"""
        df = self.get_stock_data(code, days=365)
        if df is None or len(df) < 60:
            return None

        df = self.calculate_indicators(df)
        df = self.generate_signals(df)

        # 回测变量
        cash = self.initial_capital
        shares = 0
        trades = []
        trade_details = []

        # 买入持有收益
        first_price = df['收盘'].iloc[0]
        last_price = df['收盘'].iloc[-1]
        buy_hold_return = (last_price / first_price - 1) * 100

        # 执行交易
        for i in range(len(df)):
            row = df.iloc[i]

            # 买入信号 (没有持仓时)
            if shares == 0 and row['buy_signal'] > 0:
                # 全仓买入
                buy_shares = int(cash / row['收盘'] / 100) * 100  # 整手
                if buy_shares > 0:
                    cost = buy_shares * row['收盘']
                    cash -= cost
                    shares = buy_shares

                    trade = Trade(
                        type='BUY',
                        date=row['日期'],
                        price=row['收盘'],
                        shares=buy_shares,
                        reason=row['buy_reason']
                    )
                    trades.append(trade)
                    trade_details.append({
                        'type': 'BUY',
                        'date': row['日期'].strftime('%Y-%m-%d'),
                        'price': row['收盘'],
                        'shares': buy_shares,
                        'reason': row['buy_reason']
                    })

            # 卖出信号 (有持仓时)
            elif shares > 0 and row['sell_signal'] > 0:
                # 全部卖出
                revenue = shares * row['收盘']
                cash += revenue

                trade = Trade(
                    type='SELL',
                    date=row['日期'],
                    price=row['收盘'],
                    shares=shares,
                    reason=row['sell_reason']
                )
                trades.append(trade)
                trade_details.append({
                    'type': 'SELL',
                    'date': row['日期'].strftime('%Y-%m-%d'),
                    'price': row['收盘'],
                    'shares': shares,
                    'reason': row['sell_reason']
                })
                shares = 0

        # 最后如果还持有，按收盘价清仓
        if shares > 0:
            cash += shares * df['收盘'].iloc[-1]
            trades.append(Trade(
                type='SELL',
                date=df['日期'].iloc[-1],
                price=df['收盘'].iloc[-1],
                shares=shares,
                reason='期末清仓'
            ))

        # 计算收益
        total_return = (cash / self.initial_capital - 1) * 100
        excess_return = total_return - buy_hold_return

        # 计算胜率
        win_trades = 0
        lose_trades = 0
        for i in range(0, len(trades) - 1, 2):
            if i + 1 < len(trades):
                buy_trade = trades[i]
                sell_trade = trades[i + 1]
                if sell_trade.price > buy_trade.price:
                    win_trades += 1
                else:
                    lose_trades += 1

        total_trades = win_trades + lose_trades
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

        return BacktestResult(
            code=code,
            name=name,
            total_trades=total_trades,
            win_trades=win_trades,
            lose_trades=lose_trades,
            win_rate=win_rate,
            total_return=total_return,
            buy_hold_return=buy_hold_return,
            excess_return=excess_return,
            trades=trades,
            trade_details=trade_details
        )

    def run_backtest(self, stock_pool: Dict[str, str]) -> List[BacktestResult]:
        """批量回测"""
        print()
        print('*' * 80)
        print('转折点策略回测 - 过去1年')
        print(f'回测时间: {datetime.now().strftime("%Y-%m-%d")}')
        print(f'初始资金: {self.initial_capital:,.0f} 元')
        print(f'股票数量: {len(stock_pool)}')
        print('*' * 80)
        print()

        results = []

        for i, (code, name) in enumerate(stock_pool.items(), 1):
            print(f'[{i}/{len(stock_pool)}] 回测 {name}({code})...', end=' ')

            result = self.backtest_single(code, name)
            if result:
                results.append(result)
                print(f'收益: {result.total_return:+.2f}% | 胜率: {result.win_rate:.0f}%')
            else:
                print('FAILED')

        # 显示汇总
        self._display_summary(results)

        return results

    def _display_summary(self, results: List[BacktestResult]):
        """显示回测汇总"""
        print()
        print('=' * 100)
        print('回测结果汇总')
        print('=' * 100)
        print()

        # 表头
        print(f"{'代码':<8}{'名称':<10}{'交易次数':<8}{'胜率':<8}{'策略收益':<10}{'持有收益':<10}{'超额收益':<10}")
        print('-' * 100)

        # 排序：按超额收益
        results = sorted(results, key=lambda x: x.excess_return, reverse=True)

        for r in results:
            print(f"{r.code:<8}{r.name:<10}{r.total_trades:<8}{r.win_rate:>5.0f}%   "
                  f"{r.total_return:>+8.2f}%  {r.buy_hold_return:>+8.2f}%  {r.excess_return:>+8.2f}%")

        print()

        # 统计
        avg_return = np.mean([r.total_return for r in results])
        avg_hold_return = np.mean([r.buy_hold_return for r in results])
        avg_excess = np.mean([r.excess_return for r in results])
        avg_win_rate = np.mean([r.win_rate for r in results])

        win_count = sum(1 for r in results if r.excess_return > 0)
        lose_count = len(results) - win_count

        print('=' * 100)
        print('统计汇总')
        print('=' * 100)
        print(f'  平均策略收益: {avg_return:+.2f}%')
        print(f'  平均持有收益: {avg_hold_return:+.2f}%')
        print(f'  平均超额收益: {avg_excess:+.2f}%')
        print(f'  平均胜率: {avg_win_rate:.0f}%')
        print(f'  跑赢持有: {win_count}/{len(results)} 只 ({win_count/len(results)*100:.0f}%)')
        print()

        # 策略有效性分析
        print('【策略分析】')
        if avg_excess > 0:
            print(f'  ✓ 策略有效：平均跑赢持有 {avg_excess:+.2f}%')
        else:
            print(f'  ✗ 策略无效：平均跑输持有 {avg_excess:+.2f}%')

        if avg_win_rate > 50:
            print(f'  ✓ 交易胜率：{avg_win_rate:.0f}% (超过50%)')
        else:
            print(f'  ✗ 交易胜率：{avg_win_rate:.0f}% (低于50%)')

        print()

        # 显示交易详情
        print('【交易详情】')
        print('-' * 80)

        for r in results[:3]:  # 只显示前3只
            print(f'\n{r.name}({r.code}):')
            for t in r.trade_details[:6]:  # 只显示前6笔
                print(f"  {t['date']} {t['type']:4s} {t['shares']:>4d}股 @ {t['price']:.2f} - {t['reason']}")

        print()
        print('=' * 100)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='转折点策略回测')
    parser.add_argument('--file', '-f', type=str, required=True,
                        help='股票列表CSV文件')
    parser.add_argument('--capital', type=float, default=100000,
                        help='初始资金')

    args = parser.parse_args()

    # 加载股票
    df = pd.read_csv(args.file, encoding='utf-8-sig')
    column_map = {'股票代码': 'code', 'code': 'code', '股票名称': 'name', 'name': 'name'}
    df = df.rename(columns=column_map)

    stock_pool = {}
    for _, row in df.iterrows():
        code = str(row['code']).zfill(6)
        name = row.get('name', f'股票{code}')
        stock_pool[code] = name

    # 执行回测
    backtester = ReversalBacktester(initial_capital=args.capital)
    backtester.run_backtest(stock_pool)


if __name__ == '__main__':
    main()
