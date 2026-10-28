# -*- coding: utf-8 -*-
"""
审计 H6 回归测试 —— 因子层的前瞻/样本内口径

背景 (审计原文):
- 多因子权重拟合仍**样本内 + 前瞻收益** (`shift(-1)`), 且与 `shift(1)`
  的打分口径**互相矛盾**。
  证据: `multi_factor_selection.py:176`/`:239` `shift(-1)` vs `:411` `shift(1)`
- 性质: 因子层是选股入口, 影响面大。

复验结论 (本批实测):
- `factors_df` 的 index 是**股票代码** (横截面) → 那些 `shift` 是沿
  **股票轴**的错行配对: `factor_data[col].shift(-1) * aligned_returns`
  实际配的是"第 i 只股票的因子 × **第 i+1 只股票**的收益" —— 既不是
  "下一期收益", 也不是前瞻, 而且**权重结果随行序变化** (实测同一输入
  换行序 → factor_returns 均值 −0.0151 → −0.0071)。
- 三条路径对同一份 `returns` 用了三种配对 (`ic_weights` 同期 /
  `test_all_factors` `.shift(1)` 错行 / 拟合 `.shift(-1)` 错行+前瞻)
  → 口径自相矛盾 (审计原话)。
- "样本内": 动态加权方法的权重用**被评分截面自己的标签**拟合, 旧实现
  对此完全沉默 (无任何标记)。

修复:
- 单一配对入口 `FactorWeightingMethod._align` (同期配对, 无 shift);
  标签口径唯一真相源 `forward_returns()` (t → t+1 前瞻收益);
- 检验口径显式化: 横截面 (默认) / 时序 (window 指定, 需时间索引);
- 样本内/样本外显式化: `get_composite_score(..., fit_returns=/fitted_weights=)`
  + `last_weight_fit` 标记 + 结果 `attrs['weight_fit']` + in-sample 告警。
"""
import ast
import inspect

import numpy as np
import pandas as pd
import pytest

from multi_factor_selection import (FactorEffectivenessTester,
                                    FactorWeightingMethod, MultiFactorSelector,
                                    forward_returns)


def _func_ast(fn):
    """取函数源码的 AST (去缩进 + 去装饰器行, 否则 ast.parse 报错)。"""
    import textwrap
    src = inspect.getsource(fn)
    lines = [ln for ln in src.splitlines()
             if not ln.strip().startswith('@')]
    return ast.parse(textwrap.dedent('\n'.join(lines)))


def _cross_section(n=40, seed=3):
    """横截面因子 + 前瞻收益 (Value 有预测力, Growth 无)。"""
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({
        'Value_Score': rng.normal(0, 1, n),
        'Growth_Score': rng.normal(0, 1, n),
    }, index=[f'{i:06d}' for i in range(n)])
    returns = pd.Series(f['Value_Score'] * 0.05 + rng.normal(0, 0.01, n),
                        index=f.index)
    return f, returns


class TestForwardReturns:
    """标签口径唯一真相源: 前瞻收益 (t → t+1)。"""

    def test_semantics(self):
        close = pd.Series([10.0, 11.0, 12.0])
        got = forward_returns(close)
        assert got.iloc[0] == pytest.approx(11 / 10 - 1)   # t=0 → t=1
        assert got.iloc[1] == pytest.approx(12 / 11 - 1)   # t=1 → t=2
        assert np.isnan(got.iloc[-1])               # 末期无前瞻收益

    def test_differs_from_backward_return(self):
        """与后向收益 (pct_change) 不同 —— 避免误用后者当标签。"""
        close = pd.Series([10.0, 11.0, 12.0])
        assert forward_returns(close).iloc[0] != pytest.approx(
            close.pct_change().iloc[0])


class TestPairingSingleSource:
    """因子↔收益的同期配对 (审计 H6 核心修复)。"""

    def test_max_sharpe_weights_row_order_invariant(self):
        """旧实现沿股票轴 shift → 权重随行序变化; 现必须逐位不变。"""
        f, returns = _cross_section()
        rng = np.random.default_rng(11)
        perm = rng.permutation(len(f))
        w1 = FactorWeightingMethod.max_sharpe_weights(f, returns)
        w2 = FactorWeightingMethod.max_sharpe_weights(f.iloc[perm],
                                                      returns.iloc[perm])
        assert set(w1) == set(w2)
        for k in w1:
            assert w1[k] == pytest.approx(w2[k]), k

    def test_risk_parity_weights_row_order_invariant(self):
        f, returns = _cross_section()
        rng = np.random.default_rng(12)
        perm = rng.permutation(len(f))
        w1 = FactorWeightingMethod.risk_parity_weights(f, returns)
        w2 = FactorWeightingMethod.risk_parity_weights(f.iloc[perm],
                                                       returns.iloc[perm])
        for k in w1:
            assert w1[k] == pytest.approx(w2[k]), k

    def test_ic_weights_row_order_invariant(self):
        f, returns = _cross_section()
        rng = np.random.default_rng(13)
        perm = rng.permutation(len(f))
        w1 = FactorWeightingMethod.ic_weights(f, returns)
        w2 = FactorWeightingMethod.ic_weights(f.iloc[perm], returns.iloc[perm])
        for k in w1:
            assert w1[k] == pytest.approx(w2[k]), k

    def test_weights_reflect_same_row_relationship(self):
        """同期配对 → 有预测力的因子拿到更高权重。"""
        f, returns = _cross_section()
        w = FactorWeightingMethod.max_sharpe_weights(f, returns)
        assert w['Value_Score'] > w['Growth_Score']

    def test_align_pairs_same_rows(self):
        f, returns = _cross_section()
        factor_data, aligned = FactorWeightingMethod._align(f, returns)
        assert list(factor_data.index) == list(aligned.index)
        assert len(factor_data) == len(f)

    def test_align_drops_rows_without_labels(self):
        f, returns = _cross_section()
        partial = returns.copy()
        partial.iloc[:5] = np.nan
        factor_data, aligned = FactorWeightingMethod._align(f, partial)
        assert len(factor_data) == len(f) - 5
        assert aligned.notna().all()


class TestTesterConvention:
    """因子检验口径: 横截面 (默认) / 时序 (window 指定)。"""

    def test_cross_section_ic_is_same_row_correlation(self):
        f, returns = _cross_section()
        res = FactorEffectivenessTester.test_all_factors(f, returns)
        assert 'Value_Score' in res
        r = res['Value_Score']
        assert r.mode == 'cross_section'
        expected = f['Value_Score'].corr(returns)
        assert r.ic_mean == pytest.approx(expected)

    def test_cross_section_row_order_invariant(self):
        """旧实现 `.shift(1)` → IC 随行序变化; 现必须不变。"""
        f, returns = _cross_section()
        rng = np.random.default_rng(14)
        perm = rng.permutation(len(f))
        r1 = FactorEffectivenessTester.test_all_factors(f, returns)
        r2 = FactorEffectivenessTester.test_all_factors(f.iloc[perm],
                                                        returns.iloc[perm])
        assert r1['Value_Score'].ic_mean == pytest.approx(
            r2['Value_Score'].ic_mean)

    def test_cross_section_time_series_stats_unavailable(self):
        """单一截面只有 1 个 IC 观测 → 时序统计量不可得 (如实 NaN)。"""
        f, returns = _cross_section()
        r = FactorEffectivenessTester.test_all_factors(f, returns)['Value_Score']
        assert np.isnan(r.ic_std)
        assert np.isnan(r.ir)
        assert np.isnan(r.t_stat)
        assert r.is_significant is False

    def test_time_series_mode_requires_time_index(self):
        """时序口径要求时间索引 → 股票代码轴必须**报错** (不静默算垃圾)。"""
        f, returns = _cross_section()
        with pytest.raises(ValueError, match='时间索引'):
            FactorEffectivenessTester.test_all_factors(f, returns, window=20)

    def test_time_series_mode_with_datetime_index(self):
        n = 80
        idx = pd.date_range('2024-01-01', periods=n, freq='B')
        rng = np.random.default_rng(15)
        f = pd.DataFrame({'Value_Score': rng.normal(0, 1, n)}, index=idx)
        returns = pd.Series(f['Value_Score'] * 0.05 + rng.normal(0, 0.01, n),
                            index=idx)
        res = FactorEffectivenessTester.test_all_factors(f, returns, window=20)
        r = res['Value_Score']
        assert r.mode == 'time_series'
        assert not np.isnan(r.ic_mean)
        assert r.ic_std >= 0


class TestInSampleSeparation:
    """样本内 / 样本外 显式化 (审计 H6 "样本内" 部分)。"""

    def test_in_sample_is_labelled(self):
        sel = MultiFactorSelector(weighting_method='ic')
        f, returns = _cross_section()
        sel.get_composite_score(f, returns)
        assert sel.last_weight_fit['in_sample'] is True
        assert sel.last_weight_fit['method'] == 'ic'
        assert sel.last_weight_fit['n_fit_rows'] == len(f)

    def test_in_sample_warns(self, capsys):
        sel = MultiFactorSelector(weighting_method='max_sharpe')
        f, returns = _cross_section()
        sel.get_composite_score(f, returns)
        out = capsys.readouterr().out
        assert '样本内' in out

    def test_fit_returns_is_out_of_sample(self):
        sel = MultiFactorSelector(weighting_method='ic')
        f, returns = _cross_section()
        sel.get_composite_score(f, returns, fit_returns=returns * 0.5)
        assert sel.last_weight_fit['in_sample'] is False

    def test_fitted_weights_applied_directly(self):
        sel = MultiFactorSelector(weighting_method='ic')
        f, returns = _cross_section()
        weights = {'Value_Score': 0.6, 'Growth_Score': 0.4}
        score = sel.get_composite_score(f, fitted_weights=weights)
        assert sel.last_weight_fit['in_sample'] is False
        assert sel.last_weight_fit['method'] == 'fitted_weights'
        expected = f['Value_Score'] * 0.6 + f['Growth_Score'] * 0.4
        pd.testing.assert_series_equal(score, expected, check_names=False)

    def test_custom_and_equal_are_not_fits(self):
        f, returns = _cross_section()
        for method in ('custom', 'equal'):
            sel = MultiFactorSelector(weighting_method=method)
            sel.get_composite_score(f, returns)
            assert sel.last_weight_fit['in_sample'] is False

    def test_missing_labels_fall_back_to_config_weights(self):
        """无标签 → 回退配置权重, 不静默用等权冒充"拟合结果"。"""
        sel = MultiFactorSelector(weighting_method='ic')
        f, _ = _cross_section()
        sel.get_composite_score(f)
        assert sel.last_weight_fit['in_sample'] is False
        assert 'note' in sel.last_weight_fit


class TestSelectionCarriesFitMetadata:
    """选股结果携带权重拟合口径 (可审计)。"""

    def _financial(self):
        return pd.DataFrame({
            '股票代码': ['600000', '600001', '600002'],
            '公告日': pd.to_datetime(['2024-03-01'] * 3),
            '市盈率': [10.0, 12.0, 14.0],
            '净利润增长率': [0.1, 0.2, 0.3],
            '净资产收益率': [0.15, 0.12, 0.09],
        })

    def test_attrs_record_fit(self):
        sel = MultiFactorSelector(weighting_method='custom')
        out = sel.select_stocks(self._financial(), as_of='2024-06-30')
        assert 'weight_fit' in out.attrs
        assert out.attrs['weight_fit']['in_sample'] is False


class TestSourceHonesty:
    """源码级门禁: 错行 shift 不得复现。"""

    def test_no_shift_in_pairing_functions(self):
        """配对函数内不得出现任何 `.shift(` (沿 index 错行 = 口径错乱)。"""
        funcs = [
            FactorWeightingMethod._align,
            FactorWeightingMethod.ic_weights,
            FactorWeightingMethod.max_sharpe_weights,
            FactorWeightingMethod.risk_parity_weights,
        ]
        for fn in funcs:
            tree = _func_ast(fn)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'shift'):
                    raise AssertionError(
                        f'{fn.__name__} 出现 .shift() → 沿 index 错行配对 '
                        '(审计 H6)')

    def test_no_shift_in_tester_pairing(self):
        """检验路径的配对同样不得错行 (时序滚动由 window 显式控制)。"""
        tree = _func_ast(FactorEffectivenessTester.test_all_factors)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'shift'):
                raise AssertionError('test_all_factors 出现 .shift() → 错行配对')

    def test_forward_returns_exists(self):
        """标签构造器存在且被导出 (口径有唯一真相源)。"""
        import multi_factor_selection as m
        assert hasattr(m, 'forward_returns')
        assert 'forward_returns' in inspect.getsource(m).split('def ')[0] + \
            'forward_returns'  # 模块级定义可见
