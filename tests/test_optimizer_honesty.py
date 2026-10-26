# -*- coding: utf-8 -*-
"""审计 M2/M3/M9 回归: 优化器死配置与运行元数据诚实性

- M2 target_probability 死配置删除 —— 门禁在 tests/test_indicator_skill_p0.py
  (FitnessConfig 无该字段 + FitnessEvaluator 无该属性 + 存量 JSON 兼容)
- M3 generations_run 必须记实际执行代数, 而非 GA 配置上限 —— 提前收敛时
  两者不等, 旧实现三处 OptimizationResult 构造全记 max_generations;
  迭代聚合更是误用 convergence_gen (最后改善代号) 求和冒充
- M9 risk_parity_position 的 risk_budget 死参删除 (声明后函数体从未使用)
"""
import inspect

import numpy as np
import pandas as pd
import pytest


def _plateau_fitness(params):
    """常数适应度: 仅第 0 代构成"改善", 之后连续无改善 → 必提前收敛"""
    return 1.0, {}


class TestM3GenerationsRunActual:
    """M3: generations_run = 实际执行代数, 非配置上限"""

    def test_early_convergence_reports_actual_generations(self):
        from optimization_engine import GeneticAlgorithm
        ga = GeneticAlgorithm(population_size=8, max_generations=50,
                              convergence_threshold=3)
        best, _, conv_gen, gens_run = ga.run(
            _plateau_fitness, rng=np.random.default_rng(0), verbose=False)
        # 常数适应度: gen0 改善 → conv_gen=0; 此后连续 3 代无改善 → 第 3 代 break
        assert conv_gen == 0
        assert gens_run == 4
        assert gens_run < 50, "测试前提: 必须提前收敛, 否则区分不了上限/实际"

    def test_no_early_stop_runs_to_configured_max(self):
        from optimization_engine import GeneticAlgorithm
        ga = GeneticAlgorithm(population_size=6, max_generations=7,
                              convergence_threshold=10**6)
        _, _, _, gens_run = ga.run(
            _plateau_fitness, rng=np.random.default_rng(0), verbose=False)
        assert gens_run == 7

    def test_result_sources_do_not_record_config_cap(self):
        """源码级门禁: 不得再把配置上限记进 generations_run"""
        import optimization_engine as m
        src = inspect.getsource(m)
        assert "generations_run=ga_cfg['max_generations']" not in src, (
            "generations_run 必须来自 ga.run 返回的实际代数, 不是 max_generations")

    def test_iterative_aggregate_sums_actual_generations(self):
        import optimization_engine as m
        src = inspect.getsource(m)
        # 旧实现: sum(convergence_gen) —— 最后改善代号 ≠ 跑了几代
        assert "sum(r.get('convergence_gen', 0) for r in all_round_results)" \
            not in src


class TestM9RiskParityDeadParamRemoved:
    """M9: risk_budget 声明后函数体从未使用 → 已删"""

    def test_signature_has_no_risk_budget(self):
        from risk_management import PositionSizing
        sig = inspect.signature(PositionSizing.risk_parity_position)
        assert 'risk_budget' not in sig.parameters

    def test_equal_vol_weights_sum_to_capital(self):
        from risk_management import PositionSizing
        cov = pd.DataFrame(np.diag([0.04, 0.04, 0.04]),
                           index=['A', 'B', 'C'], columns=['A', 'B', 'C'])
        pos = PositionSizing.risk_parity_position(cov, capital=30000.0)
        assert pos.sum() == pytest.approx(30000.0)
        # 等波动 → 等风险贡献解应接近等权
        assert (pos - 10000.0).abs().max() < 1.0
