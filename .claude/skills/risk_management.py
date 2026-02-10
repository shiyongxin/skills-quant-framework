# -*- coding: utf-8 -*-
"""
风险管理模块
Risk Management Module

提供风险度量、仓位管理、止损止盈功能
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


class RiskMetrics:
    """风险指标计算"""

    @staticmethod
    def var(returns: pd.Series, confidence: float = 0.95, method: str = 'historical') -> float:
        """
        计算VaR (Value at Risk)

        Args:
            returns: 收益率序列
            confidence: 置信水平
            method: 计算方法 ('historical', 'parametric', 'monte_carlo')

        Returns:
            VaR值 (正数表示损失)
        """
        if method == 'historical':
            # 历史法
            return np.abs(np.percentile(returns, (1 - confidence) * 100))

        elif method == 'parametric':
            # 参数法 (假设正态分布)
            mean = returns.mean()
            std = returns.std()
            from scipy import stats
            z_score = stats.norm.ppf(1 - confidence)
            return abs(mean + z_score * std)

        elif method == 'monte_carlo':
            # 蒙特卡洛模拟
            n_simulations = 10000
            mean = returns.mean()
            std = returns.std()
            simulated = np.random.normal(mean, std, n_simulations)
            return np.abs(np.percentile(simulated, (1 - confidence) * 100))

    @staticmethod
    def cvar(returns: pd.Series, confidence: float = 0.95) -> float:
        """
        计算CVaR (Conditional VaR) / 期望损失

        Args:
            returns: 收益率序列
            confidence: 置信水平

        Returns:
            CVaR值
        """
        var = RiskMetrics.var(returns, confidence, method='historical')
        # CVaR是超过VaR的平均损失
        return returns[returns <= -var].mean() * -1

    @staticmethod
    def max_drawdown(equity_curve: pd.Series) -> Dict:
        """
        计算最大回撤

        Args:
            equity_curve: 权益曲线

        Returns:
            包含最大回撤、持续期等信息的字典
        """
        # 计算累计最大值
        cummax = equity_curve.cummax()

        # 回撤
        drawdown = (equity_curve - cummax) / cummax

        # 最大回撤
        max_dd = drawdown.min()

        # 找到最大回撤位置
        max_dd_idx = drawdown.idxmin()

        # 回撤开始时间
        cummax_idx = equity_curve[:max_dd_idx].idxmax()

        # 回测持续期
        duration = pd.to_datetime(max_dd_idx) - pd.to_datetime(cummax_idx)

        return {
            'max_drawdown': abs(max_dd),
            'max_drawdown_pct': abs(max_dd) * 100,
            'start_date': cummax_idx,
            'end_date': max_dd_idx,
            'duration_days': duration.days
        }

    @staticmethod
    def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.03) -> float:
        """
        计算夏普比率

        Args:
            returns: 收益率序列 (日频)
            risk_free_rate: 无风险利率 (年化)

        Returns:
            夏普比率
        """
        # 年化收益率
        annual_return = returns.mean() * 252

        # 年化波动率
        annual_std = returns.std() * np.sqrt(252)

        # 超额收益
        excess_return = annual_return - risk_free_rate

        return excess_return / annual_std if annual_std > 0 else 0

    @staticmethod
    def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.03) -> float:
        """
        计算索提诺比率 (只考虑下行风险)

        Args:
            returns: 收益率序列
            risk_free_rate: 无风险利率

        Returns:
            索提诺比率
        """
        # 年化收益率
        annual_return = returns.mean() * 252

        # 下行波动率 (只考虑负收益)
        negative_returns = returns[returns < 0]
        downside_std = negative_returns.std() * np.sqrt(252) if len(negative_returns) > 0 else 0.001

        excess_return = annual_return - risk_free_rate

        return excess_return / downside_std if downside_std > 0 else 0

    @staticmethod
    def calmar_ratio(returns: pd.Series, equity_curve: pd.Series) -> float:
        """
        计算卡玛比率 (收益/最大回撤)

        Args:
            returns: 收益率序列
            equity_curve: 权益曲线

        Returns:
            卡玛比率
        """
        # 年化收益率
        annual_return = returns.mean() * 252

        # 最大回撤
        max_dd = RiskMetrics.max_drawdown(equity_curve)['max_drawdown']

        return annual_return / max_dd if max_dd > 0 else 0

    @staticmethod
    def information_ratio(returns: pd.Series, benchmark_returns: pd.Series) -> float:
        """
        计算信息比率

        Args:
            returns: 策略收益率
            benchmark_returns: 基准收益率

        Returns:
            信息比率
        """
        # 超额收益
        excess_returns = returns - benchmark_returns

        # 跟踪误差
        tracking_error = excess_returns.std() * np.sqrt(252)

        # 年化超额收益
        annual_excess = excess_returns.mean() * 252

        return annual_excess / tracking_error if tracking_error > 0 else 0

    @staticmethod
    def beta(returns: pd.Series, market_returns: pd.Series) -> float:
        """
        计算Beta系数

        Args:
            returns: 资产收益率
            market_returns: 市场收益率

        Returns:
            Beta值
        """
        # 协方差
        covariance = np.cov(returns, market_returns)[0, 1]

        # 市场方差
        market_variance = np.var(market_returns)

        return covariance / market_variance if market_variance > 0 else 0

    @staticmethod
    def alpha(returns: pd.Series, market_returns: pd.Series, risk_free_rate: float = 0.03) -> float:
        """
        计算Alpha (Jensen's Alpha)

        Args:
            returns: 资产收益率
            market_returns: 市场收益率
            risk_free_rate: 无风险利率

        Returns:
            Alpha值 (年化)
        """
        beta = RiskMetrics.beta(returns, market_returns)

        # 年化收益率
        annual_return = returns.mean() * 252
        annual_market = market_returns.mean() * 252

        # Alpha = R - (Rf + Beta * (Rm - Rf))
        alpha = annual_return - (risk_free_rate + beta * (annual_market - risk_free_rate))

        return alpha


class PositionSizing:
    """仓位管理"""

    @staticmethod
    def equal_weight(capital: float, n_stocks: int) -> float:
        """
        等权重分配

        Args:
            capital: 总资金
            n_stocks: 股票数量

        Returns:
            每只股票的仓位
        """
        return capital / n_stocks if n_stocks > 0 else 0

    @staticmethod
    def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float, capital: float) -> float:
        """
        凯利公式仓位

        Args:
            win_rate: 胜率 (0-1)
            avg_win: 平均盈利 (%)
            avg_loss: 平均亏损 (%)
            capital: 总资金

        Returns:
            建议仓位
        """
        # 胜率 / 平均盈利
        # 凯利比例 = (胜率 * 平均盈利 - 败率 * 平均亏损) / 平均盈利
        win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 1

        kelly_pct = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio

        # 保守起见，使用半凯利
        kelly_pct = max(0, min(kelly_pct, 0.25))  # 限制在25%以内

        return capital * kelly_pct

    @staticmethod
    def fixed_fractional(capital: float, risk_per_trade: float, stop_loss_pct: float) -> float:
        """
        固定比例仓位

        Args:
            capital: 总资金
            risk_per_trade: 单笔风险比例 (如0.02表示2%)
            stop_loss_pct: 止损比例

        Returns:
            建议仓位
        """
        risk_amount = capital * risk_per_trade
        position_size = risk_amount / stop_loss_pct if stop_loss_pct > 0 else 0
        return position_size

    @staticmethod
    def volatility_based(capital: float, volatility: float, target_volatility: float = 0.15) -> float:
        """
        基于波动率的仓位

        Args:
            capital: 总资金
            volatility: 当前波动率 (年化)
            target_volatility: 目标波动率

        Returns:
            建议仓位
        """
        vol_scale = target_volatility / volatility if volatility > 0 else 1
        return capital * min(vol_scale, 1.5)  # 限制最大1.5倍

    @staticmethod
    def atr_based(price: float, atr: float, risk_amount: float) -> int:
        """
        基于ATR的仓位计算

        Args:
            price: 当前价格
            atr: ATR值
            risk_amount: 风险金额

        Returns:
            建议股数
        """
        # 1 ATR的波动对应的风险
        risk_per_share = atr

        # 股数 = 风险金额 / 每股风险
        shares = int(risk_amount / risk_per_share)

        return max(0, shares)

    @staticmethod
    def risk_parity_position(cov_matrix: pd.DataFrame, capital: float, risk_budget: float = 0.01) -> pd.Series:
        """
        风险平价仓位

        Args:
            cov_matrix: 协方差矩阵
            capital: 总资金
            risk_budget: 单资产风险预算

        Returns:
            各资产仓位
        """
        n = len(cov_matrix)

        # 简化版：等风险贡献
        # 计算各资产风险贡献 = w * (cov @ w)

        # 迭代求解
        weights = np.ones(n) / n

        for _ in range(100):
            # 计算风险贡献
            portfolio_var = weights @ cov_matrix @ weights
            marginal_contrib = cov_matrix @ weights
            contrib = weights * marginal_contrib

            # 调整权重使风险贡献相等
            target_contrib = portfolio_var / n
            weights = weights * target_contrib / (contrib + 1e-8)
            weights = weights / weights.sum()

        return pd.Series(weights * capital, index=cov_matrix.index)


class StopLossManager:
    """止损止盈管理"""

    def __init__(self):
        self.positions = {}  # 持仓信息

    def add_position(self, symbol: str, entry_price: float, quantity: int,
                     stop_loss_pct: float = None, take_profit_pct: float = None,
                     trailing_stop_pct: float = None):
        """
        添加持仓

        Args:
            symbol: 股票代码
            entry_price: 入场价格
            quantity: 持仓数量
            stop_loss_pct: 固定止损比例
            take_profit_pct: 止盈比例
            trailing_stop_pct: 移动止损比例
        """
        self.positions[symbol] = {
            'entry_price': entry_price,
            'quantity': quantity,
            'stop_loss_pct': stop_loss_pct,
            'take_profit_pct': take_profit_pct,
            'trailing_stop_pct': trailing_stop_pct,
            'highest_price': entry_price,  # 最高价 (用于移动止损)
            'entry_date': pd.Timestamp.now()
        }

    def check_stop_loss(self, symbol: str, current_price: float) -> Dict:
        """
        检查是否触发止损/止盈

        Args:
            symbol: 股票代码
            current_price: 当前价格

        Returns:
            {'action': 'hold'/'sell'/'stop_loss'/'take_profit'/'trailing_stop',
             'reason': str,
             'stop_price': float}
        """
        if symbol not in self.positions:
            return {'action': 'hold', 'reason': 'Position not found'}

        pos = self.positions[symbol]
        entry_price = pos['entry_price']

        # 更新最高价
        if current_price > pos['highest_price']:
            pos['highest_price'] = current_price

        # 1. 固定止损
        if pos['stop_loss_pct']:
            stop_loss_price = entry_price * (1 - pos['stop_loss_pct'])
            if current_price <= stop_loss_price:
                return {
                    'action': 'sell',
                    'type': 'stop_loss',
                    'stop_price': stop_loss_price,
                    'reason': f'Stop loss triggered at {stop_loss_price:.2f}'
                }

        # 2. 止盈
        if pos['take_profit_pct']:
            take_profit_price = entry_price * (1 + pos['take_profit_pct'])
            if current_price >= take_profit_price:
                return {
                    'action': 'sell',
                    'type': 'take_profit',
                    'stop_price': take_profit_price,
                    'reason': f'Take profit triggered at {take_profit_price:.2f}'
                }

        # 3. 移动止损
        if pos['trailing_stop_pct']:
            trailing_stop_price = pos['highest_price'] * (1 - pos['trailing_stop_pct'])
            if current_price <= trailing_stop_price and trailing_stop_price > entry_price:
                return {
                    'action': 'sell',
                    'type': 'trailing_stop',
                    'stop_price': trailing_stop_price,
                    'reason': f'Trailing stop triggered at {trailing_stop_price:.2f}, highest was {pos["highest_price"]:.2f}'
                }

        return {'action': 'hold', 'reason': 'No stop triggered'}

    def remove_position(self, symbol: str):
        """移除持仓"""
        if symbol in self.positions:
            del self.positions[symbol]

    def get_all_positions(self) -> Dict:
        """获取所有持仓信息"""
        return self.positions.copy()


class PortfolioRiskMonitor:
    """组合风险监控"""

    def __init__(self, var_confidence: float = 0.95, max_portfolio_var: float = 0.02):
        """
        初始化风险监控

        Args:
            var_confidence: VaR置信水平
            max_portfolio_var: 最大组合VaR限制
        """
        self.var_confidence = var_confidence
        self.max_portfolio_var = max_portfolio_var

    def check_portfolio_risk(self, positions: Dict[str, float],
                           returns_history: pd.DataFrame) -> Dict:
        """
        检查组合风险

        Args:
            positions: 持仓 {symbol: value}
            returns_history: 各资产历史收益率

        Returns:
            风险检查报告
        """
        # 计算组合权重
        total_value = sum(positions.values())
        weights = pd.Series({s: v/total_value for s, v in positions.items()})

        # 组合收益率
        portfolio_returns = returns_history[list(weights.index)] @ weights

        # 计算风险指标
        var = RiskMetrics.var(portfolio_returns, self.var_confidence)
        cvar = RiskMetrics.cvar(portfolio_returns, self.var_confidence)
        std = portfolio_returns.std() * np.sqrt(252)

        # 风险等级评估
        risk_level = 'LOW'
        if var > self.max_portfolio_var:
            risk_level = 'HIGH'
        elif var > self.max_portfolio_var * 0.7:
            risk_level = 'MEDIUM'

        return {
            'portfolio_value': total_value,
            'daily_var': var,
            'daily_var_pct': var * 100,
            'daily_cvar': cvar,
            'annual_volatility': std * 100,
            'risk_level': risk_level,
            'within_limit': var <= self.max_portfolio_var
        }

    def get_concentration_risk(self, positions: Dict[str, float]) -> Dict:
        """
        计算集中度风险

        Args:
            positions: 持仓 {symbol: value}

        Returns:
            集中度分析
        """
        total = sum(positions.values())

        # 计算各资产占比
        concentrations = {s: v/total for s, v in positions.items()}

        # Herfindahl指数 (越大越集中)
        hhi = sum(c**2 for c in concentrations.values())

        # 最大单一持仓
        max_concentration = max(concentrations.values())

        # 集中度评级
        if hhi < 0.1:
            level = 'LOW'
        elif hhi < 0.2:
            level = 'MEDIUM'
        else:
            level = 'HIGH'

        return {
            'concentrations': concentrations,
            'hhi': hhi,
            'max_concentration': max_concentration,
            'concentration_level': level
        }


# 便捷函数
def calculate_var(returns, confidence=0.95):
    """计算VaR"""
    return RiskMetrics.var(returns, confidence)

def calculate_sharpe(returns, risk_free_rate=0.03):
    """计算夏普比率"""
    return RiskMetrics.sharpe_ratio(returns, risk_free_rate)

def get_kelly_position(win_rate, avg_win, avg_loss, capital):
    """凯利公式仓位"""
    return PositionSizing.kelly_criterion(win_rate, avg_win, avg_loss, capital)


if __name__ == "__main__":
    print("Risk Management Module")
    print("\nAvailable Classes:")
    print("- RiskMetrics: 风险指标计算")
    print("- PositionSizing: 仓位管理")
    print("- StopLossManager: 止损止盈")
    print("- PortfolioRiskMonitor: 组合风险监控")
