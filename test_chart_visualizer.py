# -*- coding: utf-8 -*-
"""
测试数据可视化模块
Test Chart Visualizer Module
"""

import sys
import os

# 添加skills目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.claude', 'skills'))
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from chart_visualizer import (
    ChartVisualizer,
    ChartStyle,
    plot_stock_chart
)


def get_test_data(symbol='600519', days=120):
    """获取测试数据"""
    from stock_data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()
    data = fetcher.get_quote_data(symbol, days=days)
    if data is not None:
        data = fetcher.calculate_technical_indicators(data)
    return data


def test_candlestick_chart():
    """测试K线图"""
    print("=" * 70)
    print("[Test 1] Candlestick Chart")
    print("=" * 70)

    data = get_test_data('600519')
    if data is None or len(data) == 0:
        print("Cannot fetch data for 600519")
        return None

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_candlestick(
        data, '600519', title='贵州茅台 K线图', ma_periods=[5, 20, 60]
    )

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_macd_chart():
    """测试MACD图"""
    print("\n" + "=" * 70)
    print("[Test 2] MACD Chart")
    print("=" * 70)

    data = get_test_data('600519')
    if data is None or len(data) == 0:
        print("Cannot fetch data for 600519")
        return None

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_macd(data, '600519')

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_rsi_chart():
    """测试RSI图"""
    print("\n" + "=" * 70)
    print("[Test 3] RSI Chart")
    print("=" * 70)

    data = get_test_data('600519')
    if data is None or len(data) == 0:
        print("Cannot fetch data for 600519")
        return None

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_rsi(data, '600519')

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_bollinger_chart():
    """测试布林带图"""
    print("\n" + "=" * 70)
    print("[Test 4] Bollinger Bands Chart")
    print("=" * 70)

    data = get_test_data('600519')
    if data is None or len(data) == 0:
        print("Cannot fetch data for 600519")
        return None

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_bollinger_bands(data, '600519')

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_equity_curve():
    """测试净值曲线"""
    print("\n" + "=" * 70)
    print("[Test 5] Equity Curve")
    print("=" * 70)

    # 生成模拟净值曲线
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')
    np.random.seed(42)

    # 模拟净值曲线
    initial_value = 100000
    returns = np.random.normal(0.001, 0.02, 120)
    values = initial_value * np.cumprod(1 + returns)

    equity_curve = pd.DataFrame({
        'date': dates,
        'value': values
    })

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_equity_curve(
        equity_curve, '模拟组合', benchmark_return=5.0
    )

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_drawdown_chart():
    """测试回撤曲线"""
    print("\n" + "=" * 70)
    print("[Test 6] Drawdown Chart")
    print("=" * 70)

    # 生成模拟净值曲线
    dates = pd.date_range(end=datetime.now(), periods=120, freq='D')
    np.random.seed(42)

    initial_value = 100000
    returns = np.random.normal(0.001, 0.02, 120)
    values = initial_value * np.cumprod(1 + returns)

    equity_curve = pd.DataFrame({
        'date': dates,
        'value': values
    })

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_drawdown(equity_curve, '模拟组合')

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_signals_chart():
    """测试信号标注图"""
    print("\n" + "=" * 70)
    print("[Test 7] Signals Chart")
    print("=" * 70)

    data = get_test_data('600519')
    if data is None or len(data) == 0:
        print("Cannot fetch data for 600519")
        return None

    # 生成信号
    from signal_generator import SignalGenerator
    generator = SignalGenerator()
    signals = generator.generate_signals(data)

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_signals(data, signals, '600519')

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_combined_chart():
    """测试综合分析图"""
    print("\n" + "=" * 70)
    print("[Test 8] Combined Analysis Chart")
    print("=" * 70)

    data = get_test_data('600519')
    if data is None or len(data) == 0:
        print("Cannot fetch data for 600519")
        return None

    visualizer = ChartVisualizer()
    save_path = visualizer.plot_combined_analysis(data, '600519')

    print(f"\nChart saved to: {save_path}")
    return save_path


def test_batch_charts():
    """测试批量绘图"""
    print("\n" + "=" * 70)
    print("[Test 9] Batch Charts")
    print("=" * 70)

    symbols = ['600519', '000858', '002415']
    visualizer = ChartVisualizer(output_dir="charts/batch")

    for symbol in symbols:
        data = get_test_data(symbol, days=60)
        if data is not None and len(data) > 0:
            try:
                save_path = visualizer.plot_candlestick(data, symbol)
                print(f"  {symbol}: Chart saved")
            except Exception as e:
                print(f"  {symbol}: Failed - {e}")


def test_custom_style():
    """测试自定义样式"""
    print("\n" + "=" * 70)
    print("[Test 10] Custom Style")
    print("=" * 70)

    # 自定义样式
    custom_style = ChartStyle()
    custom_style.up_color = '#00AA00'    # 绿涨红跌
    custom_style.down_color = '#FF4444'
    custom_style.figure_size = (16, 10)

    data = get_test_data('600519')
    if data is None or len(data) == 0:
        print("Cannot fetch data for 600519")
        return None

    visualizer = ChartVisualizer(style=custom_style)
    save_path = visualizer.plot_candlestick(data, '600519', title='自定义样式')

    print(f"\nCustom styled chart saved to: {save_path}")
    return save_path


def main():
    """运行所有测试"""
    print("\n")
    print("#" * 70)
    print("#              Chart Visualizer Test Suite")
    print("#" * 70)
    print("\n")

    # 运行测试
    test_candlestick_chart()
    test_macd_chart()
    test_rsi_chart()
    test_bollinger_chart()
    test_equity_curve()
    test_drawdown_chart()
    test_signals_chart()
    test_combined_chart()
    test_batch_charts()
    test_custom_style()

    print("\n")
    print("#" * 70)
    print("#                    All Tests Completed")
    print("#" * 70)
    print("\n")


if __name__ == "__main__":
    main()
