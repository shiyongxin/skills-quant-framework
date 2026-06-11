# -*- coding: utf-8 -*-
"""
向量化回测引擎 - Vectorized Backtest Engine

专为参数优化设计的快速回测引擎。
- 向量化信号生成(无逐行循环)
- 简化仓位跟踪(固定仓位比例，百分比止损)
- 单股回测 ~10ms vs 现有BacktestEngine ~500ms

用途: 遗传算法优化中的大规模回测评估
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class BacktestMetrics:
    """回测结果指标"""
    total_return: float = 0.0       # 总收益率(%)
    annualized_return: float = 0.0  # 年化收益率(%)
    max_drawdown: float = 0.0       # 最大回撤(%)
    sharpe_ratio: float = 0.0       # 夏普比率
    win_rate: float = 0.0           # 胜率(%)
    profit_factor: float = 0.0      # 盈亏比
    num_trades: int = 0             # 交易次数
    avg_holding_days: float = 0.0   # 平均持有天数
    avg_return_per_trade: float = 0.0  # 平均每笔收益(%)
    max_consecutive_losses: int = 0 # 最大连续亏损次数


class VectorizedBacktester:
    """
    向量化回测引擎

    快速计算指标→生成信号→模拟交易→返回指标
    专为优化场景设计，牺牲细节换取速度。
    """

    def __init__(self, commission=0.0003, slippage=0.001):
        """
        Parameters:
        -----------
        commission : float
            佣金率(双边)
        slippage : float
            滑点率
        """
        self.commission = commission
        self.slippage = slippage

    def backtest(self, data: pd.DataFrame, params: dict) -> BacktestMetrics:
        """
        对单只股票运行回测

        Parameters:
        -----------
        data : pd.DataFrame
            历史数据，必须包含: 日期, 开盘, 最高, 最低, 收盘, 成交量
        params : dict
            参数字典，来自ParameterSpace

        Returns:
        --------
        BacktestMetrics
        """
        if len(data) < 60:
            return BacktestMetrics()

        # Step 1: 计算指标
        df = self._compute_indicators(data, params)

        # Step 2: 生成信号
        signals = self._generate_signals(df, params)

        # Step 3: 模拟交易
        return self._simulate_trades(df, signals, params)

    def backtest_batch(self, stock_data_dict: dict, params: dict) -> pd.DataFrame:
        """
        同一参数回测多只股票

        Parameters:
        -----------
        stock_data_dict : dict
            {symbol: DataFrame}
        params : dict
            参数字典

        Returns:
        --------
        pd.DataFrame : 每只股票一行，包含各项指标
        """
        results = []
        for symbol, data in stock_data_dict.items():
            try:
                metrics = self.backtest(data, params)
                result = {
                    'symbol': symbol,
                    'total_return': metrics.total_return,
                    'annualized_return': metrics.annualized_return,
                    'max_drawdown': metrics.max_drawdown,
                    'sharpe_ratio': metrics.sharpe_ratio,
                    'win_rate': metrics.win_rate,
                    'profit_factor': metrics.profit_factor,
                    'num_trades': metrics.num_trades,
                    'avg_holding_days': metrics.avg_holding_days,
                    'avg_return_per_trade': metrics.avg_return_per_trade,
                }
                results.append(result)
            except Exception:
                pass  # 静默跳过失败股票

        return pd.DataFrame(results)

    def _compute_indicators(self, data: pd.DataFrame, params: dict) -> pd.DataFrame:
        """计算所有技术指标(向量化)"""
        df = data.copy()
        close = df['收盘'].astype(float)
        high = df['最高'].astype(float)
        low = df['最低'].astype(float)
        volume = df['成交量'].astype(float)

        # ---- 移动平均线 ----
        ma_fast_period = int(params.get('ma_fast', 5))
        ma_slow_period = int(params.get('ma_slow', 20))
        ma_mid_period = int(params.get('ma_mid', 10))

        df['ma_fast'] = close.rolling(ma_fast_period).mean()
        df['ma_slow'] = close.rolling(ma_slow_period).mean()
        df['ma_mid'] = close.rolling(ma_mid_period).mean()

        # ---- MACD ----
        macd_fast = int(params.get('macd_fast', 12))
        macd_slow = int(params.get('macd_slow', 26))
        macd_signal_period = int(params.get('macd_signal', 9))

        ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=macd_signal_period, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # ---- RSI ----
        rsi_period = int(params.get('rsi_period', 14))
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))

        # ---- KDJ ----
        kdj_n = int(params.get('kdj_n', 9))
        low_n = low.rolling(kdj_n).min()
        high_n = high.rolling(kdj_n).max()
        rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        df['k'] = rsv.ewm(span=3, adjust=False).mean()
        df['d'] = df['k'].ewm(span=3, adjust=False).mean()
        df['j'] = 3 * df['k'] - 2 * df['d']

        # ---- 布林带 ----
        bb_period = int(params.get('bb_period', 20))
        bb_std_mult = float(params.get('bb_std', 2.0))
        df['bb_mid'] = close.rolling(bb_period).mean()
        bb_std = close.rolling(bb_period).std()
        df['bb_upper'] = df['bb_mid'] + bb_std_mult * bb_std
        df['bb_lower'] = df['bb_mid'] - bb_std_mult * bb_std

        # ---- ATR ----
        atr_period = int(params.get('atr_period', 14))
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(atr_period).mean()

        # ---- 成交量均线 ----
        df['vol_ma5'] = volume.rolling(5).mean()
        df['vol_ma20'] = volume.rolling(20).mean()

        # ---- 涨跌幅 ----
        df['ret_1d'] = close.pct_change() * 100
        df['ret_5d'] = close.pct_change(5) * 100
        df['ret_20d'] = close.pct_change(20) * 100

        return df

    def _generate_signals(self, df: pd.DataFrame, params: dict) -> pd.Series:
        """
        向量化生成买卖信号

        Returns:
        --------
        pd.Series : 1=买入, -1=卖出, 0=持有
        """
        buy_threshold = float(params.get('buy_threshold', 2.0))
        sell_threshold = float(params.get('sell_threshold', 2.0))
        rsi_oversold = float(params.get('rsi_oversold', 30))
        rsi_overbought = float(params.get('rsi_overbought', 70))

        # ---- 买入信号得分 ----
        buy_score = pd.Series(0.0, index=df.index)

        # MA金叉: fast上穿slow
        ma_cross_up = (df['ma_fast'] > df['ma_slow']) & (df['ma_fast'].shift(1) <= df['ma_slow'].shift(1))
        buy_score += ma_cross_up.astype(float) * 1.0

        # 价格站上MA慢线
        price_above_slow = df['收盘'] > df['ma_slow']
        buy_score += price_above_slow.astype(float) * 0.3

        # MACD金叉
        macd_cross_up = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
        buy_score += macd_cross_up.astype(float) * 1.0

        # MACD柱由负转正
        macd_hist_turn_pos = (df['macd_hist'] > 0) & (df['macd_hist'].shift(1) <= 0)
        buy_score += macd_hist_turn_pos.astype(float) * 0.5

        # RSI超卖
        rsi_oversold_signal = df['rsi'] < rsi_oversold
        buy_score += rsi_oversold_signal.astype(float) * 0.5

        # KDJ金叉
        kdj_cross_up = (df['k'] > df['d']) & (df['k'].shift(1) <= df['d'].shift(1))
        buy_score += kdj_cross_up.astype(float) * 0.8

        # 触及布林下轨后回升
        bb_lower_touch = (df['收盘'] <= df['bb_lower'] * 1.02) & (df['收盘'] > df['bb_lower'] * 0.98)
        buy_score += bb_lower_touch.astype(float) * 0.5

        # 放量(成交量>5日均量1.5倍)
        volume_surge = df['成交量'] > df['vol_ma5'] * 1.5
        buy_score += volume_surge.astype(float) * 0.3

        # ---- 卖出信号得分 ----
        sell_score = pd.Series(0.0, index=df.index)

        # MA死叉
        ma_cross_down = (df['ma_fast'] < df['ma_slow']) & (df['ma_fast'].shift(1) >= df['ma_slow'].shift(1))
        sell_score += ma_cross_down.astype(float) * 1.0

        # 价格跌破MA慢线
        price_below_slow = df['收盘'] < df['ma_slow']
        sell_score += price_below_slow.astype(float) * 0.3

        # MACD死叉
        macd_cross_down = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))
        sell_score += macd_cross_down.astype(float) * 1.0

        # RSI超买
        rsi_overbought_signal = df['rsi'] > rsi_overbought
        sell_score += rsi_overbought_signal.astype(float) * 0.5

        # KDJ死叉
        kdj_cross_down = (df['k'] < df['d']) & (df['k'].shift(1) >= df['d'].shift(1))
        sell_score += kdj_cross_down.astype(float) * 0.8

        # 触及布林上轨
        bb_upper_touch = (df['收盘'] >= df['bb_upper'] * 0.98) & (df['收盘'] < df['bb_upper'] * 1.02)
        sell_score += bb_upper_touch.astype(float) * 0.5

        # ---- 生成最终信号 ----
        signals = pd.Series(0, index=df.index)
        signals[buy_score >= buy_threshold] = 1
        signals[sell_score >= sell_threshold] = -1

        # 如果同一天既有买入又有卖出，卖出优先
        conflict = (buy_score >= buy_threshold) & (sell_score >= sell_threshold)
        signals[conflict] = -1

        # 跳过前60行(指标计算需要warmup)
        signals.iloc[:60] = 0

        return signals

    def _simulate_trades(self, df: pd.DataFrame, signals: pd.Series,
                         params: dict) -> BacktestMetrics:
        """
        模拟交易并计算指标

        简化版本: 全仓进出，百分比止损止盈
        """
        stop_loss_pct = float(params.get('stop_loss_pct', 0.08))
        take_profit_pct = float(params.get('take_profit_pct', 0.20))
        position_size_pct = float(params.get('position_size_pct', 0.8))
        trailing_stop_pct = float(params.get('trailing_stop_pct', 0.05))

        close = df['收盘'].values
        high_arr = df['最高'].values
        low_arr = df['最低'].values

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        highest_since_entry = 0

        for i in range(len(close)):
            if not in_position:
                # 检查买入信号
                if signals.iloc[i] == 1:
                    entry_price = close[i] * (1 + self.slippage + self.commission)
                    entry_idx = i
                    highest_since_entry = close[i]
                    in_position = True
            else:
                # 更新最高价
                highest_since_entry = max(highest_since_entry, high_arr[i])

                # 检查止损
                stop_price = entry_price * (1 - stop_loss_pct)
                # 检查追踪止损
                trailing_stop = highest_since_entry * (1 - trailing_stop_pct)
                effective_stop = max(stop_price, trailing_stop)

                # 检查止盈
                take_profit_price = entry_price * (1 + take_profit_pct)

                should_exit = False
                exit_reason = ""

                # 止损触发(用最低价检查)
                if low_arr[i] <= effective_stop:
                    exit_price = effective_stop
                    should_exit = True
                    exit_reason = "stop_loss"

                # 止盈触发(用最高价检查)
                elif high_arr[i] >= take_profit_price:
                    exit_price = take_profit_price
                    should_exit = True
                    exit_reason = "take_profit"

                # 卖出信号
                elif signals.iloc[i] == -1:
                    exit_price = close[i] * (1 - self.slippage - self.commission)
                    should_exit = True
                    exit_reason = "signal"

                if should_exit:
                    pnl_pct = (exit_price / entry_price - 1) * 100
                    holding_days = i - entry_idx
                    trades.append({
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_pct': pnl_pct,
                        'holding_days': holding_days,
                        'reason': exit_reason
                    })
                    in_position = False

        # 计算指标
        if not trades:
            return BacktestMetrics()

        pnl_list = [t['pnl_pct'] for t in trades]
        holding_list = [t['holding_days'] for t in trades]

        # 胜率
        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p <= 0]
        win_rate = len(wins) / len(pnl_list) * 100 if pnl_list else 0

        # 盈亏比
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 1
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

        # 总收益(复利)
        cumulative = 1.0
        for p in pnl_list:
            cumulative *= (1 + p / 100 * position_size_pct)
        total_return = (cumulative - 1) * 100

        # 年化收益
        total_days = len(df)
        years = total_days / 252
        if years > 0 and cumulative > 0:
            annualized_return = (cumulative ** (1 / years) - 1) * 100
        else:
            annualized_return = 0

        # 最大回撤(基于权益曲线)
        equity = [1.0]
        for p in pnl_list:
            equity.append(equity[-1] * (1 + p / 100 * position_size_pct))
        equity = np.array(equity)
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak * 100
        max_drawdown = abs(drawdown.min())

        # 夏普比率
        if len(pnl_list) > 1:
            daily_returns = np.array(pnl_list) / 100
            avg_ret = np.mean(daily_returns) * 252 / np.mean(holding_list) if np.mean(holding_list) > 0 else 0
            std_ret = np.std(daily_returns) * np.sqrt(252 / np.mean(holding_list)) if np.mean(holding_list) > 0 else 1
            sharpe = (avg_ret - 0.03) / std_ret if std_ret > 0 else 0
        else:
            sharpe = 0

        # 最大连续亏损
        max_consec = 0
        current_consec = 0
        for p in pnl_list:
            if p <= 0:
                current_consec += 1
                max_consec = max(max_consec, current_consec)
            else:
                current_consec = 0

        return BacktestMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            profit_factor=profit_factor,
            num_trades=len(trades),
            avg_holding_days=np.mean(holding_list) if holding_list else 0,
            avg_return_per_trade=np.mean(pnl_list) if pnl_list else 0,
            max_consecutive_losses=max_consec
        )

    def walk_forward(self, data: pd.DataFrame, params: dict,
                     train_days=504, test_days=180, step_days=63) -> list:
        """
        单只股票的Walk-Forward验证

        Returns:
        --------
        list[BacktestMetrics] : 每个测试窗口的指标
        """
        if len(data) < train_days + test_days:
            return []

        results = []
        idx = train_days

        while idx + test_days <= len(data):
            test_data = data.iloc[idx:idx + test_days]
            metrics = self.backtest(test_data, params)
            results.append(metrics)
            idx += step_days

        return results
