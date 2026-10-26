# -*- coding: utf-8 -*-
"""
策略参数优化器
Strategy Parameter Optimizer

提供网格搜索、随机搜索、边界随机采样等参数优化功能
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any
from dataclasses import dataclass
from itertools import product
import random

from core.indicators import rsi as _core_rsi, sma as _core_sma, macd as _core_macd

try:
    from backtest_framework import BacktestEngine, PositionConfig, PositionSizingMethod
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class OptimizationResult:
    """优化结果"""
    parameters: Dict[str, Any]
    score: float
    metrics: Dict[str, float]
    backtest_result: Any = None


@dataclass
class OptimizationConfig:
    """优化配置"""
    strategy_name: str = "default"
    target_metric: str = "sharpe_ratio"  # 优化目标指标
    maximize: bool = True  # 是否最大化


# =============================================================================
# 策略模板
# =============================================================================

class StrategyTemplate:
    """策略模板基类"""

    def __init__(self, name: str):
        """
        初始化策略模板

        Args:
            name: 策略名称
        """
        self.name = name

    def generate_signals(self, data: pd.DataFrame, params: Dict) -> pd.DataFrame:
        """
        根据参数生成信号

        Args:
            data: 股票数据
            params: 策略参数

        Returns:
            添加信号的DataFrame
        """
        raise NotImplementedError

    def get_param_grid(self) -> Dict[str, List]:
        """
        获取参数网格

        Returns:
            {参数名: 参数值列表} 字典
        """
        raise NotImplementedError


class MAStrategy(StrategyTemplate):
    """移动平均线策略"""

    def __init__(self):
        super().__init__("MA交叉")

    def generate_signals(self, data: pd.DataFrame, params: Dict) -> pd.DataFrame:
        """生成MA交叉信号"""
        short_period = params.get('short_period', 5)
        long_period = params.get('long_period', 20)

        data = data.copy()

        # 计算均线
        data[f'MA{short_period}'] = _core_sma(data['收盘'], short_period)
        data[f'MA{long_period}'] = _core_sma(data['收盘'], long_period)

        # 生成信号
        data['signal_buy'] = (
            (data[f'MA{short_period}'] > data[f'MA{long_period}']) &
            (data[f'MA{short_period}'].shift(1) <= data[f'MA{long_period}'].shift(1))
        )

        data['signal_sell'] = (
            (data[f'MA{short_period}'] < data[f'MA{long_period}']) &
            (data[f'MA{short_period}'].shift(1) >= data[f'MA{long_period}'].shift(1))
        )

        return data

    def get_param_grid(self) -> Dict[str, List]:
        return {
            'short_period': [5, 10, 15, 20],
            'long_period': [20, 30, 40, 60]
        }


class MACDStrategy(StrategyTemplate):
    """MACD策略"""

    def __init__(self):
        super().__init__("MACD")

    def generate_signals(self, data: pd.DataFrame, params: Dict) -> pd.DataFrame:
        """生成MACD信号"""
        fast = params.get('fast_period', 12)
        slow = params.get('slow_period', 26)
        signal_period = params.get('signal_period', 9)

        data = data.copy()

        # 计算MACD (core 单一真相源)
        dif, dea, _hist = _core_macd(data['收盘'], fast, slow, signal_period)
        data['MACD'] = dif
        data['MACD_Signal'] = dea

        # 生成信号
        data['signal_buy'] = (
            (data['MACD'] > data['MACD_Signal']) &
            (data['MACD'].shift(1) <= data['MACD_Signal'].shift(1))
        )

        data['signal_sell'] = (
            (data['MACD'] < data['MACD_Signal']) &
            (data['MACD'].shift(1) >= data['MACD_Signal'].shift(1))
        )

        return data

    def get_param_grid(self) -> Dict[str, List]:
        return {
            'fast_period': [8, 12, 16],
            'slow_period': [20, 26, 32],
            'signal_period': [6, 9, 12]
        }


class RSIStrategy(StrategyTemplate):
    """RSI策略"""

    def __init__(self):
        super().__init__("RSI")

    def generate_signals(self, data: pd.DataFrame, params: Dict) -> pd.DataFrame:
        """生成RSI信号"""
        period = params.get('period', 14)
        oversold = params.get('oversold', 30)
        overbought = params.get('overbought', 70)

        data = data.copy()

        # 计算RSI (core 单一真相源)
        data['RSI'] = _core_rsi(data['收盘'], period)

        # 生成信号
        data['signal_buy'] = (
            (data['RSI'] < oversold) &
            (data['RSI'].shift(1) >= oversold)
        )

        data['signal_sell'] = (
            (data['RSI'] > overbought) &
            (data['RSI'].shift(1) <= overbought)
        )

        return data

    def get_param_grid(self) -> Dict[str, List]:
        return {
            'period': [7, 14, 21],
            'oversold': [20, 30, 40],
            'overbought': [60, 70, 80]
        }


class MultiFactorStrategy(StrategyTemplate):
    """多因子综合策略"""

    def __init__(self):
        super().__init__("多因子")

    def generate_signals(self, data: pd.DataFrame, params: Dict) -> pd.DataFrame:
        """生成综合信号"""
        buy_threshold = params.get('buy_threshold', 3.0)
        sell_threshold = params.get('sell_threshold', -3.0)

        data = data.copy()

        # 计算技术指标
        from signal_generator import SignalGenerator
        generator = SignalGenerator()
        data = generator.generate_signals(data)

        # 生成信号
        data['signal_buy'] = data['signal_strength'] >= buy_threshold
        data['signal_sell'] = data['signal_strength'] <= sell_threshold

        return data

    def get_param_grid(self) -> Dict[str, List]:
        return {
            'buy_threshold': [2.0, 3.0, 4.0, 5.0],
            'sell_threshold': [-5.0, -4.0, -3.0, -2.0]
        }


# =============================================================================
# 策略优化器
# =============================================================================

class StrategyOptimizer:
    """策略参数优化器"""

    def __init__(self, strategy: StrategyTemplate = None,
                 config: OptimizationConfig = None):
        """
        初始化优化器

        Args:
            strategy: 策略模板
            config: 优化配置
        """
        if not MODULES_AVAILABLE:
            raise ImportError("必要模块未安装")

        self.strategy = strategy or MAStrategy()
        self.config = config or OptimizationConfig()

    def evaluate_params(self, data: pd.DataFrame,
                       params: Dict) -> Dict[str, float]:
        """
        评估参数组合

        Args:
            data: 股票数据
            params: 策略参数

        Returns:
            评估指标字典
        """
        # 生成信号
        data_with_signals = self.strategy.generate_signals(data, params)

        # 运行回测（引擎方法是 run()，非 run_backtest；结果为 dict，非对象）
        try:
            engine = BacktestEngine(
                initial_cash=1000000,
                position_config=PositionConfig(
                    sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
                    sizing_value=0.2,
                    max_position_pct=0.2
                )
            )

            def _strategy_fn(window):
                if len(window) == 0:
                    return 0
                last = window.iloc[-1]
                if bool(last.get('signal_buy', False)):
                    return 1
                if bool(last.get('signal_sell', False)):
                    return -1
                return 0

            result = engine.run(data_with_signals, _strategy_fn, symbol='OPT')

            if not isinstance(result, dict) or not result:
                raise ValueError("回测未产生有效结果")

            return {
                'sharpe_ratio': float(result.get('sharpe_ratio', 0) or 0),
                'annual_return': float(result.get('annualized_return', 0) or 0),
                'max_drawdown': float(result.get('max_drawdown', 0) or 0),
                'total_return': float(result.get('total_return', 0) or 0),
                'win_rate': float(result.get('win_rate', 0) or 0),
                'profit_factor': float(result.get('profit_factor', 0) or 0)
            }
        except Exception as e:
            print(f"[WARN] 回测失败: {e}")
            return {
                'sharpe_ratio': -999,
                'annual_return': 0,
                'max_drawdown': 0,
                'total_return': 0,
                'win_rate': 0,
                'profit_factor': 0
            }

    def grid_search(self, data: pd.DataFrame,
                   param_grid: Dict = None,
                   verbose: bool = True) -> OptimizationResult:
        """
        网格搜索优化

        Args:
            data: 股票数据
            param_grid: 参数网格
            verbose: 是否显示进度

        Returns:
            优化结果
        """
        if param_grid is None:
            param_grid = self.strategy.get_param_grid()

        best_params = None
        best_score = -np.inf if self.config.maximize else np.inf
        best_metrics = None

        total_combinations = 1
        for values in param_grid.values():
            total_combinations *= len(values)

        if verbose:
            print(f"网格搜索开始，共 {total_combinations} 种组合")

        count = 0

        # 遍历所有参数组合（itertools.product 替代 sklearn ParameterGrid）
        _keys = list(param_grid.keys())
        for _values in product(*param_grid.values()):
            params = dict(zip(_keys, _values))
            count += 1

            if verbose:
                print(f"\r进度: {count}/{total_combinations} ({count/total_combinations*100:.1f}%)", end='')

            # 评估
            metrics = self.evaluate_params(data, params)
            score = metrics.get(self.config.target_metric, 0)

            # 更新最佳
            if self.config.maximize:
                if score > best_score:
                    best_score = score
                    best_params = params
                    best_metrics = metrics
            else:
                if score < best_score:
                    best_score = score
                    best_params = params
                    best_metrics = metrics

        if verbose:
            print()  # 换行
            print(f"最佳参数: {best_params}")
            print(f"最佳{self.config.target_metric}: {best_score:.4f}")

        return OptimizationResult(
            parameters=best_params,
            score=best_score,
            metrics=best_metrics
        )

    def random_search(self, data: pd.DataFrame,
                     param_grid: Dict = None,
                     n_iter: int = 50,
                     verbose: bool = True) -> OptimizationResult:
        """
        随机搜索优化

        Args:
            data: 股票数据
            param_grid: 参数范围
            n_iter: 迭代次数
            verbose: 是否显示进度

        Returns:
            优化结果
        """
        if param_grid is None:
            param_grid = self.strategy.get_param_grid()

        best_params = None
        best_score = -np.inf if self.config.maximize else np.inf
        best_metrics = None

        if verbose:
            print(f"随机搜索开始，共 {n_iter} 次迭代")

        for i in range(n_iter):
            # 随机采样参数
            params = {k: random.choice(v) for k, v in param_grid.items()}

            if verbose:
                print(f"\r进度: {i+1}/{n_iter} ({(i+1)/n_iter*100:.1f}%)", end='')

            # 评估
            metrics = self.evaluate_params(data, params)
            score = metrics.get(self.config.target_metric, 0)

            # 更新最佳
            if self.config.maximize:
                if score > best_score:
                    best_score = score
                    best_params = params
                    best_metrics = metrics
            else:
                if score < best_score:
                    best_score = score
                    best_params = params
                    best_metrics = metrics

        if verbose:
            print()  # 换行
            print(f"最佳参数: {best_params}")
            print(f"最佳{self.config.target_metric}: {best_score:.4f}")

        return OptimizationResult(
            parameters=best_params,
            score=best_score,
            metrics=best_metrics
        )

    def random_sampling(self, data: pd.DataFrame,
                        param_bounds: Dict,
                        n_iter: int = 50,
                        verbose: bool = True) -> OptimizationResult:
        """
        边界内均匀随机采样优化（原名 bayesian_optimize）

        审计 E-P1: 旧名 bayesian_optimize 宣称贝叶斯优化但实现是 random.uniform
        均匀随机采样, 无代理模型/采集函数 — 已更名为 random_sampling 诚实化。

        Args:
            data: 股票数据
            param_bounds: 参数边界 {param: (min, max)}
            n_iter: 迭代次数
            verbose: 是否显示进度

        Returns:
            优化结果
        """
        best_params = None
        best_score = -np.inf if self.config.maximize else np.inf
        best_metrics = None

        # 目标函数
        def objective(x):
            # x是参数值数组
            params = {name: x[i] for i, name in enumerate(param_bounds.keys())}

            # 对离散参数取整
            for name in params:
                if isinstance(param_bounds[name][0], int):
                    params[name] = int(params[name])

            # 评估
            metrics = self.evaluate_params(data, params)
            score = metrics.get(self.config.target_metric, 0)

            # 记录最佳
            nonlocal best_score, best_params, best_metrics
            if self.config.maximize:
                if score > best_score:
                    best_score = score
                    best_params = params
                    best_metrics = metrics
            else:
                if score < best_score:
                    best_score = score
                    best_params = params
                    best_metrics = metrics

            # 返回负的分数（因为是最小化）
            return -score if self.config.maximize else score

        # 初始点
        x0 = [param_bounds[name][0] for name in param_bounds.keys()]

        # 边界
        bounds = [param_bounds[name] for name in param_bounds.keys()]

        if verbose:
            print(f"随机采样开始，共 {n_iter} 次迭代")

        # 边界内均匀随机采样
        for i in range(n_iter):
            # 在边界内随机采样
            x = [random.uniform(b[0], b[1]) for b in bounds]

            if verbose:
                print(f"\r进度: {i+1}/{n_iter} ({(i+1)/n_iter*100:.1f}%)", end='')

            objective(x)

        if verbose:
            print()  # 换行
            print(f"最佳参数: {best_params}")
            print(f"最佳{self.config.target_metric}: {best_score:.4f}")

        return OptimizationResult(
            parameters=best_params,
            score=best_score,
            metrics=best_metrics
        )

    # 历史别名 (审计 E-P1 更名前的旧 API 名) — 实现同 random_sampling
    bayesian_optimize = random_sampling

    def optimize(self, data: pd.DataFrame,
                method: str = "grid",
                **kwargs) -> OptimizationResult:
        """
        优化策略参数

        Args:
            data: 股票数据
            method: 优化方法 (grid/random/random_sampling); "bayesian" 为历史名
            **kwargs: 其他参数

        Returns:
            优化结果
        """
        if method == "grid":
            return self.grid_search(data, **kwargs)
        elif method == "random":
            return self.random_search(data, **kwargs)
        elif method in ("random_sampling", "bayesian"):
            # "bayesian" 是 E-P1 更名前的历史分派名, 实现为随机采样
            return self.random_sampling(data, **kwargs)
        else:
            raise ValueError(f"未知优化方法: {method}")


# =============================================================================
# 多策略对比
# =============================================================================

def compare_strategies(data: pd.DataFrame,
                      strategies: List[StrategyTemplate] = None) -> pd.DataFrame:
    """
    对比多个策略

    Args:
        data: 股票数据
        strategies: 策略列表

    Returns:
        对比结果DataFrame
    """
    if strategies is None:
        strategies = [MAStrategy(), MACDStrategy(), RSIStrategy()]

    optimizer = StrategyOptimizer()
    results = []

    for strategy in strategies:
        # 获取默认参数网格
        param_grid = strategy.get_param_grid()

        # 使用第一个参数组合
        first_params = {k: v[0] for k, v in param_grid.items()}

        # 评估
        metrics = optimizer.evaluate_params(data, first_params)

        results.append({
            'strategy': strategy.name,
            'parameters': first_params,
            **metrics
        })

    return pd.DataFrame(results)


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("策略参数优化器 - v1.0")
    print()

    try:
        from stock_data_fetcher import StockDataFetcher

        # 获取测试数据
        fetcher = StockDataFetcher()
        data = fetcher.get_quote_data('600519', days=252)

        if data is not None and len(data) > 0:
            data = fetcher.calculate_technical_indicators(data)

            # 创建优化器
            optimizer = StrategyOptimizer(
                strategy=MAStrategy(),
                config=OptimizationConfig(target_metric="sharpe_ratio")
            )

            print("=" * 60)
            print("网格搜索优化")
            print("=" * 60)

            # 网格搜索
            result = optimizer.grid_search(
                data,
                param_grid={
                    'short_period': [5, 10, 15],
                    'long_period': [20, 30, 40]
                }
            )

            print("\n优化结果:")
            print(f"  参数: {result.parameters}")
            print(f"  夏普比率: {result.score:.4f}")
            print(f"  年化收益: {result.metrics.get('annual_return', 0):.2%}")
            print(f"  最大回撤: {result.metrics.get('max_drawdown', 0):.2%}")
            print(f"  胜率: {result.metrics.get('win_rate', 0):.2%}")

            # 随机搜索
            print("\n" + "=" * 60)
            print("随机搜索优化")
            print("=" * 60)

            result2 = optimizer.random_search(
                data,
                param_grid={
                    'short_period': [5, 10, 15, 20],
                    'long_period': [20, 30, 40, 60]
                },
                n_iter=20
            )

            print("\n优化结果:")
            print(f"  参数: {result2.parameters}")
            print(f"  夏普比率: {result2.score:.4f}")

            print("\n✓ 测试完成！")

        else:
            print("无法获取数据")

    except ImportError as e:
        print(f"✗ 模块未安装: {e}")
        print("请运行: pip install scikit-learn scipy")
    except Exception as e:
        print(f"✗ 测试失败: {e}")
