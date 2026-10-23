# -*- coding: utf-8 -*-
"""L1 选股层共享因子库 — 原始因子计算的单一真相源

审计 #11 / C-P1-11: 三套选股器 (multi_factor_selection / stock_selector /
long_term_selector) 各自重复实现动量、波动率等原始因子。本模块收敛为
**只算原始因子值** 的叶子库:

  - 不做标准化 (z-score 是 MFS 横截面引擎的职责)
  - 不做阈值打分 (0-100 绝对分是 SS 打分引擎的职责)
  - 方向语义登记在 FACTOR_REGISTRY, 由各引擎按自己的刻度应用

设计边界 (docs/skills_layers.md 决策):
  - 打分引擎分立: SS 保留绝对分 (回答"本身好不好"), MFS 保留横截面
    z-score (回答"比同池好多少") — 二者回答不同问题, 不合并
  - 本库只统一 raw 计算 + 方向性元数据

方向枚举:
  - HIGHER_BETTER: 越大越好 (动量)
  - LOWER_BETTER: 越小越好 (波动率、回撤)
  - BAND: 区间偏好 (SS 波动率 15-40% 带, 由 SS 打分层实现)

已知方向性遗留 (不在本步修复, 见 AGENTS.md): MFS volatility_factor 中
Volatility/Downside_Vol 取负后"越高越好", 而 Max_Drawdown 以正值幅度存储
导致同块内方向不一致 — 本库如实返回正值幅度, MFS 保持原存法以维持行为等价。
"""

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

HIGHER_BETTER = 'higher_better'
LOWER_BETTER = 'lower_better'
BAND = 'band'


@dataclass(frozen=True)
class FactorMeta:
    """因子元数据: 名称 / 方向 / 单位 / 说明"""
    name: str
    direction: str
    unit: str
    description: str


FACTOR_REGISTRY: Dict[str, FactorMeta] = {
    'momentum': FactorMeta(
        'momentum', HIGHER_BETTER, 'decimal',
        '过去 N 日收益率 (小数). SS 用 20 日, MFS 用 20/60/120 日'),
    'realized_volatility': FactorMeta(
        'realized_volatility', LOWER_BETTER, 'decimal',
        '已实现波动率 (日频 std, 未年化). SS 打分层自行年化×100'),
    'downside_volatility': FactorMeta(
        'downside_volatility', LOWER_BETTER, 'decimal',
        '下行波动率 (仅负收益 std)'),
    'max_drawdown': FactorMeta(
        'max_drawdown', LOWER_BETTER, 'decimal',
        '窗口内最大回撤幅度 (正值 = 回撤越深)'),
    'volume_ratio': FactorMeta(
        'volume_ratio', HIGHER_BETTER, 'ratio',
        '最新成交量 / 近 N 日均量'),
}


def to_close_panel(price_df) -> Optional[pd.DataFrame]:
    """将价格输入归一化为"股票×日期"横截面面板 (index=股票码, columns=日期)。

    支持两种形态:
      - 宽面板: price_df['收盘'] 为 DataFrame (index=日期, columns=股票码)
      - 堆叠行: price_df['收盘'] 为 MultiIndex Series ((股票,日期) 或
        (日期,股票), 日期层级为 datetime)
    单股时序、无法识别日期层级等输入无法构成横截面, 返回 None。
    """
    close = price_df['收盘']
    if isinstance(close, pd.DataFrame):
        return close.T

    if isinstance(close, pd.Series) and isinstance(close.index, pd.MultiIndex):
        date_level = None
        for i in range(close.index.nlevels):
            if pd.api.types.is_datetime64_any_dtype(close.index.levels[i].dtype):
                date_level = i
                break
        if date_level is None:
            return None
        return close.unstack(level=date_level)

    return None


# ---------------------------------------------------------------------------
# 单票时序层 (stock_selector 使用; 输入单只股票的 Series)
# ---------------------------------------------------------------------------

def momentum_pct(close: pd.Series, period: int = 20) -> float:
    """单票 N 日动量 (百分比): (close[-1] / close[-1-period] - 1) * 100。

    历史长度不足 period+1 时与旧内联写法一致抛 IndexError
    (调用方 SS 在 try/except 内跳过该票)。
    """
    return (close.iloc[-1] / close.iloc[-1 - period] - 1) * 100


def annualized_volatility_pct(close: pd.Series) -> float:
    """单票全历史年化波动率 (百分比): std(pct_change) * sqrt(252) * 100。"""
    returns = close.pct_change().dropna()
    return returns.std() * np.sqrt(252) * 100


def volume_ratio(volume: pd.Series, window: int = 5) -> float:
    """量比: 最新成交量 / 近 window 日均量。"""
    ma = volume.iloc[-window:].mean()
    return volume.iloc[-1] / ma


def volume_ma(volume: pd.Series, window: int = 5) -> float:
    """近 window 日均成交量 (供打分层自行比较, 避免 v/ma 与 v>ma*k 的浮点边界差异)。"""
    return volume.iloc[-window:].mean()


# ---------------------------------------------------------------------------
# 横截面面板层 (multi_factor_selection 使用; 输入 index=股票 columns=日期)
# 返回原始值 (未标准化, 未取负) — 标准化/方向应用留给调用引擎。
# ---------------------------------------------------------------------------

def momentum_panel(panel: pd.DataFrame,
                   periods=(20, 60, 120)) -> pd.DataFrame:
    """横截面各周期原始收益率 (小数, 未标准化)。

    Args:
        panel: index=股票码, columns=日期 的收盘面板
        periods: 周期列表; 历史长度不足的周期跳过

    Returns:
        columns=Momentum_{period} 的原始收益 DataFrame;
        无任何合格周期时返回空表 (0, 0) (与旧 MFS 行为一致)
    """
    factors = pd.DataFrame()
    if panel is None or panel.shape[1] == 0:
        return factors

    for period in periods:
        if panel.shape[1] > period:
            factors[f'Momentum_{period}'] = panel.pct_change(
                period, axis=1).iloc[:, -1]
    return factors


def realized_volatility_panel(panel: pd.DataFrame,
                              period: int = 20) -> pd.Series:
    """横截面滚动已实现波动率 (正值, 日频 std, 未年化未标准化)。

    pandas 3 rolling 无 axis 参数 → 沿用转置后沿日期轴滚动的既有写法。
    """
    returns = panel.pct_change(axis=1)
    return returns.T.rolling(period).std().iloc[-1]


def downside_volatility_panel(panel: pd.DataFrame,
                              period: int = 20) -> pd.Series:
    """横截面下行波动率 (正值): 近 period 日负收益的标准差。"""
    returns = panel.pct_change(axis=1)
    tail = returns.iloc[:, -period:]
    return tail.clip(upper=0).std(axis=1)


def max_drawdown_panel(panel: pd.DataFrame,
                       period: int = 20) -> pd.Series:
    """横截面滚动最大回撤幅度 (正值 = 回撤越深)。

    与旧 MFS 表达式逐位一致: -drawdown.T.rolling(period).min().iloc[-1]
    (drawdown ≤ 0, 取窗口最深回撤后取负得正值幅度)。
    """
    cummax = panel.cummax(axis=1)
    drawdown = (panel - cummax) / cummax
    return -drawdown.T.rolling(period).min().iloc[-1]
