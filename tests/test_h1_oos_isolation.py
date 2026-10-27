# -*- coding: utf-8 -*-
"""
审计 H1 回归测试 —— 优化器真样本外验证 (E-optimization-portfolio §3.1 第 1/2 条)

背景 (审计原文):
- 旧实现 `walk_forward` 的 train_days 只用于"跳过前 N 行", 训练段从未用于拟合;
- fitness = 各测试窗口指标的加权聚合, GA 又在**同一批窗口**上取最大
  → "样本外"窗口实为样本内, 全流程无任何未被触碰的留出集。

修复:
- 末尾 oos_ratio 比例的窗口留作 **OOS**, 从不参与参数选择;
  适应度只由 IS 窗口计算, OOS 指标只进 details['oos'] 用于最终报告;
- IS/OOS 两套指标分列 (IndicatorSystem 字段 + 落盘 oos 块 + 控制台摘要)。

门禁思路同 tests/test_optional_deps.py: 源码级 + 行为断言双向锁定。
"""
import inspect
import json

import numpy as np
import pandas as pd
import pytest

from optimization_config import OptimizationConfig, WalkForwardConfig
from optimization_engine import (FitnessEvaluator, IndicatorSystem,
                                 OptimizationEngine, OptimizationResult,
                                 Individual, split_is_oos, oos_fields)
from vectorized_backtest import BacktestMetrics


def _m(total_return=0.0, sharpe=0.0, mdd=0.0, trades=10, win_rate=50.0):
    """构造一个可区分的指标对象。"""
    return BacktestMetrics(total_return=total_return, sharpe_ratio=sharpe,
                           max_drawdown=mdd, num_trades=trades,
                           win_rate=win_rate, profit_factor=1.0)


class _StubBacktester:
    """返回可预测窗口指标的桩回测器。

    windows: 每次 walk_forward 返回的指标列表 (按时间顺序)。
    """

    def __init__(self, windows):
        self.windows = windows
        self.calls = []

    def walk_forward(self, data, params, train_days=504, test_days=180,
                     step_days=63, **kwargs):
        self.calls.append({'params': dict(params), 'train_days': train_days,
                           'test_days': test_days, 'step_days': step_days})
        return list(self.windows)

    def backtest(self, data, params, **kwargs):
        return self.windows[0] if self.windows else _m()


def _eval_with(windows, oos_ratio=0.3, target_return=10.0):
    """用桩回测器跑一次 evaluate, 返回 (fitness, details)。"""
    ev = FitnessEvaluator(walk_forward_config=WalkForwardConfig(
        train_days=100, test_days=50, step_days=50, oos_ratio=oos_ratio))
    ev.backtester = _StubBacktester(windows)
    return ev.evaluate({}, {'000001': pd.DataFrame({'收盘': [1.0] * 300})})


class TestSplitIsOOS:
    """IS/OOS 切分本身的语义。"""

    def test_split_is_chronological_oos_at_the_end(self):
        windows = [_m(total_return=i) for i in range(10)]
        is_w, oos_w = split_is_oos(windows, 0.3)
        assert len(is_w) == 7 and len(oos_w) == 3
        # OOS 必须是**末尾**窗口 (时间上更晚 → 更接近未来)
        assert is_w[-1] is windows[6]
        assert oos_w[0] is windows[7]

    def test_split_keeps_at_least_one_is_and_one_oos(self):
        windows = [_m() for _ in range(2)]
        is_w, oos_w = split_is_oos(windows, 0.1)
        assert len(is_w) == 1 and len(oos_w) == 1

    def test_split_single_window_has_no_oos(self):
        windows = [_m()]
        is_w, oos_w = split_is_oos(windows, 0.3)
        assert len(is_w) == 1 and oos_w == []

    def test_split_disabled_returns_all_as_is(self):
        windows = [_m() for _ in range(5)]
        is_w, oos_w = split_is_oos(windows, 0.0)
        assert len(is_w) == 5 and oos_w == []


class TestFitnessUsesISOnly:
    """核心断言: 适应度只由 IS 窗口计算, OOS 从不参与选择。"""

    def test_fitness_ignores_oos_windows(self):
        # 前 3 窗 IS (收益 10/20/30), 后 2 窗 OOS (收益 1000/-500)
        windows = [_m(total_return=10, sharpe=1.0), _m(total_return=20, sharpe=1.0),
                   _m(total_return=30, sharpe=1.0), _m(total_return=1000, sharpe=99.0),
                   _m(total_return=-500, sharpe=-99.0)]
        fit, details = _eval_with(windows, oos_ratio=0.4)

        # OOS 指标确实被算出来并单独报告
        oos = details['oos']
        assert oos['available'] is True
        assert oos['windows'] == 2

        # 适应度只反映 IS 窗口: 用"仅 IS 窗口"的评估器重算应完全一致
        ev_is = FitnessEvaluator(walk_forward_config=WalkForwardConfig(
            train_days=100, test_days=50, step_days=50, oos_ratio=0.0))
        ev_is.backtester = _StubBacktester(windows[:3])
        fit_is, _ = ev_is.evaluate({}, {'000001': pd.DataFrame({'收盘': [1.0] * 300})})
        assert fit == pytest.approx(fit_is)

    def test_oos_values_cannot_change_fitness(self):
        """把 OOS 窗口换成极端值, 适应度必须纹丝不动。"""
        base = [_m(total_return=5, sharpe=0.5), _m(total_return=8, sharpe=0.6),
                _m(total_return=9, sharpe=0.7), _m(total_return=11, sharpe=0.8)]
        wild = [_m(total_return=9999, sharpe=999.0), _m(total_return=-9999, sharpe=-999.0)]
        fit_a, _ = _eval_with(base + [_m(total_return=1, sharpe=0.1)], oos_ratio=0.25)
        fit_b, _ = _eval_with(base + wild, oos_ratio=0.25)
        assert fit_a == pytest.approx(fit_b)

    def test_details_report_is_and_oos_windows(self):
        windows = [_m(total_return=5), _m(total_return=6),
                   _m(total_return=7), _m(total_return=8)]
        _, details = _eval_with(windows, oos_ratio=0.25)
        assert details['is_windows'] == 3
        assert details['oos']['windows'] == 1
        assert details['oos']['available'] is True

    def test_oos_unavailable_is_marked_honestly(self):
        """窗口数不足时如实标记不可用, 不静默假装有样本外证据。"""
        _, details = _eval_with([_m(total_return=5)], oos_ratio=0.3)
        assert details['oos']['available'] is False
        assert details['oos']['windows'] == 0
        assert 'reason' in details['oos']


class TestOOSFieldsAndManifest:
    """IS/OOS 分列的落地: IndicatorSystem 字段 + 落盘 + 读回。"""

    def test_oos_fields_helper(self):
        fields = oos_fields({'oos': {'available': True, 'windows': 3,
                                     'fitness': 0.42, 'median_return': 8.1,
                                     'median_sharpe': 1.2,
                                     'median_max_drawdown': 5.0}})
        assert fields['oos_available'] is True
        assert fields['oos_windows'] == 3
        assert fields['oos_fitness'] == pytest.approx(0.42)
        assert fields['oos_median_sharpe'] == pytest.approx(1.2)

    def test_oos_fields_helper_unavailable(self):
        fields = oos_fields({'oos': {'available': False}})
        assert fields['oos_available'] is False
        assert fields['oos_windows'] == 0

    def test_indicator_system_carries_oos_fields(self):
        system = IndicatorSystem(
            name='t', description='d', applicable_regimes=['BULL'],
            params={'ma_fast': 5}, fitness_scores={'GLOBAL': 0.5},
            confidence=0.5, sample_count=3,
            **oos_fields({'oos': {'available': True, 'windows': 2,
                                  'fitness': 0.3, 'median_return': 4.0,
                                  'median_sharpe': 0.9,
                                  'median_max_drawdown': 3.0}}))
        assert system.oos_available is True
        assert system.oos_windows == 2

    def test_manifest_records_oos_policy_and_block(self, tmp_path):
        engine = OptimizationEngine(seed=42)
        engine.stock_data = {'000001': pd.DataFrame(
            {'日期': pd.to_datetime(['2020-01-02', '2020-06-30'])})}
        system = IndicatorSystem(
            name='t', description='d', applicable_regimes=['BULL'],
            params={'ma_fast': 5}, fitness_scores={'GLOBAL': -1.0},
            confidence=0.5, sample_count=1,
            **oos_fields({'oos': {'available': True, 'windows': 2,
                                  'fitness': 0.25, 'median_return': 3.5,
                                  'median_sharpe': 0.8,
                                  'median_max_drawdown': 2.5}}))
        engine.results['GLOBAL'] = OptimizationResult(
            regime='GLOBAL',
            best_individual=Individual(params={'ma_fast': 5}, fitness=-1.0),
            best_system=system, all_systems=[system],
            generations_run=3, total_time_sec=1.0, convergence_gen=2)

        fp = tmp_path / 'opt.json'
        engine.save_results(str(fp))
        data = json.loads(fp.read_text(encoding='utf-8'))

        # 落盘策略 (审计 H1: 隔离口径必须可审计)
        assert 'oos_policy' in data
        assert data['oos_policy']['ratio'] == pytest.approx(0.3)

        oos = data['systems'][0]['oos']
        assert oos['available'] is True
        assert oos['windows'] == 2
        assert oos['fitness'] == pytest.approx(0.25)
        assert oos['median_sharpe'] == pytest.approx(0.8)

        # 读回: OOS 字段不丢
        engine2 = OptimizationEngine()
        engine2.load_results(str(fp))
        loaded = engine2.results['GLOBAL'].best_system
        assert loaded.oos_available is True
        assert loaded.oos_windows == 2


class TestConfigWiring:
    """oos_ratio 走配置层 (三级优先级: 显式 > config > 默认)。"""

    def test_default_ratio_is_sane(self):
        assert WalkForwardConfig().oos_ratio == pytest.approx(0.3)

    def test_config_json_round_trip(self, tmp_path):
        cfg = OptimizationConfig()
        cfg.walk_forward.oos_ratio = 0.4
        fp = tmp_path / 'cfg.json'
        cfg.save(str(fp))
        loaded = OptimizationConfig.load(str(fp))
        assert loaded.walk_forward.oos_ratio == pytest.approx(0.4)

    def test_engine_reads_config_ratio(self):
        cfg = OptimizationConfig()
        cfg.walk_forward.oos_ratio = 0.25
        engine = OptimizationEngine(config=cfg)
        assert engine.evaluator.walk_forward_config.oos_ratio == pytest.approx(0.25)


class TestRobustModeAggregation:
    """稳健模式 (跨体制) 的样本外证据不能被丢掉。"""

    def test_aggregate_oos_across_regimes(self):
        ev = FitnessEvaluator()
        agg = ev._aggregate_oos([
            {'available': True, 'windows': 2, 'fitness': 0.4,
             'median_return': 5.0, 'median_sharpe': 1.0,
             'median_max_drawdown': 3.0},
            {'available': True, 'windows': 3, 'fitness': 0.6,
             'median_return': 9.0, 'median_sharpe': 1.4,
             'median_max_drawdown': 5.0},
        ])
        assert agg['available'] is True
        assert agg['windows'] == 5
        assert agg['regimes'] == 2
        assert agg['median_return'] == pytest.approx(7.0)
        assert agg['median_sharpe'] == pytest.approx(1.2)

    def test_aggregate_oos_unavailable(self):
        ev = FitnessEvaluator()
        agg = ev._aggregate_oos([{'available': False, 'windows': 0}])
        assert agg['available'] is False
        assert agg['windows'] == 0
        assert 'reason' in agg

    def test_robust_path_keeps_regime_oos(self):
        """源码级: 稳健模式的 details 必须保留各体制的 oos 块。"""
        src = inspect.getsource(OptimizationEngine.optimize_robust)
        assert 'regime_oos' in src
        assert "details['oos']" in src


class TestSourceHonesty:
    """源码级门禁: 选择路径不得再直接使用全部窗口。"""

    def test_evaluate_routes_through_split(self):
        src = inspect.getsource(FitnessEvaluator.evaluate)
        assert 'split_is_oos' in src
        assert '_compute_fitness(is_metrics)' in src
        # 旧的写法 (把全部窗口直接喂给适应度) 不得复现
        assert '_compute_fitness(all_metrics)' not in src

    def test_config_documents_oos_ratio(self):
        src = inspect.getsource(WalkForwardConfig)
        assert 'oos_ratio' in src
        assert '样本外' in src


class TestRealEngineEndToEnd:
    """真实引擎 (VectorizedBacktester) 上的端到端隔离验证。"""

    def test_real_walk_forward_produces_oos_segment(self):
        """数据足够长 → 真的划出 OOS 段, 且 IS/OOS 指标不同源。"""
        from vectorized_backtest import VectorizedBacktester
        rng = np.random.default_rng(5)
        n = 1200
        close = 10 * np.cumprod(1 + rng.normal(0, 0.015, n))
        data = pd.DataFrame({
            '日期': pd.date_range('2020-01-01', periods=n, freq='B'),
            '开盘': close * (1 + rng.normal(0, 0.003, n)),
            '最高': close * 1.02, '最低': close * 0.98, '收盘': close,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
        })
        ev = FitnessEvaluator(walk_forward_config=WalkForwardConfig(
            train_days=200, test_days=150, step_days=100, oos_ratio=0.34))
        ev.backtester = VectorizedBacktester()
        fitness, details = ev.evaluate({}, {'000001': data})
        assert fitness >= 0
        oos = details['oos']
        assert oos['available'] is True
        assert oos['windows'] >= 1
        assert details['is_windows'] >= 1
        # IS 与 OOS 是不同窗口 → 样本数之和 = 全部窗口数
        assert details['is_windows'] + oos['windows'] >= 2
