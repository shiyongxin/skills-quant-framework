# -*- coding: utf-8 -*-
"""
回测诚实性测试（Stage 3）:
- A (backtest_framework) / B (vectorized_backtest) / D (reversal_backtest)
- E (historical_backtest_validator) 前瞻收益
- 优化器体制过滤路径 (optimization_engine._compute_metrics_from_trades,
  审计 E-P1 口径统一: 共享 metrics_from_trades)
共性: t+1 开盘成交、真实费用、涨跌停拦截、无同根 bar 未来函数。
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backtest_framework import BacktestEngine
from execution_model import CostModel
from historical_backtest_validator import HistoricalBacktestValidator
from optimization_engine import FitnessEvaluator
from reversal_backtest import ReversalBacktester
from vectorized_backtest import (VectorizedBacktester, BacktestMetrics,
                                 TradeDetail, metrics_from_trades)


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
# H8 (审计 B21/B22/B23): 引擎 B 三处结构性偏差
# ---------------------------------------------------------------------------

class TestH8StructuralBiases:
    """H8: ① 重叠买讯伪交易 ② 最小持有期屏蔽退出 ③ warmup 吃 OOS 窗口。

    三项都是"结构性偏差"而非风格问题: 修前引擎记的交易数/胜率/Sharpe 与
    策略实际行为不符 (审计 D-backtest.md B21/B22/B23)。
    """

    # ---------- ① 重叠买入信号 → 0 持仓日伪交易 (B21) ----------

    def test_overlapping_buys_do_not_create_pseudo_trades(self):
        """密集买讯只开一仓, 不再切出 0 持仓日伪交易。

        旧实现: 持仓期终点取"下一次买入信号" → 连续买讯把上一笔切成 0 根
        bar (当日开当日平), 审计复现 63 笔 avg_holding=0.27、Sharpe 恒 0。
        """
        df = mk_flat(n=60)
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = sig.iloc[11] = sig.iloc[12] = 1   # 三个连续买讯
        sig.iloc[30] = -1                                  # 之后一个卖讯
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(df, sig, {'min_holding_days': 0},
                                     return_details=True)
        assert len(det) == 1, f"重叠买讯应只开一仓, 实际 {len(det)} 笔"
        t = det[0]
        assert t.entry_idx == 11 and t.exit_idx == 31
        assert t.exit_reason == 'signal'
        # 关键: 没有任何 0 持仓日伪交易 (入场根 == 出场根)
        assert all(d.exit_idx > d.entry_idx for d in det)

    def test_buy_signal_while_holding_is_ignored(self):
        """持仓期间的新买讯被忽略 (与 A 引擎"买入仅当无持仓"口径一致)。"""
        df = mk_flat(n=60)
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        sig.iloc[20] = 1     # 持仓中的买讯 → 忽略
        sig.iloc[30] = -1
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(df, sig, {'min_holding_days': 0},
                                     return_details=True)
        assert len(det) == 1
        assert det[0].entry_idx == 11      # 不是 21
        assert det[0].exit_idx == 31

    def test_exit_bar_buy_signal_can_reenter(self):
        """出场当根的买讯仍有效 (收盘出信号, 次根开盘再入场)。"""
        df = mk_flat(n=60)
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        sig.iloc[20] = -1   # 卖讯 → 21 出场
        sig.iloc[21] = 1    # 出场当根买讯 → 22 再入场
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(df, sig, {'min_holding_days': 0},
                                     return_details=True)
        assert [d.entry_idx for d in det] == [11, 22]
        assert det[0].exit_idx == 21

    # ---------- ② 最小持有期屏蔽退出条件 (B22) ----------

    def test_default_has_no_min_holding_lock(self):
        """默认参数不再隐式锁 20 日: 早期卖讯可立即执行。

        旧默认 20 → 锁定期内只有硬止损生效 (追踪/止盈/卖讯全废), 且 A 引擎
        无此概念 → 三引擎口径不一致 (审计 B22)。
        """
        df = mk_flat(n=60)
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        sig.iloc[15] = -1    # 入场后第 4 根就出卖点
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(df, sig, {}, return_details=True)
        assert det[0].exit_reason == 'signal'
        assert det[0].exit_idx == 16

    def test_explicit_min_holding_still_locks(self):
        """显式 min_holding_days=20 → 锁定期语义保留 (策略显式选择)。"""
        df = mk_flat(n=60)
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        sig.iloc[15] = -1
        vb = VectorizedBacktester()
        m, det = vb._simulate_trades(df, sig, {'min_holding_days': 20},
                                     return_details=True)
        assert det[0].exit_reason == 'end'      # 卖讯被锁 → 持有到期末
        assert det[0].exit_idx == 59

    def test_trailing_stop_not_blocked_by_default(self):
        """默认参数下追踪止损可生效 (旧默认被锁 → 小亏拖成大亏)。"""
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
        # 不传 min_holding_days (默认 0 = 不锁); 止盈设高以隔离追踪止损
        m, det = vb._simulate_trades(df, sig, {'take_profit_pct': 5.0},
                                     return_details=True)
        assert det[0].exit_reason == 'trailing_stop'
        assert det[0].exit_idx == 21

    # ---------- ③ warmup 吃掉 OOS 窗口 (B23) ----------

    @staticmethod
    def _step_frame(n, close):
        return pd.DataFrame({
            '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
            '开盘': close * 1.001, '最高': close * 1.02,
            '最低': close * 0.98, '收盘': close,
            '成交量': np.full(n, 1e6),
        })

    def test_history_segment_keeps_window_signals_alive(self):
        """带 history 段 → warmup 落在历史段, 窗口内信号不再被清零。

        旧实现: 每个 OOS 窗口自己重置 warmup, 180 根测试窗前 60 根信号
        被强制置 0 (审计实测: 全样本 12 笔 vs OOS 切片 6 笔, Sharpe
        -1.452 vs -6.972)。
        """
        hist = self._step_frame(60, np.full(60, 10.0))
        win = self._step_frame(150, np.concatenate([np.full(5, 10.0),
                                                    np.full(145, 12.0)]))
        p = {'buy_threshold': 1.0, 'sell_threshold': 99.0,
             'stop_loss_pct': 0.5, 'take_profit_pct': 5.0}
        vb = VectorizedBacktester()
        # 无 history: 窗口前段被 warmup 清零 → 无交易
        assert vb.backtest(win, p).num_trades == 0
        # 带 history: 买讯落在窗口第 5 根 (历史段之后) → 正常成交
        m = vb.backtest(win, p, history=hist)
        assert m.num_trades == 1

    def test_walk_forward_passes_window_history(self):
        """walk_forward 每个窗口都带上窗口前的历史段 (warmup 跨窗口继承)。"""
        rng = np.random.default_rng(7)
        n = 750
        close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
        data = self._step_frame(n, close)
        vb = VectorizedBacktester()
        seen = []
        orig = vb.backtest

        def spy(data_, params_, **kw):
            hist = kw.get('history')
            seen.append((len(data_), 0 if hist is None else len(hist)))
            return orig(data_, params_, **kw)

        vb.backtest = spy
        res = vb.walk_forward(data, {'min_holding_days': 5},
                              train_days=300, test_days=150, step_days=150)
        assert len(res) == 3
        # 窗口长度不变, 每窗都带 60 根历史 (序列开头之后的窗口都有)
        assert seen == [(150, 60)] * 3
        assert all(np.isfinite(m.total_return) for m in res)


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


class TestGoldenMetrics:
    """黄金指标快照: 锁定 seed=3/n=300 数据上 A/B 引擎的完整指标输出。
    数值漂移 → 先怀疑回测逻辑变更, 确认后才更新快照。"""

    @staticmethod
    def _big():
        rng = np.random.default_rng(3)
        n = 300
        close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
        return pd.DataFrame({
            '日期': pd.date_range('2022-01-03', periods=n, freq='B'),
            '开盘': close * (1 + rng.normal(0, 0.003, n)),
            '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
        })

    def test_engine_b_vectorized_golden(self):
        m = VectorizedBacktester().backtest(self._big(), {})
        # 审计 B22/H8② 后更新 (2026-10-26): 旧默认 min_holding_days=20 让
        # 锁定期内只有硬止损生效 (追踪止损被屏蔽) —— 同一笔持仓 (bar143 入场)
        # 因此从"追踪止损 bar145 止损 -3.05%" 变成 "扛到硬止损 bar158 -8.17%",
        # 回撤 6.52%→2.76%, 夏普 0.707→1.431, 盈亏比 2.42→6.49。
        # 数值中性证明: 显式传 min_holding_days=20 时新实现与旧实现逐位一致
        # (见 test_engine_b_golden_with_explicit_min_holding_lock) → 漂移
        # 只来自默认值诚实化, 持仓状态机 (B21) 在本数据集上无数值影响。
        assert m.total_return == pytest.approx(12.99316444226517, rel=1e-6)
        # 口径统一后(core): 日频盯市Sharpe(ddof=1) + 日频MDD + 求和式profit_factor
        assert m.sharpe_ratio == pytest.approx(1.4310959922744992, rel=1e-6)
        assert m.max_drawdown == pytest.approx(2.761219205849939, rel=1e-6)
        assert m.num_trades == 2
        assert m.win_rate == pytest.approx(50.0)
        assert m.profit_factor == pytest.approx(6.485939463249691, rel=1e-6)

    def test_engine_b_golden_with_explicit_min_holding_lock(self):
        """显式 min_holding_days=20 → 与修复前逐位一致 (锁定期语义保留)。

        同时锁定"持仓状态机 (B21) 不改变本数据集数值"这一事实:
        旧实现(买讯切分持仓)与新实现(持仓状态机)在此数据上给出同一笔交易。
        """
        m = VectorizedBacktester().backtest(
            self._big(), {'min_holding_days': 20})
        assert m.total_return == pytest.approx(8.24347173537372, rel=1e-6)
        assert m.sharpe_ratio == pytest.approx(0.7067662022777503, rel=1e-6)
        assert m.max_drawdown == pytest.approx(6.516848434608427, rel=1e-6)
        assert m.num_trades == 2
        assert m.win_rate == pytest.approx(50.0)
        assert m.profit_factor == pytest.approx(2.4186901535872116, rel=1e-6)

    def test_engine_a_framework_golden(self):
        big = self._big()
        ma5 = pd.Series(big['收盘']).rolling(5).mean()
        ma20 = pd.Series(big['收盘']).rolling(20).mean()

        def strat(d):
            i = len(d) - 1
            if i < 21:
                return 0
            up = (ma5.iloc[i] > ma20.iloc[i]
                  and ma5.iloc[i - 1] <= ma20.iloc[i - 1])
            down = (ma5.iloc[i] < ma20.iloc[i]
                    and ma5.iloc[i - 1] >= ma20.iloc[i - 1])
            if up:
                return 1
            if down:
                return -1
            return 0

        res = BacktestEngine(initial_cash=1000000).run(big, strat,
                                                       symbol='600519')
        assert res['total_return'] == pytest.approx(20.02675523695121, rel=1e-6)
        assert res['sharpe_ratio'] == pytest.approx(0.8098904708567016, rel=1e-6)
        # core 统一口径: MDD 为正值百分比
        assert res['max_drawdown'] == pytest.approx(14.194905174592487, rel=1e-6)
        assert res['trade_count'] == 9
        assert len(res['trades']) == 19
        assert res['profit_factor'] == pytest.approx(1.2589570136340924, rel=1e-6)


class TestSharedMetricsFromTrades:
    """E-P1: metrics_from_trades 共享函数与 B 引擎 _simulate_trades 指标块等价。"""

    def test_matches_b_backtest_with_details(self):
        data = TestGoldenMetrics._big()
        bt = VectorizedBacktester()
        metrics, details = bt.backtest_with_details(data, {})
        assert details  # 黄金数据默认参数下必有交易 (num_trades==2)

        m2 = metrics_from_trades(
            np.array([d.pnl_pct for d in details]),
            np.array([d.holding_days for d in details], dtype=float),
            [(d.entry_idx, d.exit_idx) for d in details],
            data['收盘'].to_numpy(dtype=float),
            data['开盘'].to_numpy(dtype=float),
            0.8)
        assert m2.total_return == pytest.approx(metrics.total_return, rel=1e-12)
        assert m2.annualized_return == pytest.approx(metrics.annualized_return, rel=1e-12)
        assert m2.max_drawdown == pytest.approx(metrics.max_drawdown, rel=1e-12)
        assert m2.sharpe_ratio == pytest.approx(metrics.sharpe_ratio, rel=1e-12)
        assert m2.win_rate == pytest.approx(metrics.win_rate, rel=1e-12)
        assert m2.profit_factor == pytest.approx(metrics.profit_factor, rel=1e-12)
        assert m2.num_trades == metrics.num_trades
        assert m2.avg_holding_days == pytest.approx(metrics.avg_holding_days, rel=1e-12)
        assert m2.avg_return_per_trade == pytest.approx(metrics.avg_return_per_trade, rel=1e-12)
        assert m2.max_consecutive_losses == metrics.max_consecutive_losses

    def test_empty_trades_returns_empty_metrics(self):
        m = metrics_from_trades([], [], [], np.array([10.0, 10.1]),
                                np.array([10.0, 10.05]), 0.8)
        assert m.num_trades == 0 and m.total_return == 0.0


class TestTradeFilterMetricsConsistency:
    """E-P1 #15/#20: 优化器体制过滤路径指标口径与 B 引擎统一。"""

    @staticmethod
    def _engine():
        return FitnessEvaluator()

    @staticmethod
    def _data(n=400, seed=11):
        rng = np.random.default_rng(seed)
        close = 10 * np.cumprod(1 + rng.normal(0.0004, 0.01, n))
        return pd.DataFrame({
            '日期': pd.date_range('2022-01-03', periods=n, freq='B'),
            '开盘': close * (1 + rng.normal(0, 0.002, n)),
            '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
        })

    @staticmethod
    def _trade(entry, exit_, pnl, hold):
        return SimpleNamespace(entry_idx=entry, exit_idx=exit_,
                               pnl_pct=pnl, holding_days=hold)

    def test_annualized_uses_exposure_span_not_full_history(self):
        data = self._data()
        trades = [self._trade(300, 330, 8.0, 30), self._trade(335, 360, 5.0, 25)]
        m = self._engine()._compute_metrics_from_trades(trades, data, {})
        assert m is not None and m.num_trades == 2

        span_bars = 360 - 300 + 1  # 暴露跨度 61 bar
        expected = ((1 + m.total_return / 100) ** (252 / span_bars) - 1) * 100
        assert m.annualized_return == pytest.approx(expected, rel=1e-9)
        # 旧口径 (len(data)=400 全历史分母) 与新口径差数个量级
        wrong = ((1 + m.total_return / 100)
                 ** (252 / (len(data) / 252)) - 1) * 100
        assert abs(m.annualized_return - wrong) > 1.0

    def test_sharpe_mdd_daily_mtm_not_trade_sequence(self):
        data = self._data()
        trades = [self._trade(300, 330, 8.0, 30), self._trade(335, 360, 5.0, 25)]
        m = self._engine()._compute_metrics_from_trades(trades, data, {})

        # 按 B 引擎同构造重算日频盯市
        w = data.iloc[300:361]
        close = w['收盘'].to_numpy(dtype=float)
        open_arr = w['开盘'].to_numpy(dtype=float)
        n = len(close)
        spans = [(0, 30), (35, 60)]
        daily_ret = np.zeros(n)
        daily_ret[1:] = close[1:] / close[:-1] - 1
        for e, x in spans:
            daily_ret[e] = close[e] / open_arr[e] - 1
            daily_ret[x] = open_arr[x] / close[x - 1] - 1
        held = np.zeros(n, dtype=bool)
        for e, x in spans:
            held[e:x + 1] = True
        mtm = np.concatenate([[1.0], np.cumprod(1 + daily_ret * 0.8 * held)])

        from core import metrics as core_m
        assert m.max_drawdown == pytest.approx(
            core_m.max_drawdown_pct(mtm), rel=1e-9)
        assert m.sharpe_ratio == pytest.approx(
            core_m.sharpe_ratio(daily_ret * held, periods_per_year=252, rf=0.03),
            rel=1e-9)
        # 旧口径 (逐笔收益 + 252/mean_hold 年化) 不同 → 修复生效
        old_sharpe = core_m.sharpe_ratio(np.array([0.08, 0.05]),
                                         periods_per_year=252 / 27.5, rf=0.03)
        assert abs(m.sharpe_ratio - old_sharpe) > 1e-3

    def test_trade_level_stats_from_core_formulas(self):
        trades = [self._trade(100, 110, 8.0, 10), self._trade(120, 130, -3.0, 10),
                  self._trade(140, 150, -2.0, 10)]
        m = self._engine()._compute_metrics_from_trades(trades, self._data(), {})
        from core import metrics as core_m
        assert m.profit_factor == pytest.approx(
            core_m.profit_factor([8.0, -3.0, -2.0]), rel=1e-12)
        assert m.win_rate == pytest.approx(100 / 3, rel=1e-12)
        assert m.num_trades == 3
        # 与 B 引擎同款 legacy 语义: 连亏段按 onset 间隔计 (2 连亏 → 1)
        assert m.max_consecutive_losses == 1
        assert m.avg_holding_days == pytest.approx(10.0)
        assert np.isfinite(m.sharpe_ratio) and np.isfinite(m.max_drawdown)

    def test_empty_trades_none_and_source_honesty(self):
        assert self._engine()._compute_metrics_from_trades(
            [], self._data(), {}) is None
        import inspect
        import optimization_engine
        src = inspect.getsource(optimization_engine)
        assert 'metrics_from_trades' in src          # 已接共享真相源
        assert '252.0 / mean_hold' not in src        # 逐笔冒充日频夏普已删
        assert "total_days = data.iloc[-1]['收盘']" not in src  # 死代码已删

    def test_evaluate_trade_filter_path_runs(self):
        engine = self._engine()
        n = 300
        data = self._data(n=n, seed=5)
        labels = pd.Series(['SIDEWAYS'] * n, dtype=object)
        for i in range(0, n, 3):          # CRASH 散点 100 天, max_consec=1
            labels.iloc[i] = 'CRASH'
        td = [TradeDetail(entry_idx=50, exit_idx=80, entry_price=10.0,
                          exit_price=11.0, pnl_pct=10.0, holding_days=30,
                          exit_reason='signal'),
              TradeDetail(entry_idx=150, exit_idx=170, entry_price=10.0,
                          exit_price=9.5, pnl_pct=-5.0, holding_days=20,
                          exit_reason='stop_loss')]

        class _Stub:
            def backtest_with_details(self, d, p):
                return BacktestMetrics(), td

        engine.backtester = _Stub()
        fit, det = engine.evaluate({}, {'000001': data},
                                   {'000001': labels}, 'CRASH')
        assert det.get('sample_count') == 1
        assert np.isfinite(fit) and fit > 0

    def test_evaluate_long_window_path_runs(self):
        engine = self._engine()
        data = self._data(n=300, seed=5)
        labels = pd.Series(['BULL'] * 200 + ['SIDEWAYS'] * 100, dtype=object)

        class _Stub:
            def backtest(self, d, p):
                assert len(d) < len(data)  # 确实按窗口切片后回测
                return BacktestMetrics(total_return=20.0, num_trades=5,
                                       sharpe_ratio=1.2, max_drawdown=8.0,
                                       win_rate=60.0)

        engine.backtester = _Stub()
        fit, det = engine.evaluate({}, {'000001': data},
                                   {'000001': labels}, 'BULL')
        assert det.get('sample_count', 0) >= 1
        assert np.isfinite(fit)
