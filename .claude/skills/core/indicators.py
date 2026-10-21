# -*- coding: utf-8 -*-
"""权威技术指标实现（审计路线图项 8：跨模块数字可比的单一真相源）。

约定:
- RSI 采用 Cutler 口径（涨跌幅的 SMA，非 Wilder EMA）。
- 0 除约定（全仓统一，消灭 fill_value=100 / NaN / 裸除三套分歧）:
    avg_loss == 0 且 avg_gain > 0  → 100（窗口内无下跌）
    avg_loss == 0 且 avg_gain == 0 → 50（完全无波动）
"""
import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Cutler RSI（SMA 口径）。

    0 除约定见模块 docstring；输出与输入同 index，前 period-1 根为 NaN。
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return result
