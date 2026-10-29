# -*- coding: utf-8 -*-
"""优化器逐股回测失败必须可见且受罚 (审计 M5, 批次 2)

复验结论 (2026-10-29): 审计 M5 属实, 且失败面比审计记的更宽 —— 静默
`except Exception` 共 **3 处**, 分布在三层:

1. `FitnessEvaluator.evaluate()` 逐股 walk-forward 回测失败 → `continue`
2. `_backtest_regime_windows()` 体制窗内逐窗回测失败 → `continue`
3. `_backtest_by_trade_filter()` 整股回测失败 → `return []`

后果 (研究有效性): 失败的股票**不参与**适应度 → 参数组可能只在**更少样本**
上被评估, 且失败完全不可见 → "崩掉难搞股票、只在好搞股票上表现好"的参数组
反而胜出; 且失败与"该股体制数据不足(不适用)"两种情形被混为一谈。

修复: 逐股记账 (失败/跳过分列) + 失败率惩罚 (按 success_rate 打折) +
硬门槛 (成功率低于 min_success_rate → 归零) + 计数落盘可见。

门禁:
- 行为: 失败计数 / 比例惩罚 / 硬门槛 / 跳过不计失败 / 全失败 → 0 分且可见
- 等价性: **零失败时适应度逐位不变** (不因重构改变任何既有数值)
- 源码级: 评估路径不得再有裸 `except Exception: continue` 式静默丢弃
"""
import ast
import inspect
from pathlib import Path

import pytest

from optimization_engine import (FitnessEvaluator, aggregate_coverage,
                                 evaluation_coverage_fields)

_SKILLS = Path(__file__).resolve().parent.parent / '.claude' / 'skills'
_ENGINE = _SKILLS / 'optimization_engine.py'


class _M:
    """最小 BacktestMetrics 替身 (只提供 _compute_fitness 用到的字段)。"""

    def __init__(self, total_return=1.0, sharpe=0.5, max_drawdown=5.0,
                 num_trades=5, win_rate=0.5, avg_holding_days=10.0):
        self.total_return = total_return
        self.sharpe_ratio = sharpe
        self.max_drawdown = max_drawdown
        self.num_trades = num_trades
        self.win_rate = win_rate
        self.avg_holding_days = avg_holding_days


class _StubBacktester:
    """按"数据对象"决定成功/失败的桩回测器。

    `walk_forward` 不接收 symbol → 用 data 值区分股票 (调用方把 symbol
    字符串当 data 传入)。
    """

    def __init__(self, failing=(), windows=3):
        self.failing = set(failing)
        self.windows = windows

    def walk_forward(self, data, params, **kwargs):
        if data in self.failing:
            raise ValueError(f"回测崩溃: {data}")
        return [_M(total_return=float(i + 1)) for i in range(self.windows)]


def _ev(failing=(), windows=3, **cfg_kwargs):
    from optimization_config import FitnessConfig
    cfg = FitnessConfig(**cfg_kwargs) if cfg_kwargs else None
    return FitnessEvaluator(_StubBacktester(failing, windows),
                            fitness_config=cfg)


class TestFailureCounting:
    def test_failures_are_counted_not_swallowed(self):
        ev = _ev(failing={'600001'})
        fitness, details = ev.evaluate({}, {'600000': '600000', '600001': '600001',
                                           '600002': '600002'})
        assert details['n_stocks_total'] == 3
        assert details['n_stocks_evaluated'] == 3
        assert details['n_stocks_failed'] == 1
        assert details['n_failed_events'] == 1
        assert details['failure_rate'] == pytest.approx(1 / 3)

    def test_failure_list_carries_symbol_and_error(self):
        ev = _ev(failing={'600001'})
        _, details = ev.evaluate({}, {'600000': '600000', '600001': '600001'})
        failed = [f for f in details['failures'] if f['symbol'] == '600001']
        assert failed and failed[0]['error'] == 'ValueError'
        assert '回测崩溃' in failed[0]['message']

    def test_success_rate_is_success_over_attempted(self):
        ev = _ev(failing={'600001'})
        _, details = ev.evaluate({}, {'600000': '600000', '600001': '600001',
                                      '600002': '600002'})
        assert details['success_rate'] == pytest.approx(2 / 3)

    def test_all_failed_yields_zero_with_visible_evidence(self):
        ev = _ev(failing={'600000', '600001'})
        fitness, details = ev.evaluate({}, {'600000': '600000', '600001': '600001'})
        assert fitness == 0.0
        assert details['n_stocks_failed'] == 2
        assert details['evaluation_available'] is False
        assert len(details['failures']) == 2

    def test_regime_data_shortage_is_skip_not_failure(self):
        """体制数据不足 = 该股**不适用** (数据驱动, 非参数驱动) → 不计失败。"""
        import pandas as pd

        class _RegimeStub(_StubBacktester):
            def walk_forward(self, data, params, **kwargs):
                raise AssertionError('体制路径不该走 walk_forward')

        ev = FitnessEvaluator(_RegimeStub())
        labels = {'600000': pd.Series(['BULL'] * 10)}   # 远少于 60 根
        fitness, details = ev.evaluate({}, {'600000': '600000'}, labels, 'BULL')
        assert details['n_stocks_skipped'] == 1
        assert details['n_stocks_failed'] == 0
        assert details['n_stocks_evaluated'] == 0
        assert details['success_rate'] == 1.0
        assert fitness == 0.0      # 无 IS 窗口 → 无适应度


class TestFailurePenalty:
    def test_fitness_scaled_by_success_rate(self):
        """部分失败 → 适应度按成功比例打折 (不得"不受罚")。"""
        clean = _ev()
        f_clean, d_clean = clean.evaluate({}, {'600000': '600000',
                                               '600001': '600001'})
        partial = _ev(failing={'600001'})
        f_partial, d_partial = partial.evaluate({}, {'600000': '600000',
                                                     '600001': '600001'})
        assert d_partial['penalty_mode'] == 'scaled'
        assert f_partial == pytest.approx(f_clean * 0.5)
        assert d_partial['fitness_before_penalty'] == pytest.approx(f_clean)

    def test_hard_gate_zeroes_fitness_below_threshold(self):
        """成功率低于 min_success_rate → 归零 (不得挤掉"完整但平庸"的参数组)。"""
        ev = _ev(failing={'600001', '600002', '600003'})
        fitness, details = ev.evaluate({}, {'600000': '600000', '600001': '600001',
                                            '600002': '600002', '600003': '600003'})
        assert details['success_rate'] == pytest.approx(0.25)
        assert details['penalty_mode'] == 'gated'
        assert fitness == 0.0

    def test_gate_threshold_is_configurable(self):
        ev = _ev(failing={'600001', '600002', '600003'},
                 min_success_rate=0.0)
        fitness, details = ev.evaluate({}, {'600000': '600000', '600001': '600001',
                                            '600002': '600002', '600003': '600003'})
        assert details['penalty_mode'] == 'scaled'
        assert fitness > 0.0

    def test_no_failure_means_no_penalty(self):
        ev = _ev()
        fitness, details = ev.evaluate({}, {'600000': '600000'})
        assert details['penalty_mode'] == 'none'
        assert details['penalty_factor'] == 1.0


class TestZeroFailureEquivalence:
    """零失败时适应度必须**逐位不变** (纯重构, 不改任何既有数值)。"""

    def test_fitness_bit_identical_without_failures(self):
        """零失败 → 适应度 == 未惩罚值 (罚项因子 1.0) 且与黄金值逐位一致。

        黄金值 0.1775 = 0.40*0 (达标率: 3 窗收益 1/2/3 均 < 目标 10%)
        + 0.25*0.04 (中位收益 2 → 2/50) + 0.20*0.25 (中位夏普 0.5 → /2)
        + 0.15*0.80 (中位回撤 5 → 1-5/25) × 交易惩罚 1.0 (均 5 笔)
        """
        ev = _ev()
        fitness, details = ev.evaluate({}, {'600000': '600000',
                                           '600001': '600001'})
        assert fitness == pytest.approx(0.1775)
        assert details['penalty_factor'] == 1.0
        assert details['penalty_mode'] == 'none'
        assert fitness == pytest.approx(details['fitness_before_penalty'])


class TestRegimePathFailureReporting:
    def test_regime_window_failures_are_reported(self):
        """体制路径内部的回测失败必须冒泡到 evaluate() (不再静默 continue)。"""
        import pandas as pd

        class _BoomBacktester:
            def backtest(self, window_data, params):
                raise RuntimeError('体制窗回测崩溃')

        ev = FitnessEvaluator(_BoomBacktester())
        n = 200
        labels = pd.Series(['BULL'] * n)
        fitness, details = ev.evaluate({}, {'600000': '600000'},
                                        {'600000': labels}, 'BULL')
        assert details['n_stocks_failed'] == 1
        assert details['failure_rate'] == 1.0
        assert details['failures']
        assert fitness == 0.0

    def test_trade_filter_path_failure_is_reported(self):
        """短体制路径 (trade filter) 整股回测失败 → 记账, 不静默返回 []。"""
        import pandas as pd

        class _BoomBacktester:
            def backtest_with_details(self, data, params):
                raise RuntimeError('整股回测崩溃')

        ev = FitnessEvaluator(_BoomBacktester())
        labels = pd.Series(['BULL'] * 200)
        fitness, details = ev.evaluate({}, {'600000': '600000'},
                                        {'600000': labels}, 'BULL')
        assert details['n_stocks_failed'] == 1
        assert details['failures']


class TestCoverageSurfacing:
    def test_coverage_fields_extracted_from_details(self):
        ev = _ev(failing={'600001'})
        _, details = ev.evaluate({}, {'600000': '600000', '600001': '600001'})
        fields = evaluation_coverage_fields(details)
        assert fields['n_stocks_total'] == 2
        assert fields['n_stocks_evaluated'] == 2
        assert fields['n_stocks_failed'] == 1
        assert fields['evaluation_success_rate'] == pytest.approx(0.5)

    def test_aggregate_coverage_sums_regimes(self):
        agg = aggregate_coverage({
            'BULL': {'n_stocks_total': 50, 'n_stocks_evaluated': 40,
                     'n_stocks_failed': 4},
            'BEAR': {'n_stocks_total': 50, 'n_stocks_evaluated': 30,
                     'n_stocks_failed': 9},
        })
        assert agg['n_stocks_evaluated'] == 70
        assert agg['n_stocks_failed'] == 13
        assert agg['success_rate'] == pytest.approx(57 / 70)

    def test_manifest_contains_failure_policy(self):
        """落盘 manifest 必须带失败口径 (与 oos/confidence/robustness 同款)。"""
        from optimization_engine import OptimizationEngine
        eng = OptimizationEngine(seed=1)
        assert hasattr(eng.evaluator, 'min_success_rate')
        src = inspect.getsource(OptimizationEngine.save_results)
        assert "'failure_policy'" in src
        assert "'evaluation'" in src


class TestSourceHonesty:
    """源码级: 评估路径不得再静默吞掉回测失败。"""

    def test_no_silent_except_continue_in_evaluator(self):
        tree = ast.parse(_ENGINE.read_text(encoding='utf-8'))
        evaluator = next(n for n in ast.walk(tree)
                         if isinstance(n, ast.ClassDef)
                         and n.name == 'FitnessEvaluator')
        offenders = []
        for meth in evaluator.body:
            if not isinstance(meth, ast.FunctionDef):
                continue
            for node in ast.walk(meth):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                # except X: continue / except X: pass / except X: return []
                body = node.body
                if len(body) == 1 and isinstance(body[0], (ast.Continue,
                                                          ast.Pass)):
                    offenders.append(f"{meth.name}:{node.lineno}")
                    continue
                if len(body) == 1 and isinstance(body[0], ast.Return):
                    ret = body[0].value
                    # 只拦"静默丢弃"形态: 返回空列表/空元组/None;
                    # 返回 (结果, 失败清单) 属记账式处理 → 放行
                    if isinstance(ret, ast.Constant) and ret.value is None:
                        offenders.append(f"{meth.name}:{node.lineno}")
                    elif isinstance(ret, ast.List) and not ret.elts:
                        offenders.append(f"{meth.name}:{node.lineno}")
                    elif (isinstance(ret, ast.Tuple) and ret.elts
                            and all(isinstance(e, ast.List) and not e.elts
                                    for e in ret.elts)):
                        offenders.append(f"{meth.name}:{node.lineno}")
        assert not offenders, (
            f"评估路径出现静默吞掉失败的 except 分支 (审计 M5: 失败必须记账"
            f"+受罚): {offenders}")

    def test_evaluate_records_failures(self):
        src = inspect.getsource(FitnessEvaluator.evaluate)
        assert 'n_stocks_failed' in src
        assert 'success_rate' in src
        assert 'penalty_mode' in src
