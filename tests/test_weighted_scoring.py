"""E-P1 死维度接线 (P1-1): vectorized_backtest 加权评分 + 优化器注入.

审计 E-optimization-portfolio #19: w_trend/w_momentum/w_risk/w_performance/
score_buy_threshold/score_sell_threshold 六维原为噪声维度 (fitness 从不读取)。
本批: 评分制实现进 _generate_signals (use_weighted_scoring 开关, 移植已删
web_backtest 评分语义) + 优化器评估路径注入开关 (默认 True)。
"""
import numpy as np
import pandas as pd
import pytest

from vectorized_backtest import VectorizedBacktester, weighted_factor_scores
from optimization_config import OptimizationConfig


def _ohlcv(n=150, trend=0.004, seed=7):
    rng = np.random.default_rng(seed)
    close = 10.0 * np.cumprod(1 + rng.normal(trend, 0.01, n))
    prev = np.concatenate([[10.0], close[:-1]])
    open_ = prev * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    dates = pd.date_range('2024-01-01', periods=n, freq='B')
    return pd.DataFrame({
        '日期': dates, '开盘': open_, '最高': high, '最低': low,
        '收盘': close,
        '成交量': rng.integers(100_000, 1_000_000, n).astype(float),
    })


def _swing_ohlcv(n=240, seed=3):
    """带完整上升/回调波段的确定性行情 — 两引擎均能产生交易."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    cyc = 0.07 * np.sin(2 * np.pi * t / 48)
    base = 10 * (1 + 0.0008 * t)
    close = base * (1 + cyc) * np.cumprod(1 + rng.normal(0, 0.004, n))
    prev = np.concatenate([[10.0], close[:-1]])
    open_ = prev * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    return pd.DataFrame({
        '日期': pd.date_range('2023-01-02', periods=n, freq='B'),
        '开盘': open_, '最高': high, '最低': low, '收盘': close,
        '成交量': rng.integers(100_000, 1_000_000, n).astype(float),
    })


def _indicator_df():
    """手工构造指标列, 便于对评分公式做逐项断言."""
    return pd.DataFrame({
        '收盘':       [9.9, 11.0, 10.0],
        'ma_fast':    [9.8, 11.0, 9.0],
        'ma_mid':     [9.9, 10.5, 9.5],
        'ma_slow':    [10.0, 10.0, 9.7],
        'macd':       [-1.0, 1.0, -2.0],
        'macd_signal': [-0.5, 0.5, -1.5],
        'rsi':        [80.0, 25.0, 60.0],
        'k':          [15.0, 65.0, 50.0],
        'd':          [25.0, 55.0, 55.0],
        'bb_lower':   [8.0, 10.0, 9.0],
        'bb_upper':   [10.0, 12.0, 11.0],
    })


class TestWeightedFactorScores:
    """评分公式逐项等价 (对齐已删 web_backtest.calculate_weighted_score)."""

    def test_formula_defaults(self):
        buy, sell = weighted_factor_scores(_indicator_df(), {})

        # row0 空头态: trend=0, mom=10(rsi80), risk=5(布林0.95), perf=50(前收NaN)
        assert buy.iloc[0] == pytest.approx(
            (30 * 0 + 25 * 10 + 15 * 5 + 30 * 50) / 100)
        # row1 多头态: 排列40+macd40+上穿20=100, rsi25→90+kdj10=100,
        # bb pos0.5→50, ret5=11/9.9-1 → 50+500*0.1111>100 → clip 100
        assert buy.iloc[1] == pytest.approx(
            (30 * 100 + 25 * 100 + 15 * 50 + 30 * 100) / 100)
        # 卖方 = 100 - 买方 (逐行镜像)
        pd.testing.assert_series_equal(sell, 100 - buy)

    def test_trend_exclusive_elif_semantics(self):
        # MA 排列成立时不再叠加 fast>slow 的 +20 (原版 elif 互斥)
        buy, _ = weighted_factor_scores(_indicator_df(), {'w_trend': 100,
                                                          'w_momentum': 0,
                                                          'w_risk': 0,
                                                          'w_performance': 0})
        assert buy.iloc[1] == pytest.approx(100)  # 而非 120/100*

    def test_weights_change_score(self):
        base, _ = weighted_factor_scores(_indicator_df(), {})
        # 表现权重独大 (wsum=100): row1 perf=100 → 99.5 ≠ 基线 92.5
        tilted, _ = weighted_factor_scores(_indicator_df(), {
            'w_trend': 1, 'w_momentum': 1, 'w_risk': 1, 'w_performance': 97})
        assert base.iloc[1] == pytest.approx(92.5)
        assert tilted.iloc[1] == pytest.approx(
            (1 * 100 + 1 * 100 + 1 * 50 + 97 * 100) / 100)
        assert tilted.iloc[1] != pytest.approx(base.iloc[1])

    def test_scores_in_unit_range(self):
        buy, sell = weighted_factor_scores(_indicator_df(), {})
        for s in (buy, sell):
            assert s.between(0, 100).all()


class TestGenerateSignalsDualMode:
    def test_flag_off_is_identical_to_default(self):
        bt = VectorizedBacktester()
        df = _ohlcv()
        ind = bt._compute_indicators(df, {})
        s_default = bt._generate_signals(ind, {})
        s_off = bt._generate_signals(ind, {'use_weighted_scoring': False})
        pd.testing.assert_series_equal(s_default, s_off)

    def test_weighted_mode_differs_from_vote_mode(self):
        bt = VectorizedBacktester()
        df = _ohlcv()
        s_vote = bt._generate_signals(bt._compute_indicators(df, {}), {})
        s_weighted = bt._generate_signals(
            bt._compute_indicators(df, {}), {'use_weighted_scoring': True})
        assert not s_vote.equals(s_weighted)

    def test_score_thresholds_gate_signals(self):
        bt = VectorizedBacktester()
        df = _ohlcv()
        ind = bt._compute_indicators(df, {})
        blocked = bt._generate_signals(ind, {
            'use_weighted_scoring': True,
            'score_buy_threshold': 101, 'score_sell_threshold': 101})
        assert (blocked == 0).all()

        allowed = bt._generate_signals(ind, {
            'use_weighted_scoring': True,
            'score_buy_threshold': 50, 'score_sell_threshold': 101})
        warmup = min(60, max(10, len(df) // 3))
        assert (allowed.iloc[warmup:] == 1).sum() > 0

    def test_scores_have_no_lookahead(self):
        bt = VectorizedBacktester()
        df = _ohlcv()
        p = {'use_weighted_scoring': True}
        buy1, sell1 = weighted_factor_scores(bt._compute_indicators(df, p), p)

        df2 = df.copy()
        df2.loc[df2.index[-1], '收盘'] *= 1.05
        buy2, sell2 = weighted_factor_scores(bt._compute_indicators(df2, p), p)
        pd.testing.assert_series_equal(buy1.iloc[:-1], buy2.iloc[:-1])
        pd.testing.assert_series_equal(sell1.iloc[:-1], sell2.iloc[:-1])

    def test_backtest_flag_switches_metrics(self):
        # 镜像分下默认 60/35 存在冲突带 (buy∈[60,65] 卖出优先),
        # 故显式用非重叠阈值 (sell≥70 ⇔ buy≤30) 构造评分制也有交易的场景
        bt = VectorizedBacktester()
        df = _swing_ohlcv()
        m_vote = bt.backtest(df, {})
        m_weighted = bt.backtest(df, {
            'use_weighted_scoring': True,
            'score_buy_threshold': 50, 'score_sell_threshold': 70})
        assert m_vote.num_trades > 0
        assert m_weighted.num_trades > 0
        assert ((m_vote.num_trades, m_vote.total_return)
                != (m_weighted.num_trades, m_weighted.total_return))


class TestOptimizerInjection:
    def test_eval_params_default_on(self):
        from optimization_engine import OptimizationEngine
        engine = OptimizationEngine(seed=1)
        merged = engine._eval_params({'rsi_period': 7})
        assert merged == {'rsi_period': 7, 'use_weighted_scoring': True}

    def test_eval_params_config_off(self):
        from optimization_engine import OptimizationEngine
        cfg = OptimizationConfig()
        cfg.use_weighted_scoring = False
        engine = OptimizationEngine(config=cfg, seed=1)
        assert engine._eval_params({})['use_weighted_scoring'] is False

    def test_config_roundtrip(self, tmp_path):
        cfg = OptimizationConfig()
        cfg.use_weighted_scoring = False
        path = tmp_path / 'opt.json'
        cfg.save(str(path))
        loaded = OptimizationConfig.load(str(path))
        assert loaded.use_weighted_scoring is False
        # 缺键的旧配置文件 → 出厂默认 True
        assert OptimizationConfig._from_dict({'name': 'x'}).use_weighted_scoring is True
        assert OptimizationConfig().use_weighted_scoring is True

    def test_evaluator_forwards_params_wholesale(self):
        from optimization_engine import FitnessEvaluator
        seen = {}

        class _SpyBacktester:
            def walk_forward(self, data, params, **kwargs):
                seen.update(params)
                return []

        ev = FitnessEvaluator(_SpyBacktester())
        fitness, details = ev.evaluate({'rsi_period': 7}, {'600000': None})
        assert seen == {'rsi_period': 7}  # 中间层不删键 → 注入的开关可直达引擎
        # 无 IS 窗口 → 无适应度 (0.0); details 仍带"评估覆盖"记账
        # (审计 M5: 旧实现返回空 details, 失败/覆盖完全不可见)
        assert fitness == 0.0
        assert details['evaluation_available'] is False
        assert details['n_stocks_evaluated'] == 1
        assert details['n_stocks_failed'] == 0
        assert 'is_metrics' not in details

    def test_global_stage_injects_flag(self):
        from optimization_engine import OptimizationEngine
        engine = OptimizationEngine(seed=42)
        engine.stock_data = {'600000': _ohlcv(150)}
        recorded = []

        class _Recorder:
            def evaluate(self, params, *args, **kwargs):
                recorded.append(dict(params))
                return 0.5, {'ok': 1}

        engine.evaluator = _Recorder()
        result = engine.optimize_global(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 6, 'max_generations': 1},
            verbose=False)
        assert result is not None
        assert recorded
        assert all(p.get('use_weighted_scoring') is True for p in recorded)
