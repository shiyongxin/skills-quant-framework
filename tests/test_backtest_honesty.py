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

from backtest_framework import BacktestEngine, StrategyFactory
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
# H9 (审计 B25): 引擎 A walk-forward 无预热 + OOS 未拼净值曲线
# ---------------------------------------------------------------------------

class TestH9WalkForwardOS:
    """H9: ① 测试窗口无预热数据 ② 各窗口结果未拼成 OOS 净值曲线。

    审计 B25: `test_data = data.iloc[train_end:test_end]` 是裸切片, 策略在
    A 内实时算 MA, 63 根窗口配 slow=20 只剩 43 根可用 bar; 且各窗口结果
    未拼接成 OOS 净值曲线 → 拿不到真正的 OOS 绩效 (OOS 被结构性削弱)。
    """

    @staticmethod
    def _data(n=750, seed=3):
        rng = np.random.default_rng(seed)
        close = 10 * np.cumprod(1 + rng.normal(0, 0.012, n))
        return pd.DataFrame({
            '日期': pd.date_range('2022-01-03', periods=n, freq='B'),
            '开盘': close * (1 + rng.normal(0, 0.003, n)),
            '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
        })

    @staticmethod
    def _recording_strategy(record, fast=5, slow=20):
        """记录每次调用时策略可见的历史长度 (裸切片 vs 带预热)"""
        def strat(d):
            record.append(len(d))
            if len(d) < slow + 1:
                return 0
            ma_fast = d['收盘'].rolling(fast).mean()
            ma_slow = d['收盘'].rolling(slow).mean()
            i = len(d) - 1
            if (ma_fast.iloc[i] > ma_slow.iloc[i]
                    and ma_fast.iloc[i - 1] <= ma_slow.iloc[i - 1]):
                return 1
            if (ma_fast.iloc[i] < ma_slow.iloc[i]
                    and ma_fast.iloc[i - 1] >= ma_slow.iloc[i - 1]):
                return -1
            return 0
        return strat

    # ---------- ① 测试窗口预热 ----------

    def test_strategy_sees_warmup_history(self):
        """带预热段 → 策略从窗口第一根起就有完整历史 (不再冷启动)。"""
        df = self._data(n=200)
        window = df.iloc[100:160]
        warm = df.iloc[40:100]

        seen = []
        BacktestEngine().run(window, self._recording_strategy(seen),
                             warmup_data=warm)
        # 首次策略调用发生在窗口第 2 根 (i=1) → 可见 预热60 + 窗口前2根
        assert seen[0] == len(warm) + 2
        assert seen[-1] == len(warm) + len(window)
        # 关键: 带预热时第一根就够算 MA20 (slow=20) → 无冷启动
        assert seen[0] >= 21

        seen_plain = []
        BacktestEngine().run(window, self._recording_strategy(seen_plain))
        # 裸切片: 第一根只有 2 行 → slow=20 之前算不出指标 (冷启动)
        assert seen_plain[0] == 2
        assert seen_plain[0] < 21

    def test_warmup_period_is_not_traded(self):
        """预热段只供策略看指标, 账户从窗口第一根空仓起步 (不交易预热段)。"""
        df = self._data(n=200)
        window = df.iloc[100:160]
        warm = df.iloc[40:100]
        res = BacktestEngine().run(window, self._recording_strategy([]),
                                   warmup_data=warm)
        trades = res['trades']
        if len(trades) > 0:
            assert trades['date'].min() >= window['日期'].iloc[0]
        # 账户初始资金未被预热期改动
        assert res['initial_cash'] == 100000

    def test_walk_forward_warms_oos_windows(self):
        """walk_forward 的 OOS 窗口带预热 → 冷启动不再压掉窗口交易。"""
        from backtest_framework import ParameterOptimizer
        df = self._data(n=750)

        with_warm = ParameterOptimizer.walk_forward(
            df, StrategyFactory.ma_cross, {'fast': [5], 'slow': [20]},
            train_period=252, test_period=63, warmup_period=60)
        without = ParameterOptimizer.walk_forward(
            df, StrategyFactory.ma_cross, {'fast': [5], 'slow': [20]},
            train_period=252, test_period=63, warmup_period=0)

        # 裸切片窗口: 63 根配 slow=20 → 多个窗口零交易; 带预热后窗口可交易
        assert without['oos']['trade_count'] < with_warm['oos']['trade_count']
        # 首个窗口之前没有历史 → 仍无交易 (如实降级, 不假装有预热)
        assert with_warm['windows'][0]['result']['trade_count'] == 0

    # ---------- ② OOS 净值曲线拼接 ----------

    def test_walk_forward_returns_oos_aggregate_and_curve(self):
        """walk_forward 现在给出真正的 OOS 整体绩效 + 拼接曲线。"""
        from backtest_framework import ParameterOptimizer
        df = self._data(n=750)
        res = ParameterOptimizer.walk_forward(
            df, StrategyFactory.ma_cross, {'fast': [5], 'slow': [20]},
            train_period=252, test_period=63)

        assert set(res.keys()) == {'windows', 'oos', 'oos_equity_curve'}
        assert len(res['windows']) == res['oos']['num_windows'] > 0
        curve = res['oos_equity_curve']
        assert len(curve) > 0
        assert list(curve['date']) == sorted(curve['date'])   # 日期单调
        assert curve['value'].iloc[0] == 100000.0              # 起点 = 初始资金
        for key in ('total_return', 'annualized_return', 'sharpe_ratio',
                    'max_drawdown', 'trade_count', 'win_rate',
                    'profit_factor', 'oos_bars', 'period_start', 'period_end'):
            assert key in res['oos']

    def test_oos_total_return_equals_compounded_windows(self):
        """拼接口径: OOS 总收益 = 各窗收益逐段复利 (不是各窗收益平均)。"""
        from backtest_framework import ParameterOptimizer
        df = self._data(n=750)
        res = ParameterOptimizer.walk_forward(
            df, StrategyFactory.ma_cross, {'fast': [5], 'slow': [20]},
            train_period=252, test_period=63)

        compounded = 1.0
        for w in res['windows']:
            compounded *= (1 + w['result']['total_return'] / 100)
        expected = (compounded - 1) * 100
        assert res['oos']['total_return'] == pytest.approx(expected, rel=1e-9)
        # 曲线末值与总收益自洽
        final = res['oos_equity_curve']['value'].iloc[-1]
        assert final == pytest.approx(100000 * compounded, rel=1e-9)

    def test_oos_curve_covers_all_window_bars(self):
        """拼接曲线覆盖各窗口全部 OOS bar (窗口边界不丢段)。"""
        from backtest_framework import ParameterOptimizer
        df = self._data(n=750)
        res = ParameterOptimizer.walk_forward(
            df, StrategyFactory.ma_cross, {'fast': [5], 'slow': [20]},
            train_period=252, test_period=63)

        curve = res['oos_equity_curve']
        window_bars = sum(len(w['result']['equity_curve']) for w in res['windows'])
        # 每窗额外补 1 个起点 (窗口首根 bar 空仓值) → 起点数 = 窗口数
        assert len(curve) == window_bars + len(res['windows'])
        assert res['oos']['oos_bars'] == len(curve) - 1

    def test_run_without_warmup_is_unchanged(self):
        """无预热时 run() 与旧版逐位一致 (黄金快照不受影响)。"""
        df = self._data(n=300)
        res = BacktestEngine().run(df, StrategyFactory.ma_cross(fast=5, slow=20))
        assert res['trade_count'] >= 0
        assert res['final_value'] > 0
        # 显式传空预热 = 不传
        res2 = BacktestEngine().run(df, StrategyFactory.ma_cross(fast=5, slow=20),
                                    warmup_data=pd.DataFrame())
        assert res2['final_value'] == res['final_value']
        assert res2['trade_count'] == res['trade_count']


# ---------------------------------------------------------------------------
# H7 (审计 B14): 回测引擎无流动性/容量约束
# ---------------------------------------------------------------------------

class TestH7CapacityConstraint:
    """H7: 成交量只用于信号打分, 从不做成交容量校验。

    审计 B14: 引擎可以在日成交额百万的票上买上亿元而不作任何惩罚 (↑乐观)。
    修复: 单笔买入金额 ≤ 当日成交额 × 参与率 (默认 5%), 不足则按上限部分成交。
    """

    # ---------- 共享助手 ----------

    def test_capacity_limit_notional_rules(self):
        from execution_model import capacity_limit_notional
        # 参与率关闭 → 不限制
        assert capacity_limit_notional(1e8, 0.0) is None
        assert capacity_limit_notional(1e8, None) is None
        # 数据缺失 → 不限制 (调用方如实跳过)
        assert capacity_limit_notional(None, 0.05) is None
        # 当日零成交 → 上限 0 (买不进, 不是"不限制")
        assert capacity_limit_notional(0.0, 0.05) == 0.0
        # 正常: 成交额 × 参与率
        assert capacity_limit_notional(2e7, 0.05) == pytest.approx(1e6)

    def test_bar_turnover_amount_sources(self):
        from execution_model import bar_turnover_amount
        # 有 成交额 → 直接用
        assert bar_turnover_amount({'成交额': 3e7, '成交量': 1e6}) == 3e7
        # 成交额为 0 (停牌/无成交) → 0.0 (不是 None)
        assert bar_turnover_amount({'成交额': 0.0, '成交量': 0.0}) == 0.0
        # 缺 成交额 → 成交量 × 价格 近似
        assert bar_turnover_amount({'成交量': 2e6, '收盘': 10.0}) == pytest.approx(2e7)
        # 两列都缺 → None (无法检查)
        assert bar_turnover_amount({'收盘': 10.0}) is None

    # ---------- 引擎 A ----------

    @staticmethod
    def _a_data(volume=1e6, n=60):
        close = np.full(n, 10.0)
        return pd.DataFrame({
            '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
            '开盘': close.copy(), '最高': close * 1.01, '最低': close * 0.99,
            '收盘': close.copy(), '成交量': np.full(n, volume),
        })

    @staticmethod
    def _a_buy_at(df, bar=10):
        def strat(d):
            return 1 if len(d) == bar + 1 else 0
        return strat

    def test_engine_a_buy_capped_by_daily_turnover(self):
        """低量票: 买入金额被截到 当日成交额×5% (部分成交)。"""
        from backtest_framework import BacktestEngine, PositionConfig
        # 日成交额 = 1e6 股 × 10 元 = 1000 万 → 5% 上限 = 50 万 → 5 万股
        df = self._a_data(volume=1e6)
        res = BacktestEngine(initial_cash=1000000).run(
            df, self._a_buy_at(df), symbol='600519')
        buys = res['trades'][res['trades']['action'] == 'buy']
        assert len(buys) == 1
        # 上限按**裸开盘价**折股数 (滑点在成交价上另计): 50 万 ÷ 10 元 = 5 万股
        assert buys.iloc[0]['shares'] == 50000
        assert buys.iloc[0]['shares'] * 10.0 <= 1e7 * 0.05 + 1e-6

    def test_engine_a_unconstrained_when_participation_zero(self):
        """participation=0 → 关闭约束 (退回旧行为, 数值中性)。"""
        from backtest_framework import BacktestEngine, PositionConfig
        df = self._a_data(volume=1e6)
        res = BacktestEngine(
            initial_cash=1000000,
            position_config=PositionConfig(max_volume_participation=0.0)
        ).run(df, self._a_buy_at(df), symbol='600519')
        buys = res['trades'][res['trades']['action'] == 'buy']
        notional = buys.iloc[0]['shares'] * buys.iloc[0]['price']
        assert notional > 1e7 * 0.05               # 未被截断

    def test_engine_a_zero_volume_day_cannot_buy(self):
        """当日零成交 → 买不进 (与"不限制"区别开)。"""
        from backtest_framework import BacktestEngine
        df = self._a_data(volume=1e6)
        df.loc[11, '成交量'] = 0.0                  # 入场日无量
        res = BacktestEngine(initial_cash=1000000).run(
            df, self._a_buy_at(df), symbol='600519')
        assert len(res['trades']) == 0

    def test_engine_a_reports_capacity_not_checked(self):
        """数据缺成交额/成交量 → 如实标记 capacity_checked=False。"""
        from backtest_framework import BacktestEngine
        df = self._a_data()
        df = df.drop(columns=['成交量'])
        res = BacktestEngine(initial_cash=1000000).run(
            df, self._a_buy_at(df), symbol='600519')
        assert res['capacity_checked'] is False

    # ---------- 引擎 B ----------

    @staticmethod
    def _b_signals(df):
        sig = pd.Series(0, index=df.index)
        sig.iloc[10] = 1
        return sig

    def test_engine_b_position_capped_by_daily_turnover(self):
        """低量票: 引擎 B 的仓位比例被容量上限截断 (部分成交)。"""
        vb = VectorizedBacktester()
        df = self._a_data(volume=1e6)              # 日成交额 1000 万
        df = vb._compute_indicators(df, {})
        m, det = vb._simulate_trades(df, self._b_signals(df),
                                     {'capital': 1_000_000}, return_details=True)
        assert len(det) == 1
        # 名义 80 万 (position_size_pct 0.8) → 上限 50 万 → 比例 0.5
        assert det[0].position_pct == pytest.approx(0.5)
        assert det[0].position_pct < 0.8

    def test_engine_b_unconstrained_when_participation_zero(self):
        """引擎 B participation=0 → 关闭约束 (退回旧行为)。"""
        vb = VectorizedBacktester()
        df = self._a_data(volume=1e6)
        df = vb._compute_indicators(df, {})
        m, det = vb._simulate_trades(df, self._b_signals(df),
                                     {'capital': 1_000_000,
                                      'max_volume_participation': 0.0},
                                     return_details=True)
        assert det[0].position_pct == pytest.approx(0.8)

    def test_engine_b_zero_volume_entry_day_cannot_buy(self):
        """当日零成交 → 不成交 (引擎 B 与 A 同口径)。"""
        vb = VectorizedBacktester()
        df = self._a_data(volume=1e6)
        df.loc[11, '成交量'] = 0.0
        df = vb._compute_indicators(df, {})
        m, det = vb._simulate_trades(df, self._b_signals(df),
                                     {'capital': 1_000_000}, return_details=True)
        assert len(det) == 0

    def test_engine_b_golden_unaffected_by_capacity(self):
        """引擎 B 黄金数据: 入场日成交额远高于名义额 → 容量约束不触发。

        (两笔入场日成交额 ≈ 4856 万 / 4156 万, 5% 上限 242 万 / 207 万
         > 名义 80 万 → 不截断, 黄金快照逐位不变)
        """
        m = VectorizedBacktester().backtest(TestGoldenMetrics._big(), {})
        assert m.total_return == pytest.approx(12.99316444226517, rel=1e-6)
        assert m.num_trades == 2


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
        # 审计 B14/H7 后更新 (2026-10-26): 默认成交容量约束 (单笔 ≤ 当日
        # 成交额 × 5%) 生效 —— 黄金数据里 10 笔买入有 3 笔落在低量日被截断
        # (2022-02-03: 97300→93100 股; 2022-08-04: 89800→64800 股;
        #  2022-10-26: 85700→71800 股), 仓位变小 → 总收益 20.03%→20.62%,
        # 夏普 0.810→0.838, 回撤 14.19%→14.00%。
        # 数值中性证明: 显式关闭容量约束 (participation=0) 时与修复前逐位一致
        # (见 test_engine_a_golden_without_capacity_constraint) → 漂移只来自
        # 容量约束本身, 与撮合/指标口径无关。
        assert res['total_return'] == pytest.approx(20.616880284178162, rel=1e-6)
        # core 统一口径: MDD 为正值百分比
        assert res['max_drawdown'] == pytest.approx(13.999296006248338, rel=1e-6)
        assert res['trade_count'] == 9
        assert res['sharpe_ratio'] == pytest.approx(0.8380161593133549, rel=1e-6)
        assert len(res['trades']) == 19
        assert res['profit_factor'] == pytest.approx(1.2589570136340924, rel=1e-6)
        # 审计 M1 (B48): 连胜/连亏改为**交易序列**口径 (旧为日频净值口径,
        # 旧值 35/4) —— 9 笔平仓的 pnl 序列为
        # [0.396, -3.8, -4.952, -0.544, 1.511, -0.901, 15.23, -2.101, -1.315]
        # → 连亏 3 笔 (-3.8/-4.952/-0.544), 连胜 1 笔 (0.396/1.511/15.23 各自独立)
        assert res['max_consecutive_losses'] == 3
        assert res['max_consecutive_wins'] == 1
        assert res['win_rate'] == pytest.approx(100 / 3, rel=1e-9)
        # 日频连涨/连跌 (独立且诚实的字段名; 持平 bar 不算涨)
        assert res['max_consecutive_up_days'] == 8
        assert res['max_consecutive_down_days'] == 4

    def test_engine_a_golden_without_capacity_constraint(self):
        """关闭容量约束 (participation=0) → 与修复前逐位一致 (数值中性证明)。"""
        from backtest_framework import PositionConfig
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

        res = BacktestEngine(
            initial_cash=1000000,
            position_config=PositionConfig(max_volume_participation=0.0)
        ).run(big, strat, symbol='600519')
        assert res['total_return'] == pytest.approx(20.02675523695121, rel=1e-6)
        assert res['sharpe_ratio'] == pytest.approx(0.8098904708567016, rel=1e-6)
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
        # 连亏统计 (审计 B48/M1): 统一为**交易序列**上的真实连亏笔数 ——
        # 旧实现用 np.diff(np.where(is_loss)) 统计的是"亏损起始点之间的间隔",
        # 既不是连亏笔数也不是连亏段数 (两笔相邻亏损恒报 1, 而两笔不相邻的
        # 亏损反而报 2) → 现由 core.consecutive_streaks 给出正确口径 2。
        assert m.max_consecutive_losses == 2
        assert m.max_consecutive_wins == 1
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
            def backtest(self, d, p, **kw):
                assert len(d) < len(data)  # 确实按窗口切片后回测
                # 审计 M4: 窗口前历史段 (指标预热) 必须传入 —— 否则窗口内
                # 指标全是 NaN → 信号恒 0 → 该窗静默失效
                assert kw.get('history') is not None
                return BacktestMetrics(total_return=20.0, num_trades=5,
                                       sharpe_ratio=1.2, max_drawdown=8.0,
                                       win_rate=60.0)

        engine.backtester = _Stub()
        fit, det = engine.evaluate({}, {'000001': data},
                                   {'000001': labels}, 'BULL')
        assert det.get('sample_count', 0) >= 1
        assert np.isfinite(fit)


# ---------------------------------------------------------------------------
# 审计 M1 (D-backtest.md B48 / 4.2 口径差异清单): 残余指标口径分歧
# ---------------------------------------------------------------------------
class TestM1MetricConventions:
    """残余指标口径统一 (审计 M1 / B48)。

    - win_rate: 两引擎公式其实已一致 (盈利笔/全部笔), 真正分歧在 **breakeven
      (pnl==0) 的归类** → 统一为"计入分母但不算赢"(core.win_rate)。
    - max_consecutive_losses: 旧引擎 A 统计在**日频净值**序列上, 旧引擎 B 统计在
      **交易**序列上 (同名字段两套口径) → 统一为交易序列 (core.consecutive_streaks)。
    - 附带修掉旧引擎 B 的连亏统计 bug: np.diff(np.where(is_loss)) 统计的是
      "亏损起始点之间的间隔", 既不是连亏笔数也不是连亏段数 (两笔相邻亏损恒报 1,
      两笔不相邻的亏损反而报 2)。
    """

    @staticmethod
    def _core():
        from core import metrics as core_m
        return core_m

    # --- core 单一真相源语义 ---
    def test_core_win_rate_breakeven_in_denominator_not_a_win(self):
        core_m = self._core()
        assert core_m.win_rate([]) == 0.0
        assert core_m.win_rate([1.0, 0.0, -1.0]) == pytest.approx(100 / 3)
        assert core_m.win_rate([1.0, 2.0]) == pytest.approx(100.0)
        assert core_m.win_rate([-1.0, -2.0]) == 0.0

    def test_core_consecutive_streaks_trade_level(self):
        core_m = self._core()
        assert core_m.consecutive_streaks([]) == (0, 0)
        assert core_m.consecutive_streaks([1.0, 1.0, -1.0, -1.0, -1.0, 0.0, 2.0]) \
            == (2, 3)
        # breakeven 打断两段 (既不算赢也不算亏)
        assert core_m.consecutive_streaks([-1.0, -1.0, 0.0, -1.0]) == (0, 2)
        assert core_m.consecutive_streaks([0.0, 0.0]) == (0, 0)

    def test_core_streak_no_longer_gap_based(self):
        """锁死旧实现的 gap bug: 相邻两笔亏损旧报 1, 不相邻两笔旧报 2。"""
        core_m = self._core()
        adjacent = core_m.consecutive_streaks([-1.0, -2.0])[1]
        separated = core_m.consecutive_streaks([-1.0, 5.0, -2.0])[1]
        assert adjacent == 2      # 旧实现给 1
        assert separated == 1    # 旧实现给 2

    def test_core_max_consecutive_true(self):
        core_m = self._core()
        assert core_m.max_consecutive_true([True, True, False, True]) == 2
        assert core_m.max_consecutive_true([False, False]) == 0
        assert core_m.max_consecutive_true([]) == 0

    # --- 引擎 A ---
    def test_engine_a_streaks_are_trade_level(self):
        core_m = self._core()
        big = TestGoldenMetrics._big()
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
            return 1 if up else (-1 if down else 0)

        res = BacktestEngine(initial_cash=1000000).run(big, strat,
                                                       symbol='600519')
        sells = res['trades'][res['trades']['action'] == 'sell']
        pnls = sells['pnl_pct'].tolist()
        wins, losses = core_m.consecutive_streaks(pnls)
        assert res['max_consecutive_wins'] == wins
        assert res['max_consecutive_losses'] == losses
        # 旧口径 (日频净值连跌) 与交易级不同 → 证明基准确实换了
        eq = res['equity_curve']['value']
        legacy_down = core_m.max_consecutive_true((eq < eq.shift(1)).tolist())
        assert res['max_consecutive_losses'] != legacy_down or legacy_down == 0

    def test_engine_a_daily_streaks_use_honest_names(self):
        big = TestGoldenMetrics._big()
        res = BacktestEngine(initial_cash=1000000).run(
            big, lambda d: 0, symbol='600519')
        assert 'max_consecutive_up_days' in res
        assert 'max_consecutive_down_days' in res
        # 持平 bar 既不算涨也不算跌 (旧实现 value>=prev 把持平日算成涨)
        eq = res['equity_curve']['value']
        strict_up = core_m_strict_up(eq)
        assert res['max_consecutive_up_days'] == strict_up
        assert res['max_consecutive_up_days'] <= len(eq)

    # --- 引擎 B ---
    def test_engine_b_streaks_match_core(self):
        core_m = self._core()
        data = TestGoldenMetrics._big()
        metrics, details = VectorizedBacktester().backtest_with_details(data, {})
        pnls = [d.pnl_pct for d in details]
        wins, losses = core_m.consecutive_streaks(pnls)
        assert metrics.max_consecutive_wins == wins
        assert metrics.max_consecutive_losses == losses
        # B 现在也提供连胜笔数 (旧版字段缺失 → 与 A 不对等)
        assert hasattr(metrics, 'max_consecutive_wins')

    def test_cross_engine_same_trades_same_streaks(self):
        """同一组交易 → A/B 引擎给出的连亏/连胜笔数必须一致 (口径统一验证)。"""
        core_m = self._core()
        big = TestGoldenMetrics._big()
        ma5 = pd.Series(big['收盘']).rolling(5).mean()
        ma20 = pd.Series(big['收盘']).rolling(20).mean()

        def strat(d):
            i = len(d) - 1
            if i < 21:
                return 0
            up = (ma5.iloc[i] > ma20.iloc[i]
                  and ma5.iloc[i - 1] <= ma20.iloc[i - 1])
            down = (ma5.iloc[i] < ma20.iloc[i]
                    and ma20.iloc[i - 1] >= ma20.iloc[i - 1])
            return 1 if up else (-1 if down else 0)

        res = BacktestEngine(initial_cash=1000000).run(big, strat,
                                                       symbol='600519')
        trades = res['trades']
        sells = trades[trades['action'] == 'sell']
        pnls = sells['pnl_pct'].tolist()
        wins, losses = core_m.consecutive_streaks(pnls)

        # 把 A 的同一组交易喂给 B 的共享指标函数 → 必须得到同样的连段数
        date_idx = {d: i for i, d in enumerate(big['日期'])}
        spans = []
        pending = None
        for _, row in trades.iterrows():
            idx = date_idx.get(row['date'])
            if row['action'] == 'buy':
                pending = idx
            elif pending is not None and idx is not None:
                spans.append((pending, idx))
                pending = None
        m = metrics_from_trades(
            np.array(pnls), np.array([1.0] * len(pnls)),
            spans, big['收盘'].to_numpy(dtype=float),
            big['开盘'].to_numpy(dtype=float), 0.8)
        assert m.max_consecutive_losses == losses
        assert m.max_consecutive_wins == wins
        assert m.win_rate == pytest.approx(res['win_rate'])

    # --- 引擎 D ---
    def test_engine_d_win_rate_keeps_numeric_semantics(self):
        import inspect
        src = inspect.getsource(ReversalBacktester)
        assert '_core_metrics.win_rate' in src

    def test_engine_d_win_rate_identity(self):
        data = mk_data(n=120, seed=7)
        rb = ReversalBacktester()
        rb.get_stock_data = lambda code, days=365: data
        result = rb.backtest_single('000001', '测试')
        if result is not None and result.total_trades > 0:
            # 口径不变: 盈利配对 / 全部配对 (breakeven 计分母不算赢)
            assert result.win_rate == pytest.approx(
                result.win_trades / result.total_trades * 100)

    # --- 源码级门禁: 胜率/连段不得在引擎内联 ---
    def test_no_inline_win_rate_or_streak_computation(self):
        import pathlib
        skills = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills'
        forbidden = ('win_rate = len(', 'win_rate = (len(', 'win_rate = len(wins)',
                      'is_loss = pnl_arr', 'loss_streaks =')
        offenders = []
        for path in skills.rglob('*.py'):
            if path.name == 'metrics.py' and path.parent.name == 'core':
                continue
            text = path.read_text(encoding='utf-8')
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.name}: {token}")
        assert not offenders, f"胜率/连段统计必须走 core/metrics: {offenders}"

    def test_engines_route_win_rate_and_streaks_through_core(self):
        import inspect
        from backtest_framework import BacktestEngine as _A
        from vectorized_backtest import metrics_from_trades as _m
        a_src = inspect.getsource(_A)
        assert '_core_metrics.win_rate' in a_src
        assert '_core_metrics.consecutive_streaks' in a_src
        assert '_core_metrics.win_rate' in inspect.getsource(_m)
        assert '_core_metrics.consecutive_streaks' in inspect.getsource(_m)


def core_m_strict_up(eq):
    """辅助: 日频净值严格上涨的连段长度 (持平不算涨)。"""
    from core import metrics as core_m
    return core_m.max_consecutive_true((eq > eq.shift(1)).tolist())
