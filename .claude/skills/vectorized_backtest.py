# -*- coding: utf-8 -*-
"""
向量化回测引擎 - Vectorized Backtest Engine

专为参数优化设计的快速回测引擎。
- 向量化信号生成(无逐行循环)
- 简化仓位跟踪(固定仓位比例，百分比止损)
- 单股回测 ~10ms vs 现有BacktestEngine ~500ms
- 成交容量约束 (审计 B14/H7): 单笔买入 ≤ 当日成交额 × 参与率 (默认 5%),
  容量不足则部分成交 (逐笔仓位比例可变) —— 成交量不再只用于信号打分

用途: 遗传算法优化中的大规模回测评估
"""

import itertools

import pandas as pd
import numpy as np
from dataclasses import dataclass

from execution_model import (CostModel, buy_open_ok, sell_open_ok, sell_intraday_ok,
                            DEFAULT_MAX_VOLUME_PARTICIPATION, capacity_limit_notional)
from core.indicator_engine import IndicatorEngine
from core import metrics as _core_metrics

# 信号 warmup 上限 (审计 B23/H8③): _generate_signals 的 warmup 恒 ≤ 此值,
# walk_forward 用它作为窗口前历史段长度, 保证 warmup 只落在历史段
WARMUP_MAX_BARS = 60


def warmup_bars(n: int) -> int:
    """信号 warmup 长度 (短窗口自适应, 上限 60) — 原内联公式唯一来源"""
    return min(WARMUP_MAX_BARS, max(10, n // 3))


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
    max_consecutive_losses: int = 0 # 最大连续亏损笔数 (交易序列口径, 审计 B48/M1)
    max_consecutive_wins: int = 0   # 最大连续盈利笔数 (交易序列口径, 审计 B48/M1)


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
    position_pct: float = 0.0  # 本笔实际仓位比例 (成交容量约束可能小于配置值)


def metrics_from_trades(pnl_arr, holding_arr, trade_spans, close, open_arr,
                        position_size_pct) -> BacktestMetrics:
    """从交易序列构建 BacktestMetrics（指标口径统一真相源, 审计 E-P1）。

    - 盈亏比: core 求和式; 最大回撤: core 正值% (日频盯市净值, 非逐笔序列)
    - 夏普: core 日频盯市收益, 年化252, rf=3%, ddof=1 (不再用逐笔收益冒充日频)
    - 总收益: 逐笔复利(仓位系数); 年化分母 = 时间轴 bar 数 (调用方决定评估窗口:
      B 引擎 = 回测窗全长; 优化器体制过滤路径 = 过滤后交易的暴露跨度)
    - trade_spans: [(entry, exit)] 相对 close/open 时间轴的 bar 下标
    - 日频盯市近似: 入场日 开盘→收盘(不含隔夜跳空), 出场日仅保留隔夜跳空;
      仅用于 MDD/Sharpe, 不改 total_return
    - position_size_pct: 标量(统一仓位比例) 或**逐笔数组** (成交容量约束
      导致部分成交时每笔比例不同, 审计 B14/H7)。全部相等时走标量路径,
      数值与旧版逐位一致。
    """
    pnl_arr = np.asarray(pnl_arr, dtype=np.float64)
    holding_arr = np.asarray(holding_arr, dtype=np.float64)
    if pnl_arr.size == 0:
        return BacktestMetrics()

    frac_arr = np.asarray(position_size_pct, dtype=np.float64)
    scalar_frac = frac_arr.ndim == 0
    if scalar_frac:
        frac = float(frac_arr)
    else:
        frac = frac_arr.reshape(-1)
        if frac.size == pnl_arr.size and np.all(frac == frac[0]):
            # 各笔比例相同 → 退化为标量路径 (与旧版逐位一致)
            frac = float(frac[0])
            scalar_frac = True
        elif frac.size != pnl_arr.size:
            frac = np.full(pnl_arr.shape, float(frac[-1]) if frac.size else 0.0)

    n = len(close)

    # 胜率 (core 统一口径: 盈亏为 0 计入分母但不算赢, 审计 M1)
    win_rate = _core_metrics.win_rate(pnl_arr)

    # 盈亏比（core 求和式口径，统一 A/B/优化器）
    profit_factor = _core_metrics.profit_factor(pnl_arr)

    # 总收益(复利, 逐笔含费口径)
    cumulative = np.cumprod(1 + pnl_arr / 100 * frac)
    total_return = (cumulative[-1] - 1) * 100 if len(cumulative) > 0 else 0

    # 年化收益
    years = n / 252
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
    if scalar_frac:
        mtm = np.concatenate(
            [[1.0], np.cumprod(1 + daily_ret * frac * held)])
    else:
        # 逐笔仓位比例 → 每根 bar 用其所属持仓的比例
        exposure = np.zeros(n, dtype=np.float64)
        for idx, (e, x) in enumerate(trade_spans):
            if e < n:
                exposure[e:x + 1] = frac[idx] if idx < frac.size else 0.0
        mtm = np.concatenate(
            [[1.0], np.cumprod(1 + daily_ret * exposure)])

    max_drawdown = _core_metrics.max_drawdown_pct(mtm)

    # 夏普(core口径: 日频盯市收益, 年化252, rf=3%, ddof=1)
    sharpe = _core_metrics.sharpe_ratio(daily_ret * held,
                                        periods_per_year=252, rf=0.03)

    # 最大连胜/连亏 (core 统一口径: **交易序列**, breakeven 不算赢也不算亏,
    # 旧实现用 pnl<=0 把 breakeven 当亏损 → 与引擎 A 分歧, 审计 B48/M1)
    max_consec_wins, max_consec = _core_metrics.consecutive_streaks(pnl_arr)

    return BacktestMetrics(
        total_return=float(total_return),
        annualized_return=float(annualized_return),
        max_drawdown=float(max_drawdown),
        sharpe_ratio=float(sharpe),
        win_rate=float(win_rate),
        profit_factor=float(profit_factor),
        num_trades=int(pnl_arr.size),
        avg_holding_days=float(np.mean(holding_arr)) if holding_arr.size else 0.0,
        avg_return_per_trade=float(np.mean(pnl_arr)),
        max_consecutive_losses=max_consec,
        max_consecutive_wins=max_consec_wins
    )


def weighted_factor_scores(df: pd.DataFrame, params: dict) -> tuple:
    """
    4 因子加权评分 (0-100 连续买卖分), 审计 E-P1 死维度接线 (P1-1)。

    移植已删 web_backtest.calculate_weighted_score 的评分制语义, 向量化:
      trend   : MA 多头排列(+40) / 仅 fast>slow(+20) + MACD 多头(+40)
                + 上穿慢线(+20), 封顶 100 (排列与 fast>slow 互斥, 同原版 elif)
      mom     : RSI14 阶梯 (<30→90, <50→70, <70→40, 否则 10; 缺数视为 50→40)
                + K>D 且 K<80 (+10), 封顶 100
      risk    : 布林带位置倒置 (1-pos)*100 — 越靠近下轨分越高;
                带宽退化/缺数 → 50
      perf    : 50 + ret5*500 clip [0,100] (前收缺失 → 50)
    卖方子分 = 100 - 买方子分 (web_backtest 同构镜像);
    总分 = Σ w_i·子分_i / Σw (wsum<=0 时按 100 归一)。
    仅用截至当 bar 的状态 — 无未来函数。

    Returns:
    --------
    (buy_score, sell_score) : 均为 0-100 的 pd.Series
    """
    w_trend = float(params.get('w_trend', 30))
    w_momentum = float(params.get('w_momentum', 25))
    w_risk = float(params.get('w_risk', 15))
    w_performance = float(params.get('w_performance', 30))
    wsum = w_trend + w_momentum + w_risk + w_performance
    if wsum <= 0:
        wsum = 100.0

    close = df['收盘']

    # ---- trend_bull ----
    trend_bull = pd.Series(0.0, index=df.index)
    ma_align = (df['ma_fast'] > df['ma_mid']) & (df['ma_mid'] > df['ma_slow'])
    trend_bull += ma_align.astype(float) * 40
    trend_bull += ((~ma_align) & (df['ma_fast'] > df['ma_slow'])).astype(float) * 20
    trend_bull += (df['macd'] > df['macd_signal']).astype(float) * 40
    cross_up = (close > df['ma_slow']) & (close.shift(1) <= df['ma_slow'].shift(1))
    trend_bull += cross_up.astype(float) * 20
    trend_bull = trend_bull.clip(0, 100)

    # ---- momentum_bull ----
    rsi = df['rsi'].fillna(50)
    mom_bull = pd.Series(
        np.select([rsi < 30, rsi < 50, rsi < 70], [90.0, 70.0, 40.0],
                  default=10.0),
        index=df.index, dtype=float)
    kdj_up = (df['k'] > df['d']) & (df['k'] < 80)
    mom_bull = (mom_bull + kdj_up.astype(float) * 10).clip(0, 100)

    # ---- risk_bull ----
    bb_range = df['bb_upper'] - df['bb_lower']
    bb_pos = ((close - df['bb_lower']) / bb_range.replace(0, np.nan)).clip(0, 1)
    risk_bull = ((1 - bb_pos) * 100).fillna(50.0)

    # ---- performance_bull ----
    prev_close = close.shift(1)
    ret5 = (close / prev_close - 1).where(prev_close > 0)
    perf_bull = (50 + ret5 * 500).clip(0, 100).fillna(50.0)

    # ---- 加权归一 (卖方 = 100 - 买方镜像) ----
    buy_score = (w_trend * trend_bull + w_momentum * mom_bull
                 + w_risk * risk_bull + w_performance * perf_bull) / wsum
    sell_score = (w_trend * (100 - trend_bull)
                  + w_momentum * (100 - mom_bull)
                  + w_risk * (100 - risk_bull)
                  + w_performance * (100 - perf_bull)) / wsum
    return buy_score, sell_score


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

    def backtest(self, data: pd.DataFrame, params: dict,
                 history: pd.DataFrame = None) -> BacktestMetrics:
        """
        对单只股票运行回测

        Parameters:
        -----------
        data : pd.DataFrame
            历史数据，必须包含: 日期, 开盘, 最高, 最低, 收盘, 成交量
        params : dict
            参数字典，来自ParameterSpace。
            成交容量相关 (审计 B14/H7):
              - max_volume_participation: 单笔买入 ≤ 当日成交额 × 该比例
                (默认 0.05; 0 = 关闭约束)
              - capital: 名义资金 (默认 100 万), 仅用于把仓位比例折算成金额
        history : pd.DataFrame, optional (审计 B23/H8③)
            窗口前历史段。给定时与 data 拼接后计算指标与信号 —— 每窗重置的
            warmup 只落在历史段 (段长 ≥ warmup 上限 60 时窗口内信号不被清零),
            再切回 data 段模拟交易。None 时行为与旧版逐位一致。

        Returns:
        --------
        BacktestMetrics
        """
        if len(data) < 15:
            return BacktestMetrics()

        if history is not None and len(history) > 0:
            ext = pd.concat([history, data]).reset_index(drop=True)
            df = self._compute_indicators(ext, params)
            signals = self._generate_signals(df, params)
            h = len(history)
            df = df.iloc[h:]
            signals = signals.iloc[h:]
        else:
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
        # 共享指标引擎 (审计 #10): 公式唯一来源 core.indicators
        eng = IndicatorEngine(df)

        # ---- 移动平均线 ----
        ma_fast_period = int(params.get('ma_fast', 5))
        ma_slow_period = int(params.get('ma_slow', 20))
        ma_mid_period = int(params.get('ma_mid', 10))

        df['ma_fast'] = eng.ma(ma_fast_period)
        df['ma_slow'] = eng.ma(ma_slow_period)
        df['ma_mid'] = eng.ma(ma_mid_period)

        # ---- MACD ----
        macd_fast = int(params.get('macd_fast', 12))
        macd_slow = int(params.get('macd_slow', 26))
        macd_signal_period = int(params.get('macd_signal', 9))

        dif, dea, hist = eng.macd(macd_fast, macd_slow, macd_signal_period)
        df['macd'], df['macd_signal'], df['macd_hist'] = dif, dea, hist

        # ---- RSI（core 权威口径）----
        rsi_period = int(params.get('rsi_period', 14))
        df['rsi'] = eng.rsi(rsi_period)

        # ---- KDJ ----
        kdj_n = int(params.get('kdj_n', 9))
        k, d, j = eng.kdj(kdj_n)
        df['k'], df['d'], df['j'] = k, d, j

        # ---- 布林带 ----
        bb_period = int(params.get('bb_period', 20))
        bb_std_mult = float(params.get('bb_std', 2.0))
        upper, middle, lower, _std = eng.bollinger(bb_period, bb_std_mult)
        df['bb_mid'] = middle
        df['bb_upper'] = upper
        df['bb_lower'] = lower

        # ---- ATR (core Wilder 单一真相源; 旧: SMA14) ----
        atr_period = int(params.get('atr_period', 14))
        df['atr'] = eng.atr(atr_period)

        # ---- 成交量均线 ----
        df['vol_ma5'] = eng.volume_ma(5)
        df['vol_ma20'] = eng.volume_ma(20)

        # ---- 涨跌幅 ----
        df['ret_1d'] = close.pct_change() * 100
        df['ret_5d'] = close.pct_change(5) * 100
        df['ret_20d'] = close.pct_change(20) * 100

        return df

    def _generate_signals(self, df: pd.DataFrame, params: dict) -> pd.Series:
        """
        向量化生成买卖信号

        双模式 (审计 E-P1 死维度接线):
        - 投票制 (默认): 各指标事件加权点数 vs buy/sell_threshold (旧基线)
        - 评分制 (use_weighted_scoring=True): 4 因子 0-100 加权分
          vs score_buy/sell_threshold, 状态触发

        Returns:
        --------
        pd.Series : 1=买入, -1=卖出, 0=持有
        """
        if bool(params.get('use_weighted_scoring', False)):
            w_buy, w_sell = weighted_factor_scores(df, params)
            score_buy_threshold = float(params.get('score_buy_threshold', 60.0))
            score_sell_threshold = float(params.get('score_sell_threshold', 35.0))

            signals = pd.Series(0, index=df.index)
            signals[w_buy >= score_buy_threshold] = 1
            signals[w_sell >= score_sell_threshold] = -1
            conflict = ((w_buy >= score_buy_threshold)
                        & (w_sell >= score_sell_threshold))
            signals[conflict] = -1

            signals.iloc[:warmup_bars(len(df))] = 0
            return signals

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

        # 跳过warmup期(短窗口自适应，最多60根; 公式见 warmup_bars)
        signals.iloc[:warmup_bars(len(df))] = 0

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
        - 持仓状态机 (审计 B21/H8①): 持仓期间的新买讯**忽略** (不再把上一笔
          切成 0 持仓日伪交易); 持仓期只由出场规则结束
        - 硬止损: 日内触发, 跌停封板不可卖出(顺延), 跳空按开盘成交
        - 追踪止损: 仅用截至前一根的最高价(无同根高低点未来函数)
        - 止盈: 最小持有期后日内触发, 跳空按开盘成交
        - 卖讯: 下一根开盘成交, 开盘跌停则顺延至下一个可成交卖讯
        - 成本: 滑点+佣金+过户费(买) / 另加印花税(卖); 持有天数按自然日计
        """
        stop_loss_pct = float(params.get('stop_loss_pct', 0.08))
        take_profit_pct = float(params.get('take_profit_pct', 0.20))
        position_size_pct = float(params.get('position_size_pct', 0.8))
        # 单票仓位硬上限 (审计项 20): 默认1.0不改变历史行为;
        # 显式传入时与 position_size_pct 取小
        max_position_pct = float(params.get('max_position_pct', 1.0))
        position_size_pct = min(position_size_pct, max_position_pct)
        trailing_stop_pct = float(params.get('trailing_stop_pct', 0.05))
        # 最小持有期默认 0 = 不锁 (审计 B22/H8②): 旧默认 20 让锁定期内只有
        # 硬止损生效 (追踪/止盈/卖讯全部失效), 且 A 引擎无此概念 → 三引擎
        # 口径不一致; 显式配置时仍作为锁定期语义生效
        min_holding = int(params.get('min_holding_days', 0))
        # 成交容量约束 (审计 B14/H7): 单笔买入金额 ≤ 当日成交额 × 参与率;
        # capital = 名义资金 (仅用于把仓位比例折算成金额, 默认 100 万/股)
        participation = float(params.get('max_volume_participation',
                                         DEFAULT_MAX_VOLUME_PARTICIPATION))
        capital = float(params.get('capital', 1_000_000))
        is_st = bool(params.get('is_st', False))
        code = params.get('symbol') or params.get('code')

        open_arr = df['开盘'].values.astype(np.float64)
        close = df['收盘'].values.astype(np.float64)
        high_arr = df['最高'].values.astype(np.float64)
        low_arr = df['最低'].values.astype(np.float64)
        signals_arr = signals.values.astype(np.int8)

        # 当日成交额 (容量约束用): 优先 '成交额' 列, 缺失时用 成交量×收盘价 近似
        # (假设成交量单位为股 —— repo 的 data_cleaner 已把 手/股 归一为股)
        turnover_arr = None
        if '成交额' in df.columns:
            turnover_arr = df['成交额'].values.astype(np.float64)
        elif '成交量' in df.columns:
            turnover_arr = df['成交量'].values.astype(np.float64) * close

        dates = pd.to_datetime(df['日期']).values if '日期' in df.columns else None

        def _empty():
            # return_details 时须始终返回 (metrics, details) 元组, 否则调用方解包崩溃
            return (BacktestMetrics(), []) if return_details else BacktestMetrics()

        n = len(close)
        if n < 2:
            return _empty()

        cm = self.cost_model
        prev_close_all = np.r_[np.nan, close[:-1]]

        # ---- 持仓状态机 (审计 B21/H8①) ----
        # 旧实现: 用"下一次买入信号"切分持仓期 → 密集买讯会把上一笔切成
        # 0 根 bar (0 持仓日伪交易), 交易数/胜率/Sharpe 全部失真。
        # 新实现: 空仓时遇买讯 → 次根开盘入场; 持仓期间的新买讯**忽略**;
        # 持仓期只由出场规则 (硬止损/追踪止损/止盈/卖讯/期末) 结束。
        # 与 A 引擎口径一致 (A: 买入仅当无持仓)。
        trades_pnl = []
        trades_holding = []
        trades_reason = []
        trade_spans = []
        trades_frac = []   # 每笔实际仓位比例 (容量约束可能部分成交)
        trade_details = [] if return_details else None

        i = 0
        while i < n:
            if signals_arr[i] != 1:
                i += 1
                continue

            signal_idx = i
            entry_bar = signal_idx + 1
            if entry_bar >= n:
                break  # 信号在最后一根, 无 t+1 可成交

            # t+1 开盘涨停(含一字板) → 买不进, 单次尝试失败即放弃
            if not bool(buy_open_ok(open_arr[entry_bar:entry_bar + 1],
                                    close[signal_idx:signal_idx + 1],
                                    code, is_st)[0]):
                i += 1
                continue

            # 成交容量约束 (审计 B14/H7): 本笔最多成交 当日成交额×参与率
            eff_fraction = position_size_pct
            if participation > 0 and turnover_arr is not None and capital > 0:
                cap_notional = capacity_limit_notional(
                    float(turnover_arr[entry_bar]), participation)
                if cap_notional is not None:
                    eff_fraction = min(position_size_pct,
                                       cap_notional / capital)
                    if eff_fraction <= 0:
                        # 当日零成交 → 买不进 (与引擎 A 同口径)
                        i += 1
                        continue

            # 入场价: 下一根开盘 + 滑点 + 买入成本(佣金+过户)
            entry_price = cm.buy_price_incl(float(open_arr[entry_bar]))

            # 止盈止损价格
            take_profit_price = entry_price * (1 + take_profit_pct)
            stop_price = entry_price * (1 - stop_loss_pct)

            # 出场扫描: 从入场根到数据末尾 (首次触发者成交)
            g = np.arange(entry_bar, n)
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
            trades_frac.append(float(eff_fraction))

            if return_details:
                trade_details.append(TradeDetail(
                    entry_idx=int(entry_bar),
                    exit_idx=int(exit_offset),
                    entry_price=float(entry_price),
                    exit_price=float(exit_price),
                    pnl_pct=float(pnl_pct),
                    holding_days=int(holding_days),
                    exit_reason=str(exit_reason) if exit_reason else "end",
                    position_pct=float(eff_fraction),
                ))

            # 扫描续点: 持仓期内(入场根~出场根)的买讯已被忽略;
            # 出场根当天的买讯仍有效 (收盘出信号, 次根开盘再入场)
            i = exit_offset

        if len(trades_pnl) == 0:
            return _empty()

        # 指标统一口径 (审计 E-P1: 共享 metrics_from_trades, 消除复制块)
        pnl_arr = np.array(trades_pnl, dtype=np.float64)
        holding_arr = np.array(trades_holding, dtype=np.float64)
        # 逐笔仓位比例 (容量约束可能部分成交; 全部相等时 metrics 走标量路径)
        frac_arr = np.array(trades_frac, dtype=np.float64)
        metrics = metrics_from_trades(pnl_arr, holding_arr, trade_spans,
                                      close, open_arr, frac_arr)

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

        warmup 跨窗口继承 (审计 B23/H8③): 每个窗口回测时把窗口**之前**的
        历史段 (最多 60 根 = warmup 上限) 作为 history 传入, 指标与信号在
        [历史+窗口] 上计算后再切回窗口段 —— 每窗重置的 warmup 不再吃掉
        OOS 窗口的前 1/3 (旧版: 180 根测试窗前 60 根信号被强制清零,
        同参数全样本 12 笔 vs OOS 切片 6 笔, Sharpe -1.452 vs -6.972)。

        Returns:
        --------
        list[BacktestMetrics] : 每个测试窗口的指标
        """
        if len(data) < train_days + test_days:
            return []

        def _history(start: int) -> pd.DataFrame:
            """窗口前历史段 (warmup 落点), 不足则取全部可用"""
            return data.iloc[max(0, start - WARMUP_MAX_BARS):start]

        def _fit_params(train_data: pd.DataFrame, history) -> dict:
            best_params, best_sharpe = params, -np.inf
            names = list(param_space.keys())
            for combo in itertools.product(*param_space.values()):
                candidate = {**params, **dict(zip(names, combo))}
                m = self.backtest(train_data, candidate, history=history)
                if m.sharpe_ratio > best_sharpe:
                    best_params, best_sharpe = candidate, m.sharpe_ratio
            return best_params

        results = []
        idx = train_days

        while idx + test_days <= len(data):
            test_data = data.iloc[idx:idx + test_days]
            if param_space:
                train_start = idx - train_days
                train_data = data.iloc[train_start:idx]
                fitted = _fit_params(train_data, _history(train_start))
            else:
                fitted = params
            metrics = self.backtest(test_data, fitted, history=_history(idx))
            results.append(metrics)
            idx += step_days

        return results
