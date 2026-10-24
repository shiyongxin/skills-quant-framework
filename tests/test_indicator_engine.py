# -*- coding: utf-8 -*-
"""共享指标引擎等价性测试（审计 C #10, 项 21）。

两类断言:
1. core/indicators.py 的每个权威实现 == 收敛前各模块的内联公式（逐位）。
   收敛后模块改调 core，若数值漂移, 这里立刻红。
2. IndicatorEngine 的列名契约（规范名 / 历史名映射 / 缺列显式报错）。
"""
import numpy as np
import pandas as pd
import pytest

from core.indicators import (atr, bollinger, ema, kdj, macd, obv, rsi, sma,
                             true_range, volume_ma, vwap)
from core.indicator_engine import (CANONICAL_COLUMNS,
                                   LEGACY_COLUMN_ALIASES, IndicatorEngine,
                                   indicator_columns)


@pytest.fixture
def ohlcv():
    rng = np.random.default_rng(20241024)
    n = 260
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.015, n))))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    volume = pd.Series(rng.uniform(1e5, 5e5, n))
    return pd.DataFrame({'收盘': close, '最高': high, '最低': low,
                         '成交量': volume})


# ==================== 与收敛前内联公式逐位等价 ====================

class TestEqualsLegacyInlineFormulas:
    def test_sma(self, ohlcv):
        close = ohlcv['收盘']
        pd.testing.assert_series_equal(sma(close, 20),
                                       close.rolling(window=20).mean())

    def test_ema_recursive(self, ohlcv):
        close = ohlcv['收盘']
        pd.testing.assert_series_equal(ema(close, 26),
                                       close.ewm(span=26, adjust=False).mean())

    def test_macd(self, ohlcv):
        close = ohlcv['收盘']
        fast = close.ewm(span=12, adjust=False).mean()
        slow = close.ewm(span=26, adjust=False).mean()
        dif = fast - slow
        dea = dif.ewm(span=9, adjust=False).mean()
        pd.testing.assert_series_equal(macd(close)[0], dif)
        pd.testing.assert_series_equal(macd(close)[1], dea)
        pd.testing.assert_series_equal(macd(close)[2], dif - dea)

    def test_kdj(self, ohlcv):
        close, high, low = ohlcv['收盘'], ohlcv['最高'], ohlcv['最低']
        low_n = low.rolling(window=9).min()
        high_n = high.rolling(window=9).max()
        rsv = (close - low_n) / (high_n - low_n) * 100
        k = rsv.ewm(span=3, adjust=False).mean()
        d = k.ewm(span=3, adjust=False).mean()
        got_k, got_d, got_j = kdj(high, low, close)
        pd.testing.assert_series_equal(got_k, k)
        pd.testing.assert_series_equal(got_d, d)
        pd.testing.assert_series_equal(got_j, 3 * k - 2 * d)

    def test_kdj_zero_denominator_is_nan(self):
        """分母 0（一字板）→ NaN，不产生 inf"""
        close = pd.Series([10.0] * 30)
        high = pd.Series([10.0] * 30)
        low = pd.Series([10.0] * 30)
        k, d, j = kdj(high, low, close)
        assert k.isna().all() and d.isna().all() and j.isna().all()

    def test_bollinger(self, ohlcv):
        close = ohlcv['收盘']
        mid = close.rolling(window=20).mean()
        std = close.rolling(window=20).std()
        upper, middle, lower, got_std = bollinger(close)
        pd.testing.assert_series_equal(middle, mid)
        pd.testing.assert_series_equal(got_std, std)
        pd.testing.assert_series_equal(upper, mid + 2 * std)
        pd.testing.assert_series_equal(lower, mid - 2 * std)

    def test_bollinger_custom_multiplier(self, ohlcv):
        close = ohlcv['收盘']
        mid = close.rolling(window=20).mean()
        std = close.rolling(window=20).std()
        upper, middle, lower, _ = bollinger(close, 20, 2.5)
        pd.testing.assert_series_equal(upper, mid + 2.5 * std)
        pd.testing.assert_series_equal(lower, mid - 2.5 * std)

    def test_volume_ma(self, ohlcv):
        vol = ohlcv['成交量']
        pd.testing.assert_series_equal(volume_ma(vol, 20),
                                       vol.rolling(window=20).mean())

    def test_obv(self, ohlcv):
        close = ohlcv['收盘'].to_numpy(dtype=float)
        vol = ohlcv['成交量'].to_numpy(dtype=float)
        direction = np.sign(np.diff(close, prepend=close[0]))
        delta = direction * vol
        delta[0] = vol[0]
        pd.testing.assert_series_equal(obv(ohlcv['收盘'], ohlcv['成交量']),
                                       pd.Series(np.cumsum(delta),
                                                 index=ohlcv.index))

    def test_vwap(self, ohlcv):
        tp = (ohlcv['最高'] + ohlcv['最低'] + ohlcv['收盘']) / 3
        expected = (tp * ohlcv['成交量']).cumsum() / ohlcv['成交量'].cumsum()
        pd.testing.assert_series_equal(
            vwap(ohlcv['最高'], ohlcv['最低'], ohlcv['收盘'], ohlcv['成交量']),
            expected)

    def test_atr_wilder_not_sma(self, ohlcv):
        """ATR 必须是 Wilder RMA, 不是 SMA14 (旧 vectorized_backtest 口径)"""
        high, low, close = ohlcv['最高'], ohlcv['最低'], ohlcv['收盘']
        tr = true_range(high, low, close)
        sma14 = tr.rolling(14).mean()
        got = atr(high, low, close, 14)
        assert not got.equals(sma14)
        pd.testing.assert_series_equal(
            got, tr.ewm(alpha=1 / 14, adjust=False,
                        min_periods=14).mean())


# ==================== IndicatorEngine ====================

class TestIndicatorEngine:
    def test_compute_canonical_columns(self, ohlcv):
        eng = IndicatorEngine(ohlcv)
        out = eng.compute(ma_periods=(5, 20), ema_periods=(20,),
                          rsi_period=14, atr_period=14,
                          vol_ma_periods=(5, 20), with_vwap=True,
                          with_obv=True)
        for col in ('MA5', 'MA20', 'EMA20', 'DIF', 'DEA', 'HIST', 'RSI',
                    'K', 'D', 'J', 'BB_Upper', 'BB_Middle', 'BB_Lower',
                    'BB_Std', 'TR', 'ATR', 'Vol_MA5', 'Vol_MA20', 'VWAP',
                    'OBV'):
            assert col in out.columns, col
        assert len(out) == len(ohlcv)
        assert list(out.index) == list(ohlcv.index)

    def test_compute_values_match_core(self, ohlcv):
        eng = IndicatorEngine(ohlcv)
        out = eng.compute(atr_period=14, rsi_period=14)
        pd.testing.assert_series_equal(out['DIF'],
                                       macd(ohlcv['收盘'])[0],
                                       check_names=False)
        pd.testing.assert_series_equal(out['HIST'],
                                       macd(ohlcv['收盘'])[2],
                                       check_names=False)
        pd.testing.assert_series_equal(out['ATR'], atr(ohlcv['最高'],
                                                       ohlcv['最低'],
                                                       ohlcv['收盘'], 14),
                                       check_names=False)

    def test_missing_column_raises(self, ohlcv):
        eng = IndicatorEngine(ohlcv.drop(columns=['最高']))
        with pytest.raises(KeyError, match='最高'):
            eng.kdj()

    def test_to_legacy_rename(self, ohlcv):
        eng = IndicatorEngine(ohlcv)
        canon = eng.compute()
        legacy = IndicatorEngine.to_legacy(canon)
        assert 'MACD' in legacy.columns and 'DIF' not in legacy.columns
        assert 'MACD_Signal' in legacy.columns
        assert 'MACD_Hist' in legacy.columns
        assert 'BB_Middle' in legacy.columns
        # 数值不变
        pd.testing.assert_series_equal(legacy['MACD'], canon['DIF'],
                                       check_names=False)

    def test_to_legacy_custom_mapping(self, ohlcv):
        eng = IndicatorEngine(ohlcv)
        canon = eng.compute()
        legacy = IndicatorEngine.to_legacy(
            canon, {'DIF': 'DIF', 'DEA': 'DEA', 'HIST': 'HIST'})
        assert 'DIF' in legacy.columns

    def test_to_canonical_roundtrip(self, ohlcv):
        eng = IndicatorEngine(ohlcv)
        canon = eng.compute()
        legacy = IndicatorEngine.to_legacy(canon)
        back = IndicatorEngine.to_canonical(legacy)
        pd.testing.assert_series_equal(back['DIF'], canon['DIF'],
                                       check_names=False)

    def test_alias_table_covers_known_legacy_names(self):
        for name in ('MACD', 'macd', 'MACD_Signal', 'macd_signal',
                     'MACD_Hist', 'macd_hist', 'BB_Middle', 'BB_Mid',
                     'bb_mid', 'bb_middle', 'Vol_MA5', 'vol_ma5',
                     'volume_ma5', 'VOL_MA5'):
            assert name in LEGACY_COLUMN_ALIASES, name

    def test_canonical_columns_documented(self):
        assert 'DIF' in CANONICAL_COLUMNS
        assert 'J' in CANONICAL_COLUMNS

    def test_indicator_columns_helper(self, ohlcv):
        eng = IndicatorEngine(ohlcv)
        cols = indicator_columns(eng, ma_periods=(5,), rsi_period=14,
                                 atr_period=14)
        assert set(cols) == {'MA5', 'DIF', 'DEA', 'HIST', 'K', 'D', 'J',
                             'BB_Upper', 'BB_Middle', 'BB_Lower', 'BB_Std',
                             'RSI', 'TR', 'ATR'}
        assert len(cols['MA5']) == len(ohlcv)

    def test_attach_writes_columns(self, ohlcv):
        eng = IndicatorEngine(ohlcv)
        df = eng.attach(ohlcv.copy(), {'MA5': eng.ma(5)})
        assert 'MA5' in df.columns


# ==================== 模块已全部改调 core（源码级） ====================

class TestModulesUseCoreEngine:
    MODULES = ('technical_analyzer.py', 'position_analyzer.py',
               'stock_data_fetcher.py', 'daily_signal_generator.py',
               'vectorized_backtest.py', 'reversal_detector.py',
               'reversal_backtest.py', 'ml_predictor.py',
               'advanced_indicators.py', 'trend_indicators.py',
               'backtest_framework.py', 'strategy_optimizer.py',
               'chart_visualizer.py', 'market_regime_classifier.py',
               'long_term_selector.py', 'web_app.py',
               'signal_generator.py', 'historical_backtest_validator.py',
               'trade_constraints.py')

    def test_no_local_ewm_formulas_left(self):
        """模块内不得再出现裸 ewm(...).mean() 指标公式（应改调 core）"""
        import pathlib
        skills = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills'
        offenders = []
        for name in self.MODULES:
            src = (skills / name).read_text(encoding='utf-8')
            for i, line in enumerate(src.split('\n'), start=1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if '.ewm(' in stripped and 'core' not in stripped:
                    offenders.append(f'{name}:{i}: {stripped}')
        assert not offenders, '\n'.join(offenders)

    def test_no_local_rolling_indicator_formulas_left(self):
        """rolling(...).mean() 形式的均线公式也应统一到 core.sma"""
        import pathlib
        skills = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills'
        allowed = ('core.indicators', 'core.sma', 'factor_library',
                   'trade_constraints', 'advanced_indicators.py',
                   'trend_indicators.py')
        offenders = []
        for name in self.MODULES:
            if name in allowed:
                continue
            src = (skills / name).read_text(encoding='utf-8')
            for i, line in enumerate(src.split('\n'), start=1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if 'rolling(' in stripped and '.mean()' in stripped:
                    offenders.append(f'{name}:{i}: {stripped}')
        assert not offenders, '\n'.join(offenders)
