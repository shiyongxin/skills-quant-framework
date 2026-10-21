# -*- coding: utf-8 -*-
"""
web_backtest (Flask) 回测引擎诚实性测试:
- t+1 开盘成交 + 真实费用(佣金min5/过户/印花税/滑点)
- 涨跌停挂单顺延/作废、风控日内 OHLC 判定、移动止损无同根未来函数
- 前端现金回放口径: buy.cost 含费、sell.revenue 净费、现金恒等
"""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("flask")

import web_backtest as wb
from execution_model import CostModel

CM = CostModel()


def mk_signals(n=40, base=10.0):
    """平坦行情信号表(含撮合所需 OHLC 列)。open=high=low=close=base。"""
    dates = pd.date_range('2024-01-01', periods=n, freq='B')
    rows = []
    for i in range(n):
        rows.append({
            'date': dates[i].strftime('%Y-%m-%d'),
            'close': base,
            'open': base,
            'high': base * 1.01,
            'low': base * 0.99,
            'prev_close': base,
            'buy_score': 0.0,
            'sell_score': 0.0,
            'buy_signals': [],
            'sell_signals': [],
        })
    return pd.DataFrame(rows), dates


def run_bt(rows, code='600519', params=None):
    return wb.backtest_stock(code, '测试', pd.DataFrame(rows), params=params)


class TestT1FillAndFees:
    def test_buy_next_open_with_fees_and_cash_identity(self):
        sig, dates = mk_signals(n=40)
        sig.loc[10, 'buy_score'] = 10.0
        sig.loc[10, 'buy_signals'] = ['测试买讯']
        sig.loc[30, 'sell_score'] = 10.0
        sig.loc[30, 'sell_signals'] = ['测试卖讯']
        res = wb.backtest_stock('600519', '测试', sig)

        trades = res['trades']
        assert len(trades) == 2, trades
        buy, sell = trades[0], trades[1]

        # t+1: 信号日 row10 → 成交日 row11 开盘
        assert buy['type'] == 'BUY'
        assert buy['date'] == dates[11].strftime('%Y-%m-%d')
        exp_fill = 10.0 * 1.001
        assert abs(buy['price'] - exp_fill) < 1e-9
        exp_qty = int(100000 * 1.0 / (10.0 * 1.001 * 1.0004) / 100) * 100
        assert buy['shares'] == exp_qty and exp_qty > 0
        exp_fee = (max(exp_qty * exp_fill * 0.0003, 5)
                   + exp_qty * exp_fill * 0.0001)
        assert abs(buy['fee'] - exp_fee) < 1e-6
        assert abs(buy['cost'] - (exp_qty * exp_fill + exp_fee)) < 1e-6

        # 卖出: row30 → row31 开盘, 净收入含印花税
        assert sell['type'] == 'SELL'
        assert sell['date'] == dates[31].strftime('%Y-%m-%d')
        exp_sfill = 10.0 * 0.999
        assert abs(sell['price'] - exp_sfill) < 1e-9
        exp_sfee = (max(exp_qty * exp_sfill * 0.0003, 5)
                    + exp_qty * exp_sfill * (0.0001 + 0.0005))
        assert abs(sell['fee'] - exp_sfee) < 1e-6
        assert abs(sell['revenue'] - (exp_qty * exp_sfill - exp_sfee)) < 1e-6

        # 现金恒等(期末空仓): final = 初始 - 买入总支出 + 卖出净收入
        exp_final = 100000 - buy['cost'] + sell['revenue']
        assert abs(res['final_value'] - exp_final) < 1e-6
        # 含费含滑点 → 平盘行情必然亏损
        assert res['final_value'] < 100000

        # 日志契约: 决策日 PENDING、成交日 BUY/SELL
        logs = res['daily_logs']
        assert len(logs) == len(sig)
        assert logs[10]['action'] == 'PENDING'
        assert '次日开盘' in logs[10]['action_reason']
        assert logs[11]['action'] == 'BUY'
        assert logs[31]['action'] == 'SELL'

    def test_buy_log_no_signal_row(self):
        sig, _ = mk_signals(n=20)
        res = wb.backtest_stock('600519', '测试', sig)
        assert res['daily_logs'][5]['action'] is None
        assert '无买卖信号' in res['daily_logs'][5]['action_reason']


class TestLimitRules:
    def test_limit_up_defer_then_fill_next_bar(self):
        sig, dates = mk_signals(n=30)
        sig.loc[10, 'buy_score'] = 10.0
        sig.loc[10, 'buy_signals'] = ['买']
        # row11 开盘涨停(前收10 → 板价11, 10.99触板), row12 恢复
        sig.loc[11, 'open'] = 10.99
        sig.loc[11, 'high'] = 10.99
        res = wb.backtest_stock('600519', '测试', sig)
        assert len(res['trades']) == 1
        assert res['trades'][0]['date'] == dates[12].strftime('%Y-%m-%d')
        assert '挂单顺延' in res['daily_logs'][11]['action_reason']

    def test_limit_up_three_bars_expires_no_trade(self):
        sig, _ = mk_signals(n=30)
        sig.loc[10, 'buy_score'] = 10.0
        for b in (11, 12, 13):
            sig.loc[b, 'open'] = 10.99
            sig.loc[b, 'high'] = 10.99
        res = wb.backtest_stock('600519', '测试', sig)
        assert len(res['trades']) == 0, res['trades']
        assert res['daily_logs'][13]['action'] == 'EXPIRED'
        assert '作废' in res['daily_logs'][13]['action_reason']

    def test_limit_down_sell_deferred(self):
        sig, dates = mk_signals(n=30)
        sig.loc[10, 'buy_score'] = 10.0
        sig.loc[20, 'sell_score'] = 10.0
        sig.loc[20, 'sell_signals'] = ['卖']
        sig.loc[21, 'open'] = 9.01   # 前收10 → 9.01 ≤ 9.018 触跌停
        sig.loc[21, 'low'] = 9.01
        res = wb.backtest_stock('600519', '测试', sig)
        assert len(res['trades']) == 2  # 买+卖
        sell = res['trades'][1]
        assert sell['date'] == dates[22].strftime('%Y-%m-%d')  # 顺延至 row22
        assert '跌停无法卖出' in res['daily_logs'][21]['action_reason']


class TestRiskExits:
    @staticmethod
    def _base_with_entry(params):
        sig, dates = mk_signals(n=30)
        sig.loc[10, 'buy_score'] = 10.0
        sig.loc[10, 'buy_signals'] = ['买']
        res = wb.backtest_stock('600519', '测试', sig, params=params)
        assert len(res['trades']) == 1  # row11 建仓
        return sig, dates, res['trades'][0]

    def test_stop_gap_fills_at_open(self):
        sig, dates, _ = self._base_with_entry({'stop_loss_pct': 0.08,
                                               'take_profit_pct': 0.0})
        entry = 10.0 * 1.001                       # 10.01
        sl = entry * 0.92                          # 9.2092
        assert sl > 9.018                          # 非跌停(前收10)
        sig.loc[12, 'open'] = 9.15                 # 跳空低于止损线
        sig.loc[12, 'high'] = 9.30
        sig.loc[12, 'low'] = 9.10
        sig.loc[12, 'close'] = 9.20
        res = wb.backtest_stock('600519', '测试', sig,
                                params={'stop_loss_pct': 0.08,
                                        'take_profit_pct': 0.0})
        sells = [t for t in res['trades'] if t['type'] == 'STOP_LOSS']
        assert len(sells) == 1, res['trades']
        assert sells[0]['date'] == dates[12].strftime('%Y-%m-%d')
        # 跳空 → 按开盘(含滑点)成交
        assert abs(sells[0]['price'] - 9.15 * 0.999) < 1e-9

    def test_stop_intraday_at_line_price(self):
        sig, dates, _ = self._base_with_entry({'stop_loss_pct': 0.08,
                                               'take_profit_pct': 0.0})
        entry = 10.0 * 1.001
        sl = entry * 0.92
        sig.loc[12, 'open'] = 9.30                 # 开盘未破线
        sig.loc[12, 'high'] = 9.35
        sig.loc[12, 'low'] = 9.15                  # 盘中砸穿止损线
        sig.loc[12, 'close'] = 9.25
        res = wb.backtest_stock('600519', '测试', sig,
                                params={'stop_loss_pct': 0.08,
                                        'take_profit_pct': 0.0})
        sells = [t for t in res['trades'] if t['type'] == 'STOP_LOSS']
        assert len(sells) == 1, res['trades']
        assert abs(sells[0]['price'] - sl * 0.999) < 1e-9  # 按止损线价

    def test_trailing_stop_uses_prior_high_no_same_bar_lookahead(self):
        sig, dates = mk_signals(n=40)
        sig.loc[10, 'buy_score'] = 10.0
        sig.loc[10, 'buy_signals'] = ['买']
        # row19 冲高: 新高点20但当根不得触发(基准须用前根)
        sig.loc[19, 'open'] = 10.0
        sig.loc[19, 'high'] = 20.0
        sig.loc[19, 'low'] = 9.6
        sig.loc[19, 'close'] = 18.0
        # row20: trail 线 = 20*0.95 = 19; 开盘19.5 > 19, 盘中18.5 ≤ 19 → 触发
        sig.loc[20, 'open'] = 19.5
        sig.loc[20, 'high'] = 19.8
        sig.loc[20, 'low'] = 18.5
        sig.loc[20, 'close'] = 19.2
        res = wb.backtest_stock('600519', '测试', sig,
                                params={'trailing_stop_pct': 0.05,
                                        'stop_loss_pct': 0.5,
                                        'take_profit_pct': 5.0,
                                        'min_holding_days': 0})
        sells = [t for t in res['trades'] if t['type'] == 'TRAILING_STOP']
        assert len(sells) == 1, res['trades']
        # 关键: row19(新高当根)不得触发, 必须在 row20
        assert sells[0]['date'] == dates[20].strftime('%Y-%m-%d')
        # 按前根高点推导的线价成交: 20*0.95=19 → 含滑点
        assert abs(sells[0]['price'] - 19.0 * 0.999) < 1e-6


class TestFrontendReplayContract:
    def test_trade_cash_flows_replay_exactly(self):
        """JS 重放: cash -= buy.cost; cash += sell.revenue → 须与服务器期末值一致。"""
        sig, _ = mk_signals(n=40)
        sig.loc[10, 'buy_score'] = 10.0
        sig.loc[30, 'sell_score'] = 10.0
        res = wb.backtest_stock('600519', '测试', sig)

        cash = 100000.0
        for t in res['trades']:
            if t['type'] in ('BUY', 'ADD'):
                cash -= t['cost']
                assert abs(t['cost'] - (t['shares'] * t['price'] + t['fee'])) < 1e-9
            else:
                cash += t['revenue']
                assert abs(t['revenue'] - (t['shares'] * t['price'] - t['fee'])) < 1e-9
        # 期末空仓 → 重放值 == 服务器 final_value
        assert abs(cash - res['final_value']) < 1e-6


class TestDetectSignalsOHLC:
    def test_detect_carries_ohlc_and_prev_close(self):
        rng = np.random.default_rng(0)
        n = 65
        close = 10 * np.cumprod(1 + rng.normal(0, 0.01, n))
        df = pd.DataFrame({
            '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
            '开盘': close * (1 + rng.normal(0, 0.002, n)),
            '最高': close * 1.01,
            '最低': close * 0.99,
            '收盘': close,
            '成交量': rng.integers(1e6, 2e6, n).astype(float),
        })
        df = wb.calculate_indicators(df, params=None)
        sig = wb.detect_reversal_signals(df, params=None)
        assert len(sig) == n - 60
        for col in ('open', 'high', 'low', 'prev_close'):
            assert col in sig.columns, col
        # 首行 prev_close = 检测起点(df 第59行)的收盘
        assert abs(sig.iloc[0]['prev_close'] - df['收盘'].iloc[59]) < 1e-9
        assert abs(sig.iloc[0]['open'] - df['开盘'].iloc[60]) < 1e-9
