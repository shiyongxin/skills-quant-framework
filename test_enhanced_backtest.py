# -*- coding: utf-8 -*-
"""
测试增强版回测框架
Test Enhanced Backtesting Framework
"""

import sys
import os

# 添加skills目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.claude', 'skills'))
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 导入增强版回测框架
from backtest_framework import (
    BacktestEngine,
    StrategyFactory,
    PositionConfig,
    PositionSizingMethod,
    StopLossMethod,
    PerformanceReport,
    get_conservative_config,
    get_balanced_config,
    get_aggressive_config,
    run_backtest
)

# 导入数据获取模块
from stock_data_fetcher import StockDataFetcher


def generate_test_data(days=252):
    """生成测试数据"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')

    # 生成随机价格数据
    np.random.seed(42)
    returns = np.random.normal(0.001, 0.02, days)
    prices = 100 * np.cumprod(1 + returns)

    data = pd.DataFrame({
        '日期': dates,
        '开盘': prices * (1 + np.random.uniform(-0.01, 0.01, days)),
        '最高': prices * (1 + np.random.uniform(0, 0.02, days)),
        '最低': prices * (1 - np.random.uniform(0, 0.02, days)),
        '收盘': prices,
        '成交量': np.random.randint(1000000, 10000000, days)
    })

    return data


def test_basic_backtest():
    """测试基础回测功能"""
    print("=" * 70)
    print("[Test 1] Basic Backtest - MA Cross Strategy")
    print("=" * 70)

    # 生成测试数据
    data = generate_test_data(252)

    # 创建策略
    strategy = StrategyFactory.ma_cross(fast=5, slow=20)

    # 运行回测
    config = get_balanced_config()
    engine = BacktestEngine(initial_cash=100000, position_config=config)
    results = engine.run(data, strategy, "TEST")

    # 生成报告
    PerformanceReport.generate_report(results, 'standard')

    return results


def test_position_sizing():
    """测试不同持仓规模方法"""
    print("\n" + "=" * 70)
    print("[Test 2] Position Sizing Methods Comparison")
    print("=" * 70)

    data = generate_test_data(252)
    strategy = StrategyFactory.ma_cross(fast=5, slow=20)

    methods = [
        ("Fixed Amount (50000)", PositionConfig(
            sizing_method=PositionSizingMethod.FIXED_AMOUNT,
            sizing_value=50000
        )),
        ("Percent Equity (80%)", PositionConfig(
            sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
            sizing_value=0.8
        )),
        ("Fixed Shares (1000)", PositionConfig(
            sizing_method=PositionSizingMethod.FIXED_SHARES,
            sizing_value=1000
        )),
    ]

    results_list = []
    names = []

    for name, config in methods:
        engine = BacktestEngine(initial_cash=100000, position_config=config)
        result = engine.run(data, strategy, "TEST")
        results_list.append(result)
        names.append(name)
        print(f"\n{name}:")
        print(f"  Return: {result['total_return']:.2f}%")
        print(f"  Trades: {result['trade_count']}")

    # 比较报告
    print("\n" + PerformanceReport.compare_strategies(results_list, names))

    return results_list


def test_stop_loss_methods():
    """测试不同止损方法"""
    print("\n" + "=" * 70)
    print("[Test 3] Stop Loss Methods Comparison")
    print("=" * 70)

    # 添加ATR到数据
    data = generate_test_data(500)
    data['ATR'] = data['最高'] - data['最低']
    data['ATR'] = data['ATR'].rolling(14).mean()

    strategy = StrategyFactory.ma_cross(fast=5, slow=20)

    methods = [
        ("No Stop Loss", PositionConfig(
            sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
            sizing_value=0.9,
            stop_loss_method=StopLossMethod.PERCENTAGE,
            stop_loss_pct=1.0  # 100% = 实际不触发
        )),
        ("5% Stop Loss", PositionConfig(
            sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
            sizing_value=0.9,
            stop_loss_method=StopLossMethod.PERCENTAGE,
            stop_loss_pct=0.05
        )),
        ("Trailing 5%", PositionConfig(
            sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
            sizing_value=0.9,
            stop_loss_method=StopLossMethod.TRAILING,
            trailing_stop_pct=0.05
        )),
    ]

    results_list = []
    names = []

    for name, config in methods:
        engine = BacktestEngine(initial_cash=100000, position_config=config)
        result = engine.run(data, strategy, "TEST")
        results_list.append(result)
        names.append(name)

    print("\n" + PerformanceReport.compare_strategies(results_list, names))

    return results_list


def test_strategy_comparison():
    """测试多策略对比"""
    print("\n" + "=" * 70)
    print("[Test 4] Strategy Comparison")
    print("=" * 70)

    data = generate_test_data(252)

    strategies = [
        ("MA Cross(5,20)", StrategyFactory.ma_cross(fast=5, slow=20)),
        ("MA Cross(10,30)", StrategyFactory.ma_cross(fast=10, slow=30)),
        ("MACD Cross", StrategyFactory.macd_cross()),
        ("RSI OB/OS", StrategyFactory.rsi_overbought_oversold()),
        ("Bollinger", StrategyFactory.bollinger_bands()),
    ]

    results_list = []
    names = []

    for name, strategy in strategies:
        config = get_balanced_config()
        engine = BacktestEngine(initial_cash=100000, position_config=config)
        result = engine.run(data, strategy, "TEST")
        results_list.append(result)
        names.append(name)

    print("\n" + PerformanceReport.compare_strategies(results_list, names))

    return results_list


def test_real_stock_backtest():
    """测试真实股票回测"""
    print("\n" + "=" * 70)
    print("[Test 5] Real Stock Backtest - 600519")
    print("=" * 70)

    try:
        fetcher = StockDataFetcher()
        data = fetcher.get_quote_data('600519', days=252)

        if data is not None and len(data) > 50:
            # 计算技术指标
            data = fetcher.calculate_technical_indicators(data)

            # 测试不同策略
            strategies = [
                ("MA 5/20", StrategyFactory.ma_cross(5, 20)),
                ("MA 10/30", StrategyFactory.ma_cross(10, 30)),
                ("MACD", StrategyFactory.macd_cross()),
            ]

            results_list = []
            names = []

            for name, strategy in strategies:
                config = get_balanced_config()
                engine = BacktestEngine(initial_cash=100000, position_config=config)
                result = engine.run(data, strategy, '600519')
                results_list.append(result)
                names.append(name)

            print("\n" + PerformanceReport.compare_strategies(results_list, names))

            return results_list
        else:
            print("Cannot fetch sufficient data for 600519")
            return None

    except Exception as e:
        print(f"Error in real stock backtest: {e}")
        return None


def test_report_types():
    """测试不同报告类型"""
    print("\n" + "=" * 70)
    print("[Test 6] Report Types")
    print("=" * 70)

    data = generate_test_data(252)
    strategy = StrategyFactory.ma_cross(fast=5, slow=20)

    engine = BacktestEngine(initial_cash=100000)
    results = engine.run(data, strategy, "TEST")

    print("\n--- Summary Report ---")
    PerformanceReport.generate_report(results, 'summary')

    print("\n--- Standard Report ---")
    PerformanceReport.generate_report(results, 'standard')

    print("\n--- Detailed Report ---")
    PerformanceReport.generate_report(results, 'detailed')

    return results


def main():
    """运行所有测试"""
    print("\n")
    print("#" * 70)
    print("#           Enhanced Backtesting Framework Test Suite")
    print("#" * 70)
    print("\n")

    # 运行测试
    test_basic_backtest()
    test_position_sizing()
    test_stop_loss_methods()
    test_strategy_comparison()
    test_report_types()
    test_real_stock_backtest()

    print("\n")
    print("#" * 70)
    print("#                    All Tests Completed")
    print("#" * 70)
    print("\n")


if __name__ == "__main__":
    main()
