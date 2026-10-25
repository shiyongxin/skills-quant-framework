# -*- coding: utf-8 -*-
"""
口径统一回归测试（审计路线图项 8/9/14/17 + P0-6）:
- core.indicators.rsi: Cutler 口径 + 0 除约定; 5 处实现同值
- core.metrics: profit_factor 求和式 / max_drawdown 正值 / sharpe ddof=1
- A/B/优化器三路径口径一致（黄金快照在 test_backtest_honesty 锁定）
- walk_forward IS 拟合 / OOS 评估训练步
- trend_indicators Chikou 无未来函数
- technical_analyzer MACD 真交叉（不再水平比较冒充金叉）
"""
import numpy as np
import pandas as pd
import pytest

from core.indicators import rsi
from core.metrics import profit_factor, max_drawdown_pct, sharpe_ratio


def mk_ohlcv(n=80, seed=0, base=10.0):
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({
        '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01, '最低': close * 0.99, '收盘': close,
        '成交量': rng.integers(1e6, 2e6, n).astype(float),
    })


class TestCoreRSI:
    def test_all_gains_is_100(self):
        close = pd.Series(np.linspace(10, 20, 30))
        r = rsi(close, 14)
        assert r.iloc[-1] == 100.0
        assert r.notna().sum() == 17  # index>=13 起有效

    def test_all_losses_is_0(self):
        close = pd.Series(np.linspace(20, 10, 30))
        assert rsi(close, 14).iloc[-1] == 0.0

    def test_flat_is_50(self):
        close = pd.Series(np.full(30, 10.0))
        assert rsi(close, 14).iloc[-1] == 50.0

    def test_mixed_bounded(self):
        r = rsi(mk_ohlcv()['收盘'], 14).dropna()
        assert ((r >= 0) & (r <= 100)).all()

    def test_five_modules_agree(self):
        # 5 处实现全部改调 core → 同一输入同一输出
        df = mk_ohlcv(n=80, seed=3)
        expected = rsi(df['收盘'], 14)

        import technical_analyzer as ta_mod
        ta = ta_mod.TechnicalAnalyzer()
        got_ta = ta._calculate_indicators(df.copy())['RSI']
        assert np.allclose(got_ta.values, expected.values, equal_nan=True)

        from daily_signal_generator import compute_indicators
        got_dsg = compute_indicators(df.copy(), {})['RSI']
        assert np.allclose(got_dsg.values, expected.values, equal_nan=True)

        from reversal_detector import ReversalDetector
        got_rd = ReversalDetector().calculate_indicators(df.copy())['RSI14']
        assert np.allclose(got_rd.values, expected.values, equal_nan=True)

        from vectorized_backtest import VectorizedBacktester
        got_vb = VectorizedBacktester()._compute_indicators(df.copy(), {})['rsi']
        assert np.allclose(got_vb.values, expected.values, equal_nan=True)

        class _StubFetcher:
            def get_quote_data(self, symbol, days=120):
                return df.copy()

            def get_quote_result(self, symbol, start_date=None, end_date=None, days=120):
                from core.fetch_result import FetchResult
                return FetchResult.success(df.copy(), source='test')

        from position_analyzer import PositionAnalyzer
        got_pa = PositionAnalyzer(fetcher=_StubFetcher()).get_stock_data('600519')['RSI']
        assert np.allclose(got_pa.values, expected.values, equal_nan=True)


class TestCoreMetrics:
    def test_profit_factor_sum_formula(self):
        assert profit_factor([5, -2, 3, -1]) == pytest.approx(8 / 3)
        assert profit_factor([5, 3]) == 0.0   # 无亏损 → 0
        assert profit_factor([]) == 0.0
        assert profit_factor([5, -5]) == 1.0

    def test_max_drawdown_positive(self):
        assert max_drawdown_pct([1, 1.2, 0.9, 1.1]) == pytest.approx(25.0)
        assert max_drawdown_pct([1, 1.1, 1.2]) == 0.0
        assert max_drawdown_pct([]) == 0.0

    def test_sharpe_ddof1_rf(self):
        r = [0.01, -0.005, 0.02, 0.0, 0.015]
        assert sharpe_ratio(r) == pytest.approx(12.066317304340897, rel=1e-12)
        # 常数序列 std=0 → 0
        assert sharpe_ratio([0.01] * 10) == 0.0
        assert sharpe_ratio([0.01]) == 0.0

    def test_engines_report_positive_mdd(self):
        from vectorized_backtest import VectorizedBacktester
        vb = VectorizedBacktester()
        m = vb.backtest(mk_ohlcv(n=120, seed=2), {})
        assert m.max_drawdown >= 0
        assert m.profit_factor >= 0


class TestWalkForwardISOS:
    def test_param_space_fits_on_train_evaluates_on_test(self):
        from vectorized_backtest import VectorizedBacktester
        vb = VectorizedBacktester()
        n = 750
        rng = np.random.default_rng(9)
        close = 10 * np.cumprod(1 + rng.normal(0.0004, 0.012, n))
        data = pd.DataFrame({
            '日期': pd.bdate_range('2020-01-01', periods=n),
            '开盘': close * (1 + rng.normal(0, 0.002, n)),
            '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
        })

        calls = []
        orig = vb.backtest

        def spy(data_, params_):
            calls.append(len(data_))
            return orig(data_, params_)

        vb.backtest = spy
        base = {'min_holding_days': 5}
        grid = {'stop_loss_pct': [0.05, 0.1], 'take_profit_pct': [0.1, 0.3]}
        res = vb.walk_forward(data, base, train_days=300, test_days=150,
                              step_days=150, param_space=grid)
        # 3 个窗口 × (4 次训练窗网格 + 1 次测试窗评估)
        assert len(res) == 3
        assert calls == [300] * 4 + [150] + [300] * 4 + [150] + [300] * 4 + [150]
        assert all(np.isfinite(m.total_return) for m in res)

    def test_no_param_space_backward_compat(self):
        from vectorized_backtest import VectorizedBacktester
        vb = VectorizedBacktester()
        n = 750
        data = mk_ohlcv(n=n, seed=10)
        res = vb.walk_forward(data, {'min_holding_days': 5},
                              train_days=300, test_days=150, step_days=150)
        assert len(res) == 3
        assert all(np.isfinite(m.total_return) for m in res)


class TestChikouNoLookahead:
    def test_chikou_equals_close(self):
        from trend_indicators import TrendIndicators
        df = mk_ohlcv(n=80, seed=4)
        out = TrendIndicators.ichimoku(df.copy())
        # 旧 bug: close.shift(-kijun) 使该列暴露未来收盘
        assert np.allclose(out['Chikou'].values, df['收盘'].values)


class TestMacdTrueCross:
    def test_cross_bar_labeled_and_not_sticky(self):
        import technical_analyzer as ta_mod
        ta = ta_mod.TechnicalAnalyzer()
        df = ta._calculate_indicators(mk_ohlcv(n=120, seed=5))
        macd, sig_line = df['MACD'], df['MACD_Signal']
        cross_up = (macd > sig_line) & (macd.shift(1) <= sig_line.shift(1))
        idxs = np.flatnonzero(cross_up.values)
        assert len(idxs) > 0, "构造数据中应存在 MACD 金叉"
        i = int(idxs[-1])
        # 金叉当根: 标 'MACD金叉'  (_analyze_signals 返回 (signals, unavailable))
        signals, _unavailable = ta._analyze_signals(df.iloc[:i + 1].copy())
        assert 'MACD金叉' in signals
        if i + 1 < len(df):
            # 次根: 不再是金叉(旧 bug 水平比较会持续误标)
            signals_next, _ = ta._analyze_signals(df.iloc[:i + 2].copy())
            assert 'MACD金叉' not in signals_next
