# -*- coding: utf-8 -*-
"""
测试组合管理模块
Test Portfolio Manager Module
"""

import sys
import os

# 添加skills目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.claude', 'skills'))
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
from datetime import datetime

from portfolio_manager import (
    PortfolioManager,
    Portfolio,
    Position,
    RebalanceMethod,
    create_portfolio,
    add_position_to_portfolio,
    get_portfolio_report
)


def test_create_portfolio():
    """测试创建组合"""
    print("=" * 70)
    print("[Test 1] Create Portfolio")
    print("=" * 70)

    manager = PortfolioManager()
    portfolio = manager.create_portfolio("test_portfolio", initial_cash=100000)

    print(f"\nCreated portfolio: {portfolio.name}")
    print(f"  Initial Cash: {portfolio.initial_cash:,.2f}")
    print(f"  Current Cash: {portfolio.cash:,.2f}")
    print(f"  Total Value: {portfolio.total_value:,.2f}")

    assert portfolio.name == "test_portfolio"
    assert portfolio.initial_cash == 100000
    assert portfolio.cash == 100000

    return portfolio


def test_add_positions():
    """测试添加持仓"""
    print("\n" + "=" * 70)
    print("[Test 2] Add Positions")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("test_portfolio", initial_cash=100000)

    # 添加持仓
    symbols = ['600519', '000858', '002415']
    names = ['贵州茅台', '五粮液', '海康威视']

    for symbol, name in zip(symbols, names):
        success = manager.add_position(
            portfolio_name="test_portfolio",
            symbol=symbol,
            name=name,
            shares=100,
            price=100
        )
        print(f"  Added {symbol} {name}: {'Success' if success else 'Failed'}")
        assert success

    # 检查组合
    portfolio = manager.get_portfolio("test_portfolio")
    print(f"\n  Position Count: {len(portfolio.positions)}")
    print(f"  Remaining Cash: {portfolio.cash:,.2f}")
    print(f"  Total Value: {portfolio.total_value:,.2f}")

    assert len(portfolio.positions) == 3
    assert portfolio.cash < 100000

    return portfolio


def test_update_prices():
    """测试更新价格"""
    print("\n" + "=" * 70)
    print("[Test 3] Update Prices")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("test_portfolio", initial_cash=100000)

    # 添加持仓
    manager.add_position("test_portfolio", "600519", "贵州茅台", 100, 100)
    manager.add_position("test_portfolio", "000858", "五粮液", 100, 100)

    # 更新价格
    price_dict = {
        '600519': 110,  # 上涨10%
        '000858': 95    # 下跌5%
    }

    manager.update_prices("test_portfolio", price_dict)

    # 检查结果
    portfolio = manager.get_portfolio("test_portfolio")

    print("\nPrice Update Results:")
    for symbol, position in portfolio.positions.items():
        print(f"  {symbol}: {position.cost_price:.2f} -> {position.current_price:.2f} "
              f"({position.profit_loss_pct:+.2f}%)")

    assert portfolio.positions['600519'].profit_loss_pct > 0
    assert portfolio.positions['000858'].profit_loss_pct < 0

    return portfolio


def test_rebalance():
    """测试组合再平衡"""
    print("\n" + "=" * 70)
    print("[Test 4] Portfolio Rebalance")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("test_portfolio", initial_cash=100000)

    # 添加不等权重持仓
    manager.add_position("test_portfolio", "600519", "贵州茅台", 200, 100)
    manager.add_position("test_portfolio", "000858", "五粮液", 100, 100)

    portfolio = manager.get_portfolio("test_portfolio")

    print("\nCurrent Weights:")
    for symbol, position in portfolio.positions.items():
        print(f"  {symbol}: {position.weight*100:.1f}%")

    # 计算再平衡建议（目标等权重）
    total_value = portfolio.total_value
    target_count = len(portfolio.positions) + 1  # 包括现金
    target_weight = 1.0 / target_count

    target_weights = {
        '600519': target_weight,
        '000858': target_weight
    }

    adjustments = manager.rebalance(
        "test_portfolio",
        target_weights,
        RebalanceMethod.TARGET_WEIGHTS
    )

    print("\nRebalance Suggestions:")
    for symbol, shares in adjustments.items():
        action = "Buy" if shares > 0 else "Sell"
        print(f"  {symbol}: {action} {abs(shares)} shares")

    return adjustments


def test_performance_report():
    """测试绩效报告"""
    print("\n" + "=" * 70)
    print("[Test 5] Performance Report")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("my_portfolio", initial_cash=100000)

    # 添加持仓
    manager.add_position("my_portfolio", "600519", "贵州茅台", 100, 100)
    manager.add_position("my_portfolio", "000858", "五粮液", 200, 50)
    manager.add_position("my_portfolio", "002415", "海康威视", 500, 30)

    # 更新价格
    price_dict = {
        '600519': 110,
        '000858': 55,
        '002415': 28
    }
    manager.update_prices("my_portfolio", price_dict)

    # 生成报告
    performance = manager.get_performance("my_portfolio")

    print("\nPortfolio Performance:")
    print(f"  Total Value:     {performance['total_value']:,.2f}")
    print(f"  Total Return:    {performance['total_return']:+.2f}%")
    print(f"  Profit/Loss:     {performance['total_profit_loss']:+,.2f}")
    print(f"  Cash:            {performance['cash']:,.2f}")

    print("\nPositions:")
    for pos in performance['positions']:
        print(f"  {pos['symbol']} {pos['name']}: "
              f"{pos['shares']} shares @ {pos['cost_price']:.2f}, "
              "P/L: {pos['profit_loss_pct']:+.2f}%")

    return performance


def test_risk_metrics():
    """测试风险指标"""
    print("\n" + "=" * 70)
    print("[Test 6] Risk Metrics")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("test_portfolio", initial_cash=100000)

    # 添加持仓
    manager.add_position("test_portfolio", "600519", "贵州茅台", 100, 100)
    manager.add_position("test_portfolio", "000858", "五粮液", 100, 100)
    manager.add_position("test_portfolio", "002415", "海康威视", 100, 100)

    # 获取风险指标
    risk_metrics = manager.get_risk_metrics("test_portfolio")

    print("\nRisk Metrics:")
    print(f"  Position Count:       {risk_metrics['position_count']}")
    print(f"  Max Position:         {risk_metrics['max_position']:.2f}%")
    print(f"  Top10 Concentration:  {risk_metrics['top10_concentration']:.2f}%")
    print(f"  HHI:                  {risk_metrics['hhi']:.0f}")
    print(f"  Cash Ratio:           {risk_metrics['cash_ratio']:.2f}%")

    # 风险评估
    print("\nRisk Assessment:")
    if risk_metrics['max_position'] > 20:
        print("  - High concentration in single position")
    if risk_metrics['hhi'] > 1000:
        print("  - High portfolio concentration")
    if risk_metrics['cash_ratio'] < 5:
        print("  - Low cash reserve")

    return risk_metrics


def test_remove_position():
    """测试移除持仓"""
    print("\n" + "=" * 70)
    print("[Test 7] Remove Position")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("test_portfolio", initial_cash=100000)

    # 添加持仓
    manager.add_position("test_portfolio", "600519", "贵州茅台", 100, 100)
    manager.add_position("test_portfolio", "000858", "五粮液", 100, 100)

    portfolio_before = manager.get_portfolio("test_portfolio")
    print(f"\nBefore: {len(portfolio_before.positions)} positions, Cash: {portfolio_before.cash:,.2f}")

    # 部分卖出
    manager.remove_position("test_portfolio", "600519", shares=50, price=110)

    portfolio_after = manager.get_portfolio("test_portfolio")
    print(f"After partial sell: {len(portfolio_after.positions)} positions, Cash: {portfolio_after.cash:,.2f}")

    # 全部卖出
    manager.remove_position("test_portfolio", "600519", price=110)

    portfolio_final = manager.get_portfolio("test_portfolio")
    print(f"After full sell: {len(portfolio_final.positions)} positions, Cash: {portfolio_final.cash:,.2f}")

    assert len(portfolio_final.positions) == 1
    assert '600519' not in portfolio_final.positions

    return portfolio_final


def test_save_load_portfolio():
    """测试保存和加载组合"""
    print("\n" + "=" * 70)
    print("[Test 8] Save and Load Portfolio")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("test_save", initial_cash=100000)

    # 添加持仓
    manager.add_position("test_save", "600519", "贵州茅台", 100, 100)
    manager.add_position("test_save", "000858", "五粮液", 100, 100)

    # 保存
    filepath = "portfolio_data/test_save.json"
    success = manager.save_portfolio("test_save", filepath)
    print(f"\nSave portfolio: {'Success' if success else 'Failed'}")

    # 加载到新管理器
    new_manager = PortfolioManager()
    loaded_portfolio = new_manager.load_portfolio(filepath, "loaded_portfolio")

    print(f"\nLoaded portfolio: {loaded_portfolio.name}")
    print(f"  Position Count: {len(loaded_portfolio.positions)}")
    print(f"  Total Value: {loaded_portfolio.total_value:,.2f}")

    assert loaded_portfolio is not None
    assert len(loaded_portfolio.positions) == 2

    return loaded_portfolio


def test_report_generation():
    """测试报告生成"""
    print("\n" + "=" * 70)
    print("[Test 9] Report Generation")
    print("=" * 70)

    manager = PortfolioManager()
    manager.create_portfolio("demo", initial_cash=100000)

    # 添加持仓
    manager.add_position("demo", "600519", "贵州茅台", 100, 100)
    manager.add_position("demo", "000858", "五粮液", 200, 50)
    manager.add_position("demo", "002415", "海康威视", 500, 30)

    # 更新价格
    price_dict = {
        '600519': 110,
        '000858': 55,
        '002415': 28
    }
    manager.update_prices("demo", price_dict)

    # 生成标准报告
    print("\n--- Standard Report ---")
    report = manager.generate_report("demo", 'standard')
    print(report)

    # 生成风险报告
    print("\n--- Risk Report ---")
    risk_report = manager.generate_report("demo", 'risk')
    print(risk_report)

    return report


def main():
    """运行所有测试"""
    print("\n")
    print("#" * 70)
    print("#              Portfolio Manager Test Suite")
    print("#" * 70)
    print("\n")

    # 运行测试
    test_create_portfolio()
    test_add_positions()
    test_update_prices()
    test_rebalance()
    test_performance_report()
    test_risk_metrics()
    test_remove_position()
    test_save_load_portfolio()
    test_report_generation()

    print("\n")
    print("#" * 70)
    print("#                    All Tests Completed")
    print("#" * 70)
    print("\n")


if __name__ == "__main__":
    main()
