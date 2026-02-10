# -*- coding: utf-8 -*-
"""
形态识别模块
Pattern Recognition Module

识别K线形态和价格形态
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple


class CandlestickPatterns:
    """K线形态识别"""

    @staticmethod
    def is_doji(df, idx, threshold=0.1):
        """
        识别十字星
        实体很小，上下影线较长

        Args:
            df: DataFrame with OHLC
            idx: 行索引
            threshold: 实体占振幅的比例阈值

        Returns:
            bool: 是否为十字星
        """
        row = df.iloc[idx]
        open_price = row['开盘']
        close = row['收盘']
        high = row['最高']
        low = row['最低']

        body = abs(close - open_price)
        range_price = high - low

        if range_price == 0:
            return False

        body_ratio = body / range_price

        return body_ratio < threshold

    @staticmethod
    def is_hammer(df, idx, body_ratio=0.3, shadow_ratio=2.0):
        """
        识别锤子线/上吊线
        小实体在顶部，下影线至少是实体的2倍

        Args:
            df: DataFrame
            idx: 行索引
            body_ratio: 实体占振幅的最大比例
            shadow_ratio: 下影线与实体的最小比例

        Returns:
            dict: {'is_hammer': bool, 'type': 'hammer'/'hanging_man'}
        """
        row = df.iloc[idx]
        open_price = row['开盘']
        close = row['收盘']
        high = row['最低']  # 错误，应该是high
        low = row['最低']

        body = abs(close - open_price)
        upper_shadow = high - max(open_price, close)
        lower_shadow = min(open_price, close) - low
        range_price = high - low

        if range_price == 0:
            return {'is_hammer': False, 'type': None}

        # 锤子线: 下影线长，上影线很短
        is_hammer = (lower_shadow >= body * shadow_ratio and
                     upper_shadow <= body * 0.5 and
                     body / range_price < body_ratio)

        # 判断是锤子线（底部）还是上吊线（顶部）
        prev_trend = 'uptrend' if idx > 0 and df.iloc[idx-1]['收盘'] < open_price else 'downtrend'

        if is_hammer:
            pattern_type = 'hammer' if prev_trend == 'downtrend' else 'hanging_man'
            return {'is_hammer': True, 'type': pattern_type}

        return {'is_hammer': False, 'type': None}

    @staticmethod
    def is_engulfing(df, idx):
        """
        识别吞没形态
        第二天K线完全包含第一天K线

        Args:
            df: DataFrame
            idx: 当前行索引

        Returns:
            dict: {'is_engulfing': bool, 'type': 'bullish'/'bearish'}
        """
        if idx < 1:
            return {'is_engulfing': False, 'type': None}

        prev = df.iloc[idx-1]
        curr = df.iloc[idx]

        prev_body = abs(prev['收盘'] - prev['开盘'])
        curr_body = abs(curr['收盘'] - curr['开盘'])

        prev_open = prev['开盘']
        prev_close = prev['收盘']
        curr_open = curr['开盘']
        curr_close = curr['收盘']

        # 看涨吞没: 前一日阴线，今日阳线包含前一日
        bullish_engulfing = (prev_close < prev_open and  # 前一日阴线
                             curr_close > curr_open and  # 今日阳线
                             curr_open <= prev_close and  # 今日开盘低于前一日收盘
                             curr_close >= prev_open)    # 今日收盘高于前一日开盘

        # 看跌吞没: 前一日阳线，今日阴线包含前一日
        bearish_engulfing = (prev_close > prev_open and  # 前一日阳线
                             curr_close < curr_open and  # 今日阴线
                             curr_open >= prev_close and  # 今日开盘高于前一日收盘
                             curr_close <= prev_open)    # 今日收盘低于前一日开盘

        if bullish_engulfing:
            return {'is_engulfing': True, 'type': 'bullish'}
        elif bearish_engulfing:
            return {'is_engulfing': True, 'type': 'bearish'}

        return {'is_engulfing': False, 'type': None}

    @staticmethod
    def is_harami(df, idx):
        """
        识别孕线形态
        第二天K线完全被第一天K线包含

        Args:
            df: DataFrame
            idx: 当前行索引

        Returns:
            dict: {'is_harami': bool, 'type': 'bullish'/'bearish'}
        """
        if idx < 1:
            return {'is_harami': False, 'type': None}

        prev = df.iloc[idx-1]
        curr = df.iloc[idx]

        prev_high = max(prev['开盘'], prev['收盘'])
        prev_low = min(prev['开盘'], prev['收盘'])
        curr_high = max(curr['开盘'], curr['收盘'])
        curr_low = min(curr['开盘'], curr['收盘'])

        # 孕线: 今日完全在前一日实体内
        is_harami = (curr_high < prev_high and curr_low > prev_low)

        if is_harami:
            # 判断方向
            if prev['收盘'] > prev['开盘']:  # 前一日阳线
                return {'is_harami': True, 'type': 'bearish'}  # 可能见顶
            else:
                return {'is_harami': True, 'type': 'bullish'}   # 可能见底

        return {'is_harami': False, 'type': None}

    @staticmethod
    def is_morning_star(df, idx):
        """
        识别早晨之星 (看涨反转)
        三根K线: 大阴线 + 小实体(十字星) + 大阳线

        Args:
            df: DataFrame
            idx: 当前行索引

        Returns:
            bool
        """
        if idx < 2:
            return False

        day1 = df.iloc[idx-2]
        day2 = df.iloc[idx-1]
        day3 = df.iloc[idx]

        # 第一天: 大阴线
        day1_body = abs(day1['收盘'] - day1['开盘'])
        day1_bearish = day1['收盘'] < day1['开盘']

        # 第二天: 小实体或十字星
        day2_body = abs(day2['收盘'] - day2['开盘'])
        day2_small = day2_body < day1_body * 0.3

        # 第三天: 大阳线
        day3_body = abs(day3['收盘'] - day3['开盘'])
        day3_bullish = day3['收盘'] > day3['开盘']
        day3_engulfs = day3['收盘'] > (day1['开盘'] + day1['收盘']) / 2

        return (day1_bearish and day2_small and
                day3_bullish and day3_engulfs)

    @staticmethod
    def is_evening_star(df, idx):
        """
        识别黄昏之星 (看跌反转)
        三根K线: 大阳线 + 小实体(十字星) + 大阴线

        Args:
            df: DataFrame
            idx: 当前行索引

        Returns:
            bool
        """
        if idx < 2:
            return False

        day1 = df.iloc[idx-2]
        day2 = df.iloc[idx-1]
        day3 = df.iloc[idx]

        # 第一天: 大阳线
        day1_body = abs(day1['收盘'] - day1['开盘'])
        day1_bullish = day1['收盘'] > day1['开盘']

        # 第二天: 小实体或十字星
        day2_body = abs(day2['收盘'] - day2['开盘'])
        day2_small = day2_body < day1_body * 0.3

        # 第三天: 大阴线
        day3_body = abs(day3['收盘'] - day3['开盘'])
        day3_bearish = day3['收盘'] < day3['开盘']
        day3_engulfs = day3['收盘'] < (day1['开盘'] + day1['收盘']) / 2

        return (day1_bullish and day2_small and
                day3_bearish and day3_engulfs)

    @staticmethod
    def is_piercing(df, idx):
        """
        识别刺透形态 (看涨)
        第二天阳线深入第一天阴线实体

        Args:
            df: DataFrame
            idx: 当前行索引

        Returns:
            bool
        """
        if idx < 1:
            return False

        day1 = df.iloc[idx-1]
        day2 = df.iloc[idx]

        # 第一天: 阴线
        day1_bearish = day1['收盘'] < day1['开盘']
        day1_body = day1['开盘'] - day1['收盘']

        # 第二天: 阳线
        day2_bullish = day2['收盘'] > day2['开盘']

        # 刺透: 第二天收盘价深入第一天实体中部以上
        day1_mid = day1['开盘'] - day1_body * 0.5
        piercing = day2_bullish and day2['收盘'] > day1_mid and day2['开盘'] < day1['收盘']

        return day1_bearish and piercing

    @staticmethod
    def is_dark_cloud(df, idx):
        """
        识别乌云盖顶 (看跌)
        第二天阴线深入第一天阳线实体

        Args:
            df: DataFrame
            idx: 当前行索引

        Returns:
            bool
        """
        if idx < 1:
            return False

        day1 = df.iloc[idx-1]
        day2 = df.iloc[idx]

        # 第一天: 阳线
        day1_bullish = day1['收盘'] > day1['开盘']
        day1_body = day1['收盘'] - day1['开盘']

        # 第二天: 阴线
        day2_bearish = day2['收盘'] < day2['开盘']

        # 乌云: 第二天收盘价深入第一天实体中部以下
        day1_mid = day1['开盘'] + day1_body * 0.5
        dark_cloud = day2_bearish and day2['收盘'] < day1_mid and day2['开盘'] > day1['收盘']

        return day1_bullish and dark_cloud

    @staticmethod
    def scan_all_patterns(df) -> pd.DataFrame:
        """
        扫描所有K线形态

        Args:
            df: OHLCV数据

        Returns:
            包含形态信号的DataFrame
        """
        df = df.copy()
        df['Pattern_Doji'] = False
        df['Pattern_Hammer'] = None
        df['Pattern_HangingMan'] = None
        df['Pattern_BullishEngulfing'] = False
        df['Pattern_BearishEngulfing'] = False
        df['Pattern_BullishHarami'] = False
        df['Pattern_BearishHarami'] = False
        df['Pattern_MorningStar'] = False
        df['Pattern_EveningStar'] = False
        df['Pattern_Piercing'] = False
        df['Pattern_DarkCloud'] = False

        for i in range(len(df)):
            # Doji
            df.loc[i, 'Pattern_Doji'] = CandlestickPatterns.is_doji(df, i)

            # Hammer/Hanging Man
            hammer = CandlestickPatterns.is_hammer(df, i)
            if hammer['is_hammer']:
                if hammer['type'] == 'hammer':
                    df.loc[i, 'Pattern_Hammer'] = True
                else:
                    df.loc[i, 'Pattern_HangingMan'] = True

            # Engulfing
            engulfing = CandlestickPatterns.is_engulfing(df, i)
            if engulfing['is_engulfing']:
                if engulfing['type'] == 'bullish':
                    df.loc[i, 'Pattern_BullishEngulfing'] = True
                else:
                    df.loc[i, 'Pattern_BearishEngulfing'] = True

            # Harami
            harami = CandlestickPatterns.is_harami(df, i)
            if harami['is_harami']:
                if harami['type'] == 'bullish':
                    df.loc[i, 'Pattern_BullishHarami'] = True
                else:
                    df.loc[i, 'Pattern_BearishHarami'] = True

            # Morning/Evening Star
            df.loc[i, 'Pattern_MorningStar'] = CandlestickPatterns.is_morning_star(df, i)
            df.loc[i, 'Pattern_EveningStar'] = CandlestickPatterns.is_evening_star(df, i)

            # Piercing/Dark Cloud
            df.loc[i, 'Pattern_Piercing'] = CandlestickPatterns.is_piercing(df, i)
            df.loc[i, 'Pattern_DarkCloud'] = CandlestickPatterns.is_dark_cloud(df, i)

        return df


class PricePatterns:
    """价格形态识别"""

    @staticmethod
    def detect_support_level(df, window=20, min_touches=2) -> List[float]:
        """
        检测支撑位
        找出多次触及但未跌破的价格水平

        Args:
            df: DataFrame
            window: 检测窗口
            min_touches: 最小触及次数

        Returns:
            支撑位列表
        """
        lows = df['最低']

        # 使用局部极小值
        from scipy.signal import find_peaks
        from scipy.ndimage import gaussian_filter1d

        # 平滑后找波谷
        smoothed = gaussian_filter1d(lows.values, sigma=2)
        peaks, _ = find_peaks(-smoothed, distance=window)

        support_levels = []
        for peak in peaks:
            level = lows.iloc[peak]

            # 检查附近是否有相似水平
            is_similar = False
            for existing in support_levels:
                if abs(level - existing) / existing < 0.02:  # 2%容差
                    is_similar = True
                    break

            if not is_similar:
                support_levels.append(level)

        return sorted(support_levels, reverse=True)[:5]

    @staticmethod
    def detect_resistance_level(df, window=20, min_touches=2) -> List[float]:
        """
        检测压力位
        找出多次触及但未突破的价格水平

        Args:
            df: DataFrame
            window: 检测窗口
            min_touches: 最小触及次数

        Returns:
            压力位列表
        """
        highs = df['最高']

        # 使用局部极大值
        from scipy.signal import find_peaks
        from scipy.ndimage import gaussian_filter1d

        # 平滑后找波峰
        smoothed = gaussian_filter1d(highs.values, sigma=2)
        peaks, _ = find_peaks(smoothed, distance=window)

        resistance_levels = []
        for peak in peaks:
            level = highs.iloc[peak]

            # 检查附近是否有相似水平
            is_similar = False
            for existing in resistance_levels:
                if abs(level - existing) / existing < 0.02:  # 2%容差
                    is_similar = True
                    break

            if not is_similar:
                resistance_levels.append(level)

        return sorted(resistance_levels)[:5]

    @staticmethod
    def detect_trend(df, period=60) -> str:
        """
        检测趋势方向

        Args:
            df: DataFrame
            period: 检测周期

        Returns:
            'uptrend', 'downtrend', 'sideways'
        """
        if len(df) < period:
            period = len(df) - 1

        recent = df.tail(period)

        # 使用线性回归
        x = np.arange(len(recent))
        y = recent['收盘'].values

        slope, _ = np.polyfit(x, y, 1)

        # 判断趋势
        price_range = y.max() - y.min()
        slope_ratio = slope * len(recent) / price_range if price_range > 0 else 0

        if slope_ratio > 0.3:
            return 'uptrend'
        elif slope_ratio < -0.3:
            return 'downtrend'
        else:
            return 'sideways'

    @staticmethod
    def detect_consolidation(df, period=20, threshold=0.05) -> bool:
        """
        检测是否处于整理状态

        Args:
            df: DataFrame
            period: 检测周期
            threshold: 价格波动阈值

        Returns:
            bool: 是否处于整理
        """
        if len(df) < period:
            return False

        recent = df.tail(period)
        price_range = (recent['最高'].max() - recent['最低'].min()) / recent['收盘'].mean()

        return price_range < threshold

    @staticmethod
    def detect_breakout(df, period=20, threshold=1.5) -> Dict:
        """
        检测突破信号

        Args:
            df: DataFrame
            period: 检测周期
            threshold: 突破倍数 (相对于ATR)

        Returns:
            {'breakout': bool, 'direction': 'up'/'down', 'strength': float}
        """
        if len(df) < period + 1:
            return {'breakout': False, 'direction': None, 'strength': 0}

        # 计算ATR
        recent = df.tail(period + 1)
        high = recent['最高']
        low = recent['最低']
        close = recent['收盘']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.iloc[-1].mean()

        # 检查突破
        latest = df.iloc[-1]
        prev_high = df['最高'].tail(period).max()
        prev_low = df['最低'].tail(period).min()

        up_breakout = latest['收盘'] > prev_high
        down_breakout = latest['收盘'] < prev_low

        if up_breakout:
            strength = (latest['收盘'] - prev_high) / atr
            return {'breakout': True, 'direction': 'up', 'strength': strength}
        elif down_breakout:
            strength = (prev_low - latest['收盘']) / atr
            return {'breakout': True, 'direction': 'down', 'strength': strength}

        return {'breakout': False, 'direction': None, 'strength': 0}

    @staticmethod
    def analyze_patterns(df) -> Dict:
        """
        综合形态分析

        Args:
            df: OHLCV数据

        Returns:
            形态分析结果
        """
        support_levels = PricePatterns.detect_support_level(df)
        resistance_levels = PricePatterns.detect_resistance_level(df)
        trend = PricePatterns.detect_trend(df)
        is_consolidating = PricePatterns.detect_consolidation(df)
        breakout = PricePatterns.detect_breakout(df)

        return {
            'support_levels': support_levels,
            'resistance_levels': resistance_levels,
            'trend': trend,
            'is_consolidating': is_consolidating,
            'breakout': breakout,
            'current_price': df['收盘'].iloc[-1],
            'price_position': {
                'vs_support': ((df['收盘'].iloc[-1] - support_levels[0]) / support_levels[0] * 100) if support_levels else None,
                'vs_resistance': ((resistance_levels[0] - df['收盘'].iloc[-1]) / resistance_levels[0] * 100) if resistance_levels else None,
            }
        }


# 便捷函数
def scan_candlestick_patterns(df):
    """扫描所有K线形态"""
    return CandlestickPatterns.scan_all_patterns(df)

def analyze_price_patterns(df):
    """分析价格形态"""
    return PricePatterns.analyze_patterns(df)


if __name__ == "__main__":
    print("Pattern Recognition Module")
    print("\nCandlestick Patterns:")
    print("- Doji, Hammer/Hanging Man, Engulfing, Harami")
    print("- Morning/Evening Star, Piercing, Dark Cloud")
    print("\nPrice Patterns:")
    print("- Support/Resistance Levels")
    print("- Trend Detection")
    print("- Consolidation Detection")
    print("- Breakout Detection")
