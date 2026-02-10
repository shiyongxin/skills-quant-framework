# -*- coding: utf-8 -*-
"""
组合管理模块 - 完整版
Portfolio Manager - Complete Version

提供组合创建、持仓管理、再平衡、绩效分析等功能
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
import json


class RebalanceMethod(Enum):
    """再平衡方法"""
    EQUAL_WEIGHT = "equal_weight"           # 等权重
    TARGET_WEIGHTS = "target_weights"      # 目标权重
    MIN_VARIANCE = "min_variance"          # 最小方差
    RISK_PARITY = "risk_parity"            # 风险平价


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    name: str = ""
    shares: int = 0
    cost_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    profit_loss: float = 0.0
    profit_loss_pct: float = 0.0
    weight: float = 0.0
    entry_date: Optional[datetime] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'name': self.name,
            'shares': self.shares,
            'cost_price': self.cost_price,
            'current_price': self.current_price,
            'market_value': self.market_value,
            'profit_loss': self.profit_loss,
            'profit_loss_pct': self.profit_loss_pct,
            'weight': self.weight,
            'entry_date': self.entry_date.isoformat() if self.entry_date else None
        }


@dataclass
class Portfolio:
    """投资组合"""
    name: str
    initial_cash: float = 100000.0
    cash: float = 100000.0
    positions: Dict[str, Position] = field(default_factory=dict)
    created_date: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def total_value(self) -> float:
        """总资产"""
        return self.cash + sum(pos.market_value for pos in self.positions.values())

    @property
    def total_cost(self) -> float:
        """总成本"""
        return sum(pos.shares * pos.cost_price for pos in self.positions.values())

    @property
    def total_profit_loss(self) -> float:
        """总盈亏"""
        return sum(pos.profit_loss for pos in self.positions.values())

    @property
    def total_profit_loss_pct(self) -> float:
        """总盈亏比例"""
        if self.total_cost > 0:
            return (self.total_value - self.total_cost) / self.total_cost * 100
        return 0.0

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'name': self.name,
            'initial_cash': self.initial_cash,
            'cash': self.cash,
            'total_value': self.total_value,
            'total_cost': self.total_cost,
            'total_profit_loss': self.total_profit_loss,
            'total_profit_loss_pct': self.total_profit_loss_pct,
            'position_count': len(self.positions),
            'created_date': self.created_date.isoformat(),
            'last_updated': self.last_updated.isoformat(),
            'positions': {k: v.to_dict() for k, v in self.positions.items()}
        }


class PortfolioManager:
    """组合管理器"""

    def __init__(self, data_dir: str = None):
        """
        初始化组合管理器

        Args:
            data_dir: 组合数据存储目录
        """
        self.portfolios: Dict[str, Portfolio] = {}
        self.data_dir = data_dir or "portfolio_data"

    def create_portfolio(self, name: str, initial_cash: float = 100000) -> Portfolio:
        """
        创建新组合

        Args:
            name: 组合名称
            initial_cash: 初始资金

        Returns:
            Portfolio对象
        """
        if name in self.portfolios:
            raise ValueError(f"Portfolio '{name}' already exists")

        portfolio = Portfolio(
            name=name,
            initial_cash=initial_cash,
            cash=initial_cash
        )

        self.portfolios[name] = portfolio
        return portfolio

    def get_portfolio(self, name: str) -> Optional[Portfolio]:
        """获取组合"""
        return self.portfolios.get(name)

    def delete_portfolio(self, name: str) -> bool:
        """删除组合"""
        if name in self.portfolios:
            del self.portfolios[name]
            return True
        return False

    def list_portfolios(self) -> List[str]:
        """列出所有组合名称"""
        return list(self.portfolios.keys())

    def add_position(self, portfolio_name: str, symbol: str, name: str = "",
                    shares: int = 0, price: float = 0.0) -> bool:
        """
        添加或更新持仓

        Args:
            portfolio_name: 组合名称
            symbol: 股票代码
            name: 股票名称
            shares: 增持股数（正数买入，负数卖出）
            price: 交易价格

        Returns:
            是否成功
        """
        portfolio = self.get_portfolio(portfolio_name)
        if not portfolio:
            return False

        # 计算交易金额
        trade_value = shares * price

        # 更新持仓（无资金限制）
        if symbol in portfolio.positions:
            position = portfolio.positions[symbol]
            total_shares = position.shares + shares

            if total_shares <= 0:
                # 清仓
                portfolio.cash += -shares * price
                del portfolio.positions[symbol]
            else:
                # 加仓或减仓，更新成本价
                old_cost = position.shares * position.cost_price
                new_cost = old_cost + shares * price
                position.shares = total_shares
                position.cost_price = new_cost / total_shares

                if shares > 0:
                    portfolio.cash -= trade_value
                else:
                    portfolio.cash += -trade_value
        else:
            # 新建持仓
            if shares <= 0:
                return False

            # 移除资金限制检查
            position = Position(
                symbol=symbol,
                name=name,
                shares=shares,
                cost_price=price,
                current_price=price,
                market_value=shares * price,
                entry_date=datetime.now()
            )
            portfolio.positions[symbol] = position
            portfolio.cash -= trade_value

        portfolio.last_updated = datetime.now()
        self._update_portfolio_values(portfolio)
        return True

    def remove_position(self, portfolio_name: str, symbol: str,
                       shares: int = None, price: float = 0.0) -> bool:
        """
        移除持仓（部分或全部）

        Args:
            portfolio_name: 组合名称
            symbol: 股票代码
            shares: 卖出股数（None表示全部卖出）
            price: 卖出价格

        Returns:
            是否成功
        """
        portfolio = self.get_portfolio(portfolio_name)
        if not portfolio:
            return False

        if symbol not in portfolio.positions:
            return False

        position = portfolio.positions[symbol]

        if shares is None:
            # 全部卖出
            shares = position.shares

        if shares > position.shares:
            return False

        # 计算卖出金额
        proceeds = shares * price
        portfolio.cash += proceeds

        if shares == position.shares:
            # 全部清仓
            del portfolio.positions[symbol]
        else:
            # 部分卖出
            position.shares -= shares

        portfolio.last_updated = datetime.now()
        self._update_portfolio_values(portfolio)
        return True

    def update_prices(self, portfolio_name: str,
                     price_dict: Dict[str, float]) -> bool:
        """
        更新持仓价格

        Args:
            portfolio_name: 组合名称
            price_dict: 价格字典 {代码: 价格}

        Returns:
            是否成功
        """
        portfolio = self.get_portfolio(portfolio_name)
        if not portfolio:
            return False

        for symbol, price in price_dict.items():
            if symbol in portfolio.positions:
                position = portfolio.positions[symbol]
                position.current_price = price
                position.market_value = position.shares * price
                position.profit_loss = (price - position.cost_price) * position.shares
                position.profit_loss_pct = (price / position.cost_price - 1) * 100

        # 更新权重
        total_value = portfolio.total_value
        for position in portfolio.positions.values():
            position.weight = position.market_value / total_value if total_value > 0 else 0

        portfolio.last_updated = datetime.now()
        return True

    def rebalance(self, portfolio_name: str, target_weights: Dict[str, float],
                 method: RebalanceMethod = RebalanceMethod.TARGET_WEIGHTS,
                 price_dict: Dict[str, float] = None) -> Dict[str, int]:
        """
        组合再平衡

        Args:
            portfolio_name: 组合名称
            target_weights: 目标权重 {代码: 权重}
            method: 再平衡方法
            price_dict: 价格字典（可选）

        Returns:
            调整建议 {代码: 调整股数}
        """
        portfolio = self.get_portfolio(portfolio_name)
        if not portfolio:
            return {}

        total_value = portfolio.total_value

        adjustments = {}

        if method == RebalanceMethod.TARGET_WEIGHTS:
            for symbol, target_weight in target_weights.items():
                target_value = total_value * target_weight

                if symbol in portfolio.positions:
                    current_value = portfolio.positions[symbol].market_value
                else:
                    current_value = 0

                diff_value = target_value - current_value

                if price_dict and symbol in price_dict:
                    price = price_dict[symbol]
                elif symbol in portfolio.positions:
                    price = portfolio.positions[symbol].current_price
                else:
                    continue

                shares_change = int(diff_value / price)
                adjustments[symbol] = shares_change

        return adjustments

    def get_performance(self, portfolio_name: str) -> Dict:
        """
        获取组合绩效

        Args:
            portfolio_name: 组合名称

        Returns:
            绩效字典
        """
        portfolio = self.get_portfolio(portfolio_name)
        if not portfolio:
            return {}

        total_return = (portfolio.total_value / portfolio.initial_cash - 1) * 100

        # 计算持仓明细
        positions_list = []
        for position in portfolio.positions.values():
            positions_list.append({
                'symbol': position.symbol,
                'name': position.name,
                'shares': position.shares,
                'cost_price': position.cost_price,
                'current_price': position.current_price,
                'market_value': position.market_value,
                'weight': position.weight,
                'profit_loss': position.profit_loss,
                'profit_loss_pct': position.profit_loss_pct
            })

        # 按市值排序
        positions_list.sort(key=lambda x: x['market_value'], reverse=True)

        return {
            'portfolio_name': portfolio.name,
            'initial_cash': portfolio.initial_cash,
            'total_value': portfolio.total_value,
            'total_return': total_return,
            'total_profit_loss': portfolio.total_profit_loss,
            'total_profit_loss_pct': portfolio.total_profit_loss_pct,
            'cash': portfolio.cash,
            'cash_ratio': portfolio.cash / portfolio.total_value * 100,
            'position_count': len(portfolio.positions),
            'positions': positions_list,
            'created_date': portfolio.created_date.isoformat(),
            'last_updated': portfolio.last_updated.isoformat()
        }

    def get_risk_metrics(self, portfolio_name: str,
                        returns_df: pd.DataFrame = None) -> Dict:
        """
        获取组合风险指标

        Args:
            portfolio_name: 组合名称
            returns_df: 收益率DataFrame（可选）

        Returns:
            风险指标字典
        """
        portfolio = self.get_portfolio(portfolio_name)
        if not portfolio:
            return {}

        # 计算集中度
        weights = [pos.weight for pos in portfolio.positions.values()]
        weights.sort(reverse=True)

        # 前十大持仓占比
        top10_concentration = sum(weights[:10]) * 100

        # 最大单一持仓占比
        max_position = max(weights) * 100 if weights else 0

        # 赫芬达尔指数（HHI）
        hhi = sum(w ** 2 for w in weights) * 10000

        risk_metrics = {
            'position_count': len(portfolio.positions),
            'max_position': max_position,
            'top10_concentration': top10_concentration,
            'hhi': hhi,
            'cash_ratio': portfolio.cash / portfolio.total_value * 100
        }

        # 如果有收益率数据，计算更多指标
        if returns_df is not None and len(returns_df) > 0:
            # 组合收益率
            portfolio_returns = returns_df.mean(axis=1)

            # 年化波动率
            volatility = portfolio_returns.std() * np.sqrt(252) * 100

            # 下行波动率
            negative_returns = portfolio_returns[portfolio_returns < 0]
            downside_volatility = negative_returns.std() * np.sqrt(252) * 100 if len(negative_returns) > 0 else 0

            risk_metrics.update({
                'volatility': volatility,
                'downside_volatility': downside_volatility
            })

        return risk_metrics

    def generate_report(self, portfolio_name: str, report_type: str = 'standard') -> str:
        """
        生成组合报告

        Args:
            portfolio_name: 组合名称
            report_type: 报告类型 (standard/detailed/risk)

        Returns:
            报告文本
        """
        performance = self.get_performance(portfolio_name)
        risk_metrics = self.get_risk_metrics(portfolio_name)

        if not performance:
            return f"Portfolio '{portfolio_name}' not found"

        if report_type == 'standard':
            return self._format_standard_report(performance)
        elif report_type == 'detailed':
            return self._format_detailed_report(performance, risk_metrics)
        elif report_type == 'risk':
            return self._format_risk_report(performance, risk_metrics)
        else:
            return "Unsupported report type"

    def _format_standard_report(self, performance: Dict) -> str:
        """格式化标准报告"""
        lines = []
        lines.append("=" * 70)
        lines.append(f"                   {performance['portfolio_name']} 组合报告")
        lines.append("=" * 70)
        lines.append("")

        lines.append("【组合概况】")
        lines.append(f"  总资产:    {performance['total_value']:>12,.2f} 元")
        lines.append(f"  总盈亏:    {performance['total_profit_loss']:>+12,.2f} 元 ({performance['total_profit_loss_pct']:>+6.2f}%)")
        lines.append(f"  现金:      {performance['cash']:>12,.2f} 元 ({performance['cash_ratio']:>5.1f}%)")
        lines.append(f"  持仓数量:  {performance['position_count']:>12} 只")
        lines.append("")

        lines.append("【持仓明细】")
        for i, pos in enumerate(performance['positions'][:10], 1):
            lines.append(f"  {i:2d}. {pos['symbol']} {pos['name']}")
            lines.append(f"      持仓: {pos['shares']:>6} 股 / {pos['cost_price']:>7.2f} 元")
            lines.append(f"      市值: {pos['market_value']:>12,.2f} 元 ({pos['weight']:>5.1f}%)")
            lines.append(f"      盈亏: {pos['profit_loss']:>+12,.2f} 元 ({pos['profit_loss_pct']:>+6.2f}%)")
            lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)

    def _format_detailed_report(self, performance: Dict, risk_metrics: Dict) -> str:
        """格式化详细报告"""
        lines = []
        lines.append("=" * 80)
        lines.append(f"                        {performance['portfolio_name']} 详细报告")
        lines.append("=" * 80)
        lines.append("")

        lines.append("【组合概况】")
        lines.append(f"  初始资金:    {performance['initial_cash']:>12,.2f} 元")
        lines.append(f"  当前市值:    {performance['total_value']:>12,.2f} 元")
        lines.append(f"  总收益率:    {performance['total_return']:>+12,.2f}%")
        lines.append(f"  总盈亏:      {performance['total_profit_loss']:>+12,.2f} 元")
        lines.append(f"  现金占比:    {performance['cash_ratio']:>12,.2f}%")
        lines.append("")

        lines.append("【风险指标】")
        lines.append(f"  持仓数量:    {risk_metrics['position_count']:>12} 只")
        lines.append(f"  最大持仓:    {risk_metrics['max_position']:>12,.2f}%")
        lines.append(f"  前十大占比:  {risk_metrics['top10_concentration']:>12,.2f}%")
        lines.append(f"  HHI指数:     {risk_metrics['hhi']:>12,.0f}")
        lines.append("")

        lines.append("【持仓明细】")
        for i, pos in enumerate(performance['positions'], 1):
            lines.append(f"  {i:2d}. {pos['symbol']} {pos['name']}")
            lines.append(f"      持仓: {pos['shares']:>6} 股 @ {pos['cost_price']:>7.2f} 元")
            lines.append(f"      现价: {pos['current_price']:>7.2f} 元")
            lines.append(f"      市值: {pos['market_value']:>12,.2f} 元 ({pos['weight']:>5.1f}%)")
            lines.append(f"      盈亏: {pos['profit_loss']:>+12,.2f} 元 ({pos['profit_loss_pct']:>+6.2f}%)")
            lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)

    def _format_risk_report(self, performance: Dict, risk_metrics: Dict) -> str:
        """格式化风险报告"""
        lines = []
        lines.append("=" * 70)
        lines.append(f"                   {performance['portfolio_name']} 风险分析报告")
        lines.append("=" * 70)
        lines.append("")

        lines.append("【集中度分析】")
        lines.append(f"  持仓数量:        {risk_metrics['position_count']:>8} 只")
        lines.append(f"  最大单一持仓:    {risk_metrics['max_position']:>8.2f}%")
        lines.append(f"  前十大持仓占比:  {risk_metrics['top10_concentration']:>8.2f}%")
        lines.append(f"  HHI指数:         {risk_metrics['hhi']:>8.0f}")
        lines.append("")

        lines.append("【风险提示】")
        if risk_metrics['max_position'] > 20:
            lines.append("  - 最大单一持仓超过20%，建议分散投资")
        if risk_metrics['top10_concentration'] > 80:
            lines.append("  - 前十大持仓占比过高，建议增加持仓多样性")
        if risk_metrics['hhi'] > 1000:
            lines.append("  - HHI指数较高，组合集中度较高")
        if risk_metrics['cash_ratio'] < 5:
            lines.append("  - 现金比例过低，建议保持一定现金储备")
        lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)

    def _update_portfolio_values(self, portfolio: Portfolio):
        """更新组合各持仓的市值和权重"""
        total_value = portfolio.total_value

        for position in portfolio.positions.values():
            position.market_value = position.shares * position.current_price
            position.profit_loss = (position.current_price - position.cost_price) * position.shares
            position.profit_loss_pct = (position.current_price / position.cost_price - 1) * 100
            position.weight = position.market_value / total_value if total_value > 0 else 0

    def save_portfolio(self, portfolio_name: str, filepath: str = None) -> bool:
        """
        保存组合数据

        Args:
            portfolio_name: 组合名称
            filepath: 保存路径（可选）

        Returns:
            是否成功
        """
        portfolio = self.get_portfolio(portfolio_name)
        if not portfolio:
            return False

        if filepath is None:
            filepath = f"{self.data_dir}/{portfolio_name}.json"

        import os
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(portfolio.to_dict(), f, ensure_ascii=False, indent=2)

        return True

    def load_portfolio(self, filepath: str, portfolio_name: str = None) -> Optional[Portfolio]:
        """
        加载组合数据

        Args:
            filepath: 文件路径
            portfolio_name: 组合名称（可选）

        Returns:
            Portfolio对象
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            name = portfolio_name or data.get('name', 'imported')

            portfolio = Portfolio(
                name=name,
                initial_cash=data.get('initial_cash', 100000),
                cash=data.get('cash', data.get('initial_cash', 100000)),
                created_date=datetime.fromisoformat(data.get('created_date', datetime.now().isoformat())),
                last_updated=datetime.fromisoformat(data.get('last_updated', datetime.now().isoformat()))
            )

            # 加载持仓
            for symbol, pos_data in data.get('positions', {}).items():
                position = Position(
                    symbol=pos_data['symbol'],
                    name=pos_data.get('name', ''),
                    shares=pos_data['shares'],
                    cost_price=pos_data['cost_price'],
                    current_price=pos_data.get('current_price', pos_data['cost_price']),
                    entry_date=datetime.fromisoformat(pos_data['entry_date']) if pos_data.get('entry_date') else None
                )
                portfolio.positions[symbol] = position

            self._update_portfolio_values(portfolio)
            self.portfolios[name] = portfolio

            return portfolio

        except Exception as e:
            print(f"Error loading portfolio: {e}")
            return None


# 便捷函数
def create_portfolio(name: str, initial_cash: float = 100000) -> Portfolio:
    """创建组合"""
    manager = PortfolioManager()
    return manager.create_portfolio(name, initial_cash)


def add_position_to_portfolio(portfolio_name: str, symbol: str, name: str,
                              shares: int, price: float) -> bool:
    """添加持仓"""
    manager = PortfolioManager()
    return manager.add_position(portfolio_name, symbol, name, shares, price)


def get_portfolio_report(portfolio_name: str) -> str:
    """获取组合报告"""
    manager = PortfolioManager()
    return manager.generate_report(portfolio_name)


if __name__ == "__main__":
    print("Portfolio Manager - Complete Version v1.0")
    print("\nFeatures:")
    print("- Create Portfolio: 创建组合")
    print("- Add Position: 添加持仓")
    print("- Remove Position: 移除持仓")
    print("- Update Prices: 更新价格")
    print("- Rebalance: 组合再平衡")
    print("- Performance Analysis: 绩效分析")
    print("- Risk Metrics: 风险指标")
    print("- Generate Report: 生成报告")
