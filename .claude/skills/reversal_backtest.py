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
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

from execution_model import CostModel, can_buy_at_open, can_sell_at_open, can_sell_intraday
from core.indicators import atr as _core_atr
from core.indicator_engine import IndicatorEngine
from sina_daily import fetch_daily, format_symbol
from reversal_rules import (
    score_oversold, score_overbought, score_divergence, score_exhaustion,
    decide_action,
)


@dataclass
class Trade:
    """交易记录"""
    type: str  # 'BUY' / 'SELL'
    date: datetime
    price: float
    shares: int
    reason: str
    fee: float = 0.0  # 交易成本(佣金+过户+印花税)


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
        self.cost_model = CostModel()  # 佣金万三(最低5元)+印花税0.05%+过户0.001%+滑点

    def get_stock_data(self, code: str, days: int = 365) -> Optional[pd.DataFrame]:
        """获取股票历史数据"""
        try:
            # 前缀规则单一真相源 (审计 M18: 旧内联映射缺 bj 分支)
            full_code = format_symbol(code)

            end_date = datetime.now()
            start_date = end_date - timedelta(days=days * 2)

            df = fetch_daily(
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
        """计算技术指标 — 与 ReversalDetector 完全一致 (审计 C-P1-13)"""
        close = df['收盘']
        high = df['最高']
        low = df['最低']
        # 共享指标引擎 (审计 #10): 与 ReversalDetector 同一真相源
        # (旧实现 ewm(adjust=True) 与全仓 adjust=False 分裂, 已统一)
        eng = IndicatorEngine(df)

        # RSI (core 单一真相源)
        for period in [6, 14, 24]:
            df[f'RSI{period}'] = eng.rsi(period)

        # KDJ
        k, d, j = eng.kdj()
        df['K'], df['D'], df['J'] = k, d, j

        # MACD
        dif, dea, hist = eng.macd()
        df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = dif, dea, hist

        # 布林带
        upper, middle, lower, std = eng.bollinger(20, 2.0)
        df['BB_Middle'], df['BB_Std'] = middle, std
        df['BB_Upper'], df['BB_Lower'] = upper, lower

        # 均线
        df['MA5'] = eng.ma(5)
        df['MA10'] = eng.ma(10)
        df['MA20'] = eng.ma(20)
        df['MA60'] = eng.ma(60)

        # 成交量
        df['Vol_MA5'] = eng.volume_ma(5)
        df['Vol_MA20'] = eng.volume_ma(20)

        # 价格变化率
        df['ROC5'] = close.pct_change(5) * 100
        df['ROC10'] = close.pct_change(10) * 100

        # ATR (core Wilder 单一真相源)
        df['ATR'] = _core_atr(high, low, close, 14)

        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成买卖信号 — 规则走 reversal_rules 单一真相源 (审计 C-P1-13):
        与 ReversalDetector (实盘) 完全一致的阈值/指标/判定闸门。
        旧版: 两套阈值 + 死代码块 (自比较恒False) + 同bar可同时买卖 — 均已消除。
        """
        df = df.copy()
        df['buy_signal'] = 0
        df['sell_signal'] = 0
        df['buy_reason'] = ''
        df['sell_reason'] = ''

        for i in range(30, len(df)):
            # 基础打分 (与实盘完全一致的规则)
            buy_score, buy_reasons = score_oversold(df, i)
            sell_score, sell_reasons = score_overbought(df, i)

            # 背离 (20 bar 窗)
            if i >= 20:
                div_type, div_score, div_reasons = score_divergence(
                    df.iloc[i - 19: i + 1].reset_index(drop=True))
                if div_type == 'BULLISH':
                    buy_score += div_score
                    buy_reasons += div_reasons
                elif div_type == 'BEARISH':
                    sell_score += div_score
                    sell_reasons += div_reasons

            # 趋势衰竭
            exhaust_type, exhaust_score, exhaust_reasons = score_exhaustion(df, i)
            if exhaust_type == 'DOWN_EXHAUSTION':
                buy_score += exhaust_score
                buy_reasons += exhaust_reasons
            elif exhaust_type == 'UP_EXHAUSTION':
                sell_score += exhaust_score
                sell_reasons += exhaust_reasons

            # 判定闸门: >=40 且严格大于对侧 (与实盘 decide_action 一致)
            action = decide_action(buy_score, sell_score)
            if action == 'BUY':
                df.loc[df.index[i], 'buy_signal'] = buy_score
                df.loc[df.index[i], 'buy_reason'] = ', '.join(buy_reasons[:2])
            elif action == 'SELL':
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

        # 执行交易 (t+1: 本根收盘信号在下一根开盘成交; 涨跌停拦截+完整成本)
        pending = None  # {'intent': 'BUY'/'SELL', 'reason': str, 'ttl': int}

        for i in range(len(df)):
            row = df.iloc[i]

            # 1) 撮合上一根收盘产生的意图 (本根开盘)
            if pending is not None and i > 0:
                prev_close = df['收盘'].iloc[i - 1]
                open_px = float(row['开盘'])
                intent = pending['intent']

                if intent == 'BUY' and shares == 0:
                    if can_buy_at_open(open_px, prev_close, code):
                        fill_px = self.cost_model.fill_buy_price(open_px)
                        buy_shares = int(cash / open_px / 100) * 100  # 整手
                        # 费用感知: 逐档下调直到总成本可负担
                        while buy_shares >= 100:
                            fee_try = self.cost_model.buy_cost(fill_px, buy_shares)
                            if buy_shares * fill_px + fee_try <= cash:
                                break
                            buy_shares -= 100
                        if buy_shares >= 100:
                            fee = self.cost_model.buy_cost(fill_px, buy_shares)
                            cost = buy_shares * fill_px + fee
                            cash -= cost
                            shares = buy_shares

                            trades.append(Trade(
                                type='BUY', date=row['日期'], price=fill_px,
                                shares=buy_shares, reason=pending['reason'], fee=fee))
                            trade_details.append({
                                'type': 'BUY',
                                'date': row['日期'].strftime('%Y-%m-%d'),
                                'price': fill_px,
                                'shares': buy_shares,
                                'fee': fee,
                                'reason': pending['reason']
                            })
                        pending = None
                    else:
                        # 开盘涨停买不进 → 顺延(最多3根)
                        pending['ttl'] -= 1
                        if pending['ttl'] <= 0:
                            pending = None

                elif intent == 'SELL' and shares > 0:
                    if can_sell_at_open(open_px, prev_close, code):
                        fill_px = self.cost_model.fill_sell_price(open_px)
                        fee = self.cost_model.sell_cost(fill_px, shares)
                        revenue = shares * fill_px - fee
                        cash += revenue

                        trades.append(Trade(
                            type='SELL', date=row['日期'], price=fill_px,
                            shares=shares, reason=pending['reason'], fee=fee))
                        trade_details.append({
                            'type': 'SELL',
                            'date': row['日期'].strftime('%Y-%m-%d'),
                            'price': fill_px,
                            'shares': shares,
                            'fee': fee,
                            'reason': pending['reason']
                        })
                        shares = 0
                        pending = None
                    else:
                        # 开盘跌停卖不出 → 顺延(最多3根)
                        pending['ttl'] -= 1
                        if pending['ttl'] <= 0:
                            pending = None
                else:
                    pending = None  # 状态已不匹配(如已持仓/已空仓)

            # 2) 本根收盘信号 → 排队下一根开盘
            if shares == 0 and row['buy_signal'] > 0:
                pending = {'intent': 'BUY', 'reason': row['buy_reason'], 'ttl': 3}
            elif shares > 0 and row['sell_signal'] > 0:
                pending = {'intent': 'SELL', 'reason': row['sell_reason'], 'ttl': 3}

        # 期末清仓 (最后一根封跌停不可卖出 → 不虚构成交, 按收盘市值计入收益)
        if shares > 0:
            last = df.iloc[-1]
            prev_close = df['收盘'].iloc[-2] if len(df) > 1 else last['收盘']
            if can_sell_intraday(float(last['开盘']), float(last['最高']),
                                 float(last['最低']), float(last['收盘']),
                                 prev_close, code):
                sell_px = self.cost_model.fill_sell_price(float(last['收盘']))
                fee = self.cost_model.sell_cost(sell_px, shares)
                cash += shares * sell_px - fee
                trades.append(Trade(
                    type='SELL', date=last['日期'], price=sell_px,
                    shares=shares, reason='期末清仓', fee=fee))
                trade_details.append({
                    'type': 'SELL',
                    'date': last['日期'].strftime('%Y-%m-%d'),
                    'price': sell_px,
                    'shares': shares,
                    'fee': fee,
                    'reason': '期末清仓'
                })
                shares = 0

        # 计算收益 (含未清仓部分的收盘市值)
        total_value = cash + shares * df['收盘'].iloc[-1] if shares > 0 else cash
        total_return = (total_value / self.initial_capital - 1) * 100
        excess_return = total_return - buy_hold_return

        # 计算胜率 (按含费净额判定)
        win_trades = 0
        lose_trades = 0
        for i in range(0, len(trades) - 1, 2):
            if i + 1 < len(trades):
                buy_trade = trades[i]
                sell_trade = trades[i + 1]
                buy_cost = buy_trade.price * buy_trade.shares + buy_trade.fee
                sell_net = sell_trade.price * sell_trade.shares - sell_trade.fee
                if sell_net > buy_cost:
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
