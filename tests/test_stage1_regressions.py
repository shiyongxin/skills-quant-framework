# -*- coding: utf-8 -*-
"""
Stage 1/2 回归测试:
- pattern_recognition: high/low 列修复、detect_breakout 不含当根、scan_all_patterns 索引保持
- technical_analyzer: Pattern_ 前缀匹配修复
- multi_factor_selection (C-P0#5): 自定义权重生效、缺因子重归一化、optimize_weights 返回权重
"""
import numpy as np
import pandas as pd

from multi_factor_selection import MultiFactorSelector
from pattern_recognition import CandlestickPatterns, PricePatterns


def mk_df(n=40, base=10.0):
    rng = np.random.default_rng(0)
    close = base * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({
        '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01, '最低': close * 0.99, '收盘': close,
        '成交量': rng.integers(1e6, 2e6, n).astype(float),
    })


class TestPatternRecognition:
    def test_is_hammer_uses_high_column(self):
        # 锤子: 长下影、短上影 — 用 最高/最低 构造（旧 bug 把 最低 当最高 → 永不成立）
        df = mk_df()
        df.loc[5, '开盘'] = 10.0
        df.loc[5, '收盘'] = 10.1
        df.loc[5, '最高'] = 10.12
        df.loc[5, '最低'] = 9.3
        r = CandlestickPatterns.is_hammer(df, 5)
        assert r['is_hammer'] is True, r
        assert r['type'] in ('hammer', 'hanging_man')

    def test_detect_breakout_excludes_current_bar(self):
        # 前 period 根平 10, 末根收盘 12 → 向上突破(若含当根则 prev_high=12 不触发)
        df = mk_df(n=30)
        df['最高'] = 10.0
        df['最低'] = 10.0
        df['收盘'] = 10.0
        df.loc[29, '收盘'] = 12.0
        df.loc[29, '最高'] = 12.2
        df.loc[29, '最低'] = 9.9
        r = PricePatterns.detect_breakout(df, period=20, threshold=1.5)
        assert r['breakout'] is True and r['direction'] == 'up', r

    def test_scan_all_patterns_preserves_index(self):
        df = mk_df(n=30)
        df.index = [f'row{i}' for i in range(30)]
        out = CandlestickPatterns.scan_all_patterns(df)
        assert list(out.index) == list(df.index)
        assert any(c.startswith('Pattern_') for c in out.columns)


class TestTechnicalAnalyzerPatterns:
    def test_pattern_prefix_scan(self):
        import technical_analyzer as ta_mod
        src = open(ta_mod.__file__, encoding='utf-8').read()
        # 修复点: 'latest' in col 永不匹配 Pattern_* 列 → 改为前缀匹配
        assert "startswith('Pattern_')" in src or 'startswith("Pattern_")' in src


class TestMultiFactorWeights:
    @staticmethod
    def _factors():
        idx = ['000001', '000002', '000003']
        return pd.DataFrame({
            'Value_Score': [0.9, 0.5, 0.1],
            'Growth_Score': [0.2, 0.7, 0.4],
            'Quality_Score': [0.6, 0.6, 0.6],
        }, index=idx)

    def test_default_weighting_is_custom(self):
        sel = MultiFactorSelector()
        assert sel.weighting_method == 'custom'

    def test_custom_weights_equal_manual_composite(self):
        fw = {'value': 0.5, 'growth': 0.3, 'quality': 0.2}
        sel = MultiFactorSelector(factor_weights=fw, weighting_method='custom')
        f = self._factors()
        got = sel.get_composite_score(f)
        exp = (f['Value_Score'] * 0.5 + f['Growth_Score'] * 0.3
               + f['Quality_Score'] * 0.2)
        assert np.allclose(got, exp), (got, exp)

    def test_missing_factor_renormalizes(self):
        fw = {'value': 0.25, 'growth': 0.25, 'quality': 0.25,
              'momentum': 0.25}
        sel = MultiFactorSelector(factor_weights=fw, weighting_method='custom')
        f = self._factors()  # momentum 缺失 → 权重按 0.25/0.75 重归一
        got = sel.get_composite_score(f)
        exp = (f['Value_Score'] * 0.25 + f['Growth_Score'] * 0.25
               + f['Quality_Score'] * 0.25) / 0.75
        assert np.allclose(got, exp), (got.to_list(), exp.to_list())
        assert got.notna().all(), "全 NaN 毒化综合分"

    def test_all_nan_column_skipped(self):
        fw = {'value': 0.5, 'growth': 0.5}
        sel = MultiFactorSelector(factor_weights=fw, weighting_method='custom')
        f = self._factors()
        f['Value_Score'] = np.nan  # 全 NaN → 跳过, 仅 growth(重归一后=1.0)
        got = sel.get_composite_score(f)
        assert np.allclose(got, f['Growth_Score']), (got, f['Growth_Score'])

    def test_optimize_weights_returns_normalized(self):
        sel = MultiFactorSelector()
        f = self._factors()
        rng = np.random.default_rng(0)
        returns = pd.Series(rng.normal(0.001, 0.02, len(f)), index=f.index)
        w = sel.optimize_weights(f, returns=returns, method='max_sharpe')
        assert w is not None and len(w) > 0
        assert abs(sum(w.values()) - 1.0) < 1e-6, w
        assert all(v >= -1e-9 for v in w.values()), w
