# -*- coding: utf-8 -*-
"""
审计 H10 回归测试 —— 优化结果的多重检验/稳健性证据 (E-optimization-portfolio)

背景 (审计原文):
- 优化结果无多重检验校正/稳健性证据: save_results 落盘无试验次数、
  最优 fitness 在随机基线上的分位数、Top-10 参数离散度、bootstrap
  置信区间; 而 optimize_global ~3200 次 / iterative ~7000 次回测量级
  → "最优"是在同一批窗口上重复评估后取最大, 天然偏乐观。

修复 (只报告, 不参与选择):
- n_selection_evaluations: 参与"取最大"的评估次数 (基线/bootstrap 以
  track=False 调用 → 不计入);
- random_baseline: 随机参数经同一评估闭包 (同一 IS 口径, 不触碰 OOS)
  的适应度分布 → 最优值分位数; 独立 RNG 子流, 不影响搜索可复现性;
- top_k_dispersion: 全程被评估参数 top-k 的逐维 range/std;
- bootstrap: 最优参数 IS 窗口重采样 95% CI (稳健模式按体制分层,
  组合口径走 _robust_combine 与搜索同源);
- 落盘 manifest 增 n_evaluations_total + robustness_policy +
  systems[].robustness。

另含 H1 遗留潜伏 bug 的行为回归 (evaluate_robust 曾调
self._aggregate_oos, 但该方法在 FitnessEvaluator 上 → 有体制标签的
稳健模式必 AttributeError; H1 测试仅源码级, 未跑行为路径)。
"""
import inspect
import json

import numpy as np
import pandas as pd
import pytest

from optimization_config import (OptimizationConfig, RobustnessConfig,
                                 WalkForwardConfig)
from optimization_engine import (FitnessEvaluator, IndicatorSystem,
                                 OptimizationEngine)
from parameter_space import ParameterSpace
from vectorized_backtest import BacktestMetrics


def _m(total_return=0.0, sharpe=0.0, mdd=0.0, trades=10, win_rate=50.0):
    """构造可区分的窗口指标对象。"""
    return BacktestMetrics(total_return=total_return, sharpe_ratio=sharpe,
                           max_drawdown=mdd, num_trades=trades,
                           win_rate=win_rate, profit_factor=1.0)


def _ohlcv(n=1200, seed=5):
    """合成日线 (足够长 → 多个 walk-forward 窗口)。"""
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
    return pd.DataFrame({
        '日期': pd.date_range('2020-01-01', periods=n, freq='B'),
        '开盘': close * (1 + rng.normal(0, 0.003, n)),
        '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
        '成交量': rng.integers(1e6, 5e6, n).astype(float),
    })


def _cfg(n_baseline=8, n_bootstrap=30, top_k=5):
    cfg = OptimizationConfig()
    cfg.robustness.n_baseline_samples = n_baseline
    cfg.robustness.n_bootstrap = n_bootstrap
    cfg.robustness.top_k = top_k
    return cfg


class _CountingEvaluator:
    """常数适应度 + 调用计数 (区分 GA 选择评估与基线/bootstrap)。"""

    def __init__(self, fitness=0.5):
        self.fitness = fitness
        self.total_calls = 0
        self.weights = {}  # save_results 读取 fitness_weights
        self.walk_forward_config = WalkForwardConfig()

    def evaluate(self, params, stock_data, regime_labels=None,
                 target_regime=None, return_is_metrics=False):
        self.total_calls += 1
        details = {'sample_count': 1}
        if return_is_metrics:
            details['is_metrics'] = [_m()]
        return self.fitness, details


class _ParamSensitiveEvaluator:
    """适应度随 ma_fast 线性变化 (让 GA 选择有梯度, 可比对参数)。"""

    def __init__(self):
        self.total_calls = 0
        self.weights = {}  # save_results 读取 fitness_weights
        self.walk_forward_config = WalkForwardConfig()

    def evaluate(self, params, stock_data, regime_labels=None,
                 target_regime=None, return_is_metrics=False):
        self.total_calls += 1
        f = float(params.get('ma_fast', 0) or 0) / 100.0
        details = {'sample_count': 1}
        if return_is_metrics:
            details['is_metrics'] = [_m()]
        return f, details


class TestRobustCombine:
    """_robust_combine: 搜索与 bootstrap 共享的组合口径 (H10 配套提炼)。"""

    def test_formula(self):
        out = FitnessEvaluator._robust_combine({'BULL': 1.0, 'BEAR': 0.0})
        assert out == pytest.approx(0.7 * 0.0 + 0.3 * 0.5)

    def test_matches_old_inline_formula(self):
        """与 optimize_robust 旧内联公式逐位一致 (口径不漂移)。"""
        rng = np.random.default_rng(3)
        for _ in range(20):
            fits = {f'R{i}': float(rng.normal(0.5, 0.3)) for i in range(4)}
            vals = list(fits.values())
            old = 0.7 * min(vals) + 0.3 * np.mean(vals)
            assert FitnessEvaluator._robust_combine(fits) == pytest.approx(old)


class TestRandomBaseline:
    """随机参数基线: 分位数语义 / 诚实关闭 / track=False 隔离。"""

    def _engine(self, seed=1):
        return OptimizationEngine(seed=seed)

    def test_best_percentile_semantics(self):
        eng = self._engine()
        fits = iter([0.1, 0.2, 0.3, 0.4])

        def evaluate_fn(params, track=True, **kwargs):
            return next(fits), {}

        rb = eng._random_baseline('global', evaluate_fn, 4, best_fitness=0.35)
        assert rb['available'] is True
        # 最优 0.35 超过基线中 3/4 个样本 (0.1/0.2/0.3 < 0.35)
        assert rb['best_percentile'] == pytest.approx(0.75)
        assert rb['fitness_mean'] == pytest.approx(0.25)
        assert rb['n_samples'] == 4

    def test_zero_samples_honest_unavailable(self):
        eng = self._engine()
        rb = eng._random_baseline('global', lambda p, track=True: (0.0, {}),
                                  0, best_fitness=1.0)
        assert rb['available'] is False
        assert 'n_baseline_samples=0' in rb['reason']

    def test_baseline_calls_use_track_false(self):
        """基线评估不进搜索计数/top-k → 必须以 track=False 调用闭包。"""
        eng = self._engine()
        seen = []

        def evaluate_fn(params, track=True, **kwargs):
            seen.append(track)
            return 0.5, {}

        eng._random_baseline('global', evaluate_fn, 3, best_fitness=0.5)
        assert seen == [False, False, False]

    def test_reproducible_with_stage_seed(self):
        """同 seed → 基线采样序列逐位可复现 (独立子流, E-P0-3 扩展)。

        evaluate_fn 依赖采样参数 (ma_fast) → 统计相同意味着两次采样的
        参数序列相同, 而非 evaluate_fn 恒定。
        """
        def make(seed):
            eng = OptimizationEngine(seed=seed)

            def evaluate_fn(params, track=True, **kwargs):
                return float(params.get('ma_fast', 0)), {}
            return eng._random_baseline('global', evaluate_fn, 6, 10.0)
        assert make(9) == make(9)


class TestTopKDispersion:
    """Top-k 参数离散度: 数值正确 / 截断 / 诚实关闭。"""

    def test_per_param_stats(self):
        entries = [
            (0.9, {'ma_fast': 5, 'ma_slow': 20}),
            (0.8, {'ma_fast': 15, 'ma_slow': 40}),
        ]
        out = OptimizationEngine._top_k_dispersion(entries, k=10)
        assert out['available'] is True
        assert out['k'] == 2
        d = out['per_param']['ma_fast']
        assert d['min'] == 5 and d['max'] == 15
        assert d['range'] == 10 and d['mean'] == 10
        assert d['std'] == pytest.approx(50 ** 0.5)  # ddof=1
        assert out['fitness_spread'] == pytest.approx(0.1)

    def test_k_truncation(self):
        entries = [(float(10 - i), {'ma_fast': i}) for i in range(10)]
        out = OptimizationEngine._top_k_dispersion(entries, k=3)
        assert out['k'] == 3
        # 前 3 名: fitness 10/9/8 → ma_fast 0/1/2
        assert out['per_param']['ma_fast']['max'] == 2

    def test_empty_honest_unavailable(self):
        out = OptimizationEngine._top_k_dispersion([], k=5)
        assert out['available'] is False
        assert '无已评估' in out['reason']


class TestBootstrapCI:
    """bootstrap 95% CI: 窗口不足诚实关闭 / 分层口径 / _robust_combine 走通。"""

    def _engine(self, seed=1):
        return OptimizationEngine(seed=seed)

    def test_insufficient_windows_honest(self):
        eng = self._engine()

        def evaluate_fn(params, track=True, return_is_metrics=False,
                        collect_regimes=False, **kwargs):
            d = {'is_metrics': [_m()]} if return_is_metrics else {}
            return 1.0, d

        out = eng._bootstrap_fitness_ci('global', evaluate_fn, {}, 50)
        assert out['available'] is False
        assert out['n_windows'] == 1
        assert '不足' in out['reason']

    def test_zero_resamples_honest(self):
        eng = self._engine()
        out = eng._bootstrap_fitness_ci('global', lambda p, **kw: (1.0, {}),
                                        {}, 0)
        assert out['available'] is False
        assert 'n_bootstrap=0' in out['reason']

    def test_is_windows_scope_and_bounds(self):
        eng = self._engine()
        metrics = [_m(total_return=r) for r in (1.0, 2.0, 3.0, 4.0, 10.0)]

        def evaluate_fn(params, track=True, return_is_metrics=False,
                        collect_regimes=False, **kwargs):
            d = {'is_metrics': metrics} if return_is_metrics else {}
            return 1.0, d

        out = eng._bootstrap_fitness_ci('global', evaluate_fn, {}, 100)
        assert out['available'] is True
        assert out['scope'] == 'is_windows'
        assert out['n_windows'] == 5
        assert out['n_resamples'] == 100
        assert out['ci_low'] <= out['ci_high']
        assert out['fitness_point'] == 1.0

    def test_reproducible_with_seed(self):
        metrics = [_m(total_return=float(r)) for r in range(1, 8)]

        def make(seed):
            eng = OptimizationEngine(seed=seed)

            def evaluate_fn(params, track=True, return_is_metrics=False,
                            collect_regimes=False, **kwargs):
                d = {'is_metrics': metrics} if return_is_metrics else {}
                return 1.0, d
            return eng._bootstrap_fitness_ci('global', evaluate_fn, {}, 60)
        assert make(4) == make(4)

    def test_regime_stratified_uses_robust_combine(self):
        """稳健模式: regime_metrics → 分层重采样, 组合走 _robust_combine。"""
        eng = self._engine()
        regime_metrics = {
            'BULL': [_m(total_return=2.0), _m(total_return=3.0)],
            'BEAR': [_m(total_return=0.5)],
        }

        def evaluate_fn(params, track=True, return_is_metrics=False,
                        collect_regimes=False, **kwargs):
            return 0.7, {'regime_metrics': regime_metrics}

        combine_calls = []
        orig = eng.evaluator._robust_combine

        def spy(d):
            combine_calls.append(dict(d))
            return orig(d)
        eng.evaluator._robust_combine = spy

        out = eng._bootstrap_fitness_ci('robust', evaluate_fn, {}, 25)
        assert out['available'] is True
        assert out['scope'] == 'per_regime_stratified'
        assert out['n_windows'] == 3
        assert combine_calls  # 组合口径确实走 _robust_combine
        assert set(combine_calls[0]) == {'BULL', 'BEAR'}


class TestEvaluationCount:
    """试验次数: 选择评估与基线/ bootstrap 严格分账。"""

    def test_selection_count_excludes_baseline(self):
        eng = OptimizationEngine(seed=2, config=_cfg(n_baseline=3, n_bootstrap=0))
        eng.stock_data = {'600000': _ohlcv(300)}
        counter = _CountingEvaluator(fitness=0.5)
        eng.evaluator = counter
        result = eng.optimize_global(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 4, 'max_generations': 1},
            verbose=False)
        rb = result.best_system.robustness
        # GA: pop=4 × 1 代 = 4 次选择评估
        assert rb['n_selection_evaluations'] == 4
        assert eng._ga_runs[-1]['n_evals'] == 4
        # 评估器总调用 = 4 (GA) + 3 (基线, track=False) → 计数分账正确
        assert counter.total_calls == 4 + 3

    def test_manifest_total_equals_ga_runs_sum(self, tmp_path):
        eng = OptimizationEngine(seed=3, config=_cfg(n_baseline=2, n_bootstrap=0))
        eng.stock_data = {'600000': _ohlcv(300)}
        eng.evaluator = _CountingEvaluator()
        eng.optimize_global(stock_sample=['600000'], n_stocks=1,
                            ga_params={'population_size': 3,
                                       'max_generations': 1},
                            verbose=False)
        fp = tmp_path / 'opt.json'
        eng.save_results(str(fp))
        data = json.loads(fp.read_text(encoding='utf-8'))
        assert data['n_evaluations_total'] == sum(
            r['n_evals'] for r in data['ga_runs'])
        assert data['systems'][0]['robustness']['n_selection_evaluations'] == 3


class TestBaselineDoesNotPerturbSearch:
    """核心门禁: 基线/bootstrap 的开关与规模不影响 GA 搜索结果。"""

    def _run(self, n_baseline):
        eng = OptimizationEngine(seed=11, config=_cfg(n_baseline=n_baseline,
                                                      n_bootstrap=0))
        eng.stock_data = {'600000': _ohlcv(300)}
        eng.evaluator = _ParamSensitiveEvaluator()
        result = eng.optimize_global(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 5, 'max_generations': 2},
            verbose=False)
        return result.best_system

    def test_same_seed_params_identical_on_vs_off(self):
        on = self._run(n_baseline=6)
        off = self._run(n_baseline=0)
        assert on.params == off.params
        assert on.fitness_scores == off.fitness_scores

    def test_same_seed_evidence_identical(self):
        a = self._run(n_baseline=6).robustness
        b = self._run(n_baseline=6).robustness
        assert a['random_baseline'] == b['random_baseline']
        assert a['top_k_dispersion'] == b['top_k_dispersion']
        assert a['n_selection_evaluations'] == b['n_selection_evaluations']


class TestEndToEnd:
    """真实引擎 (VectorizedBacktester) 端到端: 证据块齐全且语义正确。"""

    def test_global_stage_full_evidence(self):
        cfg = _cfg(n_baseline=6, n_bootstrap=40, top_k=5)
        cfg.walk_forward.train_days = 200
        cfg.walk_forward.test_days = 150
        cfg.walk_forward.step_days = 100
        eng = OptimizationEngine(seed=42, config=cfg)
        eng.stock_data = {'600000': _ohlcv(1200)}
        result = eng.optimize_global(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 5, 'max_generations': 2},
            verbose=False)
        rb = result.best_system.robustness
        assert rb['n_selection_evaluations'] > 0
        assert rb['random_baseline']['available'] is True
        assert rb['random_baseline']['n_samples'] == 6
        assert 0.0 <= rb['random_baseline']['best_percentile'] <= 1.0
        top = rb['top_k_dispersion']
        assert top['available'] is True and top['k'] == 5
        # GA 个体参数是全维度 repair 产物 → 26 维全在
        assert len(top['per_param']) == len(ParameterSpace.get_param_names())
        boot = rb['bootstrap']
        assert boot['available'] is True
        assert boot['scope'] == 'is_windows'
        assert boot['ci_low'] <= boot['ci_high']

    def test_h1_latent_bug_robust_mode_with_labels_runs(self):
        """H1 遗留回归: 有体制标签的稳健模式曾因 self._aggregate_oos 必崩。

        旧代码 evaluate_robust 内写 self._aggregate_oos (方法在
        FitnessEvaluator 上) → 只要 regime_fitnesses 非空即 AttributeError。
        本用例必须真正走到该分支: 小 walk-forward 窗口让每个 300 行体制段
        产出多个窗口 (默认 train=504 时 0 窗口 → 跳过 bug 路径)。
        """
        cfg = _cfg(n_baseline=2, n_bootstrap=0)
        cfg.walk_forward.train_days = 60
        cfg.walk_forward.test_days = 50
        cfg.walk_forward.step_days = 50
        eng = OptimizationEngine(seed=7, config=cfg)
        data = _ohlcv(600)
        eng.stock_data = {'600000': data}
        eng.regime_labels = {'600000': pd.Series(
            ['BULL'] * 300 + ['SIDEWAYS'] * 300, index=data['日期'])}
        # spy: 证明真的走到了 OOS 汇总 (旧代码此处 AttributeError)
        agg_calls = []
        orig_agg = eng.evaluator._aggregate_oos

        def agg_spy(oos_blocks):
            agg_calls.append(len(oos_blocks))
            return orig_agg(oos_blocks)
        eng.evaluator._aggregate_oos = agg_spy
        # 旧代码: evaluate_robust 内 self._aggregate_oos → AttributeError
        result = eng.optimize_robust(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 3, 'max_generations': 1},
            verbose=False)
        assert result is not None
        assert result.best_system.robustness['n_selection_evaluations'] > 0
        # 回归锁: OOS 汇总路径真的被执行 (regime_fitnesses 非空分支)
        assert agg_calls


class TestManifestRoundTrip:
    """落盘/读回: robustness 块与 robustness_policy; 旧 JSON 兼容。"""

    def _engine_with_result(self):
        eng = OptimizationEngine(seed=4, config=_cfg(n_baseline=2,
                                                     n_bootstrap=0))
        eng.stock_data = {'600000': _ohlcv(300)}
        eng.evaluator = _CountingEvaluator()
        eng.optimize_global(stock_sample=['600000'], n_stocks=1,
                            ga_params={'population_size': 3,
                                       'max_generations': 1},
                            verbose=False)
        return eng

    def test_policy_and_system_block_saved(self, tmp_path):
        eng = self._engine_with_result()
        fp = tmp_path / 'opt.json'
        eng.save_results(str(fp))
        data = json.loads(fp.read_text(encoding='utf-8'))
        policy = data['robustness_policy']
        assert policy['n_baseline_samples'] == 2
        assert policy['top_k'] == 5
        assert policy['n_bootstrap'] == 0
        assert '不参与' in policy['note']
        rb = data['systems'][0]['robustness']
        assert set(rb) == {'n_selection_evaluations', 'random_baseline',
                           'top_k_dispersion', 'bootstrap'}

    def test_load_results_reads_robustness_back(self, tmp_path):
        eng = self._engine_with_result()
        fp = tmp_path / 'opt.json'
        eng.save_results(str(fp))
        eng2 = OptimizationEngine(config=_cfg())
        eng2.load_results(str(fp))
        rb = eng2.results['GLOBAL'].best_system.robustness
        assert rb['n_selection_evaluations'] == 3
        assert rb['random_baseline']['available'] is True

    def test_old_json_without_robustness_loads(self, tmp_path):
        """旧版 JSON 无 robustness 键 → 空 dict (如实, 不编造证据)。"""
        eng = self._engine_with_result()
        fp = tmp_path / 'opt.json'
        eng.save_results(str(fp))
        data = json.loads(fp.read_text(encoding='utf-8'))
        del data['systems'][0]['robustness']
        del data['robustness_policy']
        fp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        eng2 = OptimizationEngine(config=_cfg())
        eng2.load_results(str(fp))
        assert eng2.results['GLOBAL'].best_system.robustness == {}


class TestConfigWiring:
    """RobustnessConfig: 出厂默认 / 三级落点 / 存量 JSON 兼容。"""

    def test_defaults(self):
        rc = RobustnessConfig()
        assert rc.n_baseline_samples == 100
        assert rc.top_k == 10
        assert rc.n_bootstrap == 500

    def test_engine_cfg_defaults_without_config(self):
        eng = OptimizationEngine(seed=1)
        assert eng._robustness_cfg() == {'n_baseline_samples': 100,
                                         'top_k': 10, 'n_bootstrap': 500}

    def test_engine_cfg_follows_config(self):
        cfg = OptimizationConfig()
        cfg.robustness.n_baseline_samples = 7
        cfg.robustness.top_k = 3
        cfg.robustness.n_bootstrap = 11
        eng = OptimizationEngine(seed=1, config=cfg)
        assert eng._robustness_cfg() == {'n_baseline_samples': 7,
                                         'top_k': 3, 'n_bootstrap': 11}

    def test_config_roundtrip(self, tmp_path):
        cfg = OptimizationConfig()
        cfg.robustness.n_bootstrap = 42
        fp = tmp_path / 'cfg.json'
        cfg.save(str(fp))
        loaded = OptimizationConfig.load(str(fp))
        assert loaded.robustness.n_bootstrap == 42

    def test_old_json_without_robustness_key(self):
        """存量配置 JSON 无 robustness 键 → 出厂默认 (M2 兼容层同款)。"""
        cfg = OptimizationConfig._from_dict({'name': 'legacy'})
        assert cfg.robustness.n_baseline_samples == 100


class TestSourceHonesty:
    """源码级门禁: 证据只在选择之后组装, 指标收集默认关闭。"""

    def test_evaluate_has_return_is_metrics(self):
        params = inspect.signature(FitnessEvaluator.evaluate).parameters
        assert 'return_is_metrics' in params
        assert params['return_is_metrics'].default is False

    def test_is_metrics_absent_unless_requested(self):
        """GA 路径 (默认) 的 details 不携带 is_metrics (零额外开销)。

        显式请求时只回 IS 窗口 (oos_ratio 切分后) —— bootstrap 重采样
        不得触碰 OOS 窗口, 与 H1 "适应度只由 IS 计算" 同口径。
        """
        windows = [_m(total_return=r) for r in (1.0, 2.0, 3.0)]

        class _StubBT:
            def walk_forward(self, data, params, **kwargs):
                return list(windows)

        ev = FitnessEvaluator(_StubBT())
        _, d_default = ev.evaluate({}, {'600000': None})
        assert 'is_metrics' not in d_default
        _, d_asked = ev.evaluate({}, {'600000': None}, return_is_metrics=True)
        # 3 窗 + oos_ratio=0.3 → 1 窗 OOS + 2 窗 IS; is_metrics 只含 IS
        assert d_asked['is_metrics'] == windows[:2]

    def test_indicator_system_has_robustness_field_default_empty(self):
        sys_ = IndicatorSystem(
            name='t', description='d', applicable_regimes=['BULL'],
            params={}, fitness_scores={}, confidence=0.5, sample_count=0)
        assert sys_.robustness == {}

    def test_finalize_is_post_ga_not_in_fitness(self):
        """_finalize_robustness 只在 GA 结束后调用 (不在 evaluate 闭包内)。

        行为侧已由 TestBaselineDoesNotPerturbSearch 锁定; 此处源码级
        双保险: 各阶段 evaluate 闭包体内不得出现 _finalize_robustness。
        """
        for meth in (OptimizationEngine.optimize_global,
                     OptimizationEngine.optimize_by_regime,
                     OptimizationEngine.optimize_robust,
                     OptimizationEngine.iterative_optimize):
            src = inspect.getsource(meth)
            # 闭包 def evaluate...return 之间不得调用 finalize
            assert src.count('_finalize_robustness') == 1, (
                f'{meth.__name__} 应恰好在 GA 后组装一次证据')
