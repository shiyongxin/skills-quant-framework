# -*- coding: utf-8 -*-
"""core — 单一真相源：权威指标与绩效口径（审计路线图项 8/9）+ FetchResult（项 11）
+ 统一信号输出契约 Signal/Selection（审计 C #9a/#9b, 项 21）
+ 共享技术指标引擎 IndicatorEngine（审计 C #10, 项 21）。"""

from .fetch_result import FetchResult
from .indicator_engine import (CANONICAL_COLUMNS, DEFAULT_LEGACY_NAMES,
                               LEGACY_COLUMN_ALIASES, IndicatorEngine,
                               indicator_columns)
from .indicators import (atr, bollinger, ema, kdj, macd, obv, rsi, sma,
                         true_range, volume_ma, vwap)
from .signal import (
    ACTION_BUY,
    ACTION_HOLD,
    ACTION_SELL,
    SCALE_PROB,
    SCALE_SCORE,
    SCALE_VOTE,
    SCALE_VOTE_NORM,
    SCALE_WEIGHTED,
    SCALE_ZSCORE,
    Selection,
    Signal,
    action_from_flags,
    apply_constraints,
    selections_to_frame,
    signal_to_dict,
    signals_to_frame,
)

__all__ = [
    "FetchResult",
    "Signal",
    "Selection",
    "ACTION_BUY",
    "ACTION_HOLD",
    "ACTION_SELL",
    "SCALE_VOTE",
    "SCALE_VOTE_NORM",
    "SCALE_WEIGHTED",
    "SCALE_PROB",
    "SCALE_SCORE",
    "SCALE_ZSCORE",
    "action_from_flags",
    "apply_constraints",
    "selections_to_frame",
    "signal_to_dict",
    "signals_to_frame",
    # 指标单一真相源 (审计 #10)
    "IndicatorEngine",
    "indicator_columns",
    "CANONICAL_COLUMNS",
    "LEGACY_COLUMN_ALIASES",
    "DEFAULT_LEGACY_NAMES",
    "rsi",
    "atr",
    "true_range",
    "sma",
    "ema",
    "macd",
    "kdj",
    "bollinger",
    "volume_ma",
    "obv",
    "vwap",
]

