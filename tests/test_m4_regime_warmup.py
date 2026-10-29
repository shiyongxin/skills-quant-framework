# -*- coding: utf-8 -*-
"""短体制窗口冷启动 + 短窗出场失效必须修复 (审计 M4, 批次 2)

复验结论 (2026-10-29): 审计 M4 的**方向属实、细节需订正**:

- 审计写的 `min_hold_end` **全仓不存在** (早已改名/删除) → 真正的机制是
  `min_holding_days` (引擎 B 的出场闸门: `l >= min_holding` 才允许止盈/
  移动止损/卖讯触发)。
- 冷启动属实且比审计记的更宽: 指标周期由**参数**决定 (`ma_slow` 15~120),
  而预热长度曾写死 60 根 → `ma_slow` > 60 时窗口内指标全 NaN → 信号恒 0 →
  **该窗口测不出任何东西** (既不报错也不产生交易) → 优化器把参数空间
  `ma_slow` 的上半个区间**静默当成不可用**。
  受影响路径有两条: ① `walk_forward` (全局/体制/稳健优化的主路径)
  ② 连续体制窗回测 (`_backtest_regime_windows`)。

门禁:
- 行为: 预热长度按参数 (`required_warmup_bars`); 默认参数 → 60 (零回归)
- 行为: 长周期参数 (`ma_slow=120`) 的窗口**真的能产生交易** (旧实现: 不能)
- 行为: 体制窗回测传入窗口前历史段 (指标预热)
- 行为: 窗口比 `min_holding_days` 短 → 跳过并**记账** (不静默)
- 源码级: 预热长度不得再写死
"""
import inspect

import numpy as np
import pandas as pd

from vectorized_backtest import (VectorizedBacktester, required_warmup_bars,
                                 warmup_bars)

_ENGINE = None


def _engine_mod():
    global _ENGINE
    if _ENGINE is None:
        import optimization_engine
        _ENGINE = optimization_engine
    return _ENGINE


def _frame(n=400, seed=3):
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.02, n))
    idx = pd.date_range('2023-01-02', periods=n, freq='B')
    return pd.DataFrame({
        '日期': idx,
        '开盘': close * 0.995,
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.uniform(1e6, 5e6, n),
        '成交额': rng.uniform(1e7, 5e7, n),
    })


class TestRequiredWarmup:
    def test_default_params_keep_legacy_60(self):
        """默认参数 → 60 根 (与旧实现逐位一致, 零回归)。"""
        assert required_warmup_bars({}) == 60
        assert required_warmup_bars({'min_holding_days': 5}) == 60

    def test_long_ma_slow_requires_more(self):
        """`ma_slow` 可达 120 → 预热必须 ≥ 120 (否则窗口内指标全 NaN)。"""
        assert required_warmup_bars({'ma_slow': 120}) >= 120
        assert required_warmup_bars({'ma_slow': 120}) > 60

    def test_scales_with_parameter(self):
        assert required_warmup_bars({'ma_slow': 60}) >= 60
        assert (required_warmup_bars({'ma_slow': 120})
                > required_warmup_bars({'ma_slow': 60}))

    def test_signal_mask_unchanged(self):
        """信号掩码公式不受影响 (只改"需要多少历史")。"""
        assert warmup_bars(300) == 60
        assert warmup_bars(30) == 10


class TestWalkForwardWarmup:
    def test_history_length_follows_params(self):
        """walk_forward 的窗口前历史段长度按参数所需 (旧: 写死 60)。"""
        data = _frame(750)
        vb = VectorizedBacktester()
        seen = []
        orig = vb.backtest

        def spy(data_, params_, **kw):
            hist = kw.get('history')
            seen.append(0 if hist is None else len(hist))
            return orig(data_, params_, **kw)

        vb.backtest = spy
        vb.walk_forward(data, {'min_holding_days': 5}, train_days=300,
                        test_days=150, step_days=150)
        assert seen and all(n == 60 for n in seen)   # 默认参数 → 60 (不变)

        seen.clear()
        vb.walk_forward(data, {'min_holding_days': 5, 'ma_slow': 120},
                        train_days=300, test_days=150, step_days=150)
        assert seen and all(n >= 120 for n in seen)  # 长周期 → 更长预热

    def test_long_period_window_can_trade(self):
        """`ma_slow=120` 的窗口**能产生交易** (旧实现: 恒 0 交易 → 静默失效)。"""
        data = _frame(400)
        vb = VectorizedBacktester()
        params = {'ma_slow': 120, 'ma_fast': 5, 'ma_mid': 10,
                  'min_holding_days': 1, 'stop_loss_pct': 0.05,
                  'take_profit_pct': 0.10}
        res = vb.walk_forward(data, params, train_days=200, test_days=100,
                              step_days=100)
        assert res, "窗口结果为空"
        # 旧实现: 指标全 NaN → 信号恒 0 → 0 交易 (窗口静默失效)
        assert any(m.num_trades > 0 for m in res), (
            "长周期参数的窗口仍测不出交易 → 冷启动未修复")


class TestRegimeWindowWarmup:
    def test_regime_window_receives_history(self):
        """连续体制窗回测必须传入窗口前历史段 (指标预热)。"""
        mod = _engine_mod()
        data = _frame(300)
        # 体制段之前留一段别的体制 → 该段才有"窗口前历史"可取
        labels = pd.Series(['SIDEWAYS'] * 100 + ['BULL'] * 200, dtype=object)

        seen = {}

        class _Stub:
            def backtest(self, d, p, **kw):
                seen['len_window'] = len(d)
                seen['history'] = kw.get('history')
                from vectorized_backtest import BacktestMetrics
                return BacktestMetrics(total_return=10.0, num_trades=3,
                                       sharpe_ratio=1.0, max_drawdown=5.0,
                                       win_rate=50.0)

        ev = mod.FitnessEvaluator()
        ev.backtester = _Stub()
        ev.evaluate({}, {'600000': data}, {'600000': labels}, 'BULL')
        assert seen.get('history') is not None, (
            "体制窗未传历史段 → 窗口内指标全 NaN → 冷启动")
        assert len(seen['history']) > 0
        assert seen['len_window'] < len(data)

    def test_short_window_is_skipped_and_counted(self):
        """窗口比 min_holding_days 短 → 出场规则无法检验 → 跳过并记账。"""
        mod = _engine_mod()
        data = _frame(300)
        labels = pd.Series(['BULL'] * 200 + ['SIDEWAYS'] * 100, dtype=object)

        class _Stub:
            def backtest(self, d, p, **kw):
                from vectorized_backtest import BacktestMetrics
                return BacktestMetrics(total_return=10.0, num_trades=3,
                                       sharpe_ratio=1.0, max_drawdown=5.0,
                                       win_rate=50.0)

        ev = mod.FitnessEvaluator()
        ev.backtester = _Stub()
        # min_holding_days=250 > 窗口长度 (200) → 全部窗口应被跳过
        _, details = ev.evaluate({'min_holding_days': 250},
                                 {'600000': data},
                                 {'600000': labels}, 'BULL')
        stats = details.get('regime_window_stats') or {}
        assert stats.get('skipped_short', 0) >= 1, (
            "过短窗口未被跳过 → 出场规则在窗口内永不触发却仍计入适应度")
        assert details.get('sample_count', 0) == 0

    def test_window_stats_visible(self):
        """体制窗统计必须可见 (这个体制到底测了多少东西)。"""
        mod = _engine_mod()
        data = _frame(300)
        labels = pd.Series(['BULL'] * 200 + ['SIDEWAYS'] * 100, dtype=object)

        class _Stub:
            def backtest(self, d, p, **kw):
                from vectorized_backtest import BacktestMetrics
                return BacktestMetrics(total_return=10.0, num_trades=3,
                                       sharpe_ratio=1.0, max_drawdown=5.0,
                                       win_rate=50.0)

        ev = mod.FitnessEvaluator()
        ev.backtester = _Stub()
        _, details = ev.evaluate({}, {'600000': data},
                                 {'600000': labels}, 'BULL')
        stats = details.get('regime_window_stats')
        assert stats is not None
        assert 'n_windows' in stats and 'skipped_short' in stats


class TestSourceHonesty:
    def test_warmup_length_not_hardcoded(self):
        """预热长度不得再写死 (审计 M4: 指标周期由参数决定)。"""
        src = inspect.getsource(VectorizedBacktester.walk_forward)
        assert 'required_warmup_bars' in src
        assert 'WARMUP_MAX_BARS):start' not in src, (
            "walk_forward 仍按固定 60 根取历史段 → 长周期参数窗口静默失效")

    def test_regime_path_uses_required_warmup(self):
        src = inspect.getsource(_engine_mod().FitnessEvaluator
                                ._backtest_regime_windows)
        assert 'required_warmup_bars' in src
        assert 'history=' in src
