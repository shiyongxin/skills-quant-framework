# -*- coding: utf-8 -*-
"""
向量化回测引擎 - Vectorized Backtest Engine

专为参数优化设计的快速回测引擎。
- 向量化信号生成(无逐行循环)
- 简化仓位跟踪(固定仓位比例，百分比止损)
- 单股回测 ~10ms vs 现有BacktestEngine ~500ms

用途: 遗传算法优化中的大规模回测评估
"""

import itertools

import pandas as pd
import numpy as np
from dataclasses import dataclass

from execution_model import CostModel, buy_open_ok, sell_open_ok, sell_intraday_ok, limit_pct_for
from core.indicators import rsi as _core_rsi
from core import metrics as _core_metrics


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


@dataclass
class TradeDetail:
    """单笔交易详情"""
    entry_idx: int          # 入场日在原始数据中的索引
    exit_idx: int           # 出场日在原始数据中的索引
    entry_price: float
    exit_price: float
    pnl_pct: float          # 收益率(%)
    holding_days: int
    exit_reason: str        # "stop_loss" / "take_profit" / "signal" / "end"


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
        self.cost_model = CostModel.from_engine(commission, slippage)

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
        if len(data) < 15:
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

        # ---- RSI（core 权威口径）----
        rsi_period = int(params.get('rsi_period', 14))
        df['rsi'] = _core_rsi(close, rsi_period)

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

        # 跳过warmup期(短窗口自适应，最少10天)
        warmup = min(60, max(10, len(df) // 3))
        signals.iloc[:warmup] = 0

        return signals

    def backtest_with_details(self, data: pd.DataFrame, params: dict) -> tuple:
        """
        回测并返回交易详情 (用于按体制过滤)

        Returns:
        --------
        (BacktestMetrics, list[TradeDetail])
        """
        if len(data) < 15:
            return BacktestMetrics(), []

        df = self._compute_indicators(data, params)
        signals = self._generate_signals(df, params)
        return self._simulate_trades(df, signals, params, return_details=True)

    def _simulate_trades(self, df: pd.DataFrame, signals: pd.Series,
                         params: dict, return_details=False) -> BacktestMetrics:
        """
        模拟交易并计算指标 (t+1 开盘撮合 + A股完整成本 + 涨跌停约束)

        简化版本: 全仓进出，百分比止损止盈

        撮合规则:
        - 信号在 bar t 收盘 → 持仓在 bar t+1 开盘成交; 开盘涨停不买入
        - 硬止损: 日内触发, 跌停封板不可卖出(顺延), 跳空按开盘成交
        - 追踪止损: 仅用截至前一根的最高价(无同根高低点未来函数)
        - 止盈: 最小持有期后日内触发, 跳空按开盘成交
        - 卖讯: 下一根开盘成交, 开盘跌停则顺延至下一个可成交卖讯
        - 成本: 滑点+佣金+过户费(买) / 另加印花税(卖); 持有天数按自然日计
        """
        stop_loss_pct = float(params.get('stop_loss_pct', 0.08))
        take_profit_pct = float(params.get('take_profit_pct', 0.20))
        position_size_pct = float(params.get('position_size_pct', 0.8))
        trailing_stop_pct = float(params.get('trailing_stop_pct', 0.05))
        min_holding = int(params.get('min_holding_days', 20))
        is_st = bool(params.get('is_st', False))
        code = params.get('symbol') or params.get('code')

        open_arr = df['开盘'].values.astype(np.float64)
        close = df['收盘'].values.astype(np.float64)
        high_arr = df['最高'].values.astype(np.float64)
        low_arr = df['最低'].values.astype(np.float64)
        signals_arr = signals.values.astype(np.int8)

        dates = pd.to_datetime(df['日期']).values if '日期' in df.columns else None

        def _empty():
            # return_details 时须始终返回 (metrics, details) 元组, 否则调用方解包崩溃
            return (BacktestMetrics(), []) if return_details else BacktestMetrics()

        n = len(close)
        if n < 2:
            return _empty()

        cm = self.cost_model
        prev_close_all = np.r_[np.nan, close[:-1]]

        # 找出所有买入信号索引
        buy_indices = np.where(signals_arr == 1)[0]

        if len(buy_indices) == 0:
            return _empty()

        # 向量化处理所有交易
        trades_pnl = []
        trades_holding = []
        trades_reason = []
        trade_spans = []
        trade_details = [] if return_details else None

        for idx in range(len(buy_indices)):
            signal_idx = int(buy_indices[idx])
            entry_bar = signal_idx + 1
            if entry_bar >= n:
                continue  # 信号在最后一根, 无 t+1 可成交

            # t+1 开盘涨停(含一字板) → 买不进, 单次尝试失败即放弃
            if not bool(buy_open_ok(open_arr[entry_bar:entry_bar + 1],
                                    close[signal_idx:signal_idx + 1],
                                    code, is_st)[0]):
                continue

            # 入场价: 下一根开盘 + 滑点 + 买入成本(佣金+过户)
            entry_price = cm.buy_price_incl(float(open_arr[entry_bar]))

            # 止盈止损价格
            take_profit_price = entry_price * (1 + take_profit_pct)
            stop_price = entry_price * (1 - stop_loss_pct)

            # 确定本次持仓的结束位置(下次买入信号前或数据末尾)
            if idx + 1 < len(buy_indices):
                end_idx = int(buy_indices[idx + 1])
            else:
                end_idx = n
            if end_idx < entry_bar:
                end_idx = entry_bar

            g = np.arange(entry_bar, end_idx)
            exit_offset = None
            exit_reason = None
            gross_exit = None

            if len(g) == 0:
                # 连续买讯导致持仓区间为空: 持有一根, 收盘出场
                exit_offset = entry_bar
                exit_reason = 'end'
                gross_exit = float(close[entry_bar])
            else:
                l = g - entry_bar
                prev_c = prev_close_all[g]
                intraday_ok = sell_intraday_ok(open_arr[g], high_arr[g], low_arr[g],
                                               close[g], prev_c, code, is_st)

                # 1) 硬止损(全程含入场日; 入场在开盘, 日内低点在其后)
                hard_hit = (low_arr[g] <= stop_price) & intraday_ok

                # 2) 追踪止损(最高价仅截至前一根, 避免同根高低点未来函数;
                #    仅最小持有期后生效)
                cummax_prev = np.maximum.accumulate(np.r_[-np.inf, high_arr[g][:-1]])
                trail = cummax_prev * (1 - trailing_stop_pct)
                trail_hit = ((l >= min_holding) & (low_arr[g] <= trail) &
                             intraday_ok & np.isfinite(trail))

                # 3) 止盈(最小持有期后; 上行行情无跌停约束)
                tp_hit = (l >= min_holding) & (high_arr[g] >= take_profit_price)

                cands = []  # (成交bar, 优先级, 原因, 裸出场价)

                if hard_hit.any():
                    off = int(g[np.flatnonzero(hard_hit)[0]])
                    cands.append((off, 0, 'stop_loss',
                                  min(stop_price, float(open_arr[off]))))

                if trail_hit.any():
                    off = int(g[np.flatnonzero(trail_hit)[0]])
                    cands.append((off, 1, 'trailing_stop',
                                  min(float(trail[off - entry_bar]),
                                      float(open_arr[off]))))

                if tp_hit.any():
                    off = int(g[np.flatnonzero(tp_hit)[0]])
                    cands.append((off, 2, 'take_profit',
                                  max(take_profit_price, float(open_arr[off]))))

                # 4) 卖讯 → 下一根开盘; 开盘跌停则跳过该卖讯, 顺延下一个
                sig_bars = g[(signals_arr[g] == -1) & (l >= min_holding)]
                for s in sig_bars:
                    fill = int(s) + 1
                    if fill >= n:
                        break
                    if not bool(sell_open_ok(open_arr[fill:fill + 1],
                                             close[int(s):int(s) + 1],
                                             code, is_st)[0]):
                        continue
                    cands.append((fill, 3, 'signal', float(open_arr[fill])))
                    break  # 取第一个可成交的卖讯

                if cands:
                    # 时间优先; 同根bar按 止损>追踪>止盈>卖讯
                    cands.sort(key=lambda x: (x[0], x[1]))
                    exit_offset, _, exit_reason, gross_exit = cands[0]
                else:
                    # 持有到期末(或封板至期末): 按最后收盘出场
                    last_g = int(g[-1])
                    exit_offset = last_g
                    exit_reason = 'end'
                    gross_exit = float(close[last_g])

            # 出场价: 滑点 + 卖出成本(佣金+过户+印花税)
            exit_price = cm.sell_price_incl(gross_exit)

            # 计算收益
            pnl_pct = (exit_price / entry_price - 1) * 100

            # 持有天数按自然日(停牌区间不被压缩)
            if dates is not None:
                holding_days = int(
                    (pd.Timestamp(dates[exit_offset]) -
                     pd.Timestamp(dates[entry_bar])).days)
            else:
                holding_days = int(exit_offset - entry_bar)

            trades_pnl.append(pnl_pct)
            trades_holding.append(holding_days)
            trades_reason.append(exit_reason)
            trade_spans.append((int(entry_bar), int(exit_offset)))

            if return_details:
                trade_details.append(TradeDetail(
                    entry_idx=int(entry_bar),
                    exit_idx=int(exit_offset),
                    entry_price=float(entry_price),
                    exit_price=float(exit_price),
                    pnl_pct=float(pnl_pct),
                    holding_days=int(holding_days),
                    exit_reason=str(exit_reason) if exit_reason else "end",
                ))

        if len(trades_pnl) == 0:
            return _empty()

        # 转换为numpy数组进行向量化计算
        pnl_arr = np.array(trades_pnl, dtype=np.float64)
        holding_arr = np.array(trades_holding, dtype=np.float64)

        # 胜率
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr <= 0]
        win_rate = (len(wins) / len(pnl_arr)) * 100 if len(pnl_arr) > 0 else 0

        # 盈亏比（core 求和式口径，统一 A/B/优化器）
        profit_factor = _core_metrics.profit_factor(pnl_arr)

        # 总收益(复利, 逐笔含费口径) - 向量化
        cumulative = np.cumprod(1 + pnl_arr / 100 * position_size_pct)
        total_return = (cumulative[-1] - 1) * 100 if len(cumulative) > 0 else 0

        # 年化收益
        total_days = n
        years = total_days / 252
        if years > 0 and cumulative[-1] > 0:
            annualized_return = (cumulative[-1] ** (1 / years) - 1) * 100
        else:
            annualized_return = 0

        # 日频盯市净值（审计项9: 消除逐笔复利曲线对回撤的低估）
        # 在仓区间按 日收益×仓位 累乘; 入场日按 开盘→收盘(不含隔夜跳空),
        # 出场日仅保留隔夜跳空(按开盘成交)。近似口径, 仅用于 MDD/Sharpe。
        daily_ret = np.zeros(n)
        daily_ret[1:] = close[1:] / close[:-1] - 1
        for e, x in trade_spans:
            if e < n and open_arr[e] > 0:
                daily_ret[e] = close[e] / open_arr[e] - 1
            if x < n:
                daily_ret[x] = (open_arr[x] / close[x - 1] - 1) if x > 0 else 0.0
        held = np.zeros(n, dtype=bool)
        for e, x in trade_spans:
            held[e:x + 1] = True
        mtm = np.concatenate(
            [[1.0], np.cumprod(1 + daily_ret * position_size_pct * held)])

        max_drawdown = _core_metrics.max_drawdown_pct(mtm)

        # 夏普(core口径: 日频盯市收益, 年化252, rf=3%, ddof=1)
        sharpe = _core_metrics.sharpe_ratio(daily_ret * held,
                                            periods_per_year=252, rf=0.03)

        # 最大连续亏损 - 向量化
        is_loss = pnl_arr <= 0
        if np.any(is_loss):
            # 计算连续亏损
            loss_streaks = np.diff(np.where(np.concatenate([[False], is_loss, [False]]))[0])
            max_consec = int(loss_streaks.max()) if len(loss_streaks) > 0 else 0
        else:
            max_consec = 0

        metrics = BacktestMetrics(
            total_return=float(total_return),
            annualized_return=float(annualized_return),
            max_drawdown=float(max_drawdown),
            sharpe_ratio=float(sharpe),
            win_rate=float(win_rate),
            profit_factor=float(profit_factor),
            num_trades=len(trades_pnl),
            avg_holding_days=float(np.mean(holding_arr)),
            avg_return_per_trade=float(np.mean(pnl_arr)),
            max_consecutive_losses=max_consec
        )

        if return_details:
            return metrics, trade_details
        return metrics

    def walk_forward(self, data: pd.DataFrame, params: dict,
                     train_days=504, test_days=180, step_days=63,
                     param_space: dict = None) -> list:
        """
        单只股票的Walk-Forward验证（IS 拟合 / OOS 评估，审计项 17）。

        param_space: {参数名: [候选值, ...]}。给定时每个窗口先在训练窗
        网格搜索（最大化 Sharpe）拟合参数，再在测试窗用拟合参数评估，
        保证测试窗参数不含未来信息；为 None 时退化为固定参数滚动评估。

        Returns:
        --------
        list[BacktestMetrics] : 每个测试窗口的指标
        """
        if len(data) < train_days + test_days:
            return []

        def _fit_params(train_data: pd.DataFrame) -> dict:
            best_params, best_sharpe = params, -np.inf
            names = list(param_space.keys())
            for combo in itertools.product(*param_space.values()):
                candidate = {**params, **dict(zip(names, combo))}
                m = self.backtest(train_data, candidate)
                if m.sharpe_ratio > best_sharpe:
                    best_params, best_sharpe = candidate, m.sharpe_ratio
            return best_params

        results = []
        idx = train_days

        while idx + test_days <= len(data):
            test_data = data.iloc[idx:idx + test_days]
            if param_space:
                train_data = data.iloc[idx - train_days:idx]
                fitted = _fit_params(train_data)
            else:
                fitted = params
            metrics = self.backtest(test_data, fitted)
            results.append(metrics)
            idx += step_days

        return results
