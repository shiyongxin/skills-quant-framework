# -*- coding: utf-8 -*-
"""绩效指标统一口径（审计路线图项 9：消除同名字段不同义）。

约定:
- profit_factor: 求和式 = sum(盈利笔) / |sum(亏损笔)|；无交易或无亏损 → 0。
- max_drawdown: 正值百分比（回撤幅度）；输入为盯市净值序列。
- sharpe_ratio: 年化无风险利率以小数传入（默认 0.03）；样本标准差 ddof=1。
- win_rate: 盈利笔数 / 全部交易笔数；盈亏为 0 计入分母但**不算赢**。
- consecutive_streaks: **交易序列**上的最大连胜/连亏笔数（审计 B48/M1）。
"""
import numpy as np


def profit_factor(pnl_pct) -> float:
    """求和式盈亏比。pnl_pct: 各笔交易收益率（%）。"""
    arr = np.asarray(list(pnl_pct), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    loss_sum = losses.sum()
    if len(losses) == 0 or loss_sum == 0:
        return 0.0
    return float(abs(wins.sum() / loss_sum)) if len(wins) else 0.0


def max_drawdown_pct(equity) -> float:
    """最大回撤（正值 %）。equity: 盯市净值序列（可含初始 1.0）。"""
    eq = np.asarray(equity, dtype=np.float64)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    with np.errstate(divide='ignore', invalid='ignore'):
        drawdown = (eq - peak) / peak * 100
    drawdown = drawdown[np.isfinite(drawdown)]
    if drawdown.size == 0:
        return 0.0
    return float(abs(drawdown.min()))


def sharpe_ratio(returns, periods_per_year: int = 252,
                 rf: float = 0.03, ddof: int = 1) -> float:
    """年化 Sharpe = (mean*rpy - rf) / (std*rpy**0.5)。

    returns: 每期收益率（小数，如 0.01 = 1%）；NaN 自动剔除；样本 std ddof=1。
    """
    arr = np.asarray(list(returns), dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return 0.0
    std = arr.std(ddof=ddof)
    if not np.isfinite(std) or std < 1e-12:
        return 0.0
    return float((arr.mean() * periods_per_year - rf) / (std * np.sqrt(periods_per_year)))


def win_rate(pnl_pct) -> float:
    """胜率 = 盈利笔数 / 全部交易笔数 × 100。

    约定（审计 M1 统一）：盈亏为 0（breakeven）**计入分母但不算赢**。
    与 profit_factor 的"亏损侧含 0"不同 —— 后者为避免除零把 0 归入亏损，
    这里是分类口径，两者互不矛盾。

    pnl_pct: 各笔交易收益率（%）。空序列 → 0.0。
    """
    arr = np.asarray(list(pnl_pct), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    wins = int((arr > 0).sum())
    return float(wins / arr.size * 100)


def consecutive_streaks(pnl_pct) -> tuple:
    """交易序列上的最大连胜 / 最大连亏笔数。

    约定（审计 B48/M1 统一）：
    - 赢 = pnl > 0；亏 = pnl < 0；**breakeven (pnl == 0) 两者都不算**，
      因此同时打断连胜与连亏（旧引擎 B 用 pnl <= 0 把 breakeven 当亏损）。
    - 基准是**交易序列**（不是日频净值序列）—— 旧引擎 A 在净值曲线上统计，
      同名字段两套口径。

    Returns:
    --------
    (max_consecutive_wins, max_consecutive_losses): (int, int)
    """
    arr = np.asarray(list(pnl_pct), dtype=np.float64)
    if arr.size == 0:
        return 0, 0
    max_wins = max_losses = 0
    cur_wins = cur_losses = 0
    for value in arr:
        if value > 0:
            cur_wins += 1
            cur_losses = 0
            if cur_wins > max_wins:
                max_wins = cur_wins
        elif value < 0:
            cur_losses += 1
            cur_wins = 0
            if cur_losses > max_losses:
                max_losses = cur_losses
        else:
            cur_wins = 0
            cur_losses = 0
    return int(max_wins), int(max_losses)


def max_consecutive_true(flags) -> int:
    """布尔序列中连续 True 的最长长度。

    用于日频序列统计（如连涨/连跌 bar 数）：False（含持平）打断连段。
    """
    best = 0
    current = 0
    for flag in np.asarray(list(flags), dtype=bool):
        if flag:
            current += 1
            if current > best:
                best = current
        else:
            current = 0
    return int(best)
