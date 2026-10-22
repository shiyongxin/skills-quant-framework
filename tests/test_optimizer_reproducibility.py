# -*- coding: utf-8 -*-
"""
E-P0-3/E-P0-4 优化器可复现性 + C-P0-7 财务 point-in-time 契约 回归测试

- 同 seed 同数据 → GA 结果逐位可复现; 各阶段独立子流
- 初始种群/交叉变异/最优解全部强制 repair + validate (审计实测 83.9% 初始违规)
- save_results 落盘 seed / 适应度权重 / 参数空间指纹 / 数据起止 / GA 运行元数据
- select_stocks 缺『公告日』列或缺 as_of → 拒绝运行; 按公告日≤as_of 过滤
"""

import json

import numpy as np
import pandas as pd
import pytest

from optimization_engine import (
    GeneticAlgorithm,
    OptimizationEngine,
    OptimizationResult,
    Individual,
    IndicatorSystem,
)
from parameter_space import ParameterSpace
from multi_factor_selection import (
    MultiFactorSelector,
    multi_factor_select,
    filter_point_in_time,
)
from test_e2e_regression import mk_financial


def _deterministic_fitness(params):
    """确定性适应度: 永不为0(避开GA的fitness==0重估分支), 越接近目标越大"""
    return -sum((float(v) - 7.7) ** 2 for v in params.values()) - 1.0, {}


def _run_ga(seed, population_size=24, generations=6):
    ga = GeneticAlgorithm(population_size=population_size,
                           max_generations=generations,
                           convergence_threshold=generations)
    return ga.run(_deterministic_fitness, rng=np.random.default_rng(seed),
                  verbose=False)


class TestGAReproducible:
    """E-P0-3: 同 seed 同数据 → 逐位可复现"""

    def test_same_seed_same_result(self):
        best_a, _, _ = _run_ga(42)
        best_b, _, _ = _run_ga(42)
        assert best_a.params == best_b.params
        assert best_a.fitness == best_b.fitness

    def test_different_seed_differs(self):
        best_a, _, _ = _run_ga(42)
        best_b, _, _ = _run_ga(43)
        assert best_a.params != best_b.params

    def test_best_params_valid_after_repair(self):
        """E-P0-4: GA 结束后最优解强制 repair + validate"""
        best, _, _ = _run_ga(7)
        ok, violations = ParameterSpace.validate(best.params)
        assert ok, violations


class TestGAInitPopulationRepair:
    """E-P0-4: 初始种群强制 repair (独立采样约84%违反关系约束)"""

    def test_sanity_random_sample_actually_violates(self):
        """钉住前提: 不 repair 的独立采样确实非法 (否则本组测试无意义)"""
        rng = np.random.default_rng(0)
        n_bad = sum(
            0 if ParameterSpace.validate(ParameterSpace.random_sample(rng))[0] else 1
            for _ in range(50)
        )
        assert n_bad > 0

    def test_random_population_all_valid(self):
        ga = GeneticAlgorithm(population_size=60)
        pop = ga._init_population(None, np.random.default_rng(7))
        assert len(pop) == 60
        for ind in pop:
            ok, violations = ParameterSpace.validate(ind.params)
            assert ok, (ind.params, violations)

    def test_seed_params_repaired(self):
        bad_seed = {
            'ma_fast': 30, 'ma_mid': 10, 'ma_slow': 20,  # fast>=slow → 非法
            'w_trend': 50, 'w_momentum': 50, 'w_risk': 50, 'w_performance': 50,
        }
        ok0, _ = ParameterSpace.validate(bad_seed)
        assert not ok0, "测试前提: 种子参数必须先非法"

        ga = GeneticAlgorithm(population_size=5)
        pop = ga._init_population([bad_seed], np.random.default_rng(7))
        for ind in pop:
            ok, violations = ParameterSpace.validate(ind.params)
            assert ok, (ind.params, violations)

    def test_children_valid_through_generation(self):
        """E-P0-4: 交叉/变异后子代也必须 repair (repair docstring 本要求此处调用)"""
        ga = GeneticAlgorithm(population_size=30)
        rng = np.random.default_rng(11)
        pop = ga._init_population(None, rng)
        pop = ga._next_generation(pop, _deterministic_fitness, 0.3, rng)
        assert len(pop) == 30
        for ind in pop:
            ok, violations = ParameterSpace.validate(ind.params)
            assert ok, (ind.params, violations)


class TestEngineSeedAndManifest:
    """E-P0-3: 阶段子流派生 + save_results 可复现元数据落盘"""

    def test_stage_rng_deterministic_and_independent(self):
        e1 = OptimizationEngine(seed=7)
        e2 = OptimizationEngine(seed=7)
        e3 = OptimizationEngine(seed=8)
        # 同 seed 同阶段 → 同流
        assert e1._stage_rng('global').random() == e2._stage_rng('global').random()
        # 同 seed 不同阶段 → 独立子流 (与调用顺序无关)
        assert e1._stage_rng('global').random() != e1._stage_rng('robust').random()
        # 不同 seed → 不同流
        assert e1._stage_rng('global').random() != e3._stage_rng('global').random()
        # 派生是纯函数: 重复调用同阶段得到同流
        assert e1._stage_rng('global').random() == e1._stage_rng('global').random()

    def test_unseeded_nondeterministic(self):
        e = OptimizationEngine(seed=None)
        assert e.seed is None
        assert e._stage_rng('global').random() != e._stage_rng('global').random()

    def test_same_seed_same_stratified_sample(self):
        data = {f'S{i:03d}': pd.DataFrame({'收盘': [1.0, 2.0]})
                for i in range(60)}
        e1, e2 = OptimizationEngine(seed=5), OptimizationEngine(seed=5)
        e1.stock_data = dict(data)
        e2.stock_data = dict(data)
        a = e1._get_sample(None, 10, e1._stage_py_rng('sample'))
        b = e2._get_sample(None, 10, e2._stage_py_rng('sample'))
        assert list(a) == list(b)

    def test_save_results_manifest(self, tmp_path):
        engine = OptimizationEngine(seed=42)
        engine.stock_data = {
            '000001': pd.DataFrame({'日期': pd.to_datetime(['2020-01-02', '2020-06-30'])}),
            '000002': pd.DataFrame({'收盘': [1.0]}),  # 无日期列 → 跳过
        }
        system = IndicatorSystem(
            name='t', description='d', applicable_regimes=['BULL'],
            params={'ma_fast': 5}, fitness_scores={'GLOBAL': -1.0},
            confidence=0.5, sample_count=1)
        engine.results['GLOBAL'] = OptimizationResult(
            regime='GLOBAL',
            best_individual=Individual(params={'ma_fast': 5}, fitness=-1.0),
            best_system=system, all_systems=[system],
            generations_run=3, total_time_sec=1.0, convergence_gen=2)
        engine._record_ga_run('global', {'population_size': 10, 'max_generations': 3},
                              conv_gen=2, time_sec=1.0, n_evals=30)

        fp = tmp_path / 'opt.json'
        engine.save_results(str(fp))
        data = json.loads(fp.read_text(encoding='utf-8'))

        assert data['seed'] == 42
        assert data['n_stocks'] == 2
        assert data['data_start'].startswith('2020-01-02')
        assert data['data_end'].startswith('2020-06-30')
        assert data['fitness_weights'] == engine.evaluator.weights

        ps = data['param_space']
        assert ps['n_params'] == len(ParameterSpace.get_param_names())
        assert ps['names'] == ParameterSpace.get_param_names()
        assert len(ps['digest']) == 16

        run = data['ga_runs'][0]
        assert run['stage'] == 'global'
        assert run['population_size'] == 10
        assert run['max_generations'] == 3
        assert run['convergence_gen'] == 2
        assert run['n_evals'] == 30

        # 落盘 → 加载 往返
        engine2 = OptimizationEngine()
        engine2.load_results(str(fp))
        assert 'GLOBAL' in engine2.results


class TestPITFinancialContract:
    """C-P0-7: select_stocks 的 point-in-time 财务契约 (止血版)"""

    def test_missing_announce_column_rejected(self):
        fin = mk_financial(n_stocks=6).drop(columns=['公告日'])
        with pytest.raises(ValueError, match='公告日'):
            MultiFactorSelector().select_stocks(fin, as_of='2024-06-30')

    def test_missing_as_of_rejected(self):
        fin = mk_financial(n_stocks=6)
        with pytest.raises(ValueError, match='as_of'):
            MultiFactorSelector().select_stocks(fin)

    def test_future_announcements_filtered(self):
        fin = mk_financial(n_stocks=3, seed=1)
        fin['公告日'] = pd.to_datetime(['2023-12-31', '2024-06-30', '2024-04-30'])
        out = MultiFactorSelector().select_stocks(fin, top_n=10, as_of='2024-04-30')
        # 000002.SH(2024-06-30 公告) 在 as_of 之后 → 未来财报不得进入因子
        assert '000002.SH' not in out.index
        # 截止日前已公告的两只存活 (横截面因子需≥2只)
        assert set(out.index) == {'000001.SH', '000003.SH'}

    def test_announce_after_as_of_all_filtered(self):
        fin = mk_financial(n_stocks=3, seed=1)
        fin['公告日'] = pd.to_datetime(['2024-06-30'] * 3)
        out = MultiFactorSelector().select_stocks(fin, top_n=10, as_of='2024-01-31')
        assert len(out) == 0

    def test_nan_announce_dropped(self):
        fin = mk_financial(n_stocks=3, seed=1)
        fin['公告日'] = pd.to_datetime(['2024-03-31', None, '2024-01-31'])
        out = MultiFactorSelector().select_stocks(fin, top_n=10, as_of='2024-06-30')
        # 公告日缺失 → 无法证明已披露 → 剔除
        assert set(out.index) == {'000001.SH', '000003.SH'}
        assert '000002.SH' not in out.index

    def test_filter_helper_direct(self):
        fin = mk_financial(n_stocks=2, seed=1)
        fin['公告日'] = pd.to_datetime(['2024-03-31', '2024-05-31'])
        out = filter_point_in_time(fin, '2024-04-30')
        assert list(out.index) == ['000001.SH']
        with pytest.raises(ValueError, match='公告日'):
            filter_point_in_time(fin.drop(columns=['公告日']), '2024-04-30')
        with pytest.raises(ValueError, match='as_of'):
            filter_point_in_time(fin, None)

    def test_convenience_fn_requires_as_of(self):
        with pytest.raises(ValueError, match='as_of'):
            multi_factor_select(mk_financial(n_stocks=4))

    def test_convenience_fn_with_as_of(self):
        fin = mk_financial(n_stocks=4, seed=2)
        fin['公告日'] = pd.to_datetime(['2024-04-30'] * 4)
        out = multi_factor_select(fin, top_n=2, as_of='2024-06-30')
        assert isinstance(out, pd.DataFrame)
        assert len(out) == 2
        assert 'Composite_Score' in out.columns
