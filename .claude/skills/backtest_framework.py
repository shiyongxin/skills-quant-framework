# -*- coding: utf-8 -*-
"""
回测框架 - 完整版
Backtesting Framework - Complete Version

提供策略回测、绩效分析、参数优化功能
支持单股票回测、多策略对比、风险控制等高级功能

新增功能:
- 持仓规模管理 (Position Sizing)
- 止损止盈机制 (Stop Loss / Take Profit)
- 增强绩效指标 (Enhanced Metrics)
- 分仓交易 (Partial Position)
- 详细报告 (Detailed Report)
- 成交容量约束 (审计 B14/H7): 单笔买入 ≤ 当日成交额 × 参与率 (默认 5%),
  容量不足则按上限部分成交 —— 成交量不再只用于信号打分
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Callable, Optional

from core import metrics as _core_metrics
from core.indicators import (rsi as _core_rsi, atr as _core_atr,
                              true_range as _core_true_range, sma as _core_sma,
                              macd as _core_macd, bollinger as _core_bollinger)
from dataclasses import dataclass
from enum import Enum
import warnings
warnings.filterwarnings('ignore')

from execution_model import (
    CostModel, can_buy_at_open, can_sell_at_open, can_sell_intraday,
    bar_turnover_amount, capacity_limit_notional,
)


class PositionSizingMethod(Enum):
    """持仓规模管理方法"""
    FIXED_AMOUNT = "fixed_amount"       # 固定金额
    PERCENT_OF_EQUITY = "percent_equity"  # 权益百分比
    FIXED_SHARES = "fixed_shares"       # 固定股数
    KELLY = "kelly"                     # 凯利公式
    VOLATILITY_TARGET = "volatility_target"  # 波动率目标


class StopLossMethod(Enum):
    """止损方法"""
    PERCENTAGE = "percentage"           # 百分比止损
    ATR = "atr"                         # ATR止损
    TRAILING = "trailing"               # 移动止损
    SUPPORT_RESISTANCE = "sr"           # 支撑阻力止损


@dataclass
class PositionConfig:
    """持仓配置"""
    sizing_method: PositionSizingMethod = PositionSizingMethod.PERCENT_OF_EQUITY
    sizing_value: float = 0.95          # 持仓规模参数 (金额/百分比/股数)
    max_position_pct: float = 1.0       # 最大持仓比例

    # 成交容量约束 (审计 B14/H7): 单笔买入金额 ≤ 当日成交额 × 该比例
    # 0 = 关闭 (退回旧行为)。数据缺 '成交额'/'成交量' 时如实跳过并告警。
    max_volume_participation: float = 0.05

    # 止损配置
    stop_loss_method: StopLossMethod = StopLossMethod.PERCENTAGE
    stop_loss_pct: float = 0.08         # 止损百分比
    atr_multiplier: float = 2.0         # ATR倍数
    trailing_stop_pct: float = 0.05     # 移动止损百分比

    # 止盈配置
    take_profit_pct: float = 0.20       # 止盈百分比
    take_profit_enabled: bool = False   # 是否启用止盈

    def __post_init__(self):
        if self.max_position_pct >= 1.0:
            import warnings
            warnings.warn(
                f"PositionConfig.max_position_pct={self.max_position_pct} "
                f"为无上限配置(单票可满仓), 实盘建议 ≤0.5 (审计项 20)",
                stacklevel=2)


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    shares: int
    entry_price: float
    entry_date: any
    stop_loss_price: float = None
    take_profit_price: float = None
    highest_price: float = None  # 用于移动止损


class BacktestEngine:
    """
    回测引擎 - 增强版

    支持持仓管理、止损止盈、多股票组合回测
    """

    def __init__(self, initial_cash=100000, commission=0.0003, slippage=0.001,
                 position_config: PositionConfig = None):
        """
        初始化回测引擎

        Args:
            initial_cash: 初始资金
            commission: 手续费率 (默认万三)
            slippage: 滑点率
            position_config: 持仓配置
        """
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage = slippage
        self.position_config = position_config or PositionConfig()
        self.cost_model = CostModel.from_engine(commission, slippage)

        # 回测状态
        self.cash = initial_cash
        self.positions: Dict[str, Position] = {}  # 多股票持仓
        self.trades = []    # 交易记录
        self.equity = []    # 资金曲线
        self.daily_values = []  # 每日市值
        self.pending_order: Optional[Dict] = None  # t+1 待撮合订单

    def reset(self):
        """重置回测状态"""
        self.cash = self.initial_cash
        self.positions = {}
        self.trades = []
        self.equity = []
        self.daily_values = []
        self.pending_order = None

    def run(self, data: pd.DataFrame, strategy: Callable,
            symbol: str = "STOCK",
            warmup_data: pd.DataFrame = None) -> Dict:
        """
        运行回测

        Args:
            data: DataFrame, 包含OHLCV及技术指标
            strategy: 策略函数, 返回买入/卖出信号
            symbol: 股票代码
            warmup_data: 可选的窗口前历史 (审计 B25/H9①)
                策略可见这段历史 (指标预热, 不再冷启动), 但**账户从窗口第一根
                bar 开始交易** (空仓起步, 不带入预热期盈亏)

        Returns:
            回测结果字典
        """
        self.reset()

        # ---- 预热段 + 交易窗口 (策略可见预热, 交易只在窗口内) ----
        warm = warmup_data
        if warm is not None and len(warm) > 0:
            warm = warm.reset_index(drop=True)
            combined = pd.concat([warm, data], ignore_index=True)
        else:
            warm = None
            combined = data
        w = len(warm) if warm is not None else 0

        # 确保有ATR数据 (用于ATR止损) —— 预热段参与 ATR 计算
        if 'ATR' not in combined.columns:
            combined = self._calculate_atr(combined)
        window = combined.iloc[w:].reset_index(drop=True) if w else combined

        # 成交容量约束是否可检查 (审计 B14/H7): 数据缺 成交额/成交量 列时
        # 如实记 False (结果里可查), 不假装已施加容量上限
        self.capacity_checked = bool(
            ('成交额' in window.columns) or ('成交量' in window.columns))

        pending = None

        for i in range(1, len(window)):
            current_bar = window.iloc[i]
            current_date = current_bar['日期']
            prev_close = window['收盘'].iloc[i - 1]

            # 1) t+1 撮合: 上一根收盘产生的信号在本根开盘成交（含涨跌停拦截）
            if pending is not None:
                pending = self._fill_pending(symbol, current_bar, prev_close, pending)

            # 2) 日内止损止盈（本根开盘刚成交的持仓同样有效；涨跌停封板不可卖出）
            self._check_stop_loss_take_profit(symbol, current_bar, prev_close, code=symbol)

            # 3) 策略信号（本根收盘判定 → 排队至下一根开盘）
            #    策略可见预热段 + 窗口内至当根 (无预热时与旧版逐位一致)
            view = combined.iloc[:w + i + 1] if w else window.iloc[:i + 1]
            signal = strategy(view)
            if signal in (1, -1):
                pending = {
                    'side': int(signal),
                    'ttl': 3,  # 涨跌停拦截后最多顺延3根，超时作废
                    'atr': window['ATR'].iloc[i] if 'ATR' in window.columns else None,
                }

            # 4) 记录权益
            current_value = self._get_total_value(current_bar['收盘'])
            self.equity.append({
                'date': current_date,
                'cash': self.cash,
                'value': current_value
            })

            # 记录每日市值
            self.daily_values.append({
                'date': current_date,
                'value': current_value
            })

        return self._get_results(window, symbol)

    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算ATR指标"""
        data = data.copy()
        high = data['最高']
        low = data['最低']
        close = data['收盘']

        data['prev_close'] = close.shift(1)

        # Wilder ATR (core 单一真相源, 旧: SMA)
        data['TR'] = _core_true_range(high, low, close)
        data['ATR'] = _core_atr(high, low, close, period)

        return data

    def _get_total_value(self, current_price: float) -> float:
        """计算总资产"""
        position_value = sum(
            pos.shares * current_price
            for pos in self.positions.values()
        )
        return self.cash + position_value

    def _calculate_position_size(self, price: float, atr: float = None) -> int:
        """计算持仓数量"""
        config = self.position_config
        current_equity = self.cash + sum(
            pos.shares * price for pos in self.positions.values()
        )

        shares = 0

        if config.sizing_method == PositionSizingMethod.FIXED_AMOUNT:
            # 固定金额
            shares = int(config.sizing_value / price)

        elif config.sizing_method == PositionSizingMethod.PERCENT_OF_EQUITY:
            # 权益百分比
            invest_amount = current_equity * config.sizing_value
            shares = int(invest_amount / price)

        elif config.sizing_method == PositionSizingMethod.FIXED_SHARES:
            # 固定股数
            shares = int(config.sizing_value)

        elif config.sizing_method == PositionSizingMethod.KELLY and atr:
            # 凯利公式 (简化版: 风险金额 / (2*ATR))
            risk_amount = current_equity * 0.02  # 2%风险
            shares = int(risk_amount / (2 * atr))

        elif config.sizing_method == PositionSizingMethod.VOLATILITY_TARGET and atr:
            # 波动率目标
            target_volatility = config.sizing_value
            dollar_volatility = current_equity * target_volatility
            shares = int(dollar_volatility / atr)

        # 限制最大持仓
        max_shares = int(current_equity * config.max_position_pct / price)
        shares = min(shares, max_shares)

        return max(0, shares)

    def _calculate_stop_loss_price(self, entry_price: float, atr: float = None) -> float:
        """计算止损价格"""
        config = self.position_config

        if config.stop_loss_method == StopLossMethod.PERCENTAGE:
            return entry_price * (1 - config.stop_loss_pct)

        elif config.stop_loss_method == StopLossMethod.ATR and atr:
            return entry_price - (config.atr_multiplier * atr)

        elif config.stop_loss_method == StopLossMethod.TRAILING:
            return entry_price * (1 - config.trailing_stop_pct)

        return entry_price * (1 - config.stop_loss_pct)

    def _fill_pending(self, symbol: str, bar: pd.Series, prev_close: float,
                      pending: Dict) -> Optional[Dict]:
        """
        t+1 开盘撮合待处理订单。

        买入在开盘触及涨停（含一字板）→ 不可成交，顺延最多 ttl 根后作废；
        卖出在开盘触及跌停 → 同样顺延。
        返回剩余 pending（None 表示已了结/作废）。
        """
        side = pending['side']
        atr = pending.get('atr')

        if side == 1:
            if symbol in self.positions:
                return None  # 已有持仓，买入意图作废
            fill = can_buy_at_open(bar['开盘'], prev_close, symbol) and bar['开盘']
            if not fill:
                pending['ttl'] -= 1
                return pending if pending['ttl'] > 0 else None
            raw_price = float(fill)
            shares = self._calculate_position_size(raw_price, atr)
            shares = (shares // 100) * 100  # A股整手(100股)约束

            # 成交容量约束 (审计 B14/H7): 单笔买入金额 ≤ 当日成交额 × 参与率
            cap_notional = capacity_limit_notional(
                bar_turnover_amount(bar, raw_price),
                self.position_config.max_volume_participation)
            if cap_notional is not None:
                cap_shares = (int(cap_notional / raw_price) // 100) * 100
                if cap_shares < shares:
                    shares = cap_shares
            if shares < 100:
                return None

            buy_price = self.cost_model.fill_buy_price(raw_price)
            notional = shares * buy_price
            fee = self.cost_model.buy_cost(buy_price, shares)
            cost = notional + fee
            while shares >= 100 and cost > self.cash:
                shares -= 100
                notional = shares * buy_price
                fee = self.cost_model.buy_cost(buy_price, shares)
                cost = notional + fee
            if shares < 100:
                return None

            # 计算止损止盈价格（基于决策时A股与成交价）
            stop_loss_price = self._calculate_stop_loss_price(buy_price, atr)
            take_profit_price = None
            if self.position_config.take_profit_enabled:
                take_profit_price = buy_price * (1 + self.position_config.take_profit_pct)

            position = Position(
                symbol=symbol,
                shares=shares,
                entry_price=buy_price,
                entry_date=bar['日期'],
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                highest_price=buy_price
            )
            self.positions[symbol] = position
            self.cash -= cost

            self.trades.append({
                'date': bar['日期'],
                'symbol': symbol,
                'action': 'buy',
                'price': buy_price,
                'shares': shares,
                'cost': cost,
                'fee': fee,
                'stop_loss': stop_loss_price
            })
            return None

        # 卖出
        if symbol not in self.positions:
            return None
        if not can_sell_at_open(bar['开盘'], prev_close, symbol):
            pending['ttl'] -= 1
            return pending if pending['ttl'] > 0 else None
        self._close_position(symbol, bar['日期'], float(bar['开盘']), 'signal')
        return None

    def _check_stop_loss_take_profit(self, symbol: str, bar: pd.Series,
                                     prev_close: float = None, code: str = None):
        """检查止损止盈（日内触发；跌停封板当日不可卖出 → 顺延到下一交易日）"""
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        high = bar['最高']
        low = bar['最低']
        open_price = bar['开盘']

        # 更新最高价 (用于移动止损; 收盘后生效于下一根, 避免同根高低点未来函数)
        if position.highest_price is None or high > position.highest_price:
            position.highest_price = high

        # 检查止损（跳空低于止损价时按开盘价成交, 而非幻影止损价）
        if position.stop_loss_price is not None and low <= position.stop_loss_price:
            if prev_close is None or can_sell_intraday(
                    open_price, high, low, bar['收盘'], prev_close, code or symbol):
                fill_price = min(position.stop_loss_price, open_price)
                self._close_position(symbol, bar['日期'], fill_price, 'stop_loss')
                return

        # 检查止盈（跳空高于止盈价时按开盘价成交）
        if position.take_profit_price is not None and high >= position.take_profit_price:
            if prev_close is None or can_sell_intraday(
                    open_price, high, low, bar['收盘'], prev_close, code or symbol):
                fill_price = max(position.take_profit_price, open_price)
                self._close_position(symbol, bar['日期'], fill_price, 'take_profit')
                return

        # 移动止损 (基于已收盘bar的最高价, 下一根bar生效)
        if self.position_config.stop_loss_method == StopLossMethod.TRAILING:
            new_stop_loss = position.highest_price * (1 - self.position_config.trailing_stop_pct)
            if new_stop_loss > position.stop_loss_price:
                position.stop_loss_price = new_stop_loss

    def _close_position(self, symbol: str, date: any, price: float, reason: str):
        """平仓（滑点+佣金+过户费+印花税经 CostModel 统一扣减）"""
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        sell_price = self.cost_model.fill_sell_price(price)
        fee = self.cost_model.sell_cost(sell_price, position.shares)
        proceeds = position.shares * sell_price - fee

        self.trades.append({
            'date': date,
            'symbol': symbol,
            'action': 'sell',
            'price': sell_price,
            'shares': position.shares,
            'proceeds': proceeds,
            'fee': fee,
            'entry_price': position.entry_price,
            'pnl_pct': (sell_price / position.entry_price - 1) * 100,
            'reason': reason
        })

        self.cash += proceeds
        del self.positions[symbol]

    def _get_results(self, data: pd.DataFrame, symbol: str) -> Dict:
        """计算回测结果"""
        equity_df = pd.DataFrame(self.equity)
        trades_df = pd.DataFrame(self.trades)

        if len(equity_df) == 0:
            return {}

        final_value = equity_df['value'].iloc[-1]
        total_return = (final_value / self.initial_cash - 1) * 100

        # 计算基准收益
        benchmark_return = (data['收盘'].iloc[-1] / data['收盘'].iloc[0] - 1) * 100

        # 计算回撤（core 统一口径: 正值百分比）
        equity_df['cummax'] = equity_df['value'].cummax()
        equity_df['drawdown'] = (equity_df['value'] / equity_df['cummax'] - 1) * 100
        max_drawdown = _core_metrics.max_drawdown_pct(equity_df['value'])

        # 计算每日收益率
        equity_df['daily_return'] = equity_df['value'].pct_change() * 100

        # 年化收益率
        days = len(equity_df)
        annualized_return = (1 + total_return / 100) ** (252 / days) - 1

        # 夏普比率（core 统一口径: 日频收益, rf=3%, ddof=1）
        sharpe_ratio = _core_metrics.sharpe_ratio(
            equity_df['daily_return'] / 100, periods_per_year=252, rf=0.03)

        # Sortino比率 (只考虑下行风险)
        mean_return_pct = equity_df['daily_return'].mean()
        negative_returns = equity_df['daily_return'][equity_df['daily_return'] < 0]
        downside_std = negative_returns.std() if len(negative_returns) > 0 else 0
        sortino_ratio = (mean_return_pct * 252 - 3) / (downside_std * np.sqrt(252)) if downside_std > 0 else 0

        # Calmar比率 (年化收益 / 最大回撤)
        calmar_ratio = (annualized_return * 100) / abs(max_drawdown) if max_drawdown != 0 else 0

        # 交易统计
        sell_trades = trades_df[trades_df['action'] == 'sell'] if len(trades_df) > 0 else pd.DataFrame()

        if len(sell_trades) > 0:
            trade_count = len(sell_trades)
            profits = sell_trades['pnl_pct'].tolist()

            win_trades = [p for p in profits if p > 0]
            lose_trades = [p for p in profits if p < 0]

            # 胜率: core 统一口径 (盈亏为 0 计入分母但不算赢)
            win_rate = _core_metrics.win_rate(profits)
            avg_profit = np.mean(win_trades) if win_trades else 0
            avg_loss = np.mean(lose_trades) if lose_trades else 0
            # core 求和式口径（统一 A/B/优化器）
            profit_factor = _core_metrics.profit_factor(profits)

            # 最大盈利/亏损
            max_profit = max(win_trades) if win_trades else 0
            max_loss = min(lose_trades) if lose_trades else 0

            # 平均持仓天数
            buy_trades = trades_df[trades_df['action'] == 'buy']
            holding_days = []
            for _, sell_trade in sell_trades.iterrows():
                buy_trade = buy_trades[buy_trades['date'] <= sell_trade['date']].iloc[-1:]
                if len(buy_trade) > 0:
                    days = (sell_trade['date'] - buy_trade.iloc[-1]['date']).days
                    holding_days.append(days)
            avg_holding_days = np.mean(holding_days) if holding_days else 0

            # 止损/止盈统计
            stop_loss_count = len(sell_trades[sell_trades['reason'] == 'stop_loss'])
            take_profit_count = len(sell_trades[sell_trades['reason'] == 'take_profit'])
            signal_exit_count = len(sell_trades[sell_trades['reason'] == 'signal'])
        else:
            trade_count = 0
            win_rate = 0
            avg_profit = 0
            avg_loss = 0
            profit_factor = 0
            max_profit = 0
            max_loss = 0
            avg_holding_days = 0
            stop_loss_count = 0
            take_profit_count = 0
            signal_exit_count = 0

        # 胜负序列分析 (审计 B48/M1): 连胜/连亏统计基准统一为**交易序列**
        # (与引擎 B 同口径) —— 旧实现统计在日频净值曲线上, 同名字段两套口径。
        if len(sell_trades) > 0:
            max_consecutive_wins, max_consecutive_losses = \
                _core_metrics.consecutive_streaks(
                    sell_trades['pnl_pct'].tolist())
        else:
            max_consecutive_wins, max_consecutive_losses = 0, 0

        # 日频净值序列上的连涨/连跌 bar 数 (与上面的**交易**序列口径不同,
        # 故用独立且诚实的字段名, 不再占用 max_consecutive_* 名)
        values = equity_df['value']
        prev = values.shift(1)
        up_day = values > prev
        down_day = values < prev
        max_consecutive_up_days = _core_metrics.max_consecutive_true(up_day)
        max_consecutive_down_days = _core_metrics.max_consecutive_true(down_day)

        return {
            'symbol': symbol,
            'initial_cash': self.initial_cash,
            'capacity_checked': bool(getattr(self, 'capacity_checked', True)),
            'final_value': final_value,
            'total_return': total_return,
            'annualized_return': annualized_return * 100,
            'benchmark_return': benchmark_return,
            'excess_return': total_return - benchmark_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'calmar_ratio': calmar_ratio,
            'trade_count': trade_count,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_profit': max_profit,
            'max_loss': max_loss,
            'avg_holding_days': avg_holding_days,
            'stop_loss_count': stop_loss_count,
            'take_profit_count': take_profit_count,
            'signal_exit_count': signal_exit_count,
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses,
            'max_consecutive_up_days': max_consecutive_up_days,
            'max_consecutive_down_days': max_consecutive_down_days,
            'equity_curve': equity_df,
            'trades': trades_df
        }


class StrategyFactory:
    """策略工厂 - 预定义常用策略"""

    @staticmethod
    def ma_cross(fast=5, slow=20):
        """
        均线交叉策略

        Args:
            fast: 快线周期
            slow: 慢线周期
        """
        def strategy(data):
            if len(data) < slow:
                return 0

            # 计算均线
            data = data.copy()
            data['MA_fast'] = _core_sma(data['收盘'], fast)
            data['MA_slow'] = _core_sma(data['收盘'], slow)

            latest = data.iloc[-1]
            prev = data.iloc[-2]

            # 金叉买入
            if prev['MA_fast'] <= prev['MA_slow'] and latest['MA_fast'] > latest['MA_slow']:
                return 1
            # 死叉卖出
            elif prev['MA_fast'] >= prev['MA_slow'] and latest['MA_fast'] < latest['MA_slow']:
                return -1
            else:
                return 0

        strategy.name = f'MA_Cross_{fast}_{slow}'
        return strategy

    @staticmethod
    def macd_cross(fast=12, slow=26, signal=9):
        """
        MACD交叉策略

        Args:
            fast: 快线周期
            slow: 慢线周期
            signal: 信号线周期
        """
        def strategy(data):
            if len(data) < slow + signal:
                return 0

            # 计算MACD (core 单一真相源)
            close = data['收盘']
            macd, macd_signal, _hist = _core_macd(close, fast, slow, signal)

            latest_macd = macd.iloc[-1]
            prev_macd = macd.iloc[-2]
            latest_signal = macd_signal.iloc[-1]
            prev_signal = macd_signal.iloc[-2]

            # 金叉买入
            if prev_macd <= prev_signal and latest_macd > latest_signal:
                return 1
            # 死叉卖出
            elif prev_macd >= prev_signal and latest_macd < latest_signal:
                return -1
            else:
                return 0

        strategy.name = f'MACD_Cross_{fast}_{slow}_{signal}'
        return strategy

    @staticmethod
    def rsi_overbought_oversold(period=14, oversold=30, overbought=70):
        """
        RSI超买超卖策略

        Args:
            period: RSI周期
            oversold: 超卖阈值
            overbought: 超买阈值
        """
        def strategy(data):
            if len(data) < period + 1:
                return 0

            # 计算RSI (core 单一真相源)
            rsi = _core_rsi(data['收盘'], period)

            latest_rsi = rsi.iloc[-1]
            prev_rsi = rsi.iloc[-2]

            # 超卖买入
            if prev_rsi >= oversold and latest_rsi < oversold:
                return 1
            # 超买卖出
            elif prev_rsi <= overbought and latest_rsi > overbought:
                return -1
            else:
                return 0

        strategy.name = f'RSI_{period}_{oversold}_{overbought}'
        return strategy

    @staticmethod
    def bollinger_bands(period=20, std=2):
        """
        布林带突破策略

        Args:
            period: 周期
            std: 标准差倍数
        """
        def strategy(data):
            if len(data) < period:
                return 0

            # 计算布林带 (core 单一真相源)
            close = data['收盘']
            upper, middle, lower, _std_dev = _core_bollinger(close, period, std)

            latest_close = close.iloc[-1]
            latest_upper = upper.iloc[-1]
            latest_lower = lower.iloc[-1]

            # 突破上轨买入
            if latest_close > latest_upper:
                return 1
            # 跌破下轨卖出
            elif latest_close < latest_lower:
                return -1
            else:
                return 0

        strategy.name = f'BB_{period}_{std}'
        return strategy

    @staticmethod
    def multi_signal(strategies, weights=None):
        """
        多信号融合策略

        Args:
            strategies: 策略列表
            weights: 权重列表
        """
        if weights is None:
            weights = [1] * len(strategies)

        def strategy(data):
            signals = [s(data) for s in strategies]
            weighted_signal = sum(s * w for s, w in zip(signals, weights))

            if weighted_signal > 0.5:
                return 1
            elif weighted_signal < -0.5:
                return -1
            else:
                return 0

        strategy.name = f'Multi_Signal_{len(strategies)}'
        return strategy


def _stitch_oos_equity(window_curves, initial_cash=100000):
    """把各 OOS 窗口的日频净值曲线拼成一条连续曲线 (审计 B25/H9②)

    各窗口独立回测 (每窗账户从 initial_cash 起步), 拼接时按资金连续性缩放:
    第 w 窗的净值整体乘以"累计资金 / initial_cash", 于是拼接曲线的收益率
    等于各窗收益逐段复利 —— 这才是真正的 OOS 绩效 (旧版只给每窗 dict,
    拿不到整体 OOS)。

    Args:
        window_curves: [(窗口起始日, result_dict), ...]
        initial_cash: 每窗起始资金

    Returns:
        (DataFrame 拼接曲线, dict 聚合 OOS 指标)
    """
    frames = []
    pnls = []
    capital = float(initial_cash)

    for start_date, result in window_curves:
        eq = result.get('equity_curve')
        if eq is None or len(eq) == 0:
            continue
        # 窗口第一根 bar 之前账户是空仓 (值 = initial_cash), 补上该起点,
        # 否则窗口边界处会丢一段收益
        window = pd.DataFrame({
            'date': [start_date] + list(eq['date']),
            'value': [float(initial_cash)] + list(eq['value'].astype(float)),
        })
        factor = capital / float(initial_cash)
        window['value'] = window['value'] * factor
        frames.append(window)
        capital = float(window['value'].iloc[-1])

        trades = result.get('trades')
        if trades is not None and len(trades) > 0:
            sells = trades[trades['action'] == 'sell']
            if len(sells) > 0:
                pnls.extend([float(x) for x in sells['pnl_pct'].tolist()])

    if not frames:
        return pd.DataFrame(), {}

    curve = pd.concat(frames, ignore_index=True)
    curve['daily_return'] = curve['value'].pct_change() * 100
    curve['cummax'] = curve['value'].cummax()
    curve['drawdown'] = (curve['value'] / curve['cummax'] - 1) * 100

    final_value = float(curve['value'].iloc[-1])
    total_return = (final_value / float(initial_cash) - 1) * 100
    days = max(1, len(curve) - 1)
    annualized_return = ((1 + total_return / 100) ** (252 / days) - 1) * 100
    max_drawdown = _core_metrics.max_drawdown_pct(curve['value'])
    sharpe_ratio = _core_metrics.sharpe_ratio(
        curve['daily_return'] / 100, periods_per_year=252, rf=0.03)

    if pnls:
        win_rate = _core_metrics.win_rate(pnls)
        profit_factor = _core_metrics.profit_factor(pnls)
    else:
        win_rate = 0.0
        profit_factor = 0.0

    summary = {
        'num_windows': len(frames),
        'oos_bars': days,
        'period_start': curve['date'].iloc[0],
        'period_end': curve['date'].iloc[-1],
        'initial_cash': float(initial_cash),
        'final_value': final_value,
        'total_return': total_return,
        'annualized_return': annualized_return,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe_ratio,
        'trade_count': len(pnls),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
    }
    return curve, summary


class ParameterOptimizer:
    """参数优化器"""

    @staticmethod
    def grid_search(data, strategy_template, param_grid, metric='sharpe_ratio',
                    warmup_data=None):
        """
        网格搜索优化

        Args:
            data: 历史数据
            strategy_template: 策略模板函数
            param_grid: 参数网格
            metric: 优化目标指标
            warmup_data: 可选的窗口前历史 (审计 B25/H9①), 策略可见但不参与交易

        Returns:
            最佳参数和结果
        """
        import itertools

        best_result = None
        best_params = None

        # 生成所有参数组合
        keys = param_grid.keys()
        values = param_grid.values()
        combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]

        print(f"Grid search: {len(combinations)} combinations")

        for i, params in enumerate(combinations):
            # 创建策略
            strategy = strategy_template(**params)

            # 回测
            engine = BacktestEngine()
            result = engine.run(data, strategy, warmup_data=warmup_data)

            # 评估
            if best_result is None or result[metric] > best_result[metric]:
                best_result = result
                best_params = params

            print(f"[{i+1}/{len(combinations)}] {params}: {metric}={result[metric]:.4f}")

        return best_params, best_result

    @staticmethod
    def walk_forward(data, strategy_template, param_range, train_period=252,
                     test_period=63, warmup_period=60):
        """
        滚动窗口优化 (审计 B25/H9)

        两处结构性修复:
        - **测试窗口带预热** (warmup_period 根窗口前历史): 旧版测试窗是裸
          切片, 策略内实时算 MA 时 63 根窗口配 slow=20 只剩 43 根可用 bar
          → OOS 被结构性削弱 (审计标 ↓悲观)。预热段只给策略看指标, 账户
          仍从窗口第一根 bar 空仓起步。
        - **OOS 净值曲线拼接**: 旧版只返回每窗 dict 列表, 拿不到真正的 OOS
          整体绩效; 现把各窗口日频净值曲线按资金连续性拼成一条曲线, 并给出
          聚合 OOS 指标 (总收益/夏普/回撤/年化/交易统计)。

        Args:
            data: 历史数据
            strategy_template: 策略模板
            param_range: 参数范围
            train_period: 训练周期
            test_period: 测试周期
            warmup_period: 窗口前预热长度 (0 = 关闭, 退回旧版裸切片)

        Returns:
            dict:
              - 'windows': 各窗口明细 (train_start/test_start/test_end/params/result)
              - 'oos': 拼接后的 OOS 聚合绩效
              - 'oos_equity_curve': 拼接后的日频 OOS 净值曲线 (DataFrame)
        """
        windows = []
        oos_curves = []

        for start in range(0, max(0, len(data) - train_period - test_period + 1),
                           test_period):
            train_end = start + train_period
            test_end = train_end + test_period

            train_data = data.iloc[start:train_end]
            test_data = data.iloc[train_end:test_end]

            # 预热段: 各自窗口前的历史 (训练窗用训练窗前的, 测试窗用训练窗
            # 末尾那段 —— 即"测试窗之前最近的历史")
            train_warm = data.iloc[max(0, start - warmup_period):start]
            test_warm = data.iloc[max(0, train_end - warmup_period):train_end]

            # 在训练集上优化参数
            optimizer = ParameterOptimizer()
            best_params, _ = optimizer.grid_search(
                train_data, strategy_template, param_range,
                warmup_data=train_warm if len(train_warm) else None)

            # 在测试集上验证 (带预热 → 策略指标不冷启动)
            strategy = strategy_template(**best_params)
            engine = BacktestEngine()
            result = engine.run(
                test_data, strategy,
                warmup_data=test_warm if len(test_warm) else None)

            windows.append({
                'train_start': data.iloc[start]['日期'],
                'test_start': data.iloc[train_end]['日期'],
                'test_end': data.iloc[test_end]['日期'],
                'params': best_params,
                'result': result
            })
            oos_curves.append((data.iloc[train_end]['日期'], result))

        oos_curve, oos_summary = _stitch_oos_equity(oos_curves)

        return {
            'windows': windows,
            'oos': oos_summary,
            'oos_equity_curve': oos_curve,
        }


class PerformanceReport:
    """绩效报告生成器 - 增强版"""

    @staticmethod
    def generate_report(results: Dict, report_type: str = 'standard',
                       save_path: str = None) -> str:
        """
        生成回测报告

        Args:
            results: 回测结果字典
            report_type: 报告类型 (standard/detailed/summary)
            save_path: 保存路径(可选)

        Returns:
            报告文本
        """
        if report_type == 'detailed':
            return PerformanceReport._generate_detailed_report(results, save_path)
        elif report_type == 'summary':
            return PerformanceReport._generate_summary_report(results, save_path)
        else:
            return PerformanceReport._generate_standard_report(results, save_path)

    @staticmethod
    def _generate_standard_report(results: Dict, save_path: str = None) -> str:
        """生成标准报告"""
        report = []
        report.append("=" * 70)
        report.append("                      Backtest Performance Report")
        report.append("=" * 70)
        report.append("")

        # 基本信息统计
        report.append("[Basic Information]")
        report.append(f"  Symbol:              {results.get('symbol', 'N/A')}")
        report.append(f"  Initial Capital:     {results.get('initial_cash', 0):,.2f}")
        report.append(f"  Final Value:         {results.get('final_value', 0):,.2f}")
        report.append("")

        # 收益指标
        report.append("[Return Metrics]")
        report.append(f"  Total Return:        {results['total_return']:.2f}%")
        report.append(f"  Annualized Return:   {results.get('annualized_return', 0):.2f}%")
        report.append(f"  Benchmark Return:    {results['benchmark_return']:.2f}%")
        report.append(f"  Excess Return:       {results['excess_return']:.2f}%")
        report.append("")

        # 风险指标
        report.append("[Risk Metrics]")
        report.append(f"  Max Drawdown:        {results['max_drawdown']:.2f}%")
        report.append(f"  Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
        report.append(f"  Sortino Ratio:       {results.get('sortino_ratio', 0):.2f}")
        report.append(f"  Calmar Ratio:        {results.get('calmar_ratio', 0):.2f}")
        report.append("")

        # 交易统计
        report.append("[Trade Statistics]")
        report.append(f"  Total Trades:        {results['trade_count']}")
        report.append(f"  Win Rate:            {results['win_rate']:.2f}%")
        report.append(f"  Avg Profit:          {results['avg_profit']:.2f}%")
        report.append(f"  Avg Loss:            {results['avg_loss']:.2f}%")
        report.append(f"  Profit Factor:       {results['profit_factor']:.2f}")
        report.append("")

        report.append("=" * 70)

        return PerformanceReport._save_report(report, save_path)

    @staticmethod
    def _generate_detailed_report(results: Dict, save_path: str = None) -> str:
        """生成详细报告"""
        report = []
        report.append("=" * 80)
        report.append("                   Detailed Backtest Performance Report")
        report.append("=" * 80)
        report.append("")

        # 基本信息统计
        report.append("[Basic Information]")
        report.append(f"  Symbol:              {results.get('symbol', 'N/A')}")
        report.append(f"  Initial Capital:     {results.get('initial_cash', 0):,.2f}")
        report.append(f"  Final Value:         {results.get('final_value', 0):,.2f}")
        report.append("")

        # 收益指标
        report.append("[Return Metrics]")
        report.append(f"  Total Return:        {results['total_return']:.2f}%")
        report.append(f"  Annualized Return:   {results.get('annualized_return', 0):.2f}%")
        report.append(f"  Benchmark Return:    {results['benchmark_return']:.2f}%")
        report.append(f"  Excess Return:       {results['excess_return']:.2f}%")
        report.append("")

        # 风险指标
        report.append("[Risk Metrics]")
        report.append(f"  Max Drawdown:        {results['max_drawdown']:.2f}%")
        report.append(f"  Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
        report.append(f"  Sortino Ratio:       {results.get('sortino_ratio', 0):.2f}")
        report.append(f"  Calmar Ratio:        {results.get('calmar_ratio', 0):.2f}")
        report.append("")

        # 交易统计
        report.append("[Trade Statistics]")
        report.append(f"  Total Trades:        {results['trade_count']}")
        report.append(f"  Win Rate:            {results['win_rate']:.2f}%")
        report.append(f"  Avg Profit:          {results['avg_profit']:.2f}%")
        report.append(f"  Avg Loss:            {results['avg_loss']:.2f}%")
        report.append(f"  Profit Factor:       {results['profit_factor']:.2f}")
        report.append(f"  Max Profit:          {results.get('max_profit', 0):.2f}%")
        report.append(f"  Max Loss:            {results.get('max_loss', 0):.2f}%")
        report.append(f"  Avg Holding Days:    {results.get('avg_holding_days', 0):.1f}")
        report.append("")

        # 退出方式统计
        report.append("[Exit Analysis]")
        report.append(f"  Stop Loss Exits:     {results.get('stop_loss_count', 0)}")
        report.append(f"  Take Profit Exits:   {results.get('take_profit_count', 0)}")
        report.append(f"  Signal Exits:        {results.get('signal_exit_count', 0)}")
        report.append("")

        # 序列分析 (交易序列口径, 审计 B48/M1)
        report.append("[Streak Analysis]")
        report.append(f"  Max Consecutive Wins:    {results.get('max_consecutive_wins', 0)}  (trades)")
        report.append(f"  Max Consecutive Losses:  {results.get('max_consecutive_losses', 0)}  (trades)")
        report.append(f"  Max Consecutive Up Days:   {results.get('max_consecutive_up_days', 0)}  (daily equity)")
        report.append(f"  Max Consecutive Down Days: {results.get('max_consecutive_down_days', 0)}  (daily equity)")
        report.append("")

        # 最近交易记录
        if 'trades' in results and len(results['trades']) > 0:
            report.append("[Recent Trades]")
            recent_trades = results['trades'].tail(10)
            for _, trade in recent_trades.iterrows():
                action = trade['action'].upper()
                date = str(trade['date'])[:10]
                price = trade['price']
                shares = trade['shares']
                pnl = f"({trade.get('pnl_pct', 0):+.2f}%)" if 'pnl_pct' in trade else ""
                reason = f"[{trade.get('reason', 'signal')}]" if 'reason' in trade else ""
                report.append(f"  {date} {action:4s} {shares:4d} @ {price:7.2f} {pnl:12s} {reason}")
            report.append("")

        report.append("=" * 80)

        return PerformanceReport._save_report(report, save_path)

    @staticmethod
    def _generate_summary_report(results: Dict, save_path: str = None) -> str:
        """生成摘要报告"""
        report = []
        report.append("-" * 50)
        report.append(f"Backtest Summary: {results.get('symbol', 'N/A')}")
        report.append("-" * 50)
        report.append(f"Return: {results['total_return']:+.2f}%  |  "
                    f"Max DD: {results['max_drawdown']:.2f}%  |  "
                    f"Sharpe: {results['sharpe_ratio']:.2f}")
        report.append(f"Trades: {results['trade_count']}  |  "
                    f"Win Rate: {results['win_rate']:.1f}%  |  "
                    f"Profit Factor: {results['profit_factor']:.2f}")
        report.append("-" * 50)

        return PerformanceReport._save_report(report, save_path)

    @staticmethod
    def _save_report(report: list, save_path: str = None) -> str:
        """保存报告"""
        report_text = "\n".join(report)

        print(report_text)

        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(report_text)
            print(f"\nReport saved to: {save_path}")

        return report_text

    @staticmethod
    def compare_strategies(results_list: List[Dict], strategy_names: List[str] = None) -> str:
        """
        比较多个策略

        Args:
            results_list: 回测结果列表
            strategy_names: 策略名称列表

        Returns:
            比较报告
        """
        if strategy_names is None:
            strategy_names = [f"Strategy_{i+1}" for i in range(len(results_list))]

        report = []
        report.append("=" * 100)
        report.append("                           Strategy Comparison Report")
        report.append("=" * 100)
        report.append("")

        # 表头
        header = "{:<25} {:>12} {:>12} {:>10} {:>10} {:>10} {:>10}".format(
            "Strategy", "Return", "Max DD", "Sharpe", "Win Rate", "Trades", "Profit F"
        )
        report.append(header)
        report.append("-" * 100)

        # 每个策略的数据
        for i, (name, result) in enumerate(zip(strategy_names, results_list)):
            row = "{:<25} {:>10.2f}% {:>10.2f}% {:>10.2f} {:>9.1f}% {:>10} {:>10.2f}".format(
                name,
                result['total_return'],
                result['max_drawdown'],
                result['sharpe_ratio'],
                result['win_rate'],
                result['trade_count'],
                result['profit_factor']
            )
            report.append(row)

        report.append("=" * 100)

        return "\n".join(report)


# 预定义策略快捷方式
def ma_cross_strategy(fast=5, slow=20):
    return StrategyFactory.ma_cross(fast, slow)

def macd_strategy(fast=12, slow=26, signal=9):
    return StrategyFactory.macd_cross(fast, slow, signal)

def rsi_strategy(period=14, oversold=30, overbought=70):
    return StrategyFactory.rsi_overbought_oversold(period, oversold, overbought)

def bollinger_strategy(period=20, std=2):
    return StrategyFactory.bollinger_bands(period, std)


# 持仓配置快捷方式
def get_conservative_config() -> PositionConfig:
    """保守型配置 - 低仓位、严格止损"""
    return PositionConfig(
        sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
        sizing_value=0.5,              # 50%仓位
        max_position_pct=0.5,          # 单票上限=仓位 (审计项 20: 显式约束)
        stop_loss_method=StopLossMethod.PERCENTAGE,
        stop_loss_pct=0.05,            # 5%止损
        take_profit_pct=0.10,          # 10%止盈
        take_profit_enabled=True
    )


def get_balanced_config() -> PositionConfig:
    """平衡型配置 - 中等仓位、中等止损"""
    return PositionConfig(
        sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
        sizing_value=0.8,              # 80%仓位
        max_position_pct=0.8,          # 单票上限=仓位 (审计项 20: 显式约束)
        stop_loss_method=StopLossMethod.PERCENTAGE,
        stop_loss_pct=0.08,            # 8%止损
        take_profit_pct=0.20,          # 20%止盈
        take_profit_enabled=True
    )


def get_aggressive_config() -> PositionConfig:
    """激进型配置 - 高仓位、移动止损"""
    return PositionConfig(
        sizing_method=PositionSizingMethod.PERCENT_OF_EQUITY,
        sizing_value=0.95,             # 95%仓位
        max_position_pct=1.0,          # 显式声明满仓意图 (会触发 __post_init__ 警告)
        stop_loss_method=StopLossMethod.TRAILING,
        stop_loss_pct=0.10,            # 10%止损
        trailing_stop_pct=0.05,        # 5%移动止损
        take_profit_enabled=False      # 不设置止盈
    )


def get_kelly_config() -> PositionConfig:
    """凯利公式配置"""
    return PositionConfig(
        sizing_method=PositionSizingMethod.KELLY,
        max_position_pct=1.0,          # 显式声明满仓意图 (会触发 __post_init__ 警告)
        stop_loss_method=StopLossMethod.ATR,
        atr_multiplier=2.0,
        take_profit_pct=0.25,
        take_profit_enabled=True
    )


def run_backtest(data: pd.DataFrame, strategy: Callable,
                 symbol: str = "STOCK", initial_cash: float = 100000,
                 position_config: PositionConfig = None,
                 report_type: str = 'standard') -> Dict:
    """
    运行回测的便捷函数

    Args:
        data: 价格数据
        strategy: 策略函数
        symbol: 股票代码
        initial_cash: 初始资金
        position_config: 持仓配置
        report_type: 报告类型

    Returns:
        回测结果
    """
    config = position_config or get_balanced_config()
    engine = BacktestEngine(initial_cash=initial_cash, position_config=config)
    results = engine.run(data, strategy, symbol)
    PerformanceReport.generate_report(results, report_type)
    return results


if __name__ == "__main__":
    print("Backtesting Framework - Complete Version v2.0")
    print("\nAvailable Strategies:")
    print("- MA Cross:      均线交叉策略")
    print("- MACD Cross:    MACD交叉策略")
    print("- RSI OB/OS:     RSI超买超卖策略")
    print("- Bollinger:     布林带突破策略")
    print("- Multi-Signal:  多信号融合策略")
    print("\nPosition Sizing Methods:")
    print("- Fixed Amount:     固定金额")
    print("- Percent Equity:   权益百分比")
    print("- Fixed Shares:     固定股数")
    print("- Kelly:            凯利公式")
    print("- Volatility Target: 波动率目标")
    print("\nStop Loss Methods:")
    print("- Percentage:       百分比止损")
    print("- ATR:              ATR止损")
    print("- Trailing:         移动止损")
    print("\nOptimization Methods:")
    print("- Grid Search:      网格搜索")
    print("- Walk Forward:     滚动窗口优化")
    print("\nPerformance Metrics:")
    print("- Total Return, Annualized Return, Benchmark Return")
    print("- Max Drawdown, Sharpe Ratio, Sortino Ratio, Calmar Ratio")
    print("- Win Rate, Profit Factor, Avg Profit/Loss")
    print("- Max Consecutive Wins/Losses")
    print("\nQuick Start:")
    print("  from backtest_framework import run_backtest, ma_cross_strategy")
    print("  results = run_backtest(data, ma_cross_strategy(5, 20), '600519')")
