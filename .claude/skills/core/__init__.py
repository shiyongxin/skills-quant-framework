# -*- coding: utf-8 -*-
"""core — 单一真相源：权威指标与绩效口径（审计路线图项 8/9）+ FetchResult（项 11）
+ 统一信号输出契约 Signal（审计 C #9 / 项 21 #9a）。"""

from .fetch_result import FetchResult
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
]
