# -*- coding: utf-8 -*-
"""指标口径收敛回归（审计 C #10, 项 21）。

覆盖三处"同名不同义"的收敛结果:
1. `vectorized_backtest` 的 ATR 列: 旧 SMA14 → core Wilder RMA
2. `reversal_detector` / `reversal_backtest` 的 KDJ/MACD: 旧 ewm(adjust=True)
   → core 递归口径 (adjust=False), 与全仓其余站点一致
3. `reversal_detector` 与 `reversal_backtest` 的指标列必须逐位一致
   (实盘/回测同源, 审计 C-P1-13 的延伸)
"""
import numpy as np
import pandas as pd
import pytest


def _mk_ohlcv(n=320, seed=21, base=10.0):
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.012, n))
    return pd.DataFrame({
        '日期': pd.bdate_range('2023-01-02', periods=n),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.integers(1e6, 3e6, n).astype(float),
    })


class TestVectorizedAtrConverged:
    def test_atr_column_is_wilder_not_sma(self):
        from vectorized_backtest import VectorizedBacktester
        from core.indicators import atr as core_atr

        df = _mk_ohlcv(n=200, seed=3)
        out = VectorizedBacktester()._compute_indicators(df, {})
        expected = core_atr(df['最高'], df['最低'], df['收盘'], 14)
        pd.testing.assert_series_equal(out['atr'], expected,
                                       check_names=False)

    def test_atr_differs_from_legacy_sma(self):
        """旧口径 SMA14 必须已不生效（否则收敛是假的）"""
        from vectorized_backtest import VectorizedBacktester

        df = _mk_ohlcv(n=200, seed=3)
        out = VectorizedBacktester()._compute_indicators(df, {})
        tr1 = df['最高'] - df['最低']
        tr2 = (df['最高'] - df['收盘'].shift()).abs()
        tr3 = (df['最低'] - df['收盘'].shift()).abs()
        legacy = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
        assert not np.allclose(out['atr'].dropna().values,
                               legacy.dropna().values)


class TestReversalIndicatorParity:
    def test_detector_and_backtest_indicators_identical(self):
        from reversal_detector import ReversalDetector
        from reversal_backtest import ReversalBacktester

        df = _mk_ohlcv(n=200, seed=7)
        det = ReversalDetector().calculate_indicators(df.copy())
        bk = ReversalBacktester().calculate_indicators(df.copy())
        for col in ('MA5', 'MA10', 'MA20', 'MA60', 'RSI6', 'RSI14', 'RSI24',
                    'K', 'D', 'J', 'MACD', 'MACD_Signal', 'MACD_Hist',
                    'BB_Middle', 'BB_Std', 'BB_Upper', 'BB_Lower',
                    'Vol_MA5', 'Vol_MA20', 'ATR'):
            assert col in det.columns, col
            assert col in bk.columns, col
            pd.testing.assert_series_equal(
                det[col], bk[col], check_names=False,
                obj=f'column {col}')

    def test_reversal_uses_recursive_ema_not_adjusted(self):
        """KDJ/MACD 必须与全仓 core 递归口径一致（旧的 adjust=True 已废）"""
        from reversal_detector import ReversalDetector
        from core.indicators import kdj as core_kdj, macd as core_macd

        df = _mk_ohlcv(n=200, seed=7)
        out = ReversalDetector().calculate_indicators(df.copy())
        k, d, j = core_kdj(df['最高'], df['最低'], df['收盘'])
        pd.testing.assert_series_equal(out['K'], k, check_names=False)
        pd.testing.assert_series_equal(out['D'], d, check_names=False)
        pd.testing.assert_series_equal(out['J'], j, check_names=False)
        dif, dea, hist = core_macd(df['收盘'])
        pd.testing.assert_series_equal(out['MACD'], dif, check_names=False)
        pd.testing.assert_series_equal(out['MACD_Signal'], dea,
                                       check_names=False)
        pd.testing.assert_series_equal(out['MACD_Hist'], hist,
                                       check_names=False)

    def test_reversal_recursive_differs_from_legacy_adjusted(self):
        """旧 adjust=True 口径必须已不生效"""
        from reversal_detector import ReversalDetector

        df = _mk_ohlcv(n=200, seed=7)
        out = ReversalDetector().calculate_indicators(df.copy())
        low_n = df['最低'].rolling(9).min()
        high_n = df['最高'].rolling(9).max()
        rsv = (df['收盘'] - low_n) / (high_n - low_n) * 100
        legacy_k = rsv.ewm(3).mean()          # adjust=True (旧)
        current_k = rsv.ewm(span=3, adjust=False).mean()
        assert not np.allclose(out['K'].dropna().values,
                               legacy_k.dropna().values)
        assert np.allclose(out['K'].dropna().values,
                           current_k.dropna().values)


class TestCrossModuleAgreement:
    """关键同名指标列在各模块之间必须逐位一致"""

    @pytest.mark.parametrize('module_name', ['technical_analyzer',
                                            'position_analyzer'])
    def test_technical_vs_position_macd_agree(self, module_name):
        import importlib

        from core.indicators import macd as core_macd

        df = _mk_ohlcv(n=200, seed=11)
        mod = importlib.import_module(module_name)
        if module_name == 'technical_analyzer':
            obj = mod.TechnicalAnalyzer(fetcher=_Stub(df))
            out = obj._calculate_indicators(df.copy())
        else:
            obj = mod.PositionAnalyzer(fetcher=_Stub(df))
            out = obj.get_stock_data('600519', days=200)
        dif, dea, hist = core_macd(df['收盘'])
        pd.testing.assert_series_equal(out['MACD'], dif, check_names=False)
        pd.testing.assert_series_equal(out['MACD_Hist'], hist,
                                       check_names=False)

    def test_daily_signal_generator_matches_core(self):
        from daily_signal_generator import compute_indicators
        from core.indicators import macd as core_macd, kdj as core_kdj

        df = _mk_ohlcv(n=200, seed=13)
        out = compute_indicators(df, {})
        dif, dea, hist = core_macd(df['收盘'])
        pd.testing.assert_series_equal(out['MACD'], dif, check_names=False)
        k, d, _j = core_kdj(df['最高'], df['最低'], df['收盘'])
        pd.testing.assert_series_equal(out['K'], k, check_names=False)
        pd.testing.assert_series_equal(out['D'], d, check_names=False)

    def test_vectorized_matches_core(self):
        from vectorized_backtest import VectorizedBacktester
        from core.indicators import macd as core_macd, kdj as core_kdj

        df = _mk_ohlcv(n=200, seed=17)
        out = VectorizedBacktester()._compute_indicators(df, {})
        dif, dea, hist = core_macd(df['收盘'])
        pd.testing.assert_series_equal(out['macd'], dif, check_names=False)
        k, d, j = core_kdj(df['最高'], df['最低'], df['收盘'])
        pd.testing.assert_series_equal(out['k'], k, check_names=False)
        pd.testing.assert_series_equal(out['j'], j, check_names=False)

    def test_ml_features_match_core(self):
        from ml_predictor import FeatureEngineer
        from core.indicators import macd as core_macd, bollinger as core_bollinger

        df = _mk_ohlcv(n=200, seed=19)
        out = FeatureEngineer().create_technical_features(df.copy())
        dif, dea, hist = core_macd(df['收盘'])
        pd.testing.assert_series_equal(out['macd'], dif, check_names=False)
        upper, middle, lower, std = core_bollinger(df['收盘'], 20, 2.0)
        pd.testing.assert_series_equal(out['bb_middle'], middle,
                                       check_names=False)
        pd.testing.assert_series_equal(out['bb_upper'], upper,
                                       check_names=False)


class _Stub:
    """最小 fetcher 桩（position_analyzer/technical_analyzer 依赖）"""

    def __init__(self, df=None):
        self._df = df

    def get_quote_result(self, symbol, days=120, adjust='hfq'):
        from core.fetch_result import FetchResult
        data = self._df if self._df is not None else _mk_ohlcv(n=200)
        return FetchResult(ok=True, data=data, source='stub')
