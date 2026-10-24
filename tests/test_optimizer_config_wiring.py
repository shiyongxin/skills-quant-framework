# -*- coding: utf-8 -*-
"""E-P1 #16: optimization_config 影子配置接线。

合同:
- 优先级: 显式 CLI/kwargs 参数 (ga_params, --pop/--gen/--regime-labels)
  > config.* > 阶段/CLI 内省默认; 子命令 > config.mode (run 子命令除外)。
- 零回归: 不传 config 时引擎行为逐位等于接线前 (阶段分档默认)。
- 出厂值对齐: OptimizationConfig 默认值 == 引擎旧字面量 (walk_forward/
  iterative_rounds/fitness), 接线不改数值。
"""
import numpy as np
import pandas as pd
import pytest

from optimization_config import (FitnessConfig, GAConfig, OptimizationConfig,
                                 WalkForwardConfig)
from optimization_engine import (FitnessEvaluator, GeneticAlgorithm,
                                 OptimizationEngine, main)
from vectorized_backtest import BacktestMetrics


def _df(n=100, seed=2):
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.005, n))
    return pd.DataFrame({
        '日期': pd.date_range('2022-01-03', periods=n, freq='B'),
        '开盘': close, '最高': close * 1.01, '最低': close * 0.99,
        '收盘': close, '成交量': np.full(n, 1e6),
    })


class _FakeEngine:
    """main() 测试桩: 记录构造/加载/阶段调用, 不触网络/文件。"""
    calls = []

    def __init__(self, *args, **kwargs):
        _FakeEngine.calls.append(('init', kwargs))

    def load_data(self, **kwargs):
        _FakeEngine.calls.append(('load', kwargs))

    def optimize_global(self, **kwargs):
        _FakeEngine.calls.append(('global', kwargs))

    def optimize_by_regime(self, **kwargs):
        _FakeEngine.calls.append(('regime', kwargs))

    def optimize_robust(self, **kwargs):
        _FakeEngine.calls.append(('robust', kwargs))

    def iterative_optimize(self, **kwargs):
        _FakeEngine.calls.append(('iterative', kwargs))

    def save_results(self, path):
        _FakeEngine.calls.append(('save', path))


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch):
    import optimization_engine as oe
    _FakeEngine.calls = []
    monkeypatch.setattr(oe, 'OptimizationEngine', _FakeEngine)
    yield


class TestNoConfigZeroRegression:
    """不传 config → 阶段分档/内省默认原样, 逐位等于接线前行为。"""

    def test_stage_ga_defaults_untouched(self):
        e = OptimizationEngine()
        assert e.config is None
        stage = {'population_size': 80, 'max_generations': 40,
                 'convergence_threshold': 8}
        assert e._merge_ga_cfg(stage, None) == stage
        assert e._merge_ga_cfg(stage, {'population_size': 9})['population_size'] == 9

    def test_iterative_defaults_match_config_factory_values(self):
        rounds = OptimizationEngine()._iterative_round_configs()
        assert [r['population_size'] for r in rounds] == [40, 60, 100]
        assert [r['max_generations'] for r in rounds] == [15, 25, 40]
        assert [r['mutation_rate'] for r in rounds] == [0.25, 0.18, 0.12]
        # config 出厂值 → 同一列表 (接线不改数值)
        with_cfg = OptimizationEngine(config=OptimizationConfig())
        assert with_cfg._iterative_round_configs() == rounds

    def test_walk_forward_defaults_are_old_literals(self):
        ev = FitnessEvaluator()
        wf = ev.walk_forward_config
        assert (wf.train_days, wf.test_days, wf.step_days) == (504, 180, 63)

    def test_evaluator_weights_default_unchanged(self):
        assert OptimizationEngine(config=OptimizationConfig()).evaluator.weights \
            == FitnessEvaluator().weights


class TestConfigGAPrecedence:
    """ga_params (CLI 显式) > config.ga > 阶段分档默认。"""

    STAGE = {'population_size': 80, 'max_generations': 40,
             'convergence_threshold': 8}

    def test_config_beats_stage_default(self):
        cfg = OptimizationConfig(ga=GAConfig(population_size=37,
                                             max_generations=9))
        merged = OptimizationEngine(config=cfg)._merge_ga_cfg(self.STAGE)
        assert merged['population_size'] == 37
        assert merged['max_generations'] == 9
        assert merged['convergence_threshold'] == 10  # config 覆盖 stage=8

    def test_explicit_kwargs_beat_config(self):
        cfg = OptimizationConfig(ga=GAConfig(population_size=37))
        merged = OptimizationEngine(config=cfg)._merge_ga_cfg(
            self.STAGE, {'population_size': 7})
        assert merged['population_size'] == 7
        assert merged['max_generations'] == 50  # 未显式给的键仍取 config

    def test_merged_cfg_is_constructible_ga(self):
        cfg = OptimizationConfig(ga=GAConfig(population_size=37))
        merged = OptimizationEngine(config=cfg)._merge_ga_cfg(self.STAGE)
        ga = GeneticAlgorithm(**merged)
        assert ga.population_size == 37
        assert ga.tournament_size == 3 and ga.crossover_rate == 0.8


class TestFitnessAndWalkForwardFlow:
    def test_config_fitness_flows_to_evaluator(self):
        cfg = OptimizationConfig(
            fitness=FitnessConfig(w_sharpe=0.5, target_return=7.0))
        ev = OptimizationEngine(config=cfg).evaluator
        assert ev.weights['sharpe'] == 0.5
        assert ev.target_return == 7.0

    def test_config_walk_forward_governs_evaluate(self):
        """evaluate() 旧硬编码 504/180/63 → config 小窗口真实流过"""
        cfg = OptimizationConfig(
            walk_forward=WalkForwardConfig(train_days=30, test_days=20,
                                           step_days=10))
        engine = OptimizationEngine(config=cfg)
        recorded = {}

        class _StubBW:
            def walk_forward(self, d, params, train_days=None,
                             test_days=None, step_days=None, **kw):
                recorded.update(train_days=train_days, test_days=test_days,
                                step_days=step_days)
                return [BacktestMetrics(total_return=5.0, sharpe_ratio=1.5,
                                        max_drawdown=10.0, num_trades=4,
                                        win_rate=60.0)]

        engine.evaluator.backtester = _StubBW()
        fit, det = engine.evaluator.evaluate({}, {'000001': _df(100)})
        assert recorded == {'train_days': 30, 'test_days': 20, 'step_days': 10}
        assert det.get('sample_count') == 1
        assert np.isfinite(fit) and fit > 0

    def test_iterative_rounds_from_config(self):
        from optimization_config import IterativeRoundConfig
        cfg = OptimizationConfig(iterative_rounds=[
            IterativeRoundConfig(round_num=1, population_size=7,
                                 max_generations=2, mutation_rate=0.5,
                                 convergence_threshold=1)])
        rounds = OptimizationEngine(config=cfg)._iterative_round_configs()
        assert rounds == [{'population_size': 7, 'max_generations': 2,
                           'convergence_threshold': 1, 'mutation_rate': 0.5}]


class TestConfigPersistence:
    def test_save_load_roundtrip_drives_engine(self, tmp_path, capsys):
        cfg = OptimizationConfig(name='myrun', mode='robust',
                                 ga=GAConfig(population_size=33))
        fp = tmp_path / 'opt_cfg.json'
        cfg.save(str(fp))
        loaded = OptimizationConfig.load(str(fp))
        assert loaded.name == 'myrun' and loaded.mode == 'robust'
        assert loaded.ga.population_size == 33
        merged = OptimizationEngine(config=loaded)._merge_ga_cfg(
            {'population_size': 80, 'max_generations': 40,
             'convergence_threshold': 8})
        assert merged['population_size'] == 33
        assert '配置已保存' in capsys.readouterr().out


class TestCLIDispatch:
    def test_no_config_cli_ga_params_empty(self, tmp_path):
        """--pop/--gen argparse 默认移除 → 不再遮蔽 config/阶段默认"""
        main(['global', '--save', str(tmp_path / 'o.json')])
        kinds = [c[0] for c in _FakeEngine.calls]
        assert 'global' in kinds
        glob = next(c for c in _FakeEngine.calls if c[0] == 'global')
        assert glob[1]['ga_params'] == {}
        # 无 config 时体制标签回落旧默认 (行为不变)
        load = next(c for c in _FakeEngine.calls if c[0] == 'load')
        assert load[1]['regime_labels_file'] == 'stock_data/regime_labels.csv'

    def test_explicit_pop_still_wins(self, tmp_path):
        main(['global', '--pop', '9', '--save', str(tmp_path / 'o.json')])
        glob = next(c for c in _FakeEngine.calls if c[0] == 'global')
        assert glob[1]['ga_params'] == {'population_size': 9}

    def _write_cfg(self, tmp_path, mode='global', **kw):
        cfg = OptimizationConfig(name='t', mode=mode)
        cfg.data.stock_sample_size = kw.get('n_stocks', 77)
        cfg.data.regime_labels_file = kw.get('labels', 'my_labels.csv')
        fp = tmp_path / 'cfg.json'
        cfg.save(str(fp))
        return fp

    def test_run_uses_config_mode_and_data(self, tmp_path, capsys):
        fp = self._write_cfg(tmp_path, mode='global')
        main(['run', '--config', str(fp), '--save', str(tmp_path / 'o.json')])
        load = next(c for c in _FakeEngine.calls if c[0] == 'load')
        assert load[1]['regime_labels_file'] == 'my_labels.csv'
        glob = next(c for c in _FakeEngine.calls if c[0] == 'global')
        assert glob[1]['n_stocks'] == 77
        # run: config 全权, 不传 ga_params (阶段合并只剩 config.ga 一层)
        assert 'ga_params' not in glob[1]
        assert ('save', str(tmp_path / 'o.json')) in _FakeEngine.calls
        assert 'mode=global' in capsys.readouterr().out

    def test_run_iterative_rounds_come_from_config(self, tmp_path):
        from optimization_config import IterativeRoundConfig
        cfg = OptimizationConfig(name='t', mode='iterative')
        cfg.iterative_rounds = [IterativeRoundConfig(round_num=1)]
        fp = tmp_path / 'cfg.json'
        cfg.save(str(fp))
        main(['run', '--config', str(fp), '--save', str(tmp_path / 'o.json')])
        it = next(c for c in _FakeEngine.calls if c[0] == 'iterative')
        assert it[1]['n_rounds'] == 1

    def test_subcommand_beats_config_mode(self, tmp_path):
        fp = self._write_cfg(tmp_path, mode='regime')
        main(['global', '--config', str(fp), '--save', str(tmp_path / 'o.json')])
        kinds = [c[0] for c in _FakeEngine.calls]
        assert 'global' in kinds and 'regime' not in kinds
        # config 仍注入引擎 (ga 真相源) 且标签走 config
        init = next(c for c in _FakeEngine.calls if c[0] == 'init')
        assert init[1]['config'] is not None
        load = next(c for c in _FakeEngine.calls if c[0] == 'load')
        assert load[1]['regime_labels_file'] == 'my_labels.csv'

    def test_run_requires_config(self, capsys):
        main(['run'])
        assert '[ERROR] run 子命令需要 --config' in capsys.readouterr().out

    def test_unknown_mode_errors_cleanly(self, tmp_path, capsys):
        cfg = OptimizationConfig(name='t', mode='banana')
        fp = tmp_path / 'cfg.json'
        cfg.save(str(fp))
        main(['run', '--config', str(fp), '--save', str(tmp_path / 'o.json')])
        out = capsys.readouterr().out
        assert '[ERROR] 未知 mode' in out and 'banana' in out
        assert not any(c[0] == 'save' for c in _FakeEngine.calls)


class TestSaveResultsConfigFingerprint:
    def test_manifest_records_config(self, tmp_path):
        import json
        engine = OptimizationEngine.__new__(OptimizationEngine)
        engine.stock_data = {}
        engine.evaluator = FitnessEvaluator()
        engine.results = {}
        engine._ga_runs = []
        engine.seed = 42
        engine._use_weighted_scoring = True
        engine.config = OptimizationConfig(name='fp-run', mode='robust')
        fp = tmp_path / 'res.json'
        engine.save_results(str(fp))
        data = json.loads(fp.read_text(encoding='utf-8'))
        assert data['config'] == {'name': 'fp-run', 'mode': 'robust',
                                  'version': '1.0'}
        assert data['use_weighted_scoring'] is True
        # 无 config → None (既有清单字段不变); 模式键独立于 config 落盘
        engine.config = None
        engine._use_weighted_scoring = False
        engine.save_results(str(fp))
        reloaded = json.loads(fp.read_text(encoding='utf-8'))
        assert reloaded['config'] is None
        assert reloaded['use_weighted_scoring'] is False
