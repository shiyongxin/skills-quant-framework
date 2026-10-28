# -*- coding: utf-8 -*-
"""
审计 H2 回归测试 —— IndicatorSystem.confidence 硬编码参与生产决策

背景 (审计原文):
- confidence 是硬编码常数 (0.7 / min(0.9, fitness*1.2) / 0.6 / 0.75),
  却被 daily_signal_generator.load_systems 当作同体制多系统的**唯一
  挑选依据** —— 编造的数参与决策。
- 其中全局/稳健/迭代路径的值与任何证据无关; 体制路径的 min(0.9, f*1.2)
  是对适应度的任意放大 (×1.2 无出处), 且与其余三处刻度互不一致。

修复 (单一真相源, 证据派生):
- 新增 optimization_engine.confidence_from_fitness(fitness) ——
  confidence = clamp01(适应度): GA 实际最大化的目标值本身 (FitnessConfig
  加权和, 权重和为 1, 来自真实回测窗口指标)。非统计校准概率, docstring
  已如实声明。
- 4 个构造点全部改调该函数; DSG 挑选处注释补语义与局限 (不同系统适应度
  来自各自选择窗口, 横向比较是近似裁决)。
- 旧 manifest 的硬编码值按原样读取 (历史数据不改写)。
"""
import ast
import json

import numpy as np
import pandas as pd

from optimization_config import OptimizationConfig, WalkForwardConfig
from optimization_engine import (FitnessEvaluator, OptimizationEngine,
                                 confidence_from_fitness)
from vectorized_backtest import BacktestMetrics


def _m(total_return=0.0, sharpe=0.0, mdd=0.0, trades=10, win_rate=50.0):
    return BacktestMetrics(total_return=total_return, sharpe_ratio=sharpe,
                           max_drawdown=mdd, num_trades=trades,
                           win_rate=win_rate, profit_factor=1.0)


def _ohlcv(n=400, seed=6):
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
    return pd.DataFrame({
        '日期': pd.date_range('2020-01-01', periods=n, freq='B'),
        '开盘': close * (1 + rng.normal(0, 0.003, n)),
        '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
        '成交量': rng.integers(1e6, 5e6, n).astype(float),
    })


class _FixedEvaluator:
    """适应度恒定 (可断言 confidence == clamp01(fitness))。"""

    def __init__(self, fitness=0.42):
        self.fitness = fitness
        self.weights = {}
        self.walk_forward_config = WalkForwardConfig()
        # 稳健路径 evaluate_robust 会在评估器上取组合口径 (H10 同源)
        self._robust_combine = staticmethod(FitnessEvaluator._robust_combine)
        # 稳健路径汇总各体制 OOS (H1 修复后调用点在评估器上) —— 绑定为实例
        # 方法 (该实现体不读 self, 但签名带 self)
        self._aggregate_oos = FitnessEvaluator._aggregate_oos.__get__(self)

    def evaluate(self, params, stock_data, regime_labels=None,
                 target_regime=None, return_is_metrics=False):
        details = {'sample_count': 1}
        if return_is_metrics:
            details['is_metrics'] = [_m()]
        return self.fitness, details


class TestConfidenceFromFitness:
    """单一真相源函数: 夹取语义。"""

    def test_passthrough_in_unit_interval(self):
        assert confidence_from_fitness(0.42) == 0.42
        assert confidence_from_fitness(0.0) == 0.0
        assert confidence_from_fitness(1.0) == 1.0

    def test_clamp_out_of_range(self):
        assert confidence_from_fitness(-3.5) == 0.0
        assert confidence_from_fitness(1.3) == 1.0

    def test_returns_float(self):
        assert isinstance(confidence_from_fitness(0.5), float)


class TestStagesEvidenceDerived:
    """4 个优化阶段构造的 system.confidence 必须等于 clamp01(适应度)。

    旧实现: global=0.7 / regime=min(0.9,f*1.2) / robust=0.6 /
    iterative=0.75 —— 常数与证据无关。
    """

    def _cfg(self):
        cfg = OptimizationConfig()
        cfg.robustness.n_baseline_samples = 0
        cfg.robustness.n_bootstrap = 0
        return cfg

    def test_global_stage(self):
        eng = OptimizationEngine(seed=1, config=self._cfg())
        eng.stock_data = {'600000': _ohlcv(400)}
        eng.evaluator = _FixedEvaluator(fitness=0.42)
        result = eng.optimize_global(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 3, 'max_generations': 1},
            verbose=False)
        sys_ = result.best_system
        assert sys_.confidence == sys_.fitness_scores['GLOBAL'] == 0.42
        # 旧硬编码 0.7 不再出现
        assert sys_.confidence != 0.7

    def test_regime_stage(self):
        eng = OptimizationEngine(seed=2, config=self._cfg())
        data = _ohlcv(400)
        eng.stock_data = {'600000': data}
        eng.regime_labels = {'600000': pd.Series(
            ['BULL'] * 400, index=data['日期'])}
        eng.evaluator = _FixedEvaluator(fitness=0.55)
        results = eng.optimize_by_regime(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 3, 'max_generations': 1},
            verbose=False)
        sys_ = results['BULL'].best_system
        assert sys_.confidence == sys_.fitness_scores['BULL'] == 0.55
        # 旧实现 min(0.9, 0.55*1.2)=0.66 不再出现
        assert sys_.confidence == 0.55

    def test_robust_stage(self):
        eng = OptimizationEngine(seed=3, config=self._cfg())
        data = _ohlcv(400)
        eng.stock_data = {'600000': data}
        eng.regime_labels = {'600000': pd.Series(
            ['BULL'] * 400, index=data['日期'])}
        eng.evaluator = _FixedEvaluator(fitness=0.42)
        result = eng.optimize_robust(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 3, 'max_generations': 1},
            verbose=False)
        sys_ = result.best_system
        # 各体制 fitness 恒 0.42 → 稳健组合 (0.7*min+0.3*avg) = 0.42
        assert sys_.confidence == 0.42
        # 旧硬编码 0.6 不再出现
        assert sys_.confidence != 0.6

    def test_iterative_stage(self):
        eng = OptimizationEngine(seed=4, config=self._cfg())
        eng.stock_data = {'600000': _ohlcv(400)}
        eng.evaluator = _FixedEvaluator(fitness=0.33)
        eng.iterative_optimize(
            stock_sample=['600000'], n_stocks=1,
            n_rounds=1, verbose=False)
        sys_ = eng.results['ITERATIVE'].best_system
        assert sys_.confidence == sys_.fitness_scores['GLOBAL'] == 0.33
        # 旧硬编码 0.75 不再出现
        assert sys_.confidence != 0.75

    def test_high_fitness_saturates_at_one(self):
        eng = OptimizationEngine(seed=5, config=self._cfg())
        eng.stock_data = {'600000': _ohlcv(400)}
        eng.evaluator = _FixedEvaluator(fitness=1.3)
        result = eng.optimize_global(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 3, 'max_generations': 1},
            verbose=False)
        assert result.best_system.confidence == 1.0


class TestDSGTiebreaker:
    """daily_signal_generator.load_systems: 挑选依据 = 证据派生 confidence。"""

    def _load(self, tmp_path, systems):
        from daily_signal_generator import DailySignalGenerator
        manifest = {'systems': systems}
        fp = tmp_path / 'opt.json'
        fp.write_text(json.dumps(manifest, ensure_ascii=False),
                      encoding='utf-8')
        gen = DailySignalGenerator(data_dir=str(tmp_path))
        gen.load_systems(str(fp))
        return gen

    def _sys(self, name, confidence, regimes):
        return {
            'name': name, 'description': name,
            'applicable_regimes': regimes,
            'params': {'ma_fast': 5}, 'fitness_scores': {},
            'confidence': confidence, 'sample_count': 1,
        }

    def test_higher_confidence_wins(self, tmp_path):
        gen = self._load(tmp_path, [
            self._sys('global', 0.4, ['BULL']),
            self._sys('bull_spec', 0.8, ['BULL']),
        ])
        assert gen.systems['BULL']['name'] == 'bull_spec'

    def test_ties_keep_first_loaded(self, tmp_path):
        gen = self._load(tmp_path, [
            self._sys('first', 0.5, ['BULL']),
            self._sys('second', 0.5, ['BULL']),
        ])
        assert gen.systems['BULL']['name'] == 'first'

    def test_confidence_tracks_fitness_not_stage_name(self, tmp_path):
        """新口径: 低适应度的专用系统不再凭"专用型"身份压过高适应度全局系统。

        旧实现里专用系统 min(0.9, f*1.2) 常 ≥ 全局常数 0.7 → 专用恒胜;
        现按证据 (适应度) 裁决。
        """
        gen = self._load(tmp_path, [
            self._sys('global', confidence_from_fitness(0.8), ['BULL']),
            self._sys('weak_bull', confidence_from_fitness(0.3), ['BULL']),
        ])
        assert gen.systems['BULL']['name'] == 'global'


class TestOldManifestCompat:
    """旧 manifest 的硬编码 confidence 按原样读取 (历史数据不改写)。"""

    def test_load_results_preserves_historical_value(self, tmp_path):
        eng = OptimizationEngine(seed=6)
        # 旧 manifest 形状: systems[] 每项带 regime 键
        data = {
            'systems': [{
                'regime': 'GLOBAL',
                'name': 't', 'description': 't',
                'applicable_regimes': ['BULL'],
                'params': {'ma_fast': 5},
                'fitness_scores': {'GLOBAL': 0.9},
                'confidence': 0.7,  # 旧硬编码值
                'sample_count': 1,
            }],
        }
        fp = tmp_path / 'old.json'
        fp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        eng.load_results(str(fp))
        loaded = eng.results['GLOBAL'].best_system
        assert loaded.confidence == 0.7  # 原样, 不被"纠正"成 clamp01(0.9)


class TestManifestRoundTrip:
    """save_results → load_results: 证据派生值往返不变。"""

    def test_roundtrip(self, tmp_path):
        cfg = OptimizationConfig()
        cfg.robustness.n_baseline_samples = 0
        cfg.robustness.n_bootstrap = 0
        eng = OptimizationEngine(seed=7, config=cfg)
        eng.stock_data = {'600000': _ohlcv(400)}
        eng.evaluator = _FixedEvaluator(fitness=0.61)
        eng.optimize_global(
            stock_sample=['600000'], n_stocks=1,
            ga_params={'population_size': 3, 'max_generations': 1},
            verbose=False)
        fp = tmp_path / 'opt.json'
        eng.save_results(str(fp))
        saved = json.loads(fp.read_text(encoding='utf-8'))
        assert saved['systems'][0]['confidence'] == 0.61
        # 顶层口径自证 (与 oos_policy / robustness_policy 同款)
        policy = saved['confidence_policy']
        assert policy['formula'] == 'clamp01(fitness)'
        assert '不是统计校准' in policy['note']
        eng2 = OptimizationEngine()
        eng2.load_results(str(fp))
        assert eng2.results['GLOBAL'].best_system.confidence == 0.61


class TestSourceHonesty:
    """源码级门禁: 构造点不得再出现字面量/表达式 confidence。"""

    def test_no_hardcoded_confidence_in_engine(self):
        """optimization_engine 内 confidence= 关键字只允许两种形态:
        ① confidence_from_fitness(...) 调用 (证据派生, 生产路径);
        ② sys_data['confidence'] (load_results 读历史值)。
        """
        import optimization_engine as oe
        tree = ast.parse(open(oe.__file__, encoding='utf-8').read())
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != 'confidence':
                    continue
                val = kw.value
                if (isinstance(val, ast.Call)
                        and getattr(val.func, 'id', None)
                        == 'confidence_from_fitness'):
                    continue
                if isinstance(val, ast.Subscript):
                    continue  # sys_data['confidence'] 读历史值
                offenders.append(f'line {node.lineno}: '
                                 f'{ast.dump(val)[:80]}')
        assert not offenders, (
            f'发现非证据派生的 confidence 赋值: {offenders}')

    def test_no_fabricated_constants_remain(self):
        """旧 4 个硬编码值字面量不得再作为 confidence 出现。"""
        import optimization_engine as oe
        src = open(oe.__file__, encoding='utf-8').read()
        for bad in ('confidence=0.7', 'confidence=0.6',
                    'confidence=0.75', 'confidence=min(0.9'):
            assert bad not in src, f'残留硬编码: {bad}'

    def test_indicator_system_field_documented(self):
        """字段注释必须指向单一真相源 (防静默改回"置信度"话术)。"""
        import optimization_engine as oe
        src = open(oe.__file__, encoding='utf-8').read()
        assert 'confidence_from_fitness' in src
