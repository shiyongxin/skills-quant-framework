# -*- coding: utf-8 -*-
"""
停牌建模 —— 回测引擎侧单一真相源 (审计 H5)。

背景 (审计原文):
- 停牌建模此前**只落在信号层** (`trade_constraints` + `core/trading_calendar`),
  4 套回测引擎 (`backtest_framework` / `vectorized_backtest` /
  `reversal_backtest` / `historical_backtest_validator`) 对停牌**零感知**:
  引擎只遍历个股自身的行情行, 停牌日自然没有行 → 于是
  ① "停牌期间持仓无法平仓" 从未被显式建模;
  ② 持仓跨停牌的跳空敞口在任何指标里都看不见;
  ③ 以 **bar 数** 为单位的期限口径 (年化分母 / 持有天数) 会被停牌
     **静默压扁** —— 停牌 10 天, 年化分母仍按 bar 数算 → 年化收益与
     夏普被**虚高** (真实时间流逝了, 引擎却当没发生)。

本模块提供:
- `SuspensionModel`: 由**真实交易日历** + 个股行情行推导真停牌日
  (个股在日历中有、自身无行) —— 不猜、不造日历, 复用
  `TradingCalendar.missing_trading_days` (日历经已排除节假日);
- `trading_day_index`: 交易日 → bar 下标的**前向填充**映射 —— 停牌日
  沿用上一根 bar (无价格即无 P&L, 这是精确口径) → 下游把时间轴换成
  **交易日轴**, 年化分母与夏普随之修正;
- 停牌日的可成交性判定与持仓跨停牌敞口计数。

刻意不做的事 (避免制造新的口径冒充):
- **不把停牌日补成平盘行再算指标** —— 那样 MA/RSI 等指标窗口会被
  "无成交的假 bar"污染 (复牌日的均线就错了)。指标仍在**真实 bar**
  上计算, 只把**时间轴**换成交易日轴。

诚实边界:
- **无日历 = 无停牌建模** (引擎如实记 `suspension_modeled=False`),
  绝不以自然日差或 bar 数差臆造停牌;
- 日历覆盖不到个股数据区间时, 只在日历覆盖区间内判定, 超出部分
  不猜测 (引擎回退旧口径并如实标记);
- "个股在日历中有、自身无行" = 停牌**或数据缺失** —— 二者在数据侧
  无法区分, 因此本模块的命名与报告均如实写明 (与 `trade_constraints`
  的"停牌或数据缺失"口径一致)。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

from .trading_calendar import TradingCalendar

__all__ = ['SuspensionModel', 'trading_day_index']


@dataclass
class SuspensionModel:
    """真停牌日模型 (审计 H5) —— 由交易日历 + 个股行情行推导。

    Attributes:
        calendar: 交易日历 (真相源)
        suspended_days: 真停牌交易日集合 (个股无行但日历有)
        first_day/last_day: 判定区间 (个股行情的首末交易日)
        tradable_mask: 逐"日历交易日"的可成交标记 (False = 停牌)
        calendar_days: 判定区间内的交易日列表 (与 tradable_mask 同序)
    """

    calendar: TradingCalendar
    suspended_days: frozenset = field(default_factory=frozenset)
    first_day: Optional[object] = None
    last_day: Optional[object] = None
    calendar_days: List = field(default_factory=list)
    tradable_mask: List = field(default_factory=list)

    # ---------- 构造 ----------

    @classmethod
    def build(cls, calendar: Optional[TradingCalendar],
              stock_dates: Sequence,
              start=None, end=None) -> Optional['SuspensionModel']:
        """由日历 + 个股行情日期构造停牌模型。

        Args:
            calendar: 交易日历 (None → 不建模, 返回 None)
            stock_dates: 个股已有行情的日期序列
            start/end: 判定区间端点 (None → 用个股首末行情日)

        Returns:
            SuspensionModel 或 None (无日历 / 个股无行情)
        """
        if calendar is None or not getattr(calendar, 'days', None):
            return None
        dates = []
        for d in stock_dates or []:
            try:
                dates.append(pd.Timestamp(d).date())
            except (ValueError, TypeError):
                continue
        if not dates:
            return None
        lo = pd.Timestamp(start).date() if start is not None else min(dates)
        hi = pd.Timestamp(end).date() if end is not None else max(dates)
        if hi < lo:
            return None
        cal_days = calendar.trading_days_between(lo, hi)
        if not cal_days:
            return None
        have = set(dates)
        suspended = frozenset(d for d in cal_days if d not in have)
        return cls(
            calendar=calendar,
            suspended_days=suspended,
            first_day=lo,
            last_day=hi,
            calendar_days=list(cal_days),
            tradable_mask=[d not in suspended for d in cal_days],
        )

    # ---------- 判定 ----------

    def is_suspended(self, day) -> bool:
        """该日是否停牌 (个股无行情但日历有)。"""
        try:
            return pd.Timestamp(day).date() in self.suspended_days
        except (ValueError, TypeError):
            return False

    def is_tradable(self, day) -> bool:
        """该日是否可成交 (非停牌)。"""
        return not self.is_suspended(day)

    def trading_day_count(self, start=None, end=None) -> int:
        """区间内交易日数 (日历口径; 无端点 → 整个判定区间)。"""
        lo = pd.Timestamp(start).date() if start is not None else self.first_day
        hi = pd.Timestamp(end).date() if end is not None else self.last_day
        if lo is None or hi is None:
            return 0
        return len(self.calendar.trading_days_between(lo, hi))

    def suspended_days_between(self, start, end) -> int:
        """区间内真停牌交易日数 (持仓跨停牌敞口)。"""
        try:
            lo = pd.Timestamp(start).date()
            hi = pd.Timestamp(end).date()
        except (ValueError, TypeError):
            return 0
        if hi < lo:
            return 0
        return sum(1 for d in self.calendar.trading_days_between(lo, hi)
                   if d in self.suspended_days)

    def next_tradable_after(self, day):
        """给定交易日之后 (含当日) 的第一个可交易日; 无则 None。"""
        try:
            lo = pd.Timestamp(day).date()
        except (ValueError, TypeError):
            return None
        for d in self.calendar.trading_days_between(lo, self.calendar.last_day):
            if d not in self.suspended_days:
                return d
        return None


def trading_day_index(calendar: Optional[TradingCalendar],
                      dates: Sequence) -> Optional[np.ndarray]:
    """交易日 → bar 下标 的**前向填充**映射 (审计 H5)。

    返回数组: 每个交易日对应的"当日或之前最近一根 bar"的下标。
    停牌日 (个股无 bar) → 沿用上一根 bar 的下标 → 该交易日的市值/价格
    视为不变 (无价格即无 P&L, 这是精确口径, 不是近似)。

    Args:
        calendar: 交易日历 (None → 返回 None, 调用方按"未建模"处理)
        dates: 个股行情日期序列 (升序)

    Returns:
        np.ndarray (int) 或 None
    """
    if calendar is None or not getattr(calendar, 'days', None):
        return None
    if dates is None or len(dates) == 0:
        return None
    try:
        have = np.array(pd.to_datetime(list(dates)).values)
    except (ValueError, TypeError):
        return None
    if have.size == 0:
        return None
    tdays = calendar.trading_days_between(
        pd.Timestamp(have[0]).date(), pd.Timestamp(have[-1]).date())
    if not tdays:
        return None
    want = np.array(pd.to_datetime(list(tdays)).values)
    idx = np.searchsorted(have, want, side='right') - 1
    return np.clip(idx, 0, have.size - 1).astype(np.int64)
