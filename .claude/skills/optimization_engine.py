# -*- coding: utf-8 -*-
"""
遗传算法优化引擎 - Genetic Algorithm Optimization Engine

为不同市场体制分别优化技术分析参数，产出多套指标体系。
- 阶段1: 全局优化（通用基线参数）
- 阶段2: 按体制分别优化（体制专属参数）
- 阶段3: 混合策略优化（跨体制稳健参数）
- 多轮迭代：粗→中→细，逐步精炼
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import json
import time
import copy
import random
import zlib
import hashlib

from parameter_space import ParameterSpace
from vectorized_backtest import (VectorizedBacktester, metrics_from_trades)
from historical_data_manager import HistoricalDataManager
from optimization_config import (FitnessConfig, WalkForwardConfig,
                                 OptimizationConfig)


# ==================== 数据结构 ====================

@dataclass
class IndicatorSystem:
    """一套指标体系"""
    name: str                       # 如 "牛市追涨型"
    description: str                # 适用场景描述
    applicable_regimes: list        # 适用体制: ['BULL', 'EARLY_BULL']
    params: dict                    # 完整参数集
    fitness_scores: dict            # 各体制下的fitness {regime: fitness}
    confidence: float               # clamp01(适应度), 见 confidence_from_fitness (审计 H2, 非统计校准概率)
    sample_count: int               # 支撑该结论的样本数

    # 性能统计
    median_return: float = 0.0
    win_rate_above_10pct: float = 0.0
    median_sharpe: float = 0.0
    median_max_drawdown: float = 0.0
    median_holding_days: float = 0.0
    num_trades: float = 0.0

    # 样本外 (OOS) 指标 —— 审计 H1: 参数选择只用 IS 窗口, 这些数字
    # 来自**从未参与选择**的留出窗口, 是"这套参数能否外推"的唯一证据
    oos_available: bool = False
    oos_windows: int = 0
    oos_fitness: float = 0.0
    oos_median_return: float = 0.0
    oos_median_sharpe: float = 0.0
    oos_median_max_drawdown: float = 0.0

    # 稳健性/多重检验证据 —— 审计 H10: 试验次数 (参与"取最大"的评估次数)、
    # 随机基线分位数、Top-k 参数离散度、bootstrap CI。只报告, 不参与选择
    robustness: dict = field(default_factory=dict)

    # 评估覆盖证据 —— 审计 M5: 逐股回测失败的股票不参与适应度 → 这套参数
    # 到底在多少只股票上被真正评估过 (失败既不可见也不受罚 = 偏差)
    n_stocks_total: int = 0
    n_stocks_evaluated: int = 0
    n_stocks_failed: int = 0
    evaluation_success_rate: float = 1.0


@dataclass
class Individual:
    """GA个体"""
    params: dict
    fitness: float = 0.0
    fitness_details: dict = field(default_factory=dict)


@dataclass
class OptimizationResult:
    """优化结果"""
    regime: str                     # 体制名称, "GLOBAL" 表示全局
    best_individual: Individual
    best_system: IndicatorSystem
    all_systems: list               # 所有候选体系
    generations_run: int
    total_time_sec: float
    convergence_gen: int            # 在第几代收敛


# ==================== 适应度评估 ====================

def split_is_oos(windows: list, oos_ratio: float) -> tuple:
    """按时间顺序把回测窗口切成 (IS 选择用, OOS 仅报告)。

    审计 H1 (E-optimization-portfolio §3.1 第 1/2 条): 旧实现里
    walk_forward 的 train_days 只用于"跳过前 N 行", 训练段从未用于拟合,
    且 GA 在**全部**测试窗口上既评估又取最大 → "样本外"窗口实为样本内,
    选择偏差直接来自这里。

    现在: 末尾 oos_ratio 比例的窗口留作 **OOS**, 从不参与参数选择;
    OOS 指标只用于最终报告 (分列 IS/OOS 两套指标)。

    - 窗口数 < 2 或 oos_ratio <= 0 → 无 OOS (返回空列表; 调用方如实标记
      available=False, 不静默假装有样本外证据)
    - 至少保留 1 个 IS 窗口与 1 个 OOS 窗口
    """
    n = len(windows)
    if n < 2 or oos_ratio <= 0:
        return list(windows), []
    n_oos = int(round(n * oos_ratio))
    n_oos = max(1, min(n - 1, n_oos))
    return list(windows[:n - n_oos]), list(windows[n - n_oos:])


def aggregate_coverage(regime_coverage: dict) -> dict:
    """跨体制聚合评估覆盖证据 (审计 M5)。

    稳健模式对每个体制各评估一遍 → 失败是**按体制**分别发生的, 汇总时
    求和 (总回测股次 / 总失败股次), 成功率按总量重算 (不是各体制成功率的
    平均 —— 后者会让"小样本体制"与"大样本体制"等权, 掩盖真实覆盖)。
    """
    total = sum(int(v.get('n_stocks_total', 0) or 0)
                for v in (regime_coverage or {}).values())
    evaluated = sum(int(v.get('n_stocks_evaluated', 0) or 0)
                    for v in (regime_coverage or {}).values())
    failed = sum(int(v.get('n_stocks_failed', 0) or 0)
                 for v in (regime_coverage or {}).values())
    ok = max(evaluated - failed, 0)
    return {
        'n_stocks_total': total,
        'n_stocks_evaluated': evaluated,
        'n_stocks_failed': failed,
        'success_rate': (ok / evaluated) if evaluated else 1.0,
        'failure_rate': (failed / evaluated) if evaluated else 0.0,
    }


def evaluation_coverage_fields(fitness_details: dict) -> dict:
    """从 fitness_details 提取"评估覆盖"证据 (审计 M5)。

    逐股回测失败 → 该股不参与适应度 → 参数组可能只在**更少样本**上被评估;
    这些字段让覆盖度**可见** (与 confidence/robustness 同款自证)。
    """
    d = fitness_details or {}
    return {
        'n_stocks_total': int(d.get('n_stocks_total', 0) or 0),
        'n_stocks_evaluated': int(d.get('n_stocks_evaluated', 0) or 0),
        'n_stocks_failed': int(d.get('n_stocks_failed', 0) or 0),
        'evaluation_success_rate': float(d.get('success_rate', 1.0) or 0.0),
    }


def oos_fields(fitness_details: dict) -> dict:
    """从 fitness_details 提取样本外指标字段 (构造 IndicatorSystem 用)。

    审计 H1: IS 指标是"选择口径", OOS 指标是"验证口径" —— 两者必须分列,
    不能只报前者 (那正是旧实现的误导之处)。
    """
    oos = (fitness_details or {}).get('oos') or {}
    if not oos.get('available'):
        return {'oos_available': False, 'oos_windows': 0}
    return {
        'oos_available': True,
        'oos_windows': oos.get('windows', 0),
        'oos_fitness': oos.get('fitness', 0.0),
        'oos_median_return': oos.get('median_return', 0.0),
        'oos_median_sharpe': oos.get('median_sharpe', 0.0),
        'oos_median_max_drawdown': oos.get('median_max_drawdown', 0.0),
    }


def confidence_from_fitness(fitness: float) -> float:
    """适应度 → confidence (审计 H2)。

    confidence **不是**统计校准的置信概率, 而是**适应度的 [0,1] 夹取值**
    —— 即 GA 实际最大化的目标值本身 (FitnessConfig 加权和, 来自真实
    回测窗口指标: 达标率/中位收益分/中位夏普分/回撤分, 权重和为 1)。

    审计 H2: 旧实现是 4 处互不一致的硬编码常数 (0.7 / min(0.9, f*1.2) /
    0.6 / 0.75), 其中全局/稳健/迭代路径的值与任何证据无关, 却被
    daily_signal_generator 当作同体制多系统的唯一挑选依据 = 编造的数
    参与决策。现统一为证据派生, 单一真相源, 四个阶段同口径。

    刻度: fitness < 0 → 0; fitness ∈ [0,1] → 原值; fitness > 1 → 1
    (FitnessConfig 权重和为 1, 现实适应度基本落在 [0,1], 夹取仅防御
    极端项)。旧 manifest 中的硬编码值按原样读取 (历史数据不改写)。
    """
    return float(min(max(float(fitness), 0.0), 1.0))


class FitnessEvaluator:
    """
    适应度评估器

    对给定参数在多只股票上进行Walk-Forward回测，
    聚合结果计算适应度分数。
    """

    def __init__(self, backtester=None, target_return=None,
                 max_drawdown_limit=None,
                 fitness_config=None, walk_forward_config=None):
        """
        Parameters:
        -----------
        target_return : float or None
            目标收益率(%) — None 时取 FitnessConfig 默认 (10.0)
        max_drawdown_limit : float or None
            最大回撤限制(%) — None 时取 FitnessConfig 默认 (25.0)
        fitness_config : FitnessConfig or None
            适应度权重来源 (w_target_rate/w_return/w_sharpe/w_drawdown) —
            旧实现这4个权重硬编码于 _compute_fitness, 配置字段恒死参数;
            另含 min_success_rate (审计 M5: 逐股回测失败的硬门槛)
        walk_forward_config : WalkForwardConfig or None
            Walk-Forward 窗口 (train/test/step_days) — 旧实现硬编码于
            evaluate() (审计 E-P1 接线: 配置成为真相源)

        注: 原 target_probability 参数已删 (审计 M2) —— 存入 self 后
        _compute_fitness 从未使用; FitnessConfig 同步删除该字段。
        """
        cfg = fitness_config or FitnessConfig()
        self.backtester = backtester or VectorizedBacktester()
        self.walk_forward_config = walk_forward_config or WalkForwardConfig()
        # 审计 M5: 逐股回测失败的硬门槛 (成功率低于此值 → 参数组不可用)
        self.min_success_rate = float(getattr(cfg, 'min_success_rate', 0.5))
        self.target_return = cfg.target_return if target_return is None else target_return
        self.max_drawdown_limit = cfg.max_drawdown_limit if max_drawdown_limit is None else max_drawdown_limit
        self.weights = {
            'target_rate': cfg.w_target_rate,
            'return': cfg.w_return,
            'sharpe': cfg.w_sharpe,
            'drawdown': cfg.w_drawdown,
        }

    def evaluate(self, params: dict, stock_data: dict,
                 regime_labels: dict = None,
                 target_regime: str = None,
                 return_is_metrics: bool = False) -> tuple:
        """
        评估一组参数在多只股票上的表现

        Parameters:
        -----------
        params : dict
            参数字典
        stock_data : dict
            {symbol: DataFrame} 股票数据
        regime_labels : dict or None
            {symbol: pd.Series} 每只股票的体制标签
        target_regime : str or None
            如果指定，仅评估该体制时段的数据
        return_is_metrics : bool
            True 时 details 额外携带 'is_metrics' (IS 窗口的原始指标对象
            列表) — 审计 H10 bootstrap 重采样用; GA 路径不传 (不进 details,
            零额外开销)。注: 失败路径 (无 IS 窗口) **不含** 'is_metrics'
            键 → 调用方如实标记不可用。

        审计 M5: 逐股回测失败不再静默 (`except Exception: continue` →
        失败既不可见也不受罚 → 参数组可能只在更少样本上被评估)。现在逐股
        记账 (n_stocks_failed / success_rate / failures), 适应度按
        `success_rate` 打折, 成功率低于 `min_success_rate` 直接归零; 计数与
        失败清单进 details (并由 save_results 落盘)。

        Returns:
        --------
        (fitness: float, details: dict)

        Notes:
        -----
        审计 H1: **适应度只由 IS (样本内选择) 窗口计算**; 末尾 oos_ratio 比例
        的窗口留作 OOS (样本外), 其指标只进 details['oos'] 用于最终报告,
        **从不参与参数选择** —— 旧实现 GA 在全部窗口上既评估又取最大,
        "样本外"窗口实为样本内 (选择偏差)。
        """
        is_metrics = []
        oos_metrics = []
        # 审计 M5: 逐股回测失败的记账 (旧实现 `except Exception: continue` →
        # 失败既不可见也不受罚 → 参数组可能只在**更少样本**上被评估, 且
        # 崩溃型参数组因"幸存股票恰好表现好"而胜出)
        n_total = len(stock_data)
        n_attempted = 0          # 真正发起过回测的股票数
        n_failed_stocks = 0      # 至少失败一次的股票数
        n_failed_events = 0      # 失败事件总数 (一只股票可失败多个窗口)
        n_skipped = 0            # 体制数据不足 (不适用, 非失败)
        failures = []

        for symbol, data in stock_data.items():
            stock_failed = False
            try:
                if target_regime and regime_labels and symbol in regime_labels:
                    # 按体制过滤数据
                    labels = regime_labels[symbol]
                    mask = labels == target_regime
                    if mask.sum() < 60:
                        # 该股体制数据不足 = **不适用** (数据驱动, 非参数驱动)
                        # → 不计失败, 但计数可见
                        n_skipped += 1
                        continue
                    n_attempted += 1
                    # 使用连续的体制时段进行回测
                    windows, sub_failures = self._backtest_regime_windows(
                        data, params, labels, target_regime
                    )
                    if sub_failures:
                        stock_failed = True
                        n_failed_events += len(sub_failures)
                        for f in sub_failures:
                            f['symbol'] = symbol
                        failures.extend(sub_failures)
                else:
                    n_attempted += 1
                    # Walk-Forward回测 (窗口来自 walk_forward_config, 审计 E-P1 接线)
                    wf = self.walk_forward_config
                    windows = self.backtester.walk_forward(
                        data, params, train_days=wf.train_days,
                        test_days=wf.test_days, step_days=wf.step_days
                    )
                # 按时间顺序切分: 前段 IS (选择用) / 末尾 OOS (仅报告)
                is_windows, oos_windows = split_is_oos(
                    windows, self.walk_forward_config.oos_ratio)
                is_metrics.extend(is_windows)
                oos_metrics.extend(oos_windows)
            except Exception as e:
                # 审计 M5: 不再静默丢弃 —— 记账 (供惩罚与落盘)
                stock_failed = True
                n_failed_events += 1
                failures.append({'symbol': symbol,
                                 'error': type(e).__name__,
                                 'message': str(e)[:200]})
            if stock_failed:
                n_failed_stocks += 1

        n_ok = max(n_attempted - n_failed_stocks, 0)
        success_rate = (n_ok / n_attempted) if n_attempted else 1.0
        coverage = {
            'n_stocks_total': n_total,
            'n_stocks_evaluated': n_attempted,
            'n_stocks_failed': n_failed_stocks,
            'n_failed_events': n_failed_events,
            'n_stocks_skipped': n_skipped,
            'success_rate': success_rate,
            'failure_rate': (1.0 - success_rate) if n_attempted else 0.0,
            'failures': failures[:20],
        }

        if not is_metrics:
            # 无 IS 窗口 → 无适应度 (旧实现返回 0.0, {}); 现在带上失败记账
            # (审计 M5: 失败不能静默 —— 无证据本身就是结论的一部分)
            coverage['evaluation_available'] = False
            coverage['fitness_before_penalty'] = 0.0
            coverage['penalty_factor'] = success_rate
            coverage['penalty_mode'] = 'no_evidence'
            return 0.0, coverage

        fitness, details = self._compute_fitness(is_metrics)
        details['is_windows'] = len(is_metrics)
        details['oos'] = self._summarize_oos(oos_metrics)
        # 审计 H10: 逐窗口 IS 指标 (bootstrap 重采样用) — 只在显式要求时
        # 携带, GA 路径不传 → 零额外开销
        if return_is_metrics:
            details['is_metrics'] = is_metrics

        # 审计 M5: 失败惩罚 —— 参数组只在更少样本上被评估时, 不得"不受罚"
        coverage['evaluation_available'] = True
        details.update(coverage)
        details['fitness_before_penalty'] = fitness
        details['penalty_factor'] = success_rate
        if success_rate < self.min_success_rate:
            # 失败比例过高 → 该参数组不可用 (不能靠"只在能跑通的股票上表现好"
            # 拿到高分); 归零而不是打折, 避免"崩一半"的参数组挤掉"完整但平庸"
            # 的参数组
            details['penalty_mode'] = 'gated'
            fitness = 0.0
        else:
            details['penalty_mode'] = ('scaled' if success_rate < 1.0
                                      else 'none')
            fitness = fitness * success_rate
        return fitness, details

    @staticmethod
    def _robust_combine(regime_fitnesses: dict) -> float:
        """稳健适应度 = 0.7 * min(各体制) + 0.3 * avg(各体制)。

        审计 H10 配套: 从 evaluate_robust 闭包提炼 —— bootstrap 重采样
        必须用与搜索**完全相同**的组合口径, 否则 CI 对应的不是被报告的
        那个 fitness (口径冒充)。
        """
        vals = list(regime_fitnesses.values())
        return 0.7 * min(vals) + 0.3 * float(np.mean(vals))

    def _aggregate_oos(self, oos_blocks: list) -> dict:
        """跨体制汇总样本外证据 (稳健模式用)。

        各体制的 OOS 块按窗口数汇总, 指标取跨体制中位数 —— 与 IS 侧
        "跨窗口中位数" 的聚合方式保持一致口径。
        """
        usable = [b for b in (oos_blocks or [])
                  if b and b.get('available')]
        if not usable:
            return {
                'available': False,
                'windows': 0,
                'reason': '各体制均无法划分样本外段 (窗口数不足)',
            }
        return {
            'available': True,
            'windows': int(sum(b.get('windows', 0) for b in usable)),
            'regimes': len(usable),
            'fitness': float(np.median([b.get('fitness', 0.0) for b in usable])),
            'median_return': float(np.median(
                [b.get('median_return', 0.0) for b in usable])),
            'median_sharpe': float(np.median(
                [b.get('median_sharpe', 0.0) for b in usable])),
            'median_max_drawdown': float(np.median(
                [b.get('median_max_drawdown', 0.0) for b in usable])),
        }

    def _summarize_oos(self, oos_metrics: list) -> dict:
        """汇总 OOS (样本外) 窗口指标 —— 只用于报告, 从不参与选择。

        窗口数不足 2 时无法划分样本外段 (如返回 (0, 0)), 此时如实标记
        available=False 并给出原因, 不静默假装有样本外证据。
        """
        if not oos_metrics:
            return {
                'available': False,
                'windows': 0,
                'reason': '窗口数不足, 无法划分样本外段 (需要至少 2 个窗口)',
            }
        fitness, details = self._compute_fitness(oos_metrics)
        return {
            'available': True,
            'windows': len(oos_metrics),
            'fitness': fitness,
            'median_return': details['median_return'],
            'median_sharpe': details['median_sharpe'],
            'median_max_drawdown': details['median_drawdown'],
            'target_rate': details['target_rate'],
            'avg_trades': details['avg_trades'],
        }

    def _backtest_regime_windows(self, data, params, labels, target_regime):
        """
        在体制时段内进行回测

        混合策略:
        - 长窗口体制(BULL/BEAR/SIDEWAYS): 按连续窗口切割回测
        - 短窗口体制(CRASH/RECOVERY): 全量回测后按交易入口过滤

        审计 M5: 返回 `(metrics_list, failures)` —— 体制窗内的回测失败不再
        静默丢弃, 逐窗记账并向上冒泡 (旧实现 `except Exception: continue`)。
        """
        metrics_list = []
        failures = []

        # 找出连续的体制时段
        in_regime = labels == target_regime
        regime_total_days = in_regime.sum()

        # 找出最长连续天数
        max_consec = 0
        cur = 0
        for v in in_regime:
            if v:
                cur += 1
                max_consec = max(max_consec, cur)
            else:
                cur = 0

        # 短窗口体制: 全量回测 + 交易入口过滤
        if max_consec < 15 or regime_total_days < 60:
            return self._backtest_by_trade_filter(data, params, labels,
                                                  target_regime)

        # 长窗口体制: 按连续窗口切割
        starts = []
        for i in range(len(in_regime)):
            if in_regime.iloc[i] and (i == 0 or not in_regime.iloc[i-1]):
                starts.append(i)

        for start in starts:
            end = start
            while end < len(in_regime) and in_regime.iloc[end]:
                end += 1

            if end - start < 15:
                continue

            window_data = data.iloc[start:end]
            if len(window_data) < 15:
                continue

            try:
                metrics = self.backtester.backtest(window_data, params)
                if metrics.num_trades > 0:
                    metrics_list.append(metrics)
            except Exception as e:
                # 审计 M5: 记账而非静默 continue (失败数进入上层惩罚)
                failures.append({'error': type(e).__name__,
                                 'message': str(e)[:200],
                                 'window': [int(start), int(end)]})
                continue

        return metrics_list, failures

    def _backtest_by_trade_filter(self, data, params, labels, target_regime):
        """
        全量回测 + 按交易入口体制过滤

        适用于短窗口体制(CRASH/RECOVERY):
        1. 对整只股票做回测，获取每笔交易的入场日期
        2. 检查入场日的体制标签
        3. 仅保留入场时处于目标体制的交易
        4. 用过滤后的交易计算指标

        审计 M5: 返回 `(metrics_list, failures)` —— 整股回测失败不再静默
        返回空列表 (旧实现), 失败被记账并进入上层惩罚。
        """
        try:
            metrics, trade_details = self.backtester.backtest_with_details(data, params)
        except Exception as e:
            return [], [{'error': type(e).__name__, 'message': str(e)[:200]}]

        if not trade_details:
            return [], []

        # 按入口过滤交易
        filtered_trades = []
        for td in trade_details:
            if td.entry_idx < len(labels):
                entry_regime = labels.iloc[td.entry_idx]
                if entry_regime == target_regime:
                    filtered_trades.append(td)

        if not filtered_trades:
            return []

        # 从过滤后的交易计算指标
        filtered_metrics = self._compute_metrics_from_trades(filtered_trades, data, params)
        if filtered_metrics and filtered_metrics.num_trades > 0:
            return [filtered_metrics], []
        return [], []

    def _compute_metrics_from_trades(self, trades, data, params):
        """从过滤后的交易列表计算 BacktestMetrics（审计 E-P1: 调用共享
        metrics_from_trades 统一口径, 消除与 vectorized_backtest 的重复块）。

        修正审计 #15/#20 三处口径错误:
        - 年化分母: 取过滤后交易的暴露跨度 [首笔入场, 末笔出场], 不再用
          整只股票全历史 (短体制路径年化严重失真);
        - 最大回撤: 日频盯市净值 (与 B 引擎同构造), 不再用逐笔复利序列;
        - 夏普: 日频盯市收益年化252, 不再用逐笔收益冒充日频。
        """
        if not trades:
            return None

        entry0 = min(int(t.entry_idx) for t in trades)
        exit1 = max(int(t.exit_idx) for t in trades)
        window = data.iloc[entry0:exit1 + 1]
        if len(window) < 1:
            return None

        close = window['收盘'].to_numpy(dtype=np.float64)
        open_arr = window['开盘'].to_numpy(dtype=np.float64)
        pnl_arr = np.array([t.pnl_pct for t in trades], dtype=np.float64)
        holding_arr = np.array([t.holding_days for t in trades], dtype=np.float64)
        spans = [(int(t.entry_idx) - entry0, int(t.exit_idx) - entry0)
                 for t in trades]

        # 与 B 引擎 _simulate_trades 同口径的仓位系数
        position_size_pct = float(params.get('position_size_pct', 0.8))
        max_position_pct = float(params.get('max_position_pct', 1.0))
        position_size_pct = min(position_size_pct, max_position_pct)

        return metrics_from_trades(pnl_arr, holding_arr, spans,
                                   close, open_arr, position_size_pct)

    def _compute_fitness(self, metrics_list: list) -> tuple:
        """
        从回测指标列表计算适应度

        fitness = (w_target_rate*达标率 + w_return*中位收益分
                   + w_sharpe*中位夏普分 + w_drawdown*回撤分) * 交易次数惩罚

        权重来自 FitnessConfig (self.weights), 不再硬编码 (审计项 19)。
        """
        w = self.weights
        returns = [m.total_return for m in metrics_list]
        sharpes = [m.sharpe_ratio for m in metrics_list]
        drawdowns = [m.max_drawdown for m in metrics_list]
        win_rates = [m.win_rate for m in metrics_list]
        trades = [m.num_trades for m in metrics_list]
        holding_days = [m.avg_holding_days for m in metrics_list]

        # 达标率: 收益>target_return的比例
        target_met = sum(1 for r in returns if r >= self.target_return)
        target_rate = target_met / len(returns) if returns else 0

        # 中位收益率 (归一化到0-1)
        median_ret = np.median(returns) if returns else 0
        ret_score = min(max(median_ret / 50, -1), 1)  # 50%收益得满分

        # 中位夏普 (归一化到0-1)
        median_sharpe = np.median(sharpes) if sharpes else 0
        sharpe_score = min(max(median_sharpe / 2, -1), 1)  # 夏普2得满分

        # 回撤惩罚 (越小越好; abs 兼容不同来源符号)
        median_dd = np.median([abs(d) for d in drawdowns]) if drawdowns else 100
        dd_penalty = max(0, 1 - median_dd / self.max_drawdown_limit)

        # 交易次数惩罚 (太少或太多都不好)
        avg_trades = np.mean(trades) if trades else 0
        if avg_trades < 3:
            trade_penalty = avg_trades / 3
        elif avg_trades > 50:
            trade_penalty = max(0, 1 - (avg_trades - 50) / 50)
        else:
            trade_penalty = 1.0

        # 综合适应度 (权重来自 FitnessConfig)
        fitness = (
            w['target_rate'] * target_rate +
            w['return'] * max(0, ret_score) +
            w['sharpe'] * max(0, sharpe_score) +
            w['drawdown'] * dd_penalty
        ) * trade_penalty

        details = {
            'target_rate': target_rate,
            'median_return': median_ret,
            'median_sharpe': median_sharpe,
            'median_drawdown': median_dd,
            'avg_trades': avg_trades,
            'avg_holding_days': np.mean(holding_days) if holding_days else 0,
            'sample_count': len(metrics_list),
            'win_rate': np.mean(win_rates) if win_rates else 0,
        }

        return fitness, details


# ==================== 遗传算法引擎 ====================

class GeneticAlgorithm:
    """
    遗传算法实现

    锦标赛选择(k=3) + 均匀交叉 + 高斯变异 + 自适应变异率
    """

    def __init__(self, population_size=100, max_generations=50,
                 tournament_size=3, crossover_rate=0.8,
                 mutation_rate=0.15, elite_ratio=0.1,
                 convergence_threshold=10, convergence_tolerance=0.005):
        """
        Parameters:
        -----------
        population_size : int
            种群大小
        max_generations : int
            最大代数
        tournament_size : int
            锦标赛大小
        crossover_rate : float
            交叉概率
        mutation_rate : float
            初始变异概率
        elite_ratio : float
            精英保留比例
        convergence_threshold : int
            连续N代无改善则收敛
        convergence_tolerance : float
            改善阈值
        """
        self.population_size = population_size
        self.max_generations = max_generations
        self.tournament_size = tournament_size
        self.crossover_rate = crossover_rate
        self.mutation_rate = mutation_rate
        self.elite_ratio = elite_ratio
        self.convergence_threshold = convergence_threshold
        self.convergence_tolerance = convergence_tolerance

    def run(self, evaluate_fn, seed_params=None, rng=None,
            verbose=True) -> tuple:
        """
        运行遗传算法

        Parameters:
        -----------
        evaluate_fn : callable
            评估函数: (params: dict) -> (fitness: float, details: dict)
        seed_params : list[dict] or None
            种子参数（如上一轮最优解）
        rng : np.random.Generator or None
            随机数生成器
        verbose : bool
            是否打印进度

        Returns:
        --------
        (best_individual: Individual, all_individuals: list[Individual],
         convergence_gen: int, generations_run: int)
         convergence_gen = 最后一次显著改善的代号 (0-based);
         generations_run = 实际执行的代数 (提前收敛时 < max_generations,
         审计 M3: 旧实现调用方记的是配置上限而非实际值)
        """
        if rng is None:
            rng = np.random.default_rng()

        # 初始化种群
        population = self._init_population(seed_params, rng)

        best_fitness = -np.inf
        best_individual = None
        no_improve_count = 0
        convergence_gen = 0
        generations_run = 0

        for gen in range(self.max_generations):
            generations_run = gen + 1
            gen_start = time.time()

            # 评估适应度
            for ind in population:
                if ind.fitness == 0:  # 未评估过
                    fitness, details = evaluate_fn(ind.params)
                    ind.fitness = fitness
                    ind.fitness_details = details

            # 排序
            population.sort(key=lambda x: x.fitness, reverse=True)

            # 更新最优
            gen_best = population[0]
            if gen_best.fitness > best_fitness + self.convergence_tolerance:
                best_fitness = gen_best.fitness
                best_individual = copy.deepcopy(gen_best)
                no_improve_count = 0
                convergence_gen = gen
            else:
                no_improve_count += 1

            gen_time = time.time() - gen_start

            if verbose:
                top3 = [f"{p.fitness:.4f}" for p in population[:3]]
                print(f"  Gen {gen:3d} | Best: {gen_best.fitness:.4f} "
                      f"| Top3: {', '.join(top3)} "
                      f"| NoImprove: {no_improve_count} "
                      f"| {gen_time:.1f}s")

            # 收敛检查
            if no_improve_count >= self.convergence_threshold:
                if verbose:
                    print(f"  [收敛] 连续{self.convergence_threshold}代无改善，停止")
                break

            # 自适应变异率
            current_mutation = self.mutation_rate
            if no_improve_count > 3:
                # 长期无改善，增大变异率
                current_mutation = min(0.4, self.mutation_rate * (1 + no_improve_count * 0.05))

            # 产生下一代
            population = self._next_generation(
                population, evaluate_fn, current_mutation, rng
            )

        # E-P0-4: 最优解强制 repair + validate, 确保落盘参数合法
        if best_individual is not None:
            best_individual.params = ParameterSpace.repair(best_individual.params)
            valid, violations = ParameterSpace.validate(best_individual.params)
            if not valid:
                raise ValueError(f"repair后最优参数仍非法: {violations}")

        return best_individual, population, convergence_gen, generations_run

    def _init_population(self, seed_params, rng):
        """初始化种群"""
        population = []

        # 加入种子参数 (E-P0-4: 种子也强制 repair)
        if seed_params:
            for params in seed_params:
                ind = Individual(params=ParameterSpace.repair(copy.deepcopy(params)))
                population.append(ind)

        # 随机填充剩余 (E-P0-4: 独立采样约84%违反关系约束 → 采样后立即 repair)
        while len(population) < self.population_size:
            params = ParameterSpace.repair(ParameterSpace.random_sample(rng))
            ind = Individual(params=params)
            population.append(ind)

        return population

    def _next_generation(self, population, evaluate_fn, mutation_rate, rng):
        """产生下一代"""
        next_gen = []

        # 精英保留
        n_elite = max(1, int(len(population) * self.elite_ratio))
        for i in range(n_elite):
            elite = copy.deepcopy(population[i])
            next_gen.append(elite)

        # 产生剩余个体
        while len(next_gen) < self.population_size:
            # 锦标赛选择
            parent1 = self._tournament_select(population, rng)
            parent2 = self._tournament_select(population, rng)

            # 交叉
            if rng.random() < self.crossover_rate:
                child1_params, child2_params = ParameterSpace.crossover(
                    parent1.params, parent2.params, rng
                )
            else:
                child1_params = copy.deepcopy(parent1.params)
                child2_params = copy.deepcopy(parent2.params)

            # 变异 + repair (E-P0-4: 交叉/变异可能破坏关系约束,
            # ParameterSpace.repair 的 docstring 本就要求在此调用)
            child1_params = ParameterSpace.repair(
                ParameterSpace.mutate(child1_params, mutation_rate, rng)
            )
            child2_params = ParameterSpace.repair(
                ParameterSpace.mutate(child2_params, mutation_rate, rng)
            )

            next_gen.append(Individual(params=child1_params))
            if len(next_gen) < self.population_size:
                next_gen.append(Individual(params=child2_params))

        return next_gen

    def _tournament_select(self, population, rng):
        """锦标赛选择"""
        candidates = rng.choice(len(population), size=self.tournament_size, replace=False)
        best = max(candidates, key=lambda i: population[i].fitness)
        return population[best]


# ==================== 优化引擎 ====================

class OptimizationEngine:
    """
    多体制优化引擎

    阶段1: 全局优化 → 通用基线参数
    阶段2: 按体制分别优化 → 体制专属参数
    阶段3: 混合策略优化 → 跨体制稳健参数
    """

    def __init__(self, data_dir="./stock_data", n_workers=4, seed=None,
                 config=None):
        """
        Parameters:
        -----------
        data_dir : str
            数据目录
        n_workers : int
            并行工作线程数
        seed : int or None
            随机种子 (E-P0-3): 同 seed 同数据 → 结果逐位可复现。
            各阶段(global/regime/robust/iterative)由 seed+阶段名派生
            独立子流, 与调用顺序无关; None 时保持非确定性。
        config : OptimizationConfig or None
            显式优化配置 (审计 E-P1 影子配置接线)。提供时 config 作为
            ga/fitness/walk_forward/iterative_rounds 的真相源; 优先级:
            CLI 显式参数 (ga_params, 如 --pop/--gen) > config.* > 阶段分档
            默认。None 时全部走引擎内省默认 — 既有调用行为逐位不变。
        """
        self.data_manager = HistoricalDataManager(data_dir)
        self.backtester = VectorizedBacktester()
        self.config = config
        self.evaluator = FitnessEvaluator(
            self.backtester,
            fitness_config=config.fitness if config else None,
            walk_forward_config=config.walk_forward if config else None)
        self.n_workers = n_workers
        self.seed = seed
        # 审计 E-P1 死维度接线 (P1-1): 优化器路径默认启用4 因子加权评分,
        # 使 parameter_space 中 w_trend/w_momentum/w_risk/w_performance/
        # score_buy_threshold/score_sell_threshold 六维真正影响 fitness;
        # config.use_weighted_scoring=False 可回退投票制旧基线。
        self._use_weighted_scoring = bool(
            config.use_weighted_scoring if config is not None else True)
        self._ga_runs = []  # 各阶段GA运行元数据, save_results 落盘

        self.results = {}       # {regime: OptimizationResult}
        self.stock_data = {}    # {symbol: DataFrame}
        self.regime_labels = {} # {symbol: pd.Series}

    def _eval_params(self, params: dict) -> dict:
        """GA 个体参数 → fitness 评估参数 (审计 E-P1 死维度接线 P1-1)。

        注入 use_weighted_scoring 开关: True 时 _generate_signals 走
        4 因子加权评分 (score_*_threshold 触发), 参数空间 6 个评分维
        从噪声变为有效搜索维; False 时保持投票制 (buy/sell_threshold)。
        """
        return {**params, 'use_weighted_scoring': self._use_weighted_scoring}

    def _merge_ga_cfg(self, stage_cfg: dict, ga_params=None) -> dict:
        """阶段 GA 默认 × config.ga × 显式参数 三级合并 (审计 E-P1 接线)。

        优先级: ga_params (CLI --pop/--gen 显式) > config.ga (8 键单档基线,
        与 GeneticAlgorithm 形参同名同默认) > stage_cfg (阶段分档默认)。
        无 config 且无 ga_params 时原样返回阶段分档 — 零回归。
        """
        merged = dict(stage_cfg)
        if self.config is not None:
            ga = self.config.ga
            merged.update({
                'population_size': ga.population_size,
                'max_generations': ga.max_generations,
                'tournament_size': ga.tournament_size,
                'crossover_rate': ga.crossover_rate,
                'mutation_rate': ga.mutation_rate,
                'elite_ratio': ga.elite_ratio,
                'convergence_threshold': ga.convergence_threshold,
                'convergence_tolerance': ga.convergence_tolerance,
            })
        if ga_params:
            merged.update(ga_params)
        return merged

    def _iterative_round_configs(self) -> list:
        """多轮迭代各轮 GA 配置。config.iterative_rounds 存在时为真相源
        (dataclass→dict); 否则用引擎内省默认 (两者出厂值逐位相同)。"""
        if self.config is not None and self.config.iterative_rounds:
            return [{'population_size': r.population_size,
                     'max_generations': r.max_generations,
                     'convergence_threshold': r.convergence_threshold,
                     'mutation_rate': r.mutation_rate}
                    for r in self.config.iterative_rounds]
        return [
            {'population_size': 40, 'max_generations': 15,
             'convergence_threshold': 5, 'mutation_rate': 0.25},
            {'population_size': 60, 'max_generations': 25,
             'convergence_threshold': 6, 'mutation_rate': 0.18},
            {'population_size': 100, 'max_generations': 40,
             'convergence_threshold': 8, 'mutation_rate': 0.12},
        ]

    def load_data(self, symbols=None, min_history_days=5000,
                  regime_labels_file=None):
        """
        加载股票数据和体制标签

        Parameters:
        -----------
        symbols : list or None
            股票代码列表，None则使用股票池
        min_history_days : int
            最少历史天数
        regime_labels_file : str or None
            体制标签文件路径
        """
        # 加载体制标签
        if regime_labels_file and Path(regime_labels_file).exists():
            df = pd.read_csv(regime_labels_file, encoding='utf-8-sig')
            df['日期'] = pd.to_datetime(df['日期'])
            self._index_regime_labels = df
            print(f"[OK] 加载体制标签: {len(df)} 条")
        else:
            print("[WARN] 未提供体制标签文件，将跳过按体制优化")
            self._index_regime_labels = None

        # 获取股票池
        if symbols is None:
            symbols = self.data_manager.get_universe(
                min_history_days=min_history_days, min_rows=2000
            )

        if not symbols:
            print("[ERROR] 无可用股票数据，请先运行 historical_data_manager.py batch")
            return

        print(f"[INFO] 加载 {len(symbols)} 只股票数据...")

        loaded = 0
        failed_symbols = []
        for sym in symbols:
            data = self.data_manager.load(sym)
            if data is not None and len(data) >= 252:  # 至少1年数据
                self.stock_data[sym] = data
                loaded += 1

                # 为每只股票分配体制标签
                if self._index_regime_labels is not None:
                    self._assign_regime_labels(sym, data)
            else:
                failed_symbols.append(sym)

        if failed_symbols and loaded > 0:
            print(f"[WARN] {len(failed_symbols)} 只股票数据不足252天, 已跳过: "
                  f"{failed_symbols[:10]}{'...' if len(failed_symbols) > 10 else ''}")

        if loaded == 0:
            # 旧逻辑: 即使一只都没加载成功也打印 "[OK] 成功加载 0 只股票" — 假成功
            raise RuntimeError(
                f"加载股票数据失败: {len(failed_symbols)}/{len(symbols)} 只不足252天或数据缺失. "
                f"请先运行 historical_data_manager.py batch 获取数据"
            )

        print(f"[OK] 成功加载 {loaded} 只股票")

    def _assign_regime_labels(self, symbol, data):
        """为股票数据分配体制标签(基于指数日期对齐) - 向量化版本"""
        idx_labels = self._index_regime_labels
        if idx_labels is None:
            return

        # 使用 pd.merge_asof 向量化查找最近的指数日期
        stock_df = data[['日期']].copy()
        idx_df = idx_labels[['日期', 'regime']].copy()

        # 统一datetime类型为datetime64[ns](避免us/ns不匹配)
        stock_df['日期'] = pd.to_datetime(stock_df['日期']).astype('datetime64[ns]')
        idx_df['日期'] = pd.to_datetime(idx_df['日期']).astype('datetime64[ns]')

        idx_df = idx_df.sort_values('日期')
        stock_df = stock_df.sort_values('日期')

        merged = pd.merge_asof(
            stock_df, idx_df,
            on='日期',
            direction='backward'
        )
        self.regime_labels[symbol] = merged['regime'].fillna('SIDEWAYS')

    def optimize_global(self, stock_sample=None, n_stocks=50,
                        ga_params=None, verbose=True) -> OptimizationResult:
        """
        阶段1: 全局优化

        在所有体制数据上优化，产出一套通用参数作为基线。

        Parameters:
        -----------
        stock_sample : list or None
            指定股票子集，None则随机抽样
        n_stocks : int
            抽样股票数
        ga_params : dict or None
            GA参数覆盖
        verbose : bool
            是否打印进度
        """
        print("\n" + "=" * 70)
        print("  阶段1: 全局优化 (Global Optimization)")
        print("=" * 70)

        # 抽样股票
        sample_data = self._get_sample(stock_sample, n_stocks,
                                       self._stage_py_rng('global'))
        if not sample_data:
            print("[ERROR] 无可用股票数据")
            return None

        print(f"  样本股票: {len(sample_data)} 只")
        if self.seed is not None:
            print(f"  随机种子: {self.seed} (阶段: global)")

        # GA配置 (阶段分档 × config × CLI 显式, 三级合并)
        ga_cfg = self._merge_ga_cfg({
            'population_size': 80,
            'max_generations': 40,
            'convergence_threshold': 8,
        }, ga_params)

        # 评估函数 (计数 + top-k 记录, 审计 H10: track=False 供基线/bootstrap
        # 调用 → 不计入搜索试验次数、不进 top-k 统计)
        evals = {'n': 0}
        topk = []
        rb_cfg = self._robustness_cfg()

        def _track(fitness, params):
            topk.append((float(fitness), dict(params)))
            topk.sort(key=lambda t: -t[0])
            del topk[rb_cfg['top_k']:]

        def evaluate(params, track=True, collect_regimes=False, **kwargs):
            # collect_regimes 只由稳健闭包实现; 此处吞掉 (单层评估无体制分层)
            fitness, details = self.evaluator.evaluate(
                self._eval_params(params), sample_data, **kwargs)
            if track:
                evals['n'] += 1
                _track(fitness, params)
            return fitness, details

        # 运行GA
        ga = GeneticAlgorithm(**ga_cfg)
        start_time = time.time()

        if verbose:
            print(f"  GA配置: pop={ga_cfg['population_size']}, "
                  f"max_gen={ga_cfg['max_generations']}")

        best, all_inds, conv_gen, gens_run = ga.run(
            evaluate, rng=self._stage_rng('global'), verbose=verbose)
        total_time = time.time() - start_time
        self._record_ga_run('global', ga_cfg, conv_gen, total_time, evals['n'],
                            generations_run=gens_run)
        # 审计 H10: GA 结束后组装稳健性证据 (只报告, 不参与选择)
        robustness = self._finalize_robustness(
            'global', evaluate, best, evals['n'], topk)

        # 构建结果
        system = IndicatorSystem(
            name="通用基线型",
            description="在所有市场体制下表现均衡的通用参数",
            applicable_regimes=['BULL', 'BEAR', 'SIDEWAYS', 'CRASH', 'RECOVERY'],
            params=best.params,
            fitness_scores={'GLOBAL': best.fitness},
            # 审计 H2: 旧值硬编码 0.7 (与证据无关) → 适应度夹取
            confidence=confidence_from_fitness(best.fitness),
            sample_count=best.fitness_details.get('sample_count', 0),
            median_return=best.fitness_details.get('median_return', 0),
            win_rate_above_10pct=best.fitness_details.get('target_rate', 0),
            median_sharpe=best.fitness_details.get('median_sharpe', 0),
            median_max_drawdown=best.fitness_details.get('median_drawdown', 0),
            median_holding_days=best.fitness_details.get('avg_holding_days', 0),
            num_trades=best.fitness_details.get('avg_trades', 0),
            **oos_fields(best.fitness_details),
            **evaluation_coverage_fields(best.fitness_details),
            robustness=robustness,
        )

        result = OptimizationResult(
            regime='GLOBAL',
            best_individual=best,
            best_system=system,
            all_systems=[system],
            generations_run=gens_run,  # 审计 M3: 实际代数, 非配置上限
            total_time_sec=total_time,
            convergence_gen=conv_gen,
        )

        self.results['GLOBAL'] = result

        if verbose:
            self._print_result_summary(result)

        return result

    def optimize_by_regime(self, stock_sample=None, n_stocks=50,
                           ga_params=None, verbose=True) -> dict:
        """
        阶段2: 按体制分别优化

        对每种体制分别优化，产出每种体制的最优参数集。

        Returns:
        --------
        dict : {regime_name: OptimizationResult}
        """
        print("\n" + "=" * 70)
        print("  阶段2: 按体制分别优化 (Per-Regime Optimization)")
        print("=" * 70)

        if not self.regime_labels:
            print("[ERROR] 无体制标签，请先加载体制标签文件")
            return {}

        sample_data = self._get_sample(stock_sample, n_stocks,
                                       self._stage_py_rng('regime'))
        if not sample_data:
            return {}

        # 找出数据量足够多的体制
        regime_counts = {}
        for sym, labels in self.regime_labels.items():
            if sym not in sample_data:
                continue
            for regime in labels.unique():
                count = (labels == regime).sum()
                regime_counts[regime] = regime_counts.get(regime, 0) + count

        active_regimes = [r for r, c in regime_counts.items() if c >= 200]
        print(f"  活跃体制: {active_regimes}")
        print(f"  体制数据量: {regime_counts}")
        print(f"  样本股票: {len(sample_data)} 只")
        if self.seed is not None:
            print(f"  随机种子: {self.seed} (阶段: regime)")

        ga_cfg = self._merge_ga_cfg({
            'population_size': 60,
            'max_generations': 30,
            'convergence_threshold': 6,
        }, ga_params)

        results = {}

        for regime in active_regimes:
            print(f"\n--- 优化体制: {regime} ---")

            regime_name_cn = {
                'BULL': '牛市', 'BEAR': '熊市', 'SIDEWAYS': '震荡',
                'CRASH': '暴跌', 'RECOVERY': '反弹'
            }.get(regime, regime)

            evals = {'n': 0}
            topk = []
            rb_cfg = self._robustness_cfg()

            def _track(fitness, params):
                topk.append((float(fitness), dict(params)))
                topk.sort(key=lambda t: -t[0])
                del topk[rb_cfg['top_k']:]

            def evaluate(params, r=regime, track=True, collect_regimes=False,
                         **kwargs):
                # collect_regimes 此处吞掉 (单一体制, 无分层可言)
                fitness, details = self.evaluator.evaluate(
                    self._eval_params(params), sample_data,
                    self.regime_labels, r, **kwargs)
                if track:
                    evals['n'] += 1
                    _track(fitness, params)
                return fitness, details

            ga = GeneticAlgorithm(**ga_cfg)
            start_time = time.time()

            # 各体制独立子流: 与体制循环顺序无关, 同 seed 同体制可复现
            best, all_inds, conv_gen, gens_run = ga.run(
                evaluate, rng=self._stage_rng(f'regime:{regime}'), verbose=verbose
            )
            total_time = time.time() - start_time
            self._record_ga_run(f'regime:{regime}', ga_cfg, conv_gen,
                                total_time, evals['n'], generations_run=gens_run)
            # 审计 H10: 稳健性证据 (只报告, 不参与选择)
            robustness = self._finalize_robustness(
                f'regime:{regime}', evaluate, best, evals['n'], topk)

            system = IndicatorSystem(
                name=f"{regime_name_cn}专用型",
                description=f"专为{regime_name_cn}市场体制优化的参数",
                applicable_regimes=[regime],
                params=best.params,
                fitness_scores={regime: best.fitness},
                # 审计 H2: 旧值 min(0.9, f*1.2) 是对适应度的任意放大 → 原值夹取
                confidence=confidence_from_fitness(best.fitness),
                sample_count=best.fitness_details.get('sample_count', 0),
                median_return=best.fitness_details.get('median_return', 0),
                win_rate_above_10pct=best.fitness_details.get('target_rate', 0),
                median_sharpe=best.fitness_details.get('median_sharpe', 0),
                median_max_drawdown=best.fitness_details.get('median_drawdown', 0),
                median_holding_days=best.fitness_details.get('avg_holding_days', 0),
                num_trades=best.fitness_details.get('avg_trades', 0),
                **oos_fields(best.fitness_details),
                **evaluation_coverage_fields(best.fitness_details),
                robustness=robustness,
            )

            result = OptimizationResult(
                regime=regime,
                best_individual=best,
                best_system=system,
                all_systems=[system],
                generations_run=gens_run,  # 审计 M3: 实际代数, 非配置上限
                total_time_sec=total_time,
                convergence_gen=conv_gen,
            )

            results[regime] = result
            self.results[regime] = result

            if verbose:
                self._print_result_summary(result)

        return results

    def optimize_robust(self, stock_sample=None, n_stocks=50,
                        ga_params=None, verbose=True) -> OptimizationResult:
        """
        阶段3: 混合策略优化

        优化目标: 在所有体制下都不差，而非在某一体制下最优。
        适应度 = min(各体制fitness)
        """
        print("\n" + "=" * 70)
        print("  阶段3: 稳健策略优化 (Robust Optimization)")
        print("=" * 70)

        sample_data = self._get_sample(stock_sample, n_stocks,
                                       self._stage_py_rng('robust'))
        if not sample_data:
            return None

        # 确定有哪些体制
        if self.regime_labels:
            all_regimes = set()
            for labels in self.regime_labels.values():
                all_regimes.update(labels.unique())
            all_regimes = sorted(all_regimes)
        else:
            all_regimes = []

        print(f"  样本股票: {len(sample_data)} 只")
        print(f"  体制: {all_regimes}")
        if self.seed is not None:
            print(f"  随机种子: {self.seed} (阶段: robust)")

        ga_cfg = self._merge_ga_cfg({
            'population_size': 80,
            'max_generations': 40,
            'convergence_threshold': 8,
        }, ga_params)

        evals = {'n': 0}
        topk = []
        rb_cfg = self._robustness_cfg()

        def _track(fitness, params):
            topk.append((float(fitness), dict(params)))
            topk.sort(key=lambda t: -t[0])
            del topk[rb_cfg['top_k']:]

        def evaluate_robust(params, track=True, collect_regimes=False,
                            **kwargs):
            """稳健适应度: 各体制fitness的最小值(忽略无数据体制)"""
            raw_params = dict(params)
            # bootstrap 经 kwargs 传入的 return_is_metrics 与 collect_regimes
            # 合并为同一语义 (都要逐窗口指标)。注意先 pop 再 or —— 短路会
            # 跳过 pop, kwargs 残留该键 → 与显式传参冲突
            want_kw = bool(kwargs.pop('return_is_metrics', False))
            want_metrics = collect_regimes or want_kw
            params = self._eval_params(params)
            if not all_regimes or not self.regime_labels:
                fitness, details = self.evaluator.evaluate(
                    params, sample_data, return_is_metrics=want_metrics,
                    **kwargs)
            else:
                regime_fitnesses = {}
                regime_oos = {}
                regime_metrics = {}
                # 审计 M5: 跨体制的失败记账 (各体制分别评估 → 失败数按体制求和)
                regime_coverage = {}
                for regime in all_regimes:
                    fitness_r, details_r = self.evaluator.evaluate(
                        params, sample_data, self.regime_labels, regime,
                        return_is_metrics=want_metrics, **kwargs)
                    regime_coverage[regime] = evaluation_coverage_fields(
                        details_r)
                    # 仅记录有样本的体制
                    if details_r.get('sample_count', 0) > 0:
                        regime_fitnesses[regime] = fitness_r
                        # 审计 H1: 各体制的样本外证据一并保留 (只报告, 不参与选择)
                        oos_block = details_r.get('oos')
                        if oos_block:
                            regime_oos[regime] = oos_block
                        if want_metrics:
                            regime_metrics[regime] = (
                                details_r.get('is_metrics') or [])

                if not regime_fitnesses:
                    # 审计 M5: 全体制无样本 → 失败记账仍须可见 (不静默)
                    fitness, details = 0.0, {
                        **aggregate_coverage(regime_coverage),
                        'evaluation_available': False,
                        'regime_coverage': regime_coverage,
                    }
                else:
                    # 稳健适应度 = 0.7*最差体制 + 0.3*平均 (H10: 提炼为
                    # _robust_combine, bootstrap 重采样走同一口径)
                    fitness = self.evaluator._robust_combine(regime_fitnesses)
                    details = {
                        'regime_fitnesses': regime_fitnesses,
                        'min_fitness': min(regime_fitnesses.values()),
                        'avg_fitness': float(np.mean(
                            list(regime_fitnesses.values()))),
                        'regimes_used': list(regime_fitnesses.keys()),
                        'regimes_skipped': [r for r in all_regimes
                                            if r not in regime_fitnesses],
                        # 审计 H1: 跨体制汇总的样本外证据 (IS/OOS 分列)
                        'regime_oos': regime_oos,
                        # 审计 M5: 跨体制聚合的失败/覆盖记账
                        **aggregate_coverage(regime_coverage),
                        'regime_coverage': regime_coverage,
                    }
                    # H1 遗留 bug 修复: 原写 self._aggregate_oos, 但该方法在
                    # FitnessEvaluator 上 (闭包内 self=Engine → 有体制标签时
                    # 稳健模式必 AttributeError; H1 测试仅源码级, 未跑行为路径)
                    details['oos'] = self.evaluator._aggregate_oos(
                        list(regime_oos.values()))
                    if want_metrics:
                        details['regime_metrics'] = regime_metrics
            if track:
                evals['n'] += 1
                _track(fitness, raw_params)
            return fitness, details

        ga = GeneticAlgorithm(**ga_cfg)
        start_time = time.time()

        best, all_inds, conv_gen, gens_run = ga.run(evaluate_robust,
                                                    rng=self._stage_rng('robust'),
                                                    verbose=verbose)
        total_time = time.time() - start_time
        self._record_ga_run('robust', ga_cfg, conv_gen, total_time, evals['n'],
                            generations_run=gens_run)
        # 审计 H10: 稳健性证据 (只报告, 不参与选择)
        robustness = self._finalize_robustness(
            'robust', evaluate_robust, best, evals['n'], topk)

        regime_scores = best.fitness_details.get('regime_fitnesses', {})
        regimes_used = best.fitness_details.get('regimes_used', [])
        regimes_skipped = best.fitness_details.get('regimes_skipped', [])

        if verbose:
            print(f"\n  使用体制: {regimes_used}")
            if regimes_skipped:
                print(f"  跳过体制(无数据): {regimes_skipped}")

        system = IndicatorSystem(
            name="通用稳健型",
            description="在所有市场体制下都不差的稳健参数，适合不确定市场方向时使用",
            applicable_regimes=regimes_used if regimes_used else all_regimes,
            params=best.params,
            fitness_scores=regime_scores,
            # 审计 H2: 旧值硬编码 0.6 (与证据无关) → 适应度夹取 (各体制
            # fitness 的稳健组合, 见 evaluate_robust)
            confidence=confidence_from_fitness(best.fitness),
            sample_count=best.fitness_details.get('sample_count', 0),
            median_return=best.fitness_details.get('median_return', 0),
            win_rate_above_10pct=best.fitness_details.get('target_rate', 0),
            median_sharpe=best.fitness_details.get('median_sharpe', 0),
            median_max_drawdown=best.fitness_details.get('median_drawdown', 0),
            median_holding_days=best.fitness_details.get('avg_holding_days', 0),
            num_trades=best.fitness_details.get('avg_trades', 0),
            **oos_fields(best.fitness_details),
            **evaluation_coverage_fields(best.fitness_details),
            robustness=robustness,
        )

        result = OptimizationResult(
            regime='ROBUST',
            best_individual=best,
            best_system=system,
            all_systems=[system],
            generations_run=gens_run,  # 审计 M3: 实际代数, 非配置上限
            total_time_sec=total_time,
            convergence_gen=conv_gen,
        )

        self.results['ROBUST'] = result

        if verbose:
            self._print_result_summary(result)

        return result

    def iterative_optimize(self, stock_sample=None, n_stocks=50,
                           n_rounds=3, verbose=True) -> list:
        """
        多轮迭代优化

        Round 1: 粗粒度搜索 (大参数步长，小种群) → 缩小搜索空间
        Round 2: 中粒度搜索 (中等步长，中种群) → 精炼参数范围
        Round 3: 细粒度搜索 (小步长，大种群) → 精确参数
        """
        print("\n" + "=" * 70)
        print(f"  多轮迭代优化 ({n_rounds} 轮)")
        print("=" * 70)

        sample_data = self._get_sample(stock_sample, n_stocks,
                                       self._stage_py_rng('iterative'))
        if not sample_data:
            return []

        if self.seed is not None:
            print(f"  随机种子: {self.seed} (阶段: iterative)")

        # 各轮配置 (config.iterative_rounds 为真相源; 出厂值=内省默认)
        round_configs = self._iterative_round_configs()

        all_round_results = []
        seed_params = None
        # 单条流贯穿各轮 (轮次顺序固定 → 可复现)
        rng = self._stage_rng('iterative')
        # 审计 H10: 跨轮累计 —— 最终参数经全部轮次演化, 每一轮的评估都
        # 参与了选择 → 试验次数/top-k 取全程 (非仅末轮)
        cum_evals = 0
        cum_topk = []
        rb_cfg = self._robustness_cfg()

        def _track(fitness, params):
            cum_topk.append((float(fitness), dict(params)))
            cum_topk.sort(key=lambda t: -t[0])
            del cum_topk[rb_cfg['top_k']:]

        for round_idx in range(min(n_rounds, len(round_configs))):
            cfg = round_configs[round_idx]
            print(f"\n--- Round {round_idx + 1}/{n_rounds} ---")
            print(f"  pop={cfg['population_size']}, "
                  f"max_gen={cfg['max_generations']}, "
                  f"mut_rate={cfg['mutation_rate']}")

            evals = {'n': 0}

            def evaluate(params, track=True, collect_regimes=False, **kwargs):
                # collect_regimes 此处吞掉 (无体制分层)
                fitness, details = self.evaluator.evaluate(
                    self._eval_params(params), sample_data, **kwargs)
                if track:
                    evals['n'] += 1
                    _track(fitness, params)
                return fitness, details

            ga = GeneticAlgorithm(
                population_size=cfg['population_size'],
                max_generations=cfg['max_generations'],
                convergence_threshold=cfg['convergence_threshold'],
                mutation_rate=cfg['mutation_rate'],
            )

            start_time = time.time()
            best, all_inds, conv_gen, gens_run = ga.run(
                evaluate, seed_params=seed_params, rng=rng, verbose=verbose
            )
            total_time = time.time() - start_time
            self._record_ga_run(f'iterative:r{round_idx + 1}', cfg, conv_gen,
                                total_time, evals['n'], generations_run=gens_run)
            cum_evals += evals['n']

            result = {
                'round': round_idx + 1,
                'best_fitness': best.fitness,
                'best_params': best.params,
                'best_details': best.fitness_details,
                'convergence_gen': conv_gen,
                'generations_run': gens_run,  # 审计 M3: 实际代数
                'time_sec': total_time,
            }
            all_round_results.append(result)

            # 将本轮TOP5作为下轮种子
            seed_params = [ind.params for ind in all_inds[:5]]

            if verbose:
                print(f"  最终适应度: {best.fitness:.4f}")
                print(f"  中位收益: {best.fitness_details.get('median_return', 0):.1f}%")
                print(f"  达标率: {best.fitness_details.get('target_rate', 0):.1%}")

        # 构建最终指标体系
        if all_round_results:
            final = all_round_results[-1]
            # 审计 H10: 稳健性证据 (试验次数=各轮之和; 基线/bootstrap 走
            # 末轮评估闭包 — 同一适应度函数)
            robustness = self._finalize_robustness(
                'iterative', evaluate,
                Individual(params=final['best_params'],
                           fitness=final['best_fitness']),
                cum_evals, cum_topk)
            system = IndicatorSystem(
                name="迭代优化型",
                description=f"经过{n_rounds}轮迭代精炼的参数",
                applicable_regimes=['BULL', 'BEAR', 'SIDEWAYS', 'CRASH', 'RECOVERY'],
                params=final['best_params'],
                fitness_scores={'GLOBAL': final['best_fitness']},
                # 审计 H2: 旧值硬编码 0.75 (与证据无关) → 适应度夹取
                confidence=confidence_from_fitness(final['best_fitness']),
                sample_count=final['best_details'].get('sample_count', 0),
                median_return=final['best_details'].get('median_return', 0),
                win_rate_above_10pct=final['best_details'].get('target_rate', 0),
                median_sharpe=final['best_details'].get('median_sharpe', 0),
                median_max_drawdown=final['best_details'].get('median_drawdown', 0),
                median_holding_days=final['best_details'].get('avg_holding_days', 0),
                num_trades=final['best_details'].get('avg_trades', 0),
                **oos_fields(final['best_details']),
                robustness=robustness,
            )

            result = OptimizationResult(
                regime='ITERATIVE',
                best_individual=Individual(
                    params=final['best_params'],
                    fitness=final['best_fitness'],
                    fitness_details=final['best_details'],
                ),
                best_system=system,
                all_systems=[system],
                # 审计 M3: 各轮实际代数之和 (旧实现误用 convergence_gen 求和 —
                # 那是"最后改善代号", 与"跑了几代"是两回事)
                generations_run=sum(r.get('generations_run', 0)
                                    for r in all_round_results),
                total_time_sec=sum(r['time_sec'] for r in all_round_results),
                convergence_gen=all_round_results[-1]['convergence_gen'],
            )
            self.results['ITERATIVE'] = result

        return all_round_results

    def _stage_rng(self, stage: str) -> np.random.Generator:
        """按阶段派生独立可复现随机流 (E-P0-3): seed+阶段名 → 子流"""
        if self.seed is None:
            return np.random.default_rng()
        return np.random.default_rng([int(self.seed), zlib.crc32(stage.encode())])

    def _stage_py_rng(self, stage: str) -> random.Random:
        """stdlib 随机流 (分层抽样用), 派生规则与 _stage_rng 一致"""
        if self.seed is None:
            return random.Random()
        return random.Random(f"{self.seed}:{stage}")

    def _record_ga_run(self, stage, ga_cfg, conv_gen, time_sec, n_evals,
                       generations_run=None):
        """记录一次GA运行的元数据 (save_results 落盘 — E-P0-3)

        generations_run: 实际执行代数 (审计 M3; 与 max_generations 配置上限
        区分 — 提前收敛时两者不等)
        """
        self._ga_runs.append({
            'stage': stage,
            'population_size': ga_cfg.get('population_size'),
            'max_generations': ga_cfg.get('max_generations'),
            'generations_run': generations_run,
            'convergence_threshold': ga_cfg.get('convergence_threshold'),
            'mutation_rate': ga_cfg.get('mutation_rate'),
            'convergence_gen': conv_gen,
            'n_evals': n_evals,
            'time_sec': round(time_sec, 3),
        })

    # ==================== 稳健性/多重检验证据 (审计 H10) ====================

    def _robustness_cfg(self) -> dict:
        """稳健性证据采样规模: 引擎默认 < config.robustness (审计 H10)"""
        defaults = {'n_baseline_samples': 100, 'top_k': 10, 'n_bootstrap': 500}
        rc = (getattr(self.config, 'robustness', None)
              if self.config is not None else None)
        if rc is None:
            return defaults
        return {
            'n_baseline_samples': int(rc.n_baseline_samples),
            'top_k': int(rc.top_k),
            'n_bootstrap': int(rc.n_bootstrap),
        }

    @staticmethod
    def _top_k_dispersion(topk_entries, k):
        """Top-k 已评估参数的逐维离散度 (审计 H10 ③)。

        基于**全部被评估过的**参数 (非仅末代种群) 按 fitness 取前 k:
        - range/std 尖峰 → 最优区狭窄, 对参数抖动敏感 (过拟合嫌疑);
        - 宽平台 → 相对稳健。
        entries: [(fitness, raw_params_dict), ...] 已按 fitness 降序。
        """
        if not topk_entries:
            return {'available': False, 'reason': '无已评估参数记录'}
        k_eff = min(int(k), len(topk_entries))
        top = topk_entries[:k_eff]
        per_param = {}
        names = ParameterSpace.get_param_names()
        for name in names:
            vals = [p[name] for _, p in top if name in p]
            if not vals:
                continue
            arr = np.asarray(vals, dtype=float)
            per_param[name] = {
                'min': float(arr.min()),
                'max': float(arr.max()),
                'range': float(arr.max() - arr.min()),
                'std': float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
                'mean': float(arr.mean()),
            }
        fits = [f for f, _ in top]
        return {
            'available': True,
            'k': k_eff,
            'fitness_values': [float(f) for f in fits],
            'fitness_spread': float(max(fits) - min(fits)) if len(fits) > 1 else 0.0,
            'per_param': per_param,
        }

    def _random_baseline(self, stage, evaluate_fn, n_samples, best_fitness):
        """随机参数基线 (审计 H10 ②): 回答"最优 fitness 相对随机乱猜有多罕见"。

        - 走与搜索**完全相同**的评估闭包 (同一 IS 口径, 不触碰 OOS — H1
          隔离不受影响), 以 track=False 调用 → 不计入搜索试验次数;
        - 独立 RNG 子流 (stage:baseline), 与 GA 主流隔离 → 基线的开关/
          规模不影响搜索结果 (E-P0-3 可复现性);
        - n_samples=0 → 如实标记 unavailable, 不假装有基线。
        """
        if n_samples <= 0:
            return {'available': False, 'n_samples': 0,
                    'reason': 'n_baseline_samples=0 (未配置基线)'}
        rng = self._stage_rng(f'{stage}:baseline')
        fits = []
        for _ in range(n_samples):
            params = ParameterSpace.repair(ParameterSpace.random_sample(rng))
            f, _ = evaluate_fn(params, track=False)
            fits.append(float(f))
        arr = np.asarray(fits, dtype=float)
        return {
            'available': True,
            'n_samples': n_samples,
            'fitness_mean': float(arr.mean()),
            'fitness_std': float(arr.std(ddof=1)) if n_samples > 1 else 0.0,
            'fitness_p50': float(np.percentile(arr, 50)),
            'fitness_p90': float(np.percentile(arr, 90)),
            'best_fitness': float(best_fitness),
            # 最优适应度超过基线样本的比例 (分位数); 注意: 最优值取自
            # 数千次评估, 天然偏高 — 该数字用于感知量级, 非显著性结论
            'best_percentile': float((arr < best_fitness).mean()),
        }

    def _bootstrap_fitness_ci(self, stage, evaluate_fn, best_params, n_boot):
        """最优参数的适应度 bootstrap 95% CI (审计 H10 ④)。

        重采样对象 = 选择所用的 **IS 窗口指标** (与适应度同源):
        - 普通阶段: 合并重采样 IS 窗口;
        - 稳健阶段: 按体制**分层**重采样, 组合口径走 _robust_combine
          (与搜索同一公式, 否则 CI 对应的不是被报告的那个 fitness)。
        bootstrap 回答"窗口抽样噪声有多大", **不能替代 OOS** (那是外推
        证据, 见 systems[].oos)。以 track=False 调用 → 不计入试验次数。
        """
        if n_boot <= 0:
            return {'available': False, 'n_resamples': 0,
                    'reason': 'n_bootstrap=0 (未配置)'}
        rng = self._stage_rng(f'{stage}:bootstrap')
        f0, details = evaluate_fn(best_params, track=False,
                                  return_is_metrics=True, collect_regimes=True)
        regime_metrics = (details or {}).get('regime_metrics')
        if regime_metrics:
            units = {r: list(ms) for r, ms in regime_metrics.items() if ms}
            n_windows = sum(len(ms) for ms in units.values())
            if n_windows < 2:
                return {'available': False, 'n_windows': n_windows,
                        'reason': f'IS 窗口数不足 ({n_windows} < 2)'}

            def fitness_of(sampled):
                fits = {r: self.evaluator._compute_fitness(ms)[0]
                        for r, ms in sampled.items() if ms}
                return self.evaluator._robust_combine(fits) if fits else 0.0

            scope = 'per_regime_stratified'
        else:
            metrics = list((details or {}).get('is_metrics') or [])
            if len(metrics) < 2:
                return {'available': False, 'n_windows': len(metrics),
                        'reason': f'IS 窗口数不足 ({len(metrics)} < 2)'}
            units = {'_all': metrics}
            n_windows = len(metrics)

            def fitness_of(sampled):
                return self.evaluator._compute_fitness(sampled['_all'])[0]

            scope = 'is_windows'
        boots = np.empty(n_boot, dtype=float)
        for b in range(n_boot):
            sampled = {r: [ms[int(i)] for i in rng.integers(0, len(ms), len(ms))]
                       for r, ms in units.items()}
            boots[b] = fitness_of(sampled)
        return {
            'available': True,
            'scope': scope,
            'n_resamples': n_boot,
            'n_windows': n_windows,
            'fitness_point': float(f0),
            'ci_low': float(np.percentile(boots, 2.5)),
            'ci_high': float(np.percentile(boots, 97.5)),
            'boot_mean': float(boots.mean()),
            'boot_std': float(boots.std(ddof=1)) if n_boot > 1 else 0.0,
        }

    def _finalize_robustness(self, stage, evaluate_fn, best, n_evals,
                             topk_entries):
        """GA 结束后组装稳健性证据块 (审计 H10) — 只报告, 不参与选择。

        四类证据:
        - n_selection_evaluations: 参与"取最大"的评估次数 (多重比较规模;
          基线/bootstrap 以 track=False 调用, 不计入);
        - random_baseline: 随机参数在同一适应度函数下的分布与最优分位;
        - top_k_dispersion: 全程被评估参数 top-k 的逐维离散度;
        - bootstrap: 最优参数适应度的窗口重采样 95% CI。
        """
        rb = self._robustness_cfg()
        return {
            'n_selection_evaluations': int(n_evals),
            'random_baseline': self._random_baseline(
                stage, evaluate_fn, rb['n_baseline_samples'], best.fitness),
            'top_k_dispersion': self._top_k_dispersion(
                topk_entries, rb['top_k']),
            'bootstrap': self._bootstrap_fitness_ci(
                stage, evaluate_fn, best.params, rb['n_bootstrap']),
        }

    @staticmethod
    def _param_space_signature() -> dict:
        """参数空间指纹 (版本): 个数+名称+边界/默认值摘要 — 落盘审计用"""
        names = ParameterSpace.get_param_names()
        defaults = ParameterSpace.get_defaults()
        digest = hashlib.sha256(
            repr({'names': names, 'defaults': defaults}).encode('utf-8')
        ).hexdigest()[:16]
        return {'n_params': len(names), 'names': names, 'digest': digest}

    def _get_sample(self, stock_sample, n_stocks, py_rng=None):
        """获取股票样本 (py_rng: 分层抽样随机源, 传入时可复现)"""
        if stock_sample:
            return {s: self.stock_data[s] for s in stock_sample if s in self.stock_data}

        if not self.stock_data:
            return {}

        all_symbols = list(self.stock_data.keys())
        if len(all_symbols) <= n_stocks:
            return dict(self.stock_data)

        if py_rng is None:
            py_rng = random.Random()

        # 分层抽样: 优先选择有体制标签的
        labeled = [s for s in all_symbols if s in self.regime_labels]
        unlabeled = [s for s in all_symbols if s not in self.regime_labels]

        sample = []
        n_labeled = min(len(labeled), int(n_stocks * 0.8))
        n_unlabeled = n_stocks - n_labeled

        if n_labeled > 0:
            sample.extend(py_rng.sample(labeled, n_labeled))
        if n_unlabeled > 0 and unlabeled:
            sample.extend(py_rng.sample(unlabeled, min(n_unlabeled, len(unlabeled))))

        return {s: self.stock_data[s] for s in sample}

    def _print_result_summary(self, result):
        """打印优化结果摘要"""
        system = result.best_system
        print(f"\n  结果: {system.name}")
        print(f"  适应度: {result.best_individual.fitness:.4f}")
        print(f"  中位收益率: {system.median_return:.1f}%")
        print(f"  达标率(>{self.evaluator.target_return}%): "
              f"{system.win_rate_above_10pct:.1%}")
        print(f"  中位夏普: {system.median_sharpe:.2f}")
        print(f"  中位最大回撤: {system.median_max_drawdown:.1f}%")
        print(f"  平均持有天数: {system.median_holding_days:.0f}")
        # 审计 H1: IS (选择口径) 与 OOS (验证口径) 分列 —— 只报 IS 等于误导
        if system.oos_available:
            print(f"  [样本外 OOS] {system.oos_windows} 窗 | "
                  f"适应度 {system.oos_fitness:.4f} | "
                  f"中位收益 {system.oos_median_return:.1f}% | "
                  f"中位夏普 {system.oos_median_sharpe:.2f} | "
                  f"中位回撤 {system.oos_median_max_drawdown:.1f}%")
        else:
            print("  [样本外 OOS] 不可用 (窗口数不足, 无法划分留出段)")
        # 审计 M5: 评估覆盖 (逐股回测失败的股票不参与适应度)
        if system.n_stocks_evaluated:
            cov = (f"评估 {system.n_stocks_evaluated}/{system.n_stocks_total} 只"
                   f" | 失败 {system.n_stocks_failed} 只"
                   f" | 成功率 {system.evaluation_success_rate:.1%}")
            print(f"  [评估覆盖] {cov}")
        else:
            print("  [评估覆盖] 不可用 (无股票被成功评估)")
        # 审计 H10: 多重检验/稳健性证据 (只报告, 不参与选择)
        rb = getattr(system, 'robustness', None) or {}
        if rb:
            print(f"  [稳健性证据] 选择评估 {rb.get('n_selection_evaluations', 0)} 次 "
                  "(最优值取自这批评估, 存在多重比较)")
            base = rb.get('random_baseline') or {}
            if base.get('available'):
                print(f"    随机基线(n={base['n_samples']}): "
                      f"P[随机≥最优]={1 - base['best_percentile']:.1%} | "
                      f"最优分位={base['best_percentile']:.1%} | "
                      f"基线均值={base['fitness_mean']:.4f} | "
                      f"基线p90={base['fitness_p90']:.4f}")
            else:
                print(f"    随机基线: 不可用 ({base.get('reason', '—')})")
            top = rb.get('top_k_dispersion') or {}
            if top.get('available'):
                dims = top.get('per_param', {})
                widest = max(dims.items(), key=lambda kv: kv[1]['range'],
                             default=None)
                widest_s = (f", 最宽维 {widest[0]} range={widest[1]['range']:.3g}"
                            if widest else '')
                print(f"    Top-{top.get('k')} 参数离散: {len(dims)} 维"
                      f"{widest_s}")
            else:
                print(f"    Top-k 离散: 不可用 ({top.get('reason', '—')})")
            boot = rb.get('bootstrap') or {}
            if boot.get('available'):
                print(f"    bootstrap({boot['n_windows']}窗×"
                      f"{boot['n_resamples']}次): 95% CI "
                      f"[{boot['ci_low']:.4f}, {boot['ci_high']:.4f}] "
                      f"(点估计 {boot['fitness_point']:.4f})")
            else:
                print(f"    bootstrap: 不可用 ({boot.get('reason', '—')})")
        print(f"  收敛代数: {result.convergence_gen}")
        print(f"  实际运行代数: {result.generations_run}")
        print(f"  耗时: {result.total_time_sec:.1f}s")

    def get_all_systems(self) -> list:
        """获取所有优化产出的指标体系"""
        systems = []
        for key, result in self.results.items():
            systems.extend(result.all_systems)
        return systems

    def save_results(self, filepath):
        """保存优化结果 (含 seed/适应度权重/参数空间指纹/数据起止/GA运行 — E-P0-3)"""
        # 数据起止日
        data_start = data_end = None
        for df in self.stock_data.values():
            if '日期' not in df.columns or len(df) == 0:
                continue
            d_min, d_max = df['日期'].min(), df['日期'].max()
            data_start = d_min if data_start is None else min(data_start, d_min)
            data_end = d_max if data_end is None else max(data_end, d_max)

        output = {
            'timestamp': datetime.now().isoformat(),
            'seed': self.seed,
            'config': ({'name': self.config.name, 'mode': self.config.mode,
                        'version': self.config.version}
                       if self.config is not None else None),
            # 审计 E-P1 #19 闭环: 记录本次优化的信号引擎模式,
            # optimized_params.load_optimized_params 据此下发
            'use_weighted_scoring': self._use_weighted_scoring,
            'n_stocks': len(self.stock_data),
            'data_start': str(data_start) if data_start is not None else None,
            'data_end': str(data_end) if data_end is not None else None,
            'fitness_weights': dict(self.evaluator.weights),
            'param_space': self._param_space_signature(),
            'ga_runs': list(self._ga_runs),
            # 审计 H10: 全部阶段参与"取最大"的评估次数合计 (多重比较规模;
            # 基线/bootstrap 以 track=False 调用, 不计入)
            'n_evaluations_total': int(sum(r.get('n_evals') or 0
                                           for r in self._ga_runs)),
            # 审计 H1: 落盘记录样本外隔离策略 (末尾窗口留出, 选择不参与)
            'oos_policy': {
                'ratio': self.evaluator.walk_forward_config.oos_ratio,
                'note': ('末尾比例的 walk-forward 窗口留作样本外 (OOS), '
                         '参数选择只用 IS 窗口; OOS 指标见 systems[].oos'),
            },
            # 审计 H10: 稳健性证据口径 (试验次数/随机基线/Top-k/ bootstrap)
            'robustness_policy': {
                **self._robustness_cfg(),
                'note': ('随机基线/Top-k 离散/bootstrap CI 只报告, 不参与'
                         '参数选择 (以 track=False 调用, 独立 RNG 子流); '
                         '试验次数 = 参与取最大的评估次数; bootstrap 回答'
                         '"窗口抽样噪声", 不能替代 OOS 外推证据'),
            },
            # 审计 M5: 逐股回测失败的口径 (计数 + 惩罚规则)
            'failure_policy': {
                'min_success_rate': float(getattr(
                    self.evaluator, 'min_success_rate', 0.5)),
                'penalty': 'fitness *= success_rate (成功率 = 成功回测股数/'
                           '发起回测股数); 成功率 < min_success_rate → 归零',
                'note': ('逐股回测失败不再静默丢弃 (旧实现 except: continue): '
                         '失败股数/失败率落盘, 且适应度按成功率打折 —— '
                         '参数组不得靠"只在能跑通的股票上表现好"取胜; '
                         '体制数据不足(不适用)不计失败, 见 '
                         'systems[].evaluation'),
            },
            # 审计 H2: confidence 口径 (证据派生, 非统计校准概率)
            'confidence_policy': {
                'formula': 'clamp01(fitness)',
                'note': ('confidence = 适应度的 [0,1] 夹取值 (GA 实际最大化的'
                         '目标值本身), 不是统计校准的置信概率; 供同体制'
                         '多系统裁决使用; 旧 manifest 的硬编码值按原样'
                         '读取, 不改写历史实验记录'),
            },
            'systems': []
        }

        for key, result in self.results.items():
            system = result.best_system
            output['systems'].append({
                'name': system.name,
                'description': system.description,
                'applicable_regimes': system.applicable_regimes,
                'params': system.params,
                'fitness_scores': system.fitness_scores,
                'confidence': system.confidence,
                'median_return': system.median_return,
                'win_rate_above_10pct': system.win_rate_above_10pct,
                'median_sharpe': system.median_sharpe,
                'median_max_drawdown': system.median_max_drawdown,
                'median_holding_days': system.median_holding_days,
                'num_trades': system.num_trades,
                'sample_count': system.sample_count,
                # 审计 H1: IS (选择口径) 与 OOS (验证口径) 分列落盘
                'oos': {
                    'available': system.oos_available,
                    'windows': system.oos_windows,
                    'fitness': system.oos_fitness,
                    'median_return': system.oos_median_return,
                    'median_sharpe': system.oos_median_sharpe,
                    'median_max_drawdown': system.oos_median_max_drawdown,
                },
                # 审计 H10: 稳健性/多重检验证据 (只报告, 不参与选择)
                'robustness': system.robustness or {},
                # 审计 M5: 评估覆盖证据 (在多少只股票上真正评估过)
                'evaluation': {
                    'n_stocks_total': system.n_stocks_total,
                    'n_stocks_evaluated': system.n_stocks_evaluated,
                    'n_stocks_failed': system.n_stocks_failed,
                    'success_rate': system.evaluation_success_rate,
                },
                'regime': result.regime,
                'generations_run': result.generations_run,
                'convergence_gen': result.convergence_gen,
                'total_time_sec': result.total_time_sec,
            })

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[OK] 优化结果已保存: {filepath} (seed={self.seed})")

    def load_results(self, filepath):
        """加载优化结果"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for sys_data in data.get('systems', []):
            system = IndicatorSystem(
                name=sys_data['name'],
                description=sys_data['description'],
                applicable_regimes=sys_data['applicable_regimes'],
                params=sys_data['params'],
                fitness_scores=sys_data['fitness_scores'],
                confidence=sys_data['confidence'],
                sample_count=sys_data['sample_count'],
                median_return=sys_data.get('median_return', 0),
                win_rate_above_10pct=sys_data.get('win_rate_above_10pct', 0),
                median_sharpe=sys_data.get('median_sharpe', 0),
                median_max_drawdown=sys_data.get('median_max_drawdown', 0),
                median_holding_days=sys_data.get('median_holding_days', 0),
                num_trades=sys_data.get('num_trades', 0),
                **(oos_fields({'oos': sys_data.get('oos') or {}})),
                # 审计 H10: 稳健性证据读回 (旧 JSON 无键 → 空 dict, 如实)
                robustness=sys_data.get('robustness') or {},
            )

            regime = sys_data.get('regime', 'UNKNOWN')
            result = OptimizationResult(
                regime=regime,
                best_individual=Individual(
                    params=sys_data['params'],
                    fitness=max(sys_data.get('fitness_scores', {}).values(), default=0),
                ),
                best_system=system,
                all_systems=[system],
                # 旧版 JSON 无 generations_run 键 → 退回 convergence_gen
                # (近似: 最后改善代号 ≤ 实际代数; 诚实降级, 不冒充精确值)
                generations_run=sys_data.get(
                    'generations_run', sys_data.get('convergence_gen', 0)),
                total_time_sec=sys_data.get('total_time_sec', 0),
                convergence_gen=sys_data.get('convergence_gen', 0),
            )
            self.results[regime] = result

        print(f"[OK] 加载 {len(data.get('systems', []))} 套指标体系")


# ==================== CLI ====================

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description='遗传算法优化引擎')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # global: 全局优化
    p_global = subparsers.add_parser('global', help='全局优化')
    p_global.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_global.add_argument('--pop', type=int, default=None,
                          help='种群大小 (默认: 阶段分档 80; --config 时 config.ga)')
    p_global.add_argument('--gen', type=int, default=None,
                          help='最大代数 (默认: 阶段分档 40; --config 时 config.ga)')
    p_global.add_argument('--regime-labels', default=None,
                         help='体制标签文件 (默认: stock_data/regime_labels.csv; '
                              '--config 时 config.data.regime_labels_file)')
    p_global.add_argument('--save', default='stock_data/optimization_result.json',
                         help='保存路径')

    # regime: 按体制优化
    p_regime = subparsers.add_parser('regime', help='按体制分别优化')
    p_regime.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_regime.add_argument('--pop', type=int, default=None,
                          help='种群大小 (默认: 阶段分档 60; --config 时 config.ga)')
    p_regime.add_argument('--gen', type=int, default=None,
                          help='最大代数 (默认: 阶段分档 30; --config 时 config.ga)')
    p_regime.add_argument('--regime-labels', default=None,
                         help='体制标签文件 (默认: stock_data/regime_labels.csv; '
                              '--config 时 config.data.regime_labels_file)')
    p_regime.add_argument('--save', default='stock_data/optimization_result.json',
                         help='保存路径')

    # robust: 稳健优化
    p_robust = subparsers.add_parser('robust', help='稳健策略优化')
    p_robust.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_robust.add_argument('--pop', type=int, default=None,
                          help='种群大小 (默认: 阶段分档 80; --config 时 config.ga)')
    p_robust.add_argument('--gen', type=int, default=None,
                          help='最大代数 (默认: 阶段分档 40; --config 时 config.ga)')
    p_robust.add_argument('--regime-labels', default=None,
                         help='体制标签文件 (默认: stock_data/regime_labels.csv; '
                              '--config 时 config.data.regime_labels_file)')
    p_robust.add_argument('--save', default='stock_data/optimization_result.json',
                         help='保存路径')

    # full: 完整优化流程 (全局+体制+稳健+迭代)
    p_full = subparsers.add_parser('full', help='完整优化流程')
    p_full.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_full.add_argument('--regime-labels', default=None,
                        help='体制标签文件 (默认: stock_data/regime_labels.csv; '
                             '--config 时 config.data.regime_labels_file)')
    p_full.add_argument('--save', default='stock_data/optimization_result.json',
                        help='保存路径')

    # iterative: 多轮迭代优化
    p_iter = subparsers.add_parser('iterative', help='多轮迭代优化')
    p_iter.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_iter.add_argument('--rounds', type=int, default=3, help='迭代轮数')
    p_iter.add_argument('--save', default='stock_data/optimization_result.json',
                        help='保存路径')

    # run: 按配置文件运行 (config-first, 审计 E-P1 接线)
    p_run = subparsers.add_parser(
        'run', help='按 OptimizationConfig 的 mode/数据/GA/迭代轮次完整运行')
    p_run.add_argument('--save', default='stock_data/optimization_result.json',
                       help='保存路径')

    # E-P0-3: 所有子命令支持 --seed (默认42 → 命令行运行默认可复现);
    # E-P1: 所有子命令支持 --config (config 为 ga/fitness/walk_forward/
    # iterative_rounds 真相源; 子命令 > config.mode, run 子命令除外)
    for _p in (p_global, p_regime, p_robust, p_full, p_iter, p_run):
        _p.add_argument('--seed', type=int, default=42,
                        help='随机种子 (同种子同数据可复现)')
        _p.add_argument('--config', default=None,
                        help='OptimizationConfig JSON 路径 (python '
                             'optimization_config.py create --preset ... 生成)')

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return

    cfg = OptimizationConfig.load(args.config) if args.config else None
    engine = OptimizationEngine(seed=args.seed, config=cfg)

    if args.command in ('global', 'regime', 'robust', 'full', 'iterative'):
        # 体制标签优先级: 显式 --regime-labels > config.data > 旧默认路径
        labels_file = getattr(args, 'regime_labels', None)
        if labels_file is None:
            labels_file = (cfg.data.regime_labels_file if cfg is not None
                           else 'stock_data/regime_labels.csv')
        engine.load_data(regime_labels_file=labels_file)

    ga_params = {}
    if getattr(args, 'pop', None) is not None:
        ga_params['population_size'] = args.pop
    if getattr(args, 'gen', None) is not None:
        ga_params['max_generations'] = args.gen

    if args.command == 'run':
        if cfg is None:
            print("[ERROR] run 子命令需要 --config <OptimizationConfig JSON>; "
                  "可用 python optimization_config.py create --preset quick 生成")
            return
        mode = cfg.mode
        n_stocks = cfg.data.stock_sample_size
        engine.load_data(regime_labels_file=cfg.data.regime_labels_file)
        print(f"[INFO] run: config={cfg.name} mode={mode} n_stocks={n_stocks}")
        if mode == 'global':
            engine.optimize_global(n_stocks=n_stocks)
        elif mode == 'regime':
            engine.optimize_by_regime(n_stocks=n_stocks)
        elif mode == 'robust':
            engine.optimize_robust(n_stocks=n_stocks)
        elif mode == 'iterative':
            engine.iterative_optimize(
                n_stocks=n_stocks, n_rounds=len(cfg.iterative_rounds))
        elif mode == 'full':
            engine.optimize_global(n_stocks=n_stocks)
            engine.optimize_by_regime(n_stocks=n_stocks)
            engine.optimize_robust(n_stocks=n_stocks)
            engine.iterative_optimize(
                n_stocks=n_stocks, n_rounds=len(cfg.iterative_rounds))
        else:
            print(f"[ERROR] 未知 mode: {mode!r} "
                  "(合法: global/regime/robust/iterative/full)")
            return
        engine.save_results(args.save)

    elif args.command == 'global':
        engine.optimize_global(n_stocks=args.n_stocks, ga_params=ga_params)
        engine.save_results(args.save)

    elif args.command == 'regime':
        engine.optimize_by_regime(n_stocks=args.n_stocks, ga_params=ga_params)
        engine.save_results(args.save)

    elif args.command == 'robust':
        engine.optimize_robust(n_stocks=args.n_stocks, ga_params=ga_params)
        engine.save_results(args.save)

    elif args.command == 'iterative':
        engine.iterative_optimize(n_stocks=args.n_stocks, n_rounds=args.rounds)
        engine.save_results(args.save)

    elif args.command == 'full':
        print("=" * 70)
        print("  完整优化流程: 全局 → 按体制 → 稳健 → 迭代")
        print("=" * 70)

        engine.optimize_global(n_stocks=args.n_stocks)
        engine.optimize_by_regime(n_stocks=args.n_stocks)
        engine.optimize_robust(n_stocks=args.n_stocks)
        engine.iterative_optimize(n_stocks=args.n_stocks, n_rounds=2)

        engine.save_results(args.save)

        # 打印所有体系总结
        print("\n" + "=" * 70)
        print("  优化完成 — 指标体系总结")
        print("=" * 70)
        for system in engine.get_all_systems():
            print(f"\n  [{system.name}]")
            print(f"    {system.description}")
            print(f"    适用: {', '.join(system.applicable_regimes)}")
            print(f"    中位收益: {system.median_return:.1f}% | "
                  f"达标率: {system.win_rate_above_10pct:.1%} | "
                  f"夏普: {system.median_sharpe:.2f} | "
                  f"回撤: {system.median_max_drawdown:.1f}%")


if __name__ == "__main__":
    main()
