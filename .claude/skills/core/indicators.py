# -*- coding: utf-8 -*-
"""权威技术指标实现（审计路线图项 8：跨模块数字可比的单一真相源）。

约定:
- RSI 采用 Cutler 口径（涨跌幅的 SMA，非 Wilder EMA）。
- 0 除约定（全仓统一，消灭 fill_value=100 / NaN / 裸除三套分歧）:
    avg_loss == 0 且 avg_gain > 0  → 100（窗口内无下跌）
    avg_loss == 0 且 avg_gain == 0 → 50（完全无波动）
- ATR 采用 Wilder RMA（alpha=1/period, min_periods=period, 首 period 根 NaN）。
  注意: 不是 ewm(span=14)（alpha=2/15，快 43%），也不是 SMA14——全仓统一到
  Wilder 这一教科书定义后，各模块同名 ATR 列数值才可比。
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


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """真实波幅 TR = max(H-L, |H-C_prev|, |L-C_prev|)。

    首根因无前收, 在 skipna 下退化为 H-L (仍为有效值)。
    """
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Wilder ATR（RMA，alpha=1/period）。

    输出与输入同 index；前 period-1 根为 NaN (TR 自首根起有效)。
    """
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
