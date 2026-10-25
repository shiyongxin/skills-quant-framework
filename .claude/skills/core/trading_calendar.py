# -*- coding: utf-8 -*-
"""交易日历与停牌识别（审计 C-P1-12 遗留项：停牌建模）。

背景与根本限制:
    A 股停牌日**没有行情行**——数据源里该日整行缺失，既没有"停牌=1"标记，
    也没有"该股无成交但有行"的形态。上一版（`trade_constraints` 的零成交
    末 bar 启发式）只能猜"最后一根没成交"，无法回答两个真问题:
        1) 这只票今天到底停牌了吗？（末 bar 之前就停了很久）
        2) 数据过期了几天？（按自然日算会把春节/国庆误判成停牌）

    解法: 用**指数行情**当交易日历的真相源——上证指数每个交易日都有行情行，
    个股停牌而指数照常交易。于是:
        - 交易日集合 = 指数行情的日期集合
        - 个股缺失的交易日 = 真停牌日（不是节假日）
        - "过期 N 个交易日" = 真正的停牌/数据陈旧度量（不再是自然日）

日历来源（按优先级，均为可选依赖，缺失时上层如实记 skipped_checks）:
    1. 显式传入: `TradingCalendar.from_index(index_df)` / `from_dates(dates)`
    2. 本地缓存: `data_dir/calendar/trading_days.json`（历史数据管理器的产物）
    3. akshare 官方交易日历 `tool_trade_date_hist_sina()`（需网络，可缓存落盘）

设计约束:
    - 不静默失败: 拿不到日历时返回 None / 空日历，调用方必须显式处理
    - 不臆造节假日: 没有指数数据就没有日历, 不做"周一到周五即交易日"的假设
      （A 股有调休上班的周末，也有整周假期）
"""
import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd


@dataclass
class TradingCalendar:
    """交易日历（不可变：交易日集合只读）。

    Attributes:
        days: 升序交易日列表 (datetime.date)
        source: 日历来源 (index/local/akshare/manual) — 供日志与审计
    """

    days: List = field(default_factory=list)
    source: str = 'unknown'

    def __post_init__(self):
        norm = []
        for d in self.days:
            if isinstance(d, pd.Timestamp):
                norm.append(d.date())
            elif isinstance(d, datetime):
                norm.append(d.date())
            else:
                norm.append(pd.Timestamp(d).date())
        self.days = sorted(set(norm))

    # ---------- 构造 ----------

    @classmethod
    def from_dates(cls, dates: Iterable, source: str = 'manual'
                   ) -> "TradingCalendar":
        return cls(days=list(dates), source=source)

    @classmethod
    def from_index(cls, index_df: pd.DataFrame,
                   date_col: str = '日期') -> Optional["TradingCalendar"]:
        """从指数行情构造日历（指数每个交易日都有行）。

        Args:
            index_df: 含日期列的指数行情
            date_col: 日期列名

        Returns:
            TradingCalendar; 无有效日期时返回 None（不返回空日历假装可用）
        """
        if index_df is None or len(index_df) == 0:
            return None
        if date_col in index_df.columns:
            series = index_df[date_col]
        elif isinstance(index_df.index, pd.DatetimeIndex):
            series = pd.Series(index_df.index, index=index_df.index)
        else:
            return None
        dates = pd.to_datetime(series, errors='coerce').dropna()
        if len(dates) == 0:
            return None
        return cls(days=list(pd.DatetimeIndex(dates).normalize()), source='index')

    @classmethod
    def from_local_cache(cls, path: Optional[Path] = None,
                         data_dir: str = './stock_data') -> Optional["TradingCalendar"]:
        """从本地缓存 JSON 读取日历（历史数据管理器写入）。"""
        if path is None:
            path = Path(data_dir) / 'calendar' / 'trading_days.json'
        path = Path(path)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return None
        days = raw.get('trading_days') if isinstance(raw, dict) else raw
        if not days:
            return None
        return cls(days=list(days), source=raw.get('source', 'local')
                   if isinstance(raw, dict) else 'local')

    @classmethod
    def from_akshare(cls, data_dir: str = './stock_data',
                     allow_network: bool = True) -> Optional["TradingCalendar"]:
        """用 akshare 官方交易日历构造（需网络；结果落盘缓存）。

        失败返回 None（调用方如实记 skipped_checks，不臆造日历）。
        """
        if not allow_network:
            return None
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
        except Exception:
            return None
        if df is None or len(df) == 0:
            return None
        col = 'trade_date' if 'trade_date' in df.columns else df.columns[0]
        days = pd.to_datetime(df[col], errors='coerce').dropna()
        if len(days) == 0:
            return None
        cal = cls(days=list(pd.DatetimeIndex(days).normalize()), source='akshare')
        cal.save(data_dir=data_dir)
        return cal

    # ---------- 持久化 ----------

    def save(self, data_dir: str = './stock_data') -> Path:
        """落盘缓存（供离线复用）。"""
        path = Path(data_dir) / 'calendar' / 'trading_days.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            'source': self.source,
            'trading_days': [d.isoformat() for d in self.days],
        }, ensure_ascii=False), encoding='utf-8')
        return path

    # ---------- 查询 ----------

    def __len__(self) -> int:
        return len(self.days)

    def __bool__(self) -> bool:
        return bool(self.days)

    @property
    def first_day(self):
        return self.days[0] if self.days else None

    @property
    def last_day(self):
        return self.days[-1] if self.days else None

    def is_trading_day(self, day) -> bool:
        try:
            return pd.Timestamp(day).date() in set(self.days)
        except (ValueError, TypeError):
            return False

    def trading_days_between(self, start, end) -> List:
        """[start, end] 区间内的交易日列表（含端点）。"""
        try:
            lo = pd.Timestamp(start).date()
            hi = pd.Timestamp(end).date()
        except (ValueError, TypeError):
            return []
        i = bisect_left(self.days, lo)
        j = bisect_right(self.days, hi)
        return self.days[i:j]

    def latest_trading_day(self, on_or_before=None):
        """<= on_or_before 的最近交易日（None → 日历最后一天）。"""
        if not self.days:
            return None
        if on_or_before is None:
            return self.days[-1]
        try:
            hi = pd.Timestamp(on_or_before).date()
        except (ValueError, TypeError):
            return None
        j = bisect_right(self.days, hi)
        return self.days[j - 1] if j > 0 else None

    def trading_days_since(self, last_date, as_of) -> Optional[int]:
        """(last_date, as_of] 之间缺失的交易日数 —— 停牌/过期度量。

        Returns:
            None: as_of 之前没有任何交易日（as_of 太早或日历不含该区间）
            int: 缺失的交易日数（0 = 数据是最新的）
        """
        if not self.days:
            return None
        try:
            lo = pd.Timestamp(last_date).date()
            hi = pd.Timestamp(as_of).date()
        except (ValueError, TypeError):
            return None
        if hi < lo:
            return 0
        return len(self.trading_days_between(
            pd.Timestamp(lo) + pd.Timedelta(days=1), hi))

    def missing_trading_days(self, stock_dates: Sequence, start, end) -> List:
        """个股在 [start, end] 内缺失的交易日 = 真停牌日。

        Args:
            stock_dates: 个股已有行情的日期序列
            start/end: 区间端点

        Returns:
            缺失交易日列表（按升序）
        """
        have = set()
        for d in stock_dates:
            try:
                have.add(pd.Timestamp(d).date())
            except (ValueError, TypeError):
                continue
        return [d for d in self.trading_days_between(start, end)
                if d not in have]


# ==================== 模块级日历缓存 ====================

_CALENDAR: Optional[TradingCalendar] = None


def set_calendar(calendar: Optional[TradingCalendar]) -> None:
    """注入进程级日历（由上层在启动/首次取数后设置）。"""
    global _CALENDAR
    _CALENDAR = calendar


def get_calendar(refresh: bool = False) -> Optional[TradingCalendar]:
    """取进程级日历；未注入时尝试本地缓存 (不联网，避免隐式网络依赖)。"""
    global _CALENDAR
    if _CALENDAR is None or refresh:
        _CALENDAR = TradingCalendar.from_local_cache()
    return _CALENDAR


def ensure_calendar(data_dir: str = './stock_data',
                    refresh: bool = False) -> Optional[TradingCalendar]:
    """确保进程内有可用日历 (三级来源, 全部失败则 None)。

    1. 已注入的进程级日历
    2. 本地缓存 JSON (stock_data/calendar/trading_days.json)
    3. 本地指数 parquet (000001) 现算 —— 指数每交易日有行 → 交易日集合

    不联网: akshare 日历需网络, 由部署方显式调用
    `TradingCalendar.from_akshare()` 落盘后本函数即可命中第 2 级。
    """
    global _CALENDAR
    if _CALENDAR is not None and not refresh:
        return _CALENDAR
    cached = TradingCalendar.from_local_cache(data_dir=data_dir)
    if cached is not None:
        _CALENDAR = cached
        return cached
    # 本地指数 parquet (晚导入, 避免与历史数据管理器循环依赖)
    try:
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=data_dir)
        index_df = mgr.load('000001')
        if index_df is not None and len(index_df) > 0:
            cal = build_calendar_from_index(index_df, data_dir=data_dir)
            if cal is not None:
                return cal
    except Exception:
        pass
    return None


def build_calendar_from_index(index_df: Optional[pd.DataFrame],
                              data_dir: str = './stock_data'
                              ) -> Optional[TradingCalendar]:
    """由指数行情构建日历并注入进程级缓存（含落盘）。

    指数数据缺失 → 返回 None（不臆造）。
    """
    cal = TradingCalendar.from_index(index_df) if index_df is not None else None
    if cal is None:
        return None
    try:
        cal.save(data_dir=data_dir)
    except OSError:
        pass
    set_calendar(cal)
    return cal


__all__ = ['TradingCalendar', 'build_calendar_from_index', 'ensure_calendar',
           'get_calendar', 'set_calendar']
