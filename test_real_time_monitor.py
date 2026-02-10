# -*- coding: utf-8 -*-
"""
测试实时监控模块
Test Real-Time Monitor Module
"""

import sys
import os

# 添加skills目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.claude', 'skills'))
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from real_time_monitor import (
    RealTimeMonitor,
    AlertCondition,
    AlertType,
    AlertPriority,
    create_price_alert,
    create_signal_alert
)


def test_basic_monitoring():
    """测试基础监控功能"""
    print("=" * 70)
    print("[Test 1] Basic Monitoring")
    print("=" * 70)

    monitor = RealTimeMonitor()

    # 添加监控股票
    symbols = ['600519', '000858', '002415']
    for symbol in symbols:
        from stock_list_manager import get_stock_name
        name = get_stock_name(symbol)
        monitor.add_stock(symbol, name)
        print(f"  Added {symbol} {name}")

    print(f"\nMonitoring {len(monitor.stocks)} stocks")

    return monitor


def test_price_alerts():
    """测试价格告警"""
    print("\n" + "=" * 70)
    print("[Test 2] Price Alerts")
    print("=" * 70)

    monitor = RealTimeMonitor()
    monitor.add_stock("600519", "贵州茅台")

    # 添加价格上限告警
    upper_condition = AlertCondition(
        alert_type=AlertType.PRICE_ABOVE,
        threshold=2000,  # 茅台价格不太可能达到
        priority=AlertPriority.HIGH
    )
    monitor.add_condition("600519", upper_condition)

    # 添加价格下限告警
    lower_condition = AlertCondition(
        alert_type=AlertType.PRICE_BELOW,
        threshold=1000,
        priority=AlertPriority.HIGH
    )
    monitor.add_condition("600519", lower_condition)

    print("\nAdded price alert conditions for 600519:")
    print("  Upper: 2000")
    print("  Lower: 1000")

    # 检查条件
    alerts = monitor.check_conditions("600519")
    print(f"\nTriggered alerts: {len(alerts)}")

    for alert in alerts:
        print(f"  {alert.message}")

    return monitor


def test_change_alerts():
    """测试涨跌幅告警"""
    print("\n" + "=" * 70)
    print("[Test 3] Change Alerts")
    print("=" * 70)

    monitor = RealTimeMonitor()
    monitor.add_stock("600519", "贵州茅台")

    # 添加涨幅告警
    up_condition = AlertCondition(
        alert_type=AlertType.CHANGE_UP,
        threshold=5,  # 涨幅超过5%
        priority=AlertPriority.MEDIUM
    )
    monitor.add_condition("600519", up_condition)

    # 添加跌幅告警
    down_condition = AlertCondition(
        alert_type=AlertType.CHANGE_DOWN,
        threshold=3,  # 跌幅超过3%
        priority=AlertPriority.HIGH
    )
    monitor.add_condition("600519", down_condition)

    print("\nAdded change alert conditions for 600519:")
    print("  Up: >5%")
    print("  Down: >-3%")

    # 检查条件
    alerts = monitor.check_conditions("600519")
    print(f"\nTriggered alerts: {len(alerts)}")

    return monitor


def test_breakout_alerts():
    """测试突破告警"""
    print("\n" + "=" * 70)
    print("[Test 4] Breakout Alerts")
    print("=" * 70)

    monitor = RealTimeMonitor()
    monitor.add_stock("600519", "贵州茅台")

    # 添加突破60日高点告警
    high_condition = AlertCondition(
        alert_type=AlertType.BREAKOUT_HIGH,
        period=60,
        priority=AlertPriority.MEDIUM
    )
    monitor.add_condition("600519", high_condition)

    # 添加跌破60日低点告警
    low_condition = AlertCondition(
        alert_type=AlertType.BREAKOUT_LOW,
        period=60,
        priority=AlertPriority.HIGH
    )
    monitor.add_condition("600519", low_condition)

    print("\nAdded breakout alert conditions for 600519:")
    print("  60-day high breakout")
    print("  60-day low breakdown")

    # 检查条件
    alerts = monitor.check_conditions("600519")
    print(f"\nTriggered alerts: {len(alerts)}")

    return monitor


def test_signal_alerts():
    """测试信号告警"""
    print("\n" + "=" * 70)
    print("[Test 5] Signal Alerts")
    print("=" * 70)

    monitor = create_signal_alert("600519")

    print("\nAdded signal alert conditions for 600519:")
    print("  Buy signal")
    print("  Sell signal")

    # 检查条件
    alerts = monitor.check_conditions("600519")
    print(f"\nTriggered alerts: {len(alerts)}")

    for alert in alerts:
        print(f"  {alert.message}")

    return monitor


def test_volume_alerts():
    """测试成交量告警"""
    print("\n" + "=" * 70)
    print("[Test 6] Volume Alerts")
    print("=" * 70)

    monitor = RealTimeMonitor()
    monitor.add_stock("600519", "贵州茅台")

    # 添加成交量放大告警
    volume_condition = AlertCondition(
        alert_type=AlertType.VOLUME_SURGE,
        threshold=2.0,  # 成交量放大2倍
        priority=AlertPriority.MEDIUM
    )
    monitor.add_condition("600519", volume_condition)

    print("\nAdded volume surge alert for 600519:")
    print("  Volume > 2x average")

    # 检查条件
    alerts = monitor.check_conditions("600519")
    print(f"\nTriggered alerts: {len(alerts)}")

    return monitor


def test_monitor_multiple_stocks():
    """测试多股票监控"""
    print("\n" + "=" * 70)
    print("[Test 7] Monitor Multiple Stocks")
    print("=" * 70)

    monitor = RealTimeMonitor()

    # 添加多只股票
    stocks = [
        ('600519', '贵州茅台'),
        ('000858', '五粮液'),
        ('002415', '海康威视')
    ]

    for symbol, name in stocks:
        monitor.add_stock(symbol, name)
        # 添加价格告警
        condition = AlertCondition(
            alert_type=AlertType.SIGNAL_BUY,
            priority=AlertPriority.LOW
        )
        monitor.add_condition(symbol, condition)

    print(f"\nMonitoring {len(monitor.stocks)} stocks")

    # 检查所有股票
    all_alerts = monitor.check_all_stocks()

    print("\nAlerts by stock:")
    for symbol, alerts in all_alerts.items():
        print(f"  {symbol}: {len(alerts)} alerts")

    return monitor


def test_alert_history():
    """测试告警历史"""
    print("\n" + "=" * 70)
    print("[Test 8] Alert History")
    print("=" * 70)

    monitor = RealTimeMonitor()
    monitor.add_stock("600519", "贵州茅台")

    # 添加条件并检查
    condition = AlertCondition(
        alert_type=AlertType.CHANGE_UP,
        threshold=5
    )
    monitor.add_condition("600519", condition)

    # 触发一些检查
    monitor.check_conditions("600519")

    # 获取告警历史
    alerts = monitor.get_alert_history(limit=10)

    print(f"\nAlert history: {len(alerts)} alerts")

    for alert in alerts[:5]:
        print(f"  {alert.timestamp.strftime('%H:%M:%S')} - {alert.message}")

    # 标记为已读
    if alerts:
        monitor.mark_as_read(alerts[0].id)
        print("\nMarked first alert as read")

    unread = monitor.get_alert_history(unread_only=True)
    print(f"Unread alerts: {len(unread)}")

    return monitor


def test_monitor_report():
    """测试监控报告"""
    print("\n" + "=" * 70)
    print("[Test 9] Monitor Report")
    print("=" * 70)

    monitor = RealTimeMonitor()

    # 添加监控股票
    stocks = ['600519', '000858', '002415']
    for symbol in stocks:
        from stock_list_manager import get_stock_name
        name = get_stock_name(symbol)
        monitor.add_stock(symbol, name)
        condition = AlertCondition(
            alert_type=AlertType.SIGNAL_BUY,
            priority=AlertPriority.LOW
        )
        monitor.add_condition(symbol, condition)

    # 生成报告
    report = monitor.generate_monitor_report()
    print(report)

    return monitor


def test_save_load():
    """测试保存和加载"""
    print("\n" + "=" * 70)
    print("[Test 10] Save and Load")
    print("=" * 70)

    monitor = RealTimeMonitor()
    monitor.add_stock("600519", "贵州茅台")

    condition = AlertCondition(
        alert_type=AlertType.PRICE_ABOVE,
        threshold=2000
    )
    monitor.add_condition("600519", condition)

    # 保存
    filepath = "monitor_data/test_monitor.json"
    success = monitor.save_monitor_data(filepath)
    print(f"\nSave monitor data: {'Success' if success else 'Failed'}")

    # 加载到新管理器
    new_monitor = RealTimeMonitor()
    load_success = new_monitor.load_monitor_data(filepath)
    print(f"Load monitor data: {'Success' if load_success else 'Failed'}")

    if load_success:
        print(f"\nLoaded stocks: {len(new_monitor.stocks)}")
        for symbol, stock in new_monitor.stocks.items():
            print(f"  {symbol} {stock.name}: {len(stock.conditions)} conditions")

    return monitor


def test_alert_callback():
    """测试告警回调"""
    print("\n" + "=" * 70)
    print("[Test 11] Alert Callback")
    print("=" * 70)

    monitor = RealTimeMonitor()
    monitor.add_stock("600519", "贵州茅台")

    # 注册回调
    callback_count = [0]

    def my_callback(alert):
        callback_count[0] += 1
        print(f"  [Callback] {alert.message}")

    monitor.register_callback(my_callback)

    # 添加条件
    condition = AlertCondition(
        alert_type=AlertType.CHANGE_UP,
        threshold=5
    )
    monitor.add_condition("600519", condition)

    # 检查条件
    print("\nChecking conditions (with callback)...")
    monitor.check_conditions("600519")

    print(f"\nCallback triggered: {callback_count[0]} times")

    return monitor


def test_monitor_status():
    """测试监控状态"""
    print("\n" + "=" * 70)
    print("[Test 12] Monitor Status")
    print("=" * 70)

    monitor = RealTimeMonitor()

    # 添加多只股票和条件
    stocks = ['600519', '000858', '002415']
    for symbol in stocks:
        from stock_list_manager import get_stock_name
        name = get_stock_name(symbol)
        monitor.add_stock(symbol, name)

        # 添加多个条件
        conditions = [
            AlertCondition(alert_type=AlertType.SIGNAL_BUY),
            AlertCondition(alert_type=AlertType.SIGNAL_SELL),
            AlertCondition(alert_type=AlertType.CHANGE_UP, threshold=5)
        ]
        for condition in conditions:
            monitor.add_condition(symbol, condition)

    # 获取状态
    status = monitor.get_monitor_status()

    print("\nMonitor Status:")
    print(f"  Total Stocks: {status['total_stocks']}")
    print(f"  Total Conditions: {status['total_conditions']}")
    print(f"  Total Alerts: {status['total_alerts']}")
    print(f"  Unread Alerts: {status['unread_alerts']}")

    print("\nStocks:")
    for stock in status['stocks']:
        print(f"  {stock['symbol']} {stock['name']}: {stock['conditions']} conditions")

    return monitor


def main():
    """运行所有测试"""
    print("\n")
    print("#" * 70)
    print("#              Real-Time Monitor Test Suite")
    print("#" * 70)
    print("\n")

    # 运行测试
    test_basic_monitoring()
    test_price_alerts()
    test_change_alerts()
    test_breakout_alerts()
    test_signal_alerts()
    test_volume_alerts()
    test_monitor_multiple_stocks()
    test_alert_history()
    test_monitor_report()
    test_save_load()
    test_alert_callback()
    test_monitor_status()

    print("\n")
    print("#" * 70)
    print("#                    All Tests Completed")
    print("#" * 70)
    print("\n")


if __name__ == "__main__":
    main()
