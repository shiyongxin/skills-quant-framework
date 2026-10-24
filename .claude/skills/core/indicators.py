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

审计 #10（共享 IndicatorEngine）新增约定:
- EMA 统一 `ewm(span=period, adjust=False)`（递归 EMA，非 pandas 默认的
  adjust=True 偏置修正口径）——全仓 10+ 站点原本如此，reversal 两模块曾是
  唯一的 adjust=True 异类，已收敛。
- MACD 统一 DIF=EMA(fast)-EMA(slow), DEA=EMA(signal)(DIF), HIST=DIF-DEA
  （**不乘 2**；全仓原本已统一，此处固化以防再分歧）。
- KDJ 统一 RSV=(C-LLV_n)/(HHV_n-LLV_n)*100，K=EMA(span=k_period)(RSV)，
  D=EMA(span=d_period)(K)，J=3K-2D；平滑系数 α=2/(span+1)，span=3 → α=0.5。
  注: 国内教科书口径 α=1/3（K=2/3·K_prev+1/3·RSV）**未被采纳**——那会
  一次性改动全仓 8 站点数值与全部信号语义，属策略口径决策而非重构，
  此处按全仓既有数值（α=0.5）固化并留档。
- BOLL 统一 mid=SMA(period), std=样本标准差(ddof=1), upper/lower=mid±mult·std。
- 成交量均线 = rolling(period).mean()；VWAP = 累积(TP·V)/累积V（锚定序列起点）。
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


# ==================== 审计 #10: 共享指标序列实现 ====================
# 下列函数是全仓 MA/EMA/MACD/KDJ/BOLL/量均线/OBV/VWAP 的唯一计算来源。
# 各业务模块只负责"取哪段、叫什么列名"，不再各自展开公式。


def sma(close: pd.Series, period: int) -> pd.Series:
    """简单移动平均（rolling(period).mean()，min_periods=period 默认口径）。"""
    return close.rolling(window=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    """指数移动平均（递归口径 adjust=False）。

    不用 pandas 默认的 adjust=True——两者数值不同，全仓统一到递归口径。
    """
    return close.ewm(span=period, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9):
    """MACD → (dif, dea, hist)。

    dif = EMA(fast) - EMA(slow); dea = EMA(signal)(dif); hist = dif - dea
    （hist **不乘 2**；中/美式分歧在源头消除）。
    """
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return dif, dea, dif - dea


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9,
        k_period: int = 3, d_period: int = 3):
    """KDJ 随机指标 → (k, d, j)。

    rsv = (C - LLV_n) / (HHV_n - LLV_n) * 100（分母 0 → NaN）
    k = EMA(k_period)(rsv); d = EMA(d_period)(k); j = 3k - 2d
    """
    low_n = low.rolling(window=n).min()
    high_n = high.rolling(window=n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = ema(rsv, k_period)
    d = ema(k, d_period)
    return k, d, 3 * k - 2 * d


def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """布林带 → (upper, middle, lower, std)。

    middle = SMA(period); std = 样本标准差(ddof=1);
    upper/lower = middle ± std_mult · std
    """
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return middle + std_mult * std, middle, middle - std_mult * std, std


def volume_ma(volume: pd.Series, period: int) -> pd.Series:
    """成交量移动平均（rolling(period).mean()）。"""
    return volume.rolling(window=period).mean()


def obv(close, volume) -> pd.Series:
    """能量潮 OBV（向量化：方向符号×成交量累加）。

    obv[0] = volume[0]; obv[i] = obv[i-1] + sign(Δclose_i)·volume_i

    close/volume 可为 Series 或 ndarray（返回 Series 时沿用 Series 的 index）。
    """
    close_arr = np.asarray(close, dtype=float)
    volume_arr = np.asarray(volume, dtype=float)
    direction = np.sign(np.diff(close_arr, prepend=close_arr[0]))
    delta = direction * volume_arr
    delta[0] = volume_arr[0]
    index = getattr(close, 'index', None)
    return pd.Series(np.cumsum(delta), index=index)


def vwap(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series) -> pd.Series:
    """成交量加权平均价（累积口径，锚定序列起点）。

    TP = (H+L+C)/3; VWAP = cumsum(TP·V) / cumsum(V)
    """
    tp = (high + low + close) / 3
    return (tp * volume).cumsum() / volume.cumsum()
