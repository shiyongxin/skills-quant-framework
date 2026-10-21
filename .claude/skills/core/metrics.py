# -*- coding: utf-8 -*-
"""绩效指标统一口径（审计路线图项 9：消除同名字段不同义）。

约定:
- profit_factor: 求和式 = sum(盈利笔) / |sum(亏损笔)|；无交易或无亏损 → 0。
- max_drawdown: 正值百分比（回撤幅度）；输入为盯市净值序列。
- sharpe_ratio: 年化无风险利率以小数传入（默认 0.03）；样本标准差 ddof=1。
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
