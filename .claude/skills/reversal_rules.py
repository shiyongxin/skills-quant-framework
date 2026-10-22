# -*- coding: utf-8 -*-
"""
反转规则单一真相源 (审计 C-P1-13)

reversal_detector (实盘预警) 与 reversal_backtest (回测) 旧版各持一套
阈值/指标 (回测缺 RSI24/ROC/ATR/Vol_MA20, 阈值与背离窗口均不同),
导致"回测无法验证实盘预警"。本模块是唯一规则定义处:

- 买入/卖出基础打分: score_oversold / score_overbought
- 背离: score_divergence (20 bar 窗, 允许价格枢轴在最后或倒数第2 bar)
- 趋势衰竭: score_exhaustion (ROC 动能 + 影线)
- 判定闸门: score >= BUY/SELL_THRESHOLD (40) 且 严格大于对侧

两侧调用方必须通过本模块打分, 不得本地复制阈值。
"""
from typing import List, Tuple

import pandas as pd

BUY_THRESHOLD = 40.0
SELL_THRESHOLD = 40.0


def _row_get(row, key: str, default=float('nan')):
    try:
        v = row[key]
    except (KeyError, TypeError):
        return default
    return v if pd.notna(v) else default


def _down_days(df: pd.DataFrame, i: int, max_k: int = 5) -> int:
    """截至 bar i 的连续下跌天数 (最多统计 max_k 个下跌步)"""
    return sum(1 for k in range(1, min(max_k + 1, i + 1))
               if df['收盘'].iloc[i - k + 1] < df['收盘'].iloc[i - k])


def _up_days(df: pd.DataFrame, i: int, max_k: int = 5) -> int:
    """截至 bar i 的连续上涨天数"""
    return sum(1 for k in range(1, min(max_k + 1, i + 1))
               if df['收盘'].iloc[i - k + 1] > df['收盘'].iloc[i - k])


def score_oversold(df: pd.DataFrame, i: int) -> Tuple[int, List[str]]:
    """
    bar i 的超卖(买入)打分 — 规则集合与实盘 ReversalDetector 完全一致:
    RSI14 分档 / KDJ-J 分档 / 触及布林下轨 / 低于MA20超10% / 连续下跌 /
    量能萎缩 / 下跌后放量 (背离与趋势衰竭走独立函数)
    """
    row = df.iloc[i]
    signals: List[str] = []
    score = 0

    rsi14 = _row_get(row, 'RSI14')
    if rsi14 < 20:
        signals.append(f'RSI严重超卖({rsi14:.1f})')
        score += 30
    elif rsi14 < 30:
        signals.append(f'RSI超卖({rsi14:.1f})')
        score += 20
    elif rsi14 < 40:
        signals.append(f'RSI偏低({rsi14:.1f})')
        score += 10

    j = _row_get(row, 'J')
    if j < 0:
        signals.append(f'KDJ-J负值({j:.1f})')
        score += 20
    elif j < 20:
        signals.append(f'KDJ超卖(J={j:.1f})')
        score += 15

    bb_lower = _row_get(row, 'BB_Lower')
    if pd.notna(bb_lower) and row['收盘'] <= bb_lower * 1.02:
        signals.append('触及布林下轨')
        score += 15

    ma20 = _row_get(row, 'MA20')
    if row['收盘'] < ma20 * 0.9:
        signals.append('价格低于MA20超10%')
        score += 15

    down_days = _down_days(df, i)
    if down_days >= 4:
        signals.append(f'连续下跌{down_days}天')
        score += 10

    vol_ma20 = _row_get(row, 'Vol_MA20')
    if row['成交量'] < vol_ma20 * 0.5:
        signals.append('量能萎缩')
        score += 10

    vol_ma5 = _row_get(row, 'Vol_MA5')
    if down_days >= 2 and row['成交量'] > vol_ma5 * 1.2:
        signals.append('下跌后放量')
        score += 15

    return score, signals


def score_overbought(df: pd.DataFrame, i: int) -> Tuple[int, List[str]]:
    """
    bar i 的超买(卖出)打分 — 与实盘一致:
    RSI14 分档 / KDJ-J 分档 / 触及布林上轨 / 高于MA20超15% / 连续上涨 /
    量价背离 / 上涨后缩量
    """
    row = df.iloc[i]
    prev = df.iloc[i - 1] if i >= 1 else None
    signals: List[str] = []
    score = 0

    rsi14 = _row_get(row, 'RSI14')
    if rsi14 > 80:
        signals.append(f'RSI严重超买({rsi14:.1f})')
        score += 30
    elif rsi14 > 70:
        signals.append(f'RSI超买({rsi14:.1f})')
        score += 20
    elif rsi14 > 60:
        signals.append(f'RSI偏高({rsi14:.1f})')
        score += 10

    j = _row_get(row, 'J')
    if j > 100:
        signals.append(f'KDJ-J超100({j:.1f})')
        score += 20
    elif j > 80:
        signals.append(f'KDJ超买(J={j:.1f})')
        score += 15

    bb_upper = _row_get(row, 'BB_Upper')
    if row['收盘'] >= bb_upper * 0.98:
        signals.append('触及布林上轨')
        score += 15

    ma20 = _row_get(row, 'MA20')
    if row['收盘'] > ma20 * 1.15:
        signals.append('价格高于MA20超15%')
        score += 15

    up_days = _up_days(df, i)
    if up_days >= 4:
        signals.append(f'连续上涨{up_days}天')
        score += 10

    if prev is not None and row['收盘'] > prev['收盘'] \
            and row['成交量'] < prev['成交量'] * 0.7:
        signals.append('量价背离')
        score += 15

    vol_ma5 = _row_get(row, 'Vol_MA5')
    if up_days >= 2 and row['成交量'] < vol_ma5 * 0.7:
        signals.append('上涨后缩量')
        score += 15

    return score, signals


def score_divergence(recent: pd.DataFrame) -> Tuple[str, int, List[str]]:
    """
    20 bar 窗 RSI 背离 (实盘口径):
    - 底背离: 价格枢轴在最后或倒数第2 bar, 且存在更早价格低点而 RSI 未创新低
    - 顶背离: 对称
    Returns: (type ∈ {'NONE','BULLISH','BEARISH'}, score, reasons)
    """
    signals: List[str] = []
    score = 0
    divergence_type = 'NONE'

    if len(recent) < 20 or 'RSI14' not in recent.columns:
        return divergence_type, signals, score

    recent = recent.tail(20)
    if recent['RSI14'].isna().all():
        return divergence_type, signals, score

    price_low_idx = recent['收盘'].idxmin()
    if price_low_idx in (recent.index[-1], recent.index[-2]):
        recent_prices = recent['收盘'].values
        recent_rsi = recent['RSI14'].values
        for i in range(len(recent_prices) - 3, 5, -1):
            if recent_prices[i] < recent_prices[i - 1] and \
                    recent_prices[i] < recent_prices[i + 1]:
                if pd.notna(recent_rsi[-1]) and pd.notna(recent_rsi[i]) \
                        and recent_rsi[-1] > recent_rsi[i] \
                        and recent_prices[-1] < recent_prices[i]:
                    signals.append('RSI底背离')
                    score += 25
                    divergence_type = 'BULLISH'
                    break

    price_high_idx = recent['收盘'].idxmax()
    if divergence_type == 'NONE' and \
            price_high_idx in (recent.index[-1], recent.index[-2]):
        recent_prices = recent['收盘'].values
        recent_rsi = recent['RSI14'].values
        for i in range(len(recent_prices) - 3, 5, -1):
            if recent_prices[i] > recent_prices[i - 1] and \
                    recent_prices[i] > recent_prices[i + 1]:
                if pd.notna(recent_rsi[-1]) and pd.notna(recent_rsi[i]) \
                        and recent_rsi[-1] < recent_rsi[i] \
                        and recent_prices[-1] > recent_prices[i]:
                    signals.append('RSI顶背离')
                    score += 25
                    divergence_type = 'BEARISH'
                    break

    return divergence_type, score, signals


def score_exhaustion(df: pd.DataFrame, i: int) -> Tuple[str, int, List[str]]:
    """
    bar i 的趋势衰竭打分 (实盘口径): ROC 动能收窄 + 连续影线
    依赖列: ROC5, ROC10, 开盘, 最高, 最低, 收盘
    Returns: (type ∈ {'NONE','UP_EXHAUSTION','DOWN_EXHAUSTION'}, score, reasons)
    """
    signals: List[str] = []
    score = 0
    exhaustion_type = 'NONE'

    if i < 10:
        return exhaustion_type, signals, score

    row = df.iloc[i]

    roc5 = _row_get(row, 'ROC5')
    roc10 = _row_get(row, 'ROC10')

    if roc10 > 10 and roc5 < roc10 * 0.5:
        signals.append('上涨动能衰减')
        score += 15
        exhaustion_type = 'UP_EXHAUSTION'

    upper_shadows = 0
    for k in range(1, 4):
        bar = df.iloc[i - k + 1]
        upper_shadow = bar['最高'] - max(bar['开盘'], bar['收盘'])
        body = abs(bar['收盘'] - bar['开盘'])
        if upper_shadow > body * 0.5:
            upper_shadows += 1
    if upper_shadows >= 2:
        signals.append('连续上影线(抛压)')
        score += 15
        if exhaustion_type == 'NONE':
            exhaustion_type = 'UP_EXHAUSTION'

    if roc10 < -10 and roc5 > roc10 * 0.5:
        signals.append('下跌动能衰减')
        score += 15
        exhaustion_type = 'DOWN_EXHAUSTION'

    lower_shadows = 0
    for k in range(1, 4):
        bar = df.iloc[i - k + 1]
        lower_shadow = min(bar['开盘'], bar['收盘']) - bar['最低']
        body = abs(bar['收盘'] - bar['开盘'])
        if lower_shadow > body * 0.5:
            lower_shadows += 1
    if lower_shadows >= 2:
        signals.append('连续下影线(承接)')
        score += 15
        if exhaustion_type == 'NONE':
            exhaustion_type = 'DOWN_EXHAUSTION'

    return exhaustion_type, score, signals


def decide_action(buy_score: int, sell_score: int) -> str:
    """
    统一判定闸门 (两侧一致): >=40 且严格大于对侧 → BUY/SELL, 否则 WATCH
    旧回测用 >=40 且不比较对侧 → 同 bar 可同时买卖 (已消除)
    """
    if buy_score >= BUY_THRESHOLD and buy_score > sell_score:
        return 'BUY'
    if sell_score >= SELL_THRESHOLD and sell_score > buy_score:
        return 'SELL'
    return 'WATCH'
