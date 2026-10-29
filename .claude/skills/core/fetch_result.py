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
- `adjust` 记录本次数据的复权口径 (''=不复权 / 'qfq'=前复权 / 'hfq'=后复权)
  —— 复权是数据维度不是装饰: 不同口径的序列混用会产生除权跳空,
  收益率/指标全错 (审计 P0-4: 落库必须带 adjust 维度)
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
    adjust: Optional[str] = None      # ''=不复权 / 'qfq' / 'hfq'
    # 附加口径元信息 (审计 M20): 取数窗口/日历是否可用/行数等 —— 让
    # "这次取数到底是怎么来的"可审计 (不靠日志猜测)
    meta: dict = field(default_factory=dict)

    @classmethod
    def success(cls, data: pd.DataFrame, source: Optional[str] = None,
                adjust: Optional[str] = None,
                as_of: Optional[str] = None,
                meta: Optional[dict] = None) -> "FetchResult":
        return cls(ok=True, data=data, source=source,
                   as_of=as_of or datetime.now().isoformat(), adjust=adjust,
                   meta=meta or {})

    @classmethod
    def failure(cls, error: str, source: Optional[str] = None,
                data: Optional[pd.DataFrame] = None,
                adjust: Optional[str] = None,
                as_of: Optional[str] = None,
                meta: Optional[dict] = None) -> "FetchResult":
        return cls(ok=False, data=data if data is not None else pd.DataFrame(),
                   error=error, source=source,
                   as_of=as_of or datetime.now().isoformat(), adjust=adjust,
                   meta=meta or {})
