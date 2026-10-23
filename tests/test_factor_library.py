# -*- coding: utf-8 -*-
"""factor_library 单元测试 + SS/MFS 切换行为等价断言 (C-P1-11 Step1)"""

import numpy as np
import pandas as pd
import pytest

import factor_library as fl


def _make_close(n=150, seed=7, mu=0.001, sigma=0.02) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2025-01-01', periods=n)
    return pd.Series(100 * np.cumprod(1 + rng.normal(mu, sigma, n)), index=idx)


def _make_panel(stocks=('AAA', 'BBB', 'CCC'), n=150, seed=11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2025-01-01', periods=n)
    drifts = {'AAA': 0.002, 'BBB': 0.0, 'CCC': -0.002}
    return pd.DataFrame({
        s: 100 * np.cumprod(1 + rng.normal(drifts.get(s, 0.0), 0.01, len(idx)))
        for s in stocks
    }, index=idx)


class TestRegistry:
    def test_registry_entries_have_valid_direction(self):
        valid = {fl.HIGHER_BETTER, fl.LOWER_BETTER, fl.BAND}
        assert set(fl.FACTOR_REGISTRY) == {
            'momentum', 'realized_volatility', 'downside_volatility',
            'max_drawdown', 'volume_ratio'}
        for meta in fl.FACTOR_REGISTRY.values():
            assert meta.direction in valid
            assert meta.unit in {'decimal', 'ratio'}
            assert meta.description


class TestSingleStockFunctions:
    def test_momentum_pct_matches_manual(self):
        close = _make_close()
        assert fl.momentum_pct(close, 20) == pytest.approx(
            (close.iloc[-1] / close.iloc[-21] - 1) * 100)
        assert fl.momentum_pct(close, 60) == pytest.approx(
            (close.iloc[-1] / close.iloc[-61] - 1) * 100)

    def test_momentum_pct_insufficient_history_raises_like_legacy(self):
        close = _make_close(n=10)
        # 旧 SS 内联写法对短序列同样抛 IndexError (iloc[-21])
        with pytest.raises(IndexError):
            fl.momentum_pct(close, 20)

    def test_annualized_volatility_pct_matches_manual(self):
        close = _make_close()
        returns = close.pct_change().dropna()
        expected = returns.std() * np.sqrt(252) * 100
        assert fl.annualized_volatility_pct(close) == pytest.approx(expected)

    def test_volume_ratio_and_ma(self):
        vol = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0])
        assert fl.volume_ma(vol, 5) == pytest.approx(300.0)
        assert fl.volume_ratio(vol, 5) == pytest.approx(500.0 / 300.0)


class TestPanelFunctions:
    def test_momentum_panel_matches_manual_and_legacy_mfs(self):
        panel = _make_panel().T  # (股票 × 日期)
        mom = fl.momentum_panel(panel, periods=[20, 60, 120])
        # 与旧 MFS 内联: panel.pct_change(period, axis=1).iloc[:, -1]
        for p in (20, 60, 120):
            expected = panel.pct_change(p, axis=1).iloc[:, -1]
            assert np.allclose(mom[f'Momentum_{p}'].values, expected.values)

    def test_momentum_panel_empty_when_no_period_qualifies(self):
        panel = _make_panel(n=30).T
        assert fl.momentum_panel(panel, periods=[60, 120]).shape == (0, 0)

    def test_momentum_panel_empty_on_none(self):
        assert fl.momentum_panel(None).shape == (0, 0)

    def test_realized_volatility_panel_matches_legacy(self):
        panel = _make_panel().T
        returns = panel.pct_change(axis=1)
        expected = returns.T.rolling(20).std().iloc[-1]
        got = fl.realized_volatility_panel(panel, 20)
        assert np.allclose(got.values, expected.values)
        assert (got.dropna() >= 0).all()

    def test_downside_volatility_panel_matches_legacy(self):
        panel = _make_panel().T
        returns = panel.pct_change(axis=1)
        tail = returns.iloc[:, -20:]
        expected = tail.clip(upper=0).std(axis=1)
        got = fl.downside_volatility_panel(panel, 20)
        assert np.allclose(got.values, expected.values)

    def test_max_drawdown_panel_matches_legacy(self):
        panel = _make_panel().T
        cummax = panel.cummax(axis=1)
        drawdown = (panel - cummax) / cummax
        expected = -drawdown.T.rolling(20).min().iloc[-1]
        got = fl.max_drawdown_panel(panel, 20)
        assert np.allclose(got.values, expected.values)
        assert (got.dropna() >= 0).all()


class TestToClosePanel:
    def test_wide_panel_transposed(self):
        wide = _make_panel()  # (日期 × 股票)
        panel = fl.to_close_panel({'收盘': wide})
        assert panel.shape == (3, 150)  # → (股票 × 日期)
        assert panel.index.tolist() == ['AAA', 'BBB', 'CCC']

    def test_single_stock_returns_none(self):
        wide = _make_panel()
        assert fl.to_close_panel({'收盘': wide['AAA']}) is None


class TestMFSBehaviorEquivalence:
    """MFS 切换到因子库后输出与旧内联实现逐位等价"""

    def test_momentum_factor_matches_legacy_inline(self):
        from multi_factor_selection import FactorModels
        wide = _make_panel()
        got = FactorModels.momentum_factor({'收盘': wide}, periods=[20, 60, 120])

        # 旧内联完整路径 (含 z-score 标准化)
        panel = wide.T
        legacy = pd.DataFrame()
        for p in (20, 60, 120):
            legacy[f'Momentum_{p}'] = panel.pct_change(p, axis=1).iloc[:, -1]
        for col in legacy.columns:
            legacy[col] = (legacy[col] - legacy[col].mean()) / legacy[col].std()
        legacy['Momentum_Score'] = legacy.mean(axis=1)

        assert got.index.equals(legacy.index)
        assert np.allclose(got.values, legacy.values)

    def test_volatility_factor_matches_legacy_inline(self):
        from multi_factor_selection import FactorModels
        wide = _make_panel()
        got = FactorModels.volatility_factor({'收盘': wide}, period=20)

        panel = wide.T
        returns = panel.pct_change(axis=1)
        legacy = pd.DataFrame()
        legacy['Volatility'] = -returns.T.rolling(20).std().iloc[-1]
        tail = returns.iloc[:, -20:]
        legacy['Downside_Vol'] = -tail.clip(upper=0).std(axis=1)
        cummax = panel.cummax(axis=1)
        drawdown = (panel - cummax) / cummax
        legacy['Max_Drawdown'] = -drawdown.T.rolling(20).min().iloc[-1]
        for col in legacy.columns:
            legacy[col] = (legacy[col] - legacy[col].mean()) / legacy[col].std()
        legacy['Volatility_Score'] = legacy.mean(axis=1)

        assert got.index.equals(legacy.index)
        assert np.allclose(got.values, legacy.values)

    def test_single_stock_still_empty(self):
        from multi_factor_selection import FactorModels
        wide = _make_panel()
        assert FactorModels.momentum_factor({'收盘': wide['AAA']}).empty
        assert FactorModels.volatility_factor({'收盘': wide['AAA']}).empty


class TestSSBehaviorEquivalence:
    """SS 切换到因子库后 _calculate_stock_score 与旧内联逐位等价"""

    @staticmethod
    def _legacy_score(data, latest):
        score = 0
        current_price = latest['收盘']
        if current_price > latest['MA5'] > latest['MA10'] > latest['MA20']:
            score += 30
        elif current_price > latest['MA5'] > latest['MA20']:
            score += 25
        elif current_price > latest['MA20']:
            score += 20
        elif latest['MA5'] > latest['MA20']:
            score += 10
        elif current_price > latest['MA60']:
            score += 5
        if latest['MACD'] > 0 and latest['MACD_Signal'] > 0:
            score += 20
        elif latest['MACD'] > latest['MACD_Signal']:
            score += 10
        rsi = latest['RSI']
        if 40 <= rsi <= 65:
            score += 15
        elif rsi < 30:
            score += 10
        elif rsi < 40:
            score += 8
        change_20d = (current_price / data['收盘'].iloc[-21] - 1) * 100
        if change_20d > 10:
            score += 15
        elif change_20d > 5:
            score += 12
        elif change_20d > 0:
            score += 8
        vol_ma5 = data['成交量'].tail(5).mean()
        if latest['成交量'] > vol_ma5 * 1.2:
            score += 10
        elif latest['成交量'] > vol_ma5:
            score += 5
        returns = data['收盘'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) * 100
        if 15 <= volatility <= 40:
            score += 10
        elif volatility < 15:
            score += 6
        return min(score, 100)

    @staticmethod
    def _make_ss_data(n=100, seed=3):
        close = _make_close(n=n, seed=seed, sigma=0.015)
        rng = np.random.default_rng(seed)
        data = pd.DataFrame({
            '收盘': close,
            '成交量': rng.uniform(1e6, 5e6, n),
            'MA5': close.rolling(5).mean(),
            'MA10': close.rolling(10).mean(),
            'MA20': close.rolling(20).mean(),
            'MA60': close.rolling(60).mean(),
            'MACD': rng.normal(0, 0.5, n),
            'MACD_Signal': rng.normal(0, 0.5, n),
            'RSI': rng.uniform(20, 80, n),
        })
        return data.dropna()

    def test_score_matches_legacy_across_seeds(self):
        from stock_selector import StockSelector, DEFAULT_SCORE_CONFIG
        ss = StockSelector.__new__(StockSelector)  # 跳过网络依赖的 __init__
        ss.score_config = DEFAULT_SCORE_CONFIG
        for seed in range(8):
            data = self._make_ss_data(seed=seed)
            latest = data.iloc[-1]
            assert ss._calculate_stock_score(data, latest) == \
                self._legacy_score(data, latest), f'seed={seed} 分数漂移'

    def test_score_boundary_cases(self):
        from stock_selector import StockSelector, DEFAULT_SCORE_CONFIG
        ss = StockSelector.__new__(StockSelector)
        ss.score_config = DEFAULT_SCORE_CONFIG
        data = self._make_ss_data(seed=99)
        # 构造 RSI 边界: 40 / 65 / 29 / 39
        for rsi, expected_rsi_pts in [(40, 15), (65, 15), (29, 10), (39, 8), (66, 0)]:
            data.loc[data.index[-1], 'RSI'] = rsi
            latest = data.iloc[-1]
            legacy = self._legacy_score(data, latest)
            assert ss._calculate_stock_score(data, latest) == legacy


class TestJSONConfig:
    """Step2: JSON 配置外置 — 出厂值与内置默认逐位一致, 配置可覆盖"""

    def test_stock_selector_config_matches_builtin(self):
        from stock_selector import DEFAULT_SCORE_CONFIG
        cfg = fl.load_config('stock_selector')
        assert cfg is not None
        for key, val in DEFAULT_SCORE_CONFIG.items():
            assert cfg[key] == val, f'{key} 出厂值与内置默认漂移'

    def test_multi_factor_config_matches_builtin(self):
        cfg = fl.load_config('multi_factor')
        assert cfg is not None
        assert cfg['weighting_method'] == 'custom'
        assert cfg['factor_weights'] == {
            'value': 0.25, 'growth': 0.25, 'quality': 0.25,
            'momentum': 0.15, 'volatility': 0.10}

    def test_mfs_ctor_reads_config(self):
        from multi_factor_selection import MultiFactorSelector
        sel = MultiFactorSelector()
        assert sel.weighting_method == 'custom'
        assert sel.factor_weights['momentum'] == 0.15

    def test_mfs_ctor_explicit_args_override_config(self):
        from multi_factor_selection import MultiFactorSelector
        sel = MultiFactorSelector(factor_weights={'value': 1.0},
                                  weighting_method='equal')
        assert sel.factor_weights == {'value': 1.0}
        assert sel.weighting_method == 'equal'

    def test_ss_custom_config_changes_score(self):
        from stock_selector import StockSelector, DEFAULT_SCORE_CONFIG
        data = TestSSBehaviorEquivalence._make_ss_data(seed=5)
        latest = data.iloc[-1]

        ss_default = StockSelector.__new__(StockSelector)
        ss_default.score_config = DEFAULT_SCORE_CONFIG
        base = ss_default._calculate_stock_score(data, latest)

        # 把 RSI sweet points 从 15 提到 15+X, 分数应同步变化 (若当前落在 sweet 档)
        boosted = dict(DEFAULT_SCORE_CONFIG)
        boosted['rsi_sweet_points'] = 15 + 10
        ss_boosted = StockSelector.__new__(StockSelector)
        ss_boosted.score_config = boosted
        new_score = ss_boosted._calculate_stock_score(data, latest)
        rsi = latest['RSI']
        if 40 <= rsi <= 65:
            assert new_score == base + 10
        else:
            assert new_score == base

    def test_load_config_missing_returns_none(self):
        assert fl.load_config('nonexistent_module') is None
