# -*- coding: utf-8 -*-
"""
测试增强版多因子选股系统
Test Enhanced Multi-Factor Selection System
"""

import sys
import os

# 添加skills目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.claude', 'skills'))
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 导入增强版多因子选股模块
from multi_factor_selection import (
    MultiFactorSelector,
    FactorEffectivenessTester,
    FactorWeightingMethod,
    PortfolioOptimizer,
    FactorTestResult,
    multi_factor_select,
    test_factor_effectiveness,
    optimize_portfolio_markowitz,
    optimize_portfolio_risk_parity
)


def generate_test_financial_data(n_stocks=100):
    """生成测试财务数据"""
    np.random.seed(42)

    symbols = [f'{i:06d}' for i in range(600000, 600000 + n_stocks)]

    data = pd.DataFrame({
        'code': symbols,
        '市盈率-动态': np.random.uniform(5, 50, n_stocks),
        '市净率': np.random.uniform(0.5, 10, n_stocks),
        '市销率': np.random.uniform(1, 20, n_stocks),
        '市现率': np.random.uniform(3, 30, n_stocks),
        '股息率': np.random.uniform(0, 0.08, n_stocks),
        '营业总收入同比增长': np.random.uniform(-0.2, 0.5, n_stocks),
        '净利润同比增长': np.random.uniform(-0.3, 0.6, n_stocks),
        '净资产收益率': np.random.uniform(0.01, 0.3, n_stocks),
        '总资产净利率': np.random.uniform(0.01, 0.2, n_stocks),
        '销售毛利率': np.random.uniform(0.1, 0.5, n_stocks),
        '销售净利率': np.random.uniform(0.02, 0.3, n_stocks),
        '资产负债率': np.random.uniform(0.2, 0.8, n_stocks),
        '流动比率': np.random.uniform(0.5, 3.0, n_stocks),
        '速动比率': np.random.uniform(0.3, 2.0, n_stocks),
    })

    data = data.set_index('code')
    return data


def generate_test_price_data(n_stocks=100, days=252):
    """生成测试价格数据"""
    np.random.seed(42)

    symbols = [f'{i:06d}' for i in range(600000, 600000 + n_stocks)]
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')

    price_data = {}

    for symbol in symbols:
        # 生成价格序列
        returns = np.random.normal(0.001, 0.02, days)
        prices = 100 * np.cumprod(1 + returns)

        df = pd.DataFrame({
            '日期': dates,
            '开盘': prices * (1 + np.random.uniform(-0.01, 0.01, days)),
            '最高': prices * (1 + np.random.uniform(0, 0.02, days)),
            '最低': prices * (1 - np.random.uniform(0, 0.02, days)),
            '收盘': prices,
            '成交量': np.random.randint(1000000, 10000000, days)
        })
        price_data[symbol] = df

    return price_data


def test_basic_selection():
    """测试基础选股功能"""
    print("=" * 80)
    print("[Test 1] Basic Multi-Factor Selection")
    print("=" * 80)

    # 生成测试数据
    financial_df = generate_test_financial_data(50)

    # 创建选股器
    selector = MultiFactorSelector(weighting_method='equal')

    # 计算因子
    factors_df = selector.calculate_factors(financial_df)

    print(f"\nCalculated {len(factors_df.columns)} factor types:")
    for col in factors_df.columns:
        print(f"  - {col}")

    # 选股
    selected = selector.select_stocks(financial_df, top_n=10)

    print(f"\nTop 10 selected stocks:")
    print(selected[['Composite_Score']].head(10))

    return selected


def test_weighting_methods():
    """测试不同加权方法"""
    print("\n" + "=" * 80)
    print("[Test 2] Factor Weighting Methods Comparison")
    print("=" * 80)

    financial_df = generate_test_financial_data(50)

    # 生成价格数据用于计算收益率
    price_data = generate_test_price_data(50, days=120)

    # 计算综合收益率
    returns = pd.Series()
    for symbol, df in price_data.items():
        symbol_return = df['收盘'].pct_change().iloc[-1]
        returns[symbol] = symbol_return

    methods = ['equal', 'ic', 'max_sharpe', 'risk_parity']

    results = {}
    for method in methods:
        selector = MultiFactorSelector(weighting_method=method)
        selected = selector.select_stocks(financial_df, top_n=10, returns=returns)
        results[method] = selected['Composite_Score'].mean()
        print(f"\n{method:15s}: Avg Score = {results[method]:.4f}")

    return results


def test_factor_effectiveness():
    """测试因子有效性"""
    print("\n" + "=" * 80)
    print("[Test 3] Factor Effectiveness Testing")
    print("=" * 80)

    financial_df = generate_test_financial_data(50)
    price_data = generate_test_price_data(50, days=120)

    # 创建选股器并计算因子
    selector = MultiFactorSelector()
    factors_df = selector.calculate_factors(financial_df)

    # 计算收益率
    returns_list = []
    for symbol in factors_df.index:
        if symbol in price_data:
            symbol_return = price_data[symbol]['收盘'].pct_change().iloc[-1]
            returns_list.append(symbol_return)
        else:
            returns_list.append(0)

    returns = pd.Series(returns_list, index=factors_df.index)

    # 测试因子有效性
    test_results = selector.test_factor_effectiveness(factors_df, returns)

    # 生成报告
    report = tester = FactorEffectivenessTester.generate_test_report(test_results)
    print(report)

    return test_results


def test_portfolio_optimization():
    """测试组合优化"""
    print("\n" + "=" * 80)
    print("[Test 4] Portfolio Optimization")
    print("=" * 80)

    # 生成收益率数据
    n_assets = 10
    days = 252
    np.random.seed(42)

    symbols = [f'STOCK_{i}' for i in range(n_assets)]
    returns_df = pd.DataFrame(
        np.random.normal(0.001, 0.02, (days, n_assets)),
        index=pd.date_range(end=datetime.now(), periods=days, freq='D'),
        columns=symbols
    )

    # 测试不同优化方法
    optimizer = PortfolioOptimizer()

    print("\n1. Equal Weights:")
    weights = optimizer.equal_weights(symbols)
    print({k: f"{v:.3f}" for k, v in list(weights.items())[:5]})

    print("\n2. Inverse Volatility Weights:")
    weights = optimizer.inverse_volatility_weights(returns_df)
    print({k: f"{v:.3f}" for k, v in list(weights.items())[:5]})

    print("\n3. Risk Parity Weights:")
    weights = optimizer.equal_risk_contribution(returns_df)
    print({k: f"{v:.3f}" for k, v in list(weights.items())[:5]})

    print("\n4. Markowitz Optimization (Max Sharpe):")
    expected_returns = returns_df.mean() * 252
    cov_matrix = returns_df.cov() * 252
    result = optimizer.markowitz_optimization(expected_returns, cov_matrix)
    print(f"Expected Return: {result['expected_return']:.4f}")
    print(f"Expected Std: {result['expected_std']:.4f}")
    print(f"Sharpe Ratio: {result['sharpe_ratio']:.4f}")

    return result


def test_smart_beta_strategies():
    """测试Smart Beta策略"""
    print("\n" + "=" * 80)
    print("[Test 5] Smart Beta Strategies")
    print("=" * 80)

    # 生成测试数据
    n_stocks = 50
    financial_df = generate_test_financial_data(n_stocks)
    price_data = generate_test_price_data(n_stocks, days=120)

    # 计算动量
    momentum_scores = pd.Series()
    for symbol, df in price_data.items():
        momentum = (df['收盘'].iloc[-1] / df['收盘'].iloc[0] - 1)
        momentum_scores[symbol] = momentum

    # 高股息策略
    print("\nHigh Dividend Strategy:")
    high_div = financial_df['股息率'].nlargest(10)
    print(high_div.head(5))

    # 质量因子策略
    print("\nQuality Factor Strategy (ROE):")
    high_roe = financial_df['净资产收益率'].nlargest(10)
    print(high_roe.head(5))

    # 动量策略
    print("\nMomentum Strategy:")
    high_momentum = momentum_scores.nlargest(10)
    print(high_momentum.head(5))

    return {
        'high_dividend': high_div,
        'high_roe': high_roe,
        'high_momentum': high_momentum
    }


def test_factor_contribution_analysis():
    """测试因子贡献分析"""
    print("\n" + "=" * 80)
    print("[Test 6] Factor Contribution Analysis")
    print("=" * 80)

    financial_df = generate_test_financial_data(50)
    price_data = generate_test_price_data(50, days=120)

    selector = MultiFactorSelector()

    # 分析一只股票的因子贡献
    test_stock = financial_df.index[0]
    analysis = selector.analyze_factor_contributions(test_stock, financial_df)

    print(f"\nStock: {analysis['stock_code']}")
    print(f"Composite Score: {analysis['composite_score']:.4f}")
    print("\nFactor Contributions:")
    for factor, data in analysis['factor_contributions'].items():
        print(f"  {factor:15s}: Score={data['score']:7.3f}, Weight={data['weight']:.2f}, Contribution={data['contribution']:7.3f}")

    return analysis


def main():
    """运行所有测试"""
    print("\n")
    print("#" * 80)
    print("#           Enhanced Multi-Factor Selection Test Suite")
    print("#" * 80)
    print("\n")

    # 运行测试
    test_basic_selection()
    test_weighting_methods()
    test_factor_effectiveness()
    test_portfolio_optimization()
    test_smart_beta_strategies()
    test_factor_contribution_analysis()

    print("\n")
    print("#" * 80)
    print("#                    All Tests Completed")
    print("#" * 80)
    print("\n")


if __name__ == "__main__":
    main()
