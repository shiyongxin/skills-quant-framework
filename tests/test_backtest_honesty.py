# -*- coding: utf-8 -*-
"""
回测诚实性测试（Stage 3）:
- A (backtest_framework) / B (vectorized_backtest) / D (reversal_backtest)
- E (historical_backtest_validator) 前瞻收益
共性: t+1 开盘成交、真实费用、涨跌停拦截、无同根 bar 未来函数。
"""
import numpy as np
import pandas as pd

from backtest_framework import BacktestEngine
from execution_model import CostModel
from historical_backtest_validator import HistoricalBacktestValidator
from reversal_backtest import ReversalBacktester
from vectorized_backtest import VectorizedBacktester


def mk_data(n=60, base=10.0, seed=1):
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({
        '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01, '最低': close * 0.99, '收盘': close,
        '成交量': rng.integers(1e6, 2e6, n).astype(float),
    })


def mk_flat(n=80, base=10.0):
    x = np.full(n, base)
    return pd.DataFrame({
        '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
        '开盘': x.copy(), '最高': x * 1.01, '最低': x * 0.99, '收盘': x,
        '成交量': np.full(n, 1e6),
    })


# ---------------------------------------------------------------------------
# A 引擎: backtest_framework
# ---------------------------------------------------------------------------

class TestEngineA:
    def test_t1_fill_fees_and_round_lot(self):
        data = mk_data()

        def strat(d):
            pos = len(d) - 1
            if pos == 10:
                return 1
            if pos == 25:
                return -1
            return 0

        eng = BacktestEngine(initial_cash=100000)
        res = eng.run(data, strat, symbol='600519')
        trades = eng.trades
        assert len(trades) == 2, trades
        buy, sell = trades[0], trades[1]
        # 成交在信号次根开盘
        assert buy['date'] == data['日期'].iloc[11]
        assert abs(buy['price'] - data['开盘'].iloc[11] * 1.001) < 1e-9
        assert sell['date'] == data['日期'].iloc[26]
        assert abs(sell['price'] - data['开盘'].iloc[26] * 0.999) < 1e-9
        # 信号 bar 当根绝不成交
        assert buy['date'] > data['日期'].iloc[10]
        # 费用 = 佣金(max 5元) + 过户 (+ 卖出印花税)
        exp_fee_b = (max(buy['shares'] * buy['price'] * 0.0003, 5)
                     + buy['shares'] * buy['price'] * 0.0001)
        assert abs(buy['fee'] - exp_fee_b) < 1e-6
        exp_fee_s = (max(sell['shares'] * sell['price'] * 0.0003, 5)
                     + sell['shares'] * sell['price'] * (0.0001 + 0.0005))
        assert abs(sell['fee'] - exp_fee_s) < 1e-6
        # 现金恒等（空仓期末）
        assert abs(eng.cash - res['final_value']) < 1e-6
        # 整手
        assert buy['shares'] % 100 == 0 and buy['shares'] >= 100

    def test_stop_loss_on_entry_bar_legal(self):
        data = mk_data()
        data.loc[11, '最低'] = 5.0  # 入场日崩盘

        def strat(d):
            pos = len(d) - 1
            return 1 if pos == 10 else (0 if pos < 20 else -1)

        eng = BacktestEngine(initial_cash=100000)
        eng.run(data, strat, symbol='600519')
        t = eng.trades
        assert len(t) == 2 and t[1]['reason'] == 'stop_loss', t
        # 开盘入场后同日止损（合法: 低点在开盘成交之后）
        assert t[1]['date'] == data['日期'].iloc[11]

    def test_limit_up_blocks_then_defers(self):
        # 连续3根开盘涨停 → pending ttl=3 作废, 零交易
        data = mk_data()

        def strat(d):
            return 1 if len(d) - 1 == 10 else 0

        for b in (11, 12, 13):
            data.loc[b, '开盘'] = round(data.loc[b - 1, '收盘'] * 1.099, 2)
        eng = BacktestEngine(initial_cash=100000)
        eng.run(data, strat, symbol='600519')
        assert len(eng.trades) == 0, eng.trades

        # 仅堵1根 → bar12 开盘顺延成交
        data2 = mk_data()
        data2.loc[11, '开盘'] = round(data2.loc[10, '收盘'] * 1.099, 2)
        eng2 = BacktestEngine(initial_cash=100000)
        eng2.run(data2, strat, symbol='600519')
        assert len(eng2.trades) == 1
        assert eng2.trades[0]['date'] == data2['日期'].iloc[12]
        assert abs(eng2.trades[0]['price'] - data2['开盘'].iloc[12] * 1.001) < 1e-9

    def test_sell_defers_on_limit_down_open(self):
        data = mk_data()

        def strat(d):
            pos = len(d) - 1
            if pos == 10:
                return 1
            if pos == 25:
                return -1
            return 0

        data.loc[26, '开盘'] = round(data.loc[25, '收盘'] * 0.901, 2)  # 卖出日开盘跌停
        eng = BacktestEngine(initial_cash=100000)
        eng.run(data, strat, symbol='600519')
        sells = [t for t in eng.trades if t['action'] == 'sell']
        assert len(sells) == 1 and sells[0]['date'] != data['日期'].iloc[26]

    def test_zero_trades_identity(self):
        big = mk_data(n=300, seed=3)
        res = BacktestEngine().run(big, lambda d: 0, symbol='600519')
        assert res['total_return'] == 0


# ---------------------------------------------------------------------------
# B 引擎: vectorized_backtest
# ---------------------------------------------------------------------------

class TestEngineB:
    def test_t1_fill_with_pure_fees(self):
        df = mk_flat()
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        sig.iloc[30] = -1
        vb = VectorizedBacktester()
        m, details = vb._simulate_trades(
            df, sig, {'min_holding_days': 5, 'stop_loss_pct': 0.5,
                      'take_profit_pct': 0.9}, return_details=True)
        assert len(details) == 1, details
        d0 = details[0]
        exp_entry = 10.0 * 1.001 * 1.0004
        assert abs(d0.entry_price - exp_entry) < 1e-9
        assert d0.entry_idx == 11        # 信号次根成交
        assert d0.exit_idx == 31         # 卖讯次根成交
        exp_exit = 10.0 * 0.999 * 0.9991
        assert abs(d0.exit_price - exp_exit) < 1e-9
        exp_pnl = (exp_exit / exp_entry - 1) * 100
        assert abs(d0.pnl_pct - exp_pnl) < 1e-9

    def test_limit_up_open_no_entry(self):
        df = mk_flat()
        df.loc[11, '开盘'] = 10.99
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(df, sig, {'min_holding_days': 1},
                                     return_details=True)
        assert len(det) == 0, det

    def test_trailing_stop_no_same_bar_lookahead(self):
        # bar20 冲高 200/低170: 旧逻辑用当根高点即触发; 新逻辑 trail 基于前根
        df = mk_flat(n=60, base=100.0)
        df.loc[20, '最高'] = 200.0
        df.loc[20, '最低'] = 170.0
        df.loc[20, '开盘'] = 100.0
        df.loc[20, '收盘'] = 200.0
        df.loc[21, '最高'] = 195.0
        df.loc[21, '最低'] = 180.0
        df.loc[21, '开盘'] = 190.0
        df.loc[21, '收盘'] = 185.0
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(
            df, sig, {'min_holding_days': 5, 'trailing_stop_pct': 0.05,
                      'stop_loss_pct': 0.5, 'take_profit_pct': 5.0},
            return_details=True)
        assert len(det) == 1, det
        t = det[0]
        # bar20 不触发(用前根 trail=95 < 170), bar21 用 bar20 高点 trail=190 → low180 触发
        assert t.exit_reason == 'trailing_stop'
        assert t.exit_idx == 21
        exp = min(200.0 * 0.95, 190.0) * 0.999 * 0.9991
        assert abs(t.exit_price - exp) < 1e-6

    def test_calendar_day_holding_and_limit_sell_blocked(self):
        df = mk_flat(n=40)
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        sig.iloc[30] = -1
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(df, sig, {'min_holding_days': 5},
                                     return_details=True)
        t = det[0]
        cal_days = (df['日期'].iloc[31] - df['日期'].iloc[11]).days
        assert t.holding_days == cal_days
        assert t.holding_days > 31 - 11  # 自然日 > bar数(含周末)
        # 卖讯日开盘跌停 → 拦截, 持有到期末 'end'
        df.loc[31, '开盘'] = round(df.loc[30, '收盘'] * 0.901, 2)
        m2, det2 = vb._simulate_trades(df, sig, {'min_holding_days': 5},
                                       return_details=True)
        assert det2[0].exit_reason == 'end'
        assert det2[0].exit_idx == 39

    def test_gap_down_stop_fills_at_open(self):
        df = mk_flat(n=40, base=10.0)
        # bar12 开盘 9.10 低于止损价(10*0.92≈9.2)但非跌停
        df.loc[12, '开盘'] = 9.10
        df.loc[12, '最低'] = 9.05
        df.loc[12, '最高'] = 9.30
        df.loc[12, '收盘'] = 9.15
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(
            df, sig, {'min_holding_days': 5, 'stop_loss_pct': 0.08,
                      'take_profit_pct': 0.9}, return_details=True)
        t = det[0]
        assert t.exit_reason == 'stop_loss' and t.exit_idx == 12
        assert abs(t.exit_price - 9.10 * 0.999 * 0.9991) < 1e-9

    def test_end_to_end_finite(self):
        rng = np.random.default_rng(3)
        n = 300
        close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
        big = pd.DataFrame({
            '日期': pd.date_range('2022-01-03', periods=n, freq='B'),
            '开盘': close * (1 + rng.normal(0, 0.003, n)),
            '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
        })
        vb = VectorizedBacktester()
        m = vb.backtest(big, {})
        assert np.isfinite(m.total_return) and np.isfinite(m.sharpe_ratio)


# ---------------------------------------------------------------------------
# D 引擎: reversal_backtest
# ---------------------------------------------------------------------------

class TestEngineD:
    @staticmethod
    def _mk_rb(df, buy_idx, sell_idx=None):
        rb = ReversalBacktester(initial_capital=100000)
        rb.get_stock_data = lambda code, days=365: df.copy()

        def fake_signals(frame):
            frame = frame.copy()
            frame['buy_signal'] = 0.0
            frame['sell_signal'] = 0.0
            frame['buy_reason'] = ''
            frame['sell_reason'] = ''
            frame.loc[frame.index[buy_idx], 'buy_signal'] = 50.0
            frame.loc[frame.index[buy_idx], 'buy_reason'] = 'test_buy'
            if sell_idx is not None:
                frame.loc[frame.index[sell_idx], 'sell_signal'] = 50.0
                frame.loc[frame.index[sell_idx], 'sell_reason'] = 'test_sell'
            return frame

        rb.generate_signals = fake_signals
        return rb

    def test_t1_fill_and_fees(self):
        df = mk_flat(n=120, base=20.0)
        rb = self._mk_rb(df, 30, 60)
        res = rb.backtest_single('600519', 'x')
        assert res is not None
        tr = res.trades
        assert len(tr) == 2, tr
        buy, sell = tr[0], tr[1]
        assert buy.type == 'BUY' and buy.date == df['日期'].iloc[31]
        assert abs(buy.price - df['开盘'].iloc[31] * 1.001) < 1e-9
        exp_fee_b = (max(buy.price * buy.shares * 0.0003, 5)
                     + buy.price * buy.shares * 0.0001)
        assert abs(buy.fee - exp_fee_b) < 1e-6
        assert sell.type == 'SELL' and sell.date == df['日期'].iloc[61]
        assert abs(sell.price - df['开盘'].iloc[61] * 0.999) < 1e-9
        exp_fee_s = (max(sell.price * sell.shares * 0.0003, 5)
                     + sell.price * sell.shares * (0.0001 + 0.0005))
        assert abs(sell.fee - exp_fee_s) < 1e-6
        assert buy.shares % 100 == 0
        # 含费收益必须低于零成本(仅滑点)口径
        zero_cost = ((df['收盘'].iloc[61] * 0.999)
                     / (df['开盘'].iloc[31] * 1.001) - 1) * 100
        assert res.total_return < zero_cost + 0.0001

    def test_limit_up_ttl_blocks_all(self):
        df = mk_flat(n=80, base=20.0)
        # 连续3根开盘涨停 → ttl=3 全部作废
        for b in (31, 32, 33):
            prev_c = df.loc[b - 1, '收盘']
            df.loc[b, '开盘'] = round(prev_c * 1.099, 2)
            df.loc[b, '收盘'] = prev_c
            df.loc[b, '最高'] = max(df.loc[b, '开盘'], prev_c)
            df.loc[b, '最低'] = prev_c * 0.999
        rb = self._mk_rb(df, 30)
        res = rb.backtest_single('600519', 'x')
        assert len(res.trades) == 0, res.trades


# ---------------------------------------------------------------------------
# E: historical_backtest_validator 前瞻收益
# ---------------------------------------------------------------------------

class TestValidatorE:
    def test_next_open_entry_costs_and_benchmark_alignment(self):
        import types
        v = HistoricalBacktestValidator.__new__(HistoricalBacktestValidator)
        v.backtester = VectorizedBacktester()
        v.cost_model = CostModel()
        v.systems = {}

        stk = pd.DataFrame({
            '日期': pd.to_datetime(['2024-03-05', '2024-03-06', '2024-03-07',
                                    '2024-03-08', '2024-03-11', '2024-03-12']),
            '开盘': [10.0, 10.2, 10.4, 10.6, 10.8, 11.0],
            '最高': [10.1, 10.3, 10.5, 10.7, 10.9, 11.1],
            '最低': [9.9, 10.1, 10.3, 10.5, 10.7, 10.9],
            '收盘': [10.0, 10.2, 10.4, 10.6, 10.8, 11.0],
            '成交量': [1e6] * 6,
        })
        v.data_manager = types.SimpleNamespace(load=lambda sym: stk.copy())
        csi = pd.DataFrame({
            '日期': pd.to_datetime(['2024-03-04', '2024-03-05', '2024-03-06',
                                    '2024-03-07', '2024-03-08', '2024-03-11',
                                    '2024-03-12', '2024-03-13']),
            '收盘': [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0],
        })
        v._load_index_data = lambda code: csi.copy()

        ret, csi_ret = v.calculate_forward_return('600519', '2024-03-05',
                                                  holding_days=5)
        cm = CostModel()
        exp_entry = cm.buy_price_incl(10.2)     # pick 次日开盘
        exp_exit = cm.sell_price_incl(11.0)     # 第5持有日收盘
        exp_ret = (exp_exit / exp_entry - 1) * 100
        assert abs(ret - exp_ret) < 1e-9, (ret, exp_ret)
        # 基准按个股真实入场/出场日期对齐: 03-06→03-12, 毛收益不扣个股成本
        exp_csi = (106.0 / 102.0 - 1) * 100
        assert abs(csi_ret - exp_csi) < 1e-9, (csi_ret, exp_csi)
        # 扣成本后收益低于裸价差
        assert ret < (11.0 / 10.2 - 1) * 100
