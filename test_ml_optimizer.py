# -*- coding: utf-8 -*-
"""
ML和优化器测试
ML and Optimizer Test

测试机器学习预测器和策略优化器
"""

import sys
sys.path.append('.')

from datetime import datetime
from ml_predictor import MLPredictor, RegressionPredictor
from strategy_optimizer import (
    StrategyOptimizer,
    MAStrategy,
    MACDStrategy,
    RSIStrategy,
    MultiFactorStrategy,
    compare_strategies
)


def test_ml_predictor():
    """测试机器学习预测器"""
    print("=" * 60)
    print("机器学习预测器测试")
    print("=" * 60)
    print()

    try:
        from stock_data_fetcher import StockDataFetcher

        # 获取数据
        fetcher = StockDataFetcher()
        data = fetcher.get_quote_data('600519', days=500)

        if data is not None and len(data) > 0:
            data = fetcher.calculate_technical_indicators(data)

            print(f"使用 {len(data)} 条数据训练模型...")

            # 创建预测器
            predictor = MLPredictor(model_type="random_forest")

            # 训练
            print("\n训练模型...")
            evaluation = predictor.train(data, test_size=0.2, forward_days=5, threshold=0.02)

            print("\n模型评估:")
            print(f"  准确率: {evaluation.accuracy:.2%}")
            print(f"  精确率: {evaluation.precision:.2%}")
            print(f"  召回率: {evaluation.recall:.2%}")
            print(f"  F1分数: {evaluation.f1_score:.2%}")

            # 特征重要性
            print("\n特征重要性 (Top 10):")
            importance_df = predictor.get_feature_importance(top_n=10)

            for i, row in enumerate(importance_df.itertuples(), 1):
                print(f"  {i}. {row.feature}: {row.importance:.3f}")

            # 预测
            print("\n最新数据预测:")
            result = predictor.predict(data)
            print(f"  预测: {result.prediction}")
            print(f"  概率: {result.probability:.2%}")
            print(f"  置信度: {result.confidence:.2%}")

            # 交叉验证
            print("\n5折交叉验证:")
            cv_scores = predictor.cross_validate(data, cv=5)
            print(f"  平均准确率: {cv_scores['accuracy_mean']:.2%} ± {cv_scores['accuracy_std']:.2%}")

            return True

    except ImportError:
        print("✗ scikit-learn未安装")
        return False
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_regression_predictor():
    """测试回归预测器"""
    print("\n" + "=" * 60)
    print("回归预测器测试（预测涨跌幅）")
    print("=" * 60)
    print()

    try:
        from stock_data_fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        data = fetcher.get_quote_data('600519', days=500)

        if data is not None and len(data) > 0:
            data = fetcher.calculate_technical_indicators(data)

            # 创建回归预测器
            regressor = RegressionPredictor()

            # 训练
            print("训练回归模型...")
            metrics = regressor.train(data, forward_days=5)

            print("\n模型评估:")
            print(f"  MSE: {metrics['mse']:.6f}")
            print(f"  MAE: {metrics['mae']:.6f}")
            print(f"  RMSE: {metrics['rmse']:.6f}")
            print(f"  R²: {metrics['r2_score']:.4f}")

            # 预测收益率
            predicted_return = regressor.predict_return(data)
            print(f"\n预测5日后收益率: {predicted_return:+.2%}")

            return True

    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_strategy_optimizer():
    """测试策略优化器"""
    print("\n" + "=" * 60)
    print("策略优化器测试")
    print("=" * 60)
    print()

    try:
        from stock_data_fetcher import StockDataFetcher

        # 获取数据
        fetcher = StockDataFetcher()
        data = fetcher.get_quote_data('600519', days=500)

        if data is not None and len(data) > 0:
            data = fetcher.calculate_technical_indicators(data)

            # MA策略优化
            print("MA策略网格搜索...")
            optimizer = StrategyOptimizer(
                strategy=MAStrategy(),
                config=OptimizationConfig(target_metric="sharpe_ratio")
            )

            result = optimizer.grid_search(
                data,
                param_grid={
                    'short_period': [5, 10, 15, 20],
                    'long_period': [20, 30, 40, 60]
                }
            )

            print("\n最佳参数:")
            for param, value in result.parameters.items():
                print(f"  {param}: {value}")

            print(f"\n最佳夏普比率: {result.score:.4f}")
            print(f"年化收益: {result.metrics.get('annual_return', 0):.2%}")
            print(f"最大回撤: {result.metrics.get('max_drawdown', 0):.2%}")

            # MACD策略优化
            print("\n" + "-" * 60)
            print("MACD策略随机搜索...")
            optimizer2 = StrategyOptimizer(
                strategy=MACDStrategy(),
                config=OptimizationConfig(target_metric="sharpe_ratio")
            )

            result2 = optimizer2.random_search(
                data,
                param_grid={
                    'fast_period': [8, 12, 16],
                    'slow_period': [20, 26, 32],
                    'signal_period': [6, 9, 12]
                },
                n_iter=10
            )

            print("\n最佳参数:")
            for param, value in result2.parameters.items():
                print(f"  {param}: {value}")

            print(f"\n最佳夏普比率: {result2.score:.4f}")

            # 多策略对比
            print("\n" + "-" * 60)
            print("多策略对比...")
            comparison = compare_strategies(
                data,
                strategies=[MAStrategy(), MACDStrategy(), RSIStrategy()]
            )

            print("\n策略对比结果:")
            print(comparison.to_string(index=False))

            return True

    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


def test_all():
    """运行所有测试"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 18 + "ML和优化器测试" + " " * 30 + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    # 1. ML预测器测试
    ml_success = test_ml_predictor()

    # 2. 回归预测器测试
    reg_success = test_regression_predictor()

    # 3. 策略优化器测试
    opt_success = test_strategy_optimizer()

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"  ML分类预测器: {'✓ 通过' if ml_success else '✗ 失败'}")
    print(f"  回归预测器:    {'✓ 通过' if reg_success else '✗ 失败'}")
    print(f"  策略优化器:    {'✓ 通过' if opt_success else '✗ 失败'}")
    print("=" * 60)


if __name__ == "__main__":
    test_all()
