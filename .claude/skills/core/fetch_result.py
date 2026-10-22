# -*- coding: utf-8 -*-
"""
统一数据获取结果类型 (审计路线图项 11 / P0-2)

背景: 上游接口失败被 `except` 吞掉后返回空 DataFrame，与"该股真的无数据"
在下游无法区分 —— 导致 optimization_engine 打印"成功加载 0 只股票"等假成功
（历史案例: concurrent_fetcher 失败计数恒 0，该模块已随孤岛清理删除）。

约定:
- 失败必须携带 error 信息 (ok=False)，不再静默返回空 DF 假装成功
- 调用方应优先依据 `ok` 而非 `len(data)` 判定成败
- `data` 在失败时是空 DataFrame (不是 None)，方便向后兼容旧调用方
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd


@dataclass
class FetchResult:
    """一次数据获取的完整结果"""

    ok: bool
    data: pd.DataFrame = field(default_factory=pd.DataFrame)
    error: Optional[str] = None
    source: Optional[str] = None
    as_of: Optional[str] = None

    @classmethod
    def success(cls, data: pd.DataFrame, source: Optional[str] = None) -> "FetchResult":
        return cls(ok=True, data=data, source=source,
                   as_of=datetime.now().isoformat())

    @classmethod
    def failure(cls, error: str, source: Optional[str] = None,
                data: Optional[pd.DataFrame] = None) -> "FetchResult":
        return cls(ok=False, data=data if data is not None else pd.DataFrame(),
                   error=error, source=source,
                   as_of=datetime.now().isoformat())
