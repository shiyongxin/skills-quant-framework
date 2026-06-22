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
from typing import Optional
from pathlib import Path
from datetime import datetime
import json
import time
import copy

from parameter_space import ParameterSpace
from vectorized_backtest import VectorizedBacktester, BacktestMetrics
from historical_data_manager import HistoricalDataManager


# ==================== 数据结构 ====================

@dataclass
class IndicatorSystem:
    """一套指标体系"""
    name: str                       # 如 "牛市追涨型"
    description: str                # 适用场景描述
    applicable_regimes: list        # 适用体制: ['BULL', 'EARLY_BULL']
    params: dict                    # 完整参数集
    fitness_scores: dict            # 各体制下的fitness {regime: fitness}
    confidence: float               # 置信度 (0-1)
    sample_count: int               # 支撑该结论的样本数

    # 性能统计
    median_return: float = 0.0
    win_rate_above_10pct: float = 0.0
    median_sharpe: float = 0.0
    median_max_drawdown: float = 0.0
    median_holding_days: float = 0.0
    num_trades: float = 0.0


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

class FitnessEvaluator:
    """
    适应度评估器

    对给定参数在多只股票上进行Walk-Forward回测，
    聚合结果计算适应度分数。
    """

    def __init__(self, backtester=None, target_return=10.0,
                 target_probability=0.80, max_drawdown_limit=25.0):
        """
        Parameters:
        -----------
        target_return : float
            目标收益率(%)
        target_probability : float
            目标达标概率
        max_drawdown_limit : float
            最大回撤限制(%)
        """
        self.backtester = backtester or VectorizedBacktester()
        self.target_return = target_return
        self.target_probability = target_probability
        self.max_drawdown_limit = max_drawdown_limit

    def evaluate(self, params: dict, stock_data: dict,
                 regime_labels: dict = None,
                 target_regime: str = None) -> tuple:
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

        Returns:
        --------
        (fitness: float, details: dict)
        """
        all_metrics = []

        for symbol, data in stock_data.items():
            try:
                if target_regime and regime_labels and symbol in regime_labels:
                    # 按体制过滤数据
                    labels = regime_labels[symbol]
                    mask = labels == target_regime
                    if mask.sum() < 60:
                        continue
                    # 使用连续的体制时段进行回测
                    metrics_list = self._backtest_regime_windows(
                        data, params, labels, target_regime
                    )
                    all_metrics.extend(metrics_list)
                else:
                    # Walk-Forward回测
                    metrics_list = self.backtester.walk_forward(
                        data, params, train_days=504, test_days=180, step_days=63
                    )
                    all_metrics.extend(metrics_list)
            except Exception:
                continue

        if not all_metrics:
            return 0.0, {}

        return self._compute_fitness(all_metrics)

    def _backtest_regime_windows(self, data, params, labels, target_regime):
        """
        在体制时段内进行回测

        混合策略:
        - 长窗口体制(BULL/BEAR/SIDEWAYS): 按连续窗口切割回测
        - 短窗口体制(CRASH/RECOVERY): 全量回测后按交易入口过滤
        """
        metrics_list = []

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
            return self._backtest_by_trade_filter(data, params, labels, target_regime)

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
            except Exception:
                continue

        return metrics_list

    def _backtest_by_trade_filter(self, data, params, labels, target_regime):
        """
        全量回测 + 按交易入口体制过滤

        适用于短窗口体制(CRASH/RECOVERY):
        1. 对整只股票做回测，获取每笔交易的入场日期
        2. 检查入场日的体制标签
        3. 仅保留入场时处于目标体制的交易
        4. 用过滤后的交易计算指标
        """
        try:
            metrics, trade_details = self.backtester.backtest_with_details(data, params)
        except Exception:
            return []

        if not trade_details:
            return []

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
            return [filtered_metrics]
        return []

    def _compute_metrics_from_trades(self, trades, data, params):
        """从交易列表计算BacktestMetrics"""
        import numpy as np

        if not trades:
            return None

        pnl_arr = np.array([t.pnl_pct for t in trades], dtype=np.float64)
        holding_arr = np.array([t.holding_days for t in trades], dtype=np.float64)
        position_size_pct = float(params.get('position_size_pct', 0.8))

        # 胜率
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr <= 0]
        win_rate = (len(wins) / len(pnl_arr)) * 100 if len(pnl_arr) > 0 else 0

        # 盈亏比
        avg_win = np.mean(wins) if len(wins) > 0 else 0
        avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 1
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

        # 总收益(复利)
        cumulative = np.cumprod(1 + pnl_arr / 100 * position_size_pct)
        total_return = (cumulative[-1] - 1) * 100 if len(cumulative) > 0 else 0

        # 年化收益
        total_days = data.iloc[-1]['收盘']  # placeholder
        total_days = len(data)
        years = total_days / 252
        if years > 0 and cumulative[-1] > 0:
            annualized_return = (cumulative[-1] ** (1 / years) - 1) * 100
        else:
            annualized_return = 0

        # 最大回撤
        equity = np.concatenate([[1.0], cumulative])
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak * 100
        max_drawdown = abs(drawdown.min()) if len(drawdown) > 0 else 0

        # 夏普比率
        if len(pnl_arr) > 1:
            daily_returns = pnl_arr / 100
            avg_ret = np.mean(daily_returns) * 252 / np.mean(holding_arr) if np.mean(holding_arr) > 0 else 0
            std_ret = np.std(daily_returns) * np.sqrt(252 / np.mean(holding_arr)) if np.mean(holding_arr) > 0 else 1
            sharpe = (avg_ret - 0.03) / std_ret if std_ret > 0 else 0
        else:
            sharpe = 0

        # 最大连续亏损
        is_loss = pnl_arr <= 0
        max_consec = 0
        if np.any(is_loss):
            loss_streaks = np.diff(np.where(np.concatenate([[False], is_loss, [False]]))[0])
            max_consec = int(loss_streaks.max()) if len(loss_streaks) > 0 else 0

        from vectorized_backtest import BacktestMetrics
        return BacktestMetrics(
            total_return=float(total_return),
            annualized_return=float(annualized_return),
            max_drawdown=float(max_drawdown),
            sharpe_ratio=float(sharpe),
            win_rate=float(win_rate),
            profit_factor=float(profit_factor),
            num_trades=len(pnl_arr),
            avg_holding_days=float(np.mean(holding_arr)),
            avg_return_per_trade=float(np.mean(pnl_arr)),
            max_consecutive_losses=max_consec
        )

    def _compute_fitness(self, metrics_list: list) -> tuple:
        """
        从回测指标列表计算适应度

        适应度 = 0.40*达标率 + 0.25*中位收益 + 0.20*中位夏普 + 0.15*回撤惩罚
        """
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

        # 回撤惩罚 (越小越好)
        median_dd = np.median(drawdowns) if drawdowns else 100
        dd_penalty = max(0, 1 - median_dd / self.max_drawdown_limit)

        # 交易次数惩罚 (太少或太多都不好)
        avg_trades = np.mean(trades) if trades else 0
        if avg_trades < 3:
            trade_penalty = avg_trades / 3
        elif avg_trades > 50:
            trade_penalty = max(0, 1 - (avg_trades - 50) / 50)
        else:
            trade_penalty = 1.0

        # 综合适应度
        fitness = (
            0.40 * target_rate +
            0.25 * max(0, ret_score) +
            0.20 * max(0, sharpe_score) +
            0.15 * dd_penalty
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
         convergence_gen: int)
        """
        if rng is None:
            rng = np.random.default_rng()

        # 初始化种群
        population = self._init_population(seed_params, rng)

        best_fitness = -np.inf
        best_individual = None
        no_improve_count = 0
        convergence_gen = 0

        for gen in range(self.max_generations):
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

        return best_individual, population, convergence_gen

    def _init_population(self, seed_params, rng):
        """初始化种群"""
        population = []

        # 加入种子参数
        if seed_params:
            for params in seed_params:
                ind = Individual(params=copy.deepcopy(params))
                population.append(ind)

        # 随机填充剩余
        while len(population) < self.population_size:
            params = ParameterSpace.random_sample(rng)
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

            # 变异
            child1_params = ParameterSpace.mutate(child1_params, mutation_rate, rng)
            child2_params = ParameterSpace.mutate(child2_params, mutation_rate, rng)

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

    def __init__(self, data_dir="./stock_data", n_workers=4):
        """
        Parameters:
        -----------
        data_dir : str
            数据目录
        n_workers : int
            并行工作线程数
        """
        self.data_manager = HistoricalDataManager(data_dir)
        self.backtester = VectorizedBacktester()
        self.evaluator = FitnessEvaluator(self.backtester)
        self.n_workers = n_workers

        self.results = {}       # {regime: OptimizationResult}
        self.stock_data = {}    # {symbol: DataFrame}
        self.regime_labels = {} # {symbol: pd.Series}

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
        for sym in symbols:
            data = self.data_manager.load(sym)
            if len(data) >= 252:  # 至少1年数据
                self.stock_data[sym] = data
                loaded += 1

                # 为每只股票分配体制标签
                if self._index_regime_labels is not None:
                    self._assign_regime_labels(sym, data)

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
        sample_data = self._get_sample(stock_sample, n_stocks)
        if not sample_data:
            print("[ERROR] 无可用股票数据")
            return None

        print(f"  样本股票: {len(sample_data)} 只")

        # GA配置
        ga_cfg = {
            'population_size': 80,
            'max_generations': 40,
            'convergence_threshold': 8,
        }
        if ga_params:
            ga_cfg.update(ga_params)

        # 评估函数
        def evaluate(params):
            return self.evaluator.evaluate(params, sample_data)

        # 运行GA
        ga = GeneticAlgorithm(**ga_cfg)
        start_time = time.time()

        if verbose:
            print(f"  GA配置: pop={ga_cfg['population_size']}, "
                  f"max_gen={ga_cfg['max_generations']}")

        best, all_inds, conv_gen = ga.run(evaluate, verbose=verbose)
        total_time = time.time() - start_time

        # 构建结果
        system = IndicatorSystem(
            name="通用基线型",
            description="在所有市场体制下表现均衡的通用参数",
            applicable_regimes=['BULL', 'BEAR', 'SIDEWAYS', 'CRASH', 'RECOVERY'],
            params=best.params,
            fitness_scores={'GLOBAL': best.fitness},
            confidence=0.7,
            sample_count=best.fitness_details.get('sample_count', 0),
            median_return=best.fitness_details.get('median_return', 0),
            win_rate_above_10pct=best.fitness_details.get('target_rate', 0),
            median_sharpe=best.fitness_details.get('median_sharpe', 0),
            median_max_drawdown=best.fitness_details.get('median_drawdown', 0),
            median_holding_days=best.fitness_details.get('avg_holding_days', 0),
            num_trades=best.fitness_details.get('avg_trades', 0),
        )

        result = OptimizationResult(
            regime='GLOBAL',
            best_individual=best,
            best_system=system,
            all_systems=[system],
            generations_run=ga_cfg['max_generations'],
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

        sample_data = self._get_sample(stock_sample, n_stocks)
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

        ga_cfg = {
            'population_size': 60,
            'max_generations': 30,
            'convergence_threshold': 6,
        }
        if ga_params:
            ga_cfg.update(ga_params)

        results = {}

        for regime in active_regimes:
            print(f"\n--- 优化体制: {regime} ---")

            regime_name_cn = {
                'BULL': '牛市', 'BEAR': '熊市', 'SIDEWAYS': '震荡',
                'CRASH': '暴跌', 'RECOVERY': '反弹'
            }.get(regime, regime)

            def evaluate(params, r=regime):
                return self.evaluator.evaluate(
                    params, sample_data, self.regime_labels, r
                )

            ga = GeneticAlgorithm(**ga_cfg)
            start_time = time.time()

            best, all_inds, conv_gen = ga.run(evaluate, verbose=verbose)
            total_time = time.time() - start_time

            system = IndicatorSystem(
                name=f"{regime_name_cn}专用型",
                description=f"专为{regime_name_cn}市场体制优化的参数",
                applicable_regimes=[regime],
                params=best.params,
                fitness_scores={regime: best.fitness},
                confidence=min(0.9, best.fitness * 1.2),
                sample_count=best.fitness_details.get('sample_count', 0),
                median_return=best.fitness_details.get('median_return', 0),
                win_rate_above_10pct=best.fitness_details.get('target_rate', 0),
                median_sharpe=best.fitness_details.get('median_sharpe', 0),
                median_max_drawdown=best.fitness_details.get('median_drawdown', 0),
                median_holding_days=best.fitness_details.get('avg_holding_days', 0),
                num_trades=best.fitness_details.get('avg_trades', 0),
            )

            result = OptimizationResult(
                regime=regime,
                best_individual=best,
                best_system=system,
                all_systems=[system],
                generations_run=ga_cfg['max_generations'],
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

        sample_data = self._get_sample(stock_sample, n_stocks)
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

        ga_cfg = {
            'population_size': 80,
            'max_generations': 40,
            'convergence_threshold': 8,
        }
        if ga_params:
            ga_cfg.update(ga_params)

        def evaluate_robust(params):
            """稳健适应度: 各体制fitness的最小值(忽略无数据体制)"""
            if not all_regimes or not self.regime_labels:
                return self.evaluator.evaluate(params, sample_data)

            regime_fitnesses = {}
            for regime in all_regimes:
                fitness, details = self.evaluator.evaluate(
                    params, sample_data, self.regime_labels, regime
                )
                # 仅记录有样本的体制
                if details.get('sample_count', 0) > 0:
                    regime_fitnesses[regime] = fitness

            if not regime_fitnesses:
                return 0.0, {}

            # 稳健适应度 = 最小fitness (最大化最差表现)
            fitness_values = list(regime_fitnesses.values())
            min_fitness = min(fitness_values)
            avg_fitness = np.mean(fitness_values)
            # 70%最小 + 30%平均
            robust_fitness = 0.7 * min_fitness + 0.3 * avg_fitness

            details = {
                'regime_fitnesses': regime_fitnesses,
                'min_fitness': min_fitness,
                'avg_fitness': avg_fitness,
                'regimes_used': list(regime_fitnesses.keys()),
                'regimes_skipped': [r for r in all_regimes if r not in regime_fitnesses],
            }
            return robust_fitness, details

        ga = GeneticAlgorithm(**ga_cfg)
        start_time = time.time()

        best, all_inds, conv_gen = ga.run(evaluate_robust, verbose=verbose)
        total_time = time.time() - start_time

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
            confidence=0.6,
            sample_count=best.fitness_details.get('sample_count', 0),
            median_return=best.fitness_details.get('median_return', 0),
            win_rate_above_10pct=best.fitness_details.get('target_rate', 0),
            median_sharpe=best.fitness_details.get('median_sharpe', 0),
            median_max_drawdown=best.fitness_details.get('median_drawdown', 0),
            median_holding_days=best.fitness_details.get('avg_holding_days', 0),
            num_trades=best.fitness_details.get('avg_trades', 0),
        )

        result = OptimizationResult(
            regime='ROBUST',
            best_individual=best,
            best_system=system,
            all_systems=[system],
            generations_run=ga_cfg['max_generations'],
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

        sample_data = self._get_sample(stock_sample, n_stocks)
        if not sample_data:
            return []

        # 各轮配置
        round_configs = [
            {'population_size': 40, 'max_generations': 15,
             'convergence_threshold': 5, 'mutation_rate': 0.25},
            {'population_size': 60, 'max_generations': 25,
             'convergence_threshold': 6, 'mutation_rate': 0.18},
            {'population_size': 100, 'max_generations': 40,
             'convergence_threshold': 8, 'mutation_rate': 0.12},
        ]

        all_round_results = []
        seed_params = None

        for round_idx in range(min(n_rounds, len(round_configs))):
            cfg = round_configs[round_idx]
            print(f"\n--- Round {round_idx + 1}/{n_rounds} ---")
            print(f"  pop={cfg['population_size']}, "
                  f"max_gen={cfg['max_generations']}, "
                  f"mut_rate={cfg['mutation_rate']}")

            def evaluate(params):
                return self.evaluator.evaluate(params, sample_data)

            ga = GeneticAlgorithm(
                population_size=cfg['population_size'],
                max_generations=cfg['max_generations'],
                convergence_threshold=cfg['convergence_threshold'],
                mutation_rate=cfg['mutation_rate'],
            )

            start_time = time.time()
            best, all_inds, conv_gen = ga.run(
                evaluate, seed_params=seed_params, verbose=verbose
            )
            total_time = time.time() - start_time

            result = {
                'round': round_idx + 1,
                'best_fitness': best.fitness,
                'best_params': best.params,
                'best_details': best.fitness_details,
                'convergence_gen': conv_gen,
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
            system = IndicatorSystem(
                name="迭代优化型",
                description=f"经过{n_rounds}轮迭代精炼的参数",
                applicable_regimes=['BULL', 'BEAR', 'SIDEWAYS', 'CRASH', 'RECOVERY'],
                params=final['best_params'],
                fitness_scores={'GLOBAL': final['best_fitness']},
                confidence=0.75,
                sample_count=final['best_details'].get('sample_count', 0),
                median_return=final['best_details'].get('median_return', 0),
                win_rate_above_10pct=final['best_details'].get('target_rate', 0),
                median_sharpe=final['best_details'].get('median_sharpe', 0),
                median_max_drawdown=final['best_details'].get('median_drawdown', 0),
                median_holding_days=final['best_details'].get('avg_holding_days', 0),
                num_trades=final['best_details'].get('avg_trades', 0),
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
                generations_run=sum(r.get('convergence_gen', 0) for r in all_round_results),
                total_time_sec=sum(r['time_sec'] for r in all_round_results),
                convergence_gen=all_round_results[-1]['convergence_gen'],
            )
            self.results['ITERATIVE'] = result

        return all_round_results

    def _get_sample(self, stock_sample, n_stocks):
        """获取股票样本"""
        if stock_sample:
            return {s: self.stock_data[s] for s in stock_sample if s in self.stock_data}

        if not self.stock_data:
            return {}

        all_symbols = list(self.stock_data.keys())
        if len(all_symbols) <= n_stocks:
            return dict(self.stock_data)

        # 分层抽样: 优先选择有体制标签的
        import random
        labeled = [s for s in all_symbols if s in self.regime_labels]
        unlabeled = [s for s in all_symbols if s not in self.regime_labels]

        sample = []
        n_labeled = min(len(labeled), int(n_stocks * 0.8))
        n_unlabeled = n_stocks - n_labeled

        if n_labeled > 0:
            sample.extend(random.sample(labeled, n_labeled))
        if n_unlabeled > 0 and unlabeled:
            sample.extend(random.sample(unlabeled, min(n_unlabeled, len(unlabeled))))

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
        print(f"  收敛代数: {result.convergence_gen}")
        print(f"  耗时: {result.total_time_sec:.1f}s")

    def get_all_systems(self) -> list:
        """获取所有优化产出的指标体系"""
        systems = []
        for key, result in self.results.items():
            systems.extend(result.all_systems)
        return systems

    def save_results(self, filepath):
        """保存优化结果"""
        output = {
            'timestamp': datetime.now().isoformat(),
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
                'regime': result.regime,
                'convergence_gen': result.convergence_gen,
                'total_time_sec': result.total_time_sec,
            })

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[OK] 优化结果已保存: {filepath}")

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
                generations_run=sys_data.get('convergence_gen', 0),
                total_time_sec=sys_data.get('total_time_sec', 0),
                convergence_gen=sys_data.get('convergence_gen', 0),
            )
            self.results[regime] = result

        print(f"[OK] 加载 {len(data.get('systems', []))} 套指标体系")


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='遗传算法优化引擎')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # global: 全局优化
    p_global = subparsers.add_parser('global', help='全局优化')
    p_global.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_global.add_argument('--pop', type=int, default=80, help='种群大小')
    p_global.add_argument('--gen', type=int, default=40, help='最大代数')
    p_global.add_argument('--regime-labels', default='stock_data/regime_labels.csv',
                         help='体制标签文件')
    p_global.add_argument('--save', default='stock_data/optimization_result.json',
                         help='保存路径')

    # regime: 按体制优化
    p_regime = subparsers.add_parser('regime', help='按体制分别优化')
    p_regime.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_regime.add_argument('--pop', type=int, default=60, help='种群大小')
    p_regime.add_argument('--gen', type=int, default=30, help='最大代数')
    p_regime.add_argument('--regime-labels', default='stock_data/regime_labels.csv',
                         help='体制标签文件')
    p_regime.add_argument('--save', default='stock_data/optimization_result.json',
                         help='保存路径')

    # robust: 稳健优化
    p_robust = subparsers.add_parser('robust', help='稳健策略优化')
    p_robust.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_robust.add_argument('--pop', type=int, default=80, help='种群大小')
    p_robust.add_argument('--gen', type=int, default=40, help='最大代数')
    p_robust.add_argument('--regime-labels', default='stock_data/regime_labels.csv',
                         help='体制标签文件')
    p_robust.add_argument('--save', default='stock_data/optimization_result.json',
                         help='保存路径')

    # full: 完整优化流程 (全局+体制+稳健+迭代)
    p_full = subparsers.add_parser('full', help='完整优化流程')
    p_full.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_full.add_argument('--regime-labels', default='stock_data/regime_labels.csv',
                        help='体制标签文件')
    p_full.add_argument('--save', default='stock_data/optimization_result.json',
                        help='保存路径')

    # iterative: 多轮迭代优化
    p_iter = subparsers.add_parser('iterative', help='多轮迭代优化')
    p_iter.add_argument('--n-stocks', type=int, default=50, help='抽样股票数')
    p_iter.add_argument('--rounds', type=int, default=3, help='迭代轮数')
    p_iter.add_argument('--save', default='stock_data/optimization_result.json',
                        help='保存路径')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    engine = OptimizationEngine()

    if args.command in ('global', 'regime', 'robust', 'full', 'iterative'):
        labels_file = getattr(args, 'regime_labels', None)
        engine.load_data(regime_labels_file=labels_file)

    ga_params = {}
    if hasattr(args, 'pop'):
        ga_params['population_size'] = args.pop
    if hasattr(args, 'gen'):
        ga_params['max_generations'] = args.gen

    if args.command == 'global':
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
