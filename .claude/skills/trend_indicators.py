# -*- coding: utf-8 -*-
"""
趋势指标库
Trend Indicators Library

包含: EMA, DEMA, TEMA, VWMA, Hull MA, 自适应MA等
"""

import pandas as pd
import numpy as np


class TrendIndicators:
    """趋势指标集合"""

    @staticmethod
    def ema(df, period=20, column='收盘'):
        """
        指数移动平均 (Exponential Moving Average)
        对近期价格赋予更高权重

        Args:
            df: DataFrame
            period: 周期
            column: 列名

        Returns:
            添加EMA列的DataFrame
        """
        df = df.copy()
        df[f'EMA_{period}'] = df[column].ewm(span=period, adjust=False).mean()
        return df

    @staticmethod
    def dema(df, period=20, column='收盘'):
        """
        双指数移动平均 (Double Exponential Moving Average)
        减少EMA的滞后

        Args:
            df: DataFrame
            period: 周期
            column: 列名

        Returns:
            添加DEMA列的DataFrame
        """
        df = df.copy()
        ema1 = df[column].ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        df[f'DEMA_{period}'] = 2 * ema1 - ema2
        return df

    @staticmethod
    def tema(df, period=20, column='收盘'):
        """
        三重指数移动平均 (Triple Exponential Moving Average)
        进一步减少滞后

        Args:
            df: DataFrame
            period: 周期
            column: 列名

        Returns:
            添加TEMA列的DataFrame
        """
        df = df.copy()
        ema1 = df[column].ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()
        df[f'TEMA_{period}'] = 3 * ema1 - 3 * ema2 + ema3
        return df

    @staticmethod
    def vwma(df, period=20):
        """
        成交量加权移动平均 (Volume Weighted Moving Average)
        成交量大时权重更高

        Args:
            df: DataFrame (需要收盘和成交量)
            period: 周期

        Returns:
            添加VWMA列的DataFrame
        """
        df = df.copy()

        typical_price = df['收盘']
        volume = df['成交量']

        # 成交量加权的价格
        vwma = (typical_price * volume).rolling(window=period).sum() / \
               volume.rolling(window=period).sum()

        df[f'VWMA_{period}'] = vwma
        return df

    @staticmethod
    def hull_ma(df, period=20, column='收盘'):
        """
        Hull移动平均 (Hull Moving Average)
        几乎零滞后，非常平滑

        Args:
            df: DataFrame
            period: 周期
            column: 列名

        Returns:
            添加HMA列的DataFrame
        """
        df = df.copy()

        # HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))
        def wma(series, w):
            weights = np.arange(1, w + 1)
            return series.rolling(window=w).apply(
                lambda x: np.dot(x, weights) / weights.sum(), raw=True
            )

        half_period = int(period / 2)
        sqrt_period = int(np.sqrt(period))

        wma_half = wma(df[column], half_period)
        wma_full = wma(df[column], period)

        raw = 2 * wma_half - wma_full
        df[f'HMA_{period}'] = wma(raw, sqrt_period)

        return df

    @staticmethod
    def adaptive_ma(df, fast=2, slow=30, column='收盘'):
        """
        自适应移动平均 (Adaptive Moving Average)
        根据波动率调整周期

        Args:
            df: DataFrame
            fast: 快速周期
            slow: 慢速周期
            column: 列名

        Returns:
            添加KAMA列的DataFrame (Kaufman's Adaptive MA)
        """
        df = df.copy()

        # 计算方向性
        change = df[column].diff().abs()
        volatility = df[column].diff().abs().rolling(window=10).sum()

        # 效率比率 (ER)
        er = change / volatility
        er = er.fillna(0)

        # 平滑常数
        fastest_sc = 2 / (fast + 1)
        slowest_sc = 2 / (slow + 1)

        sc = (er * (fastest_sc - slowest_sc) + slowest_sc) ** 2

        # KAMA
        kama = df[column].iloc[0]
        kama_values = [kama]

        for i in range(1, len(df)):
            kama = kama + sc.iloc[i] * (df[column].iloc[i] - kama)
            kama_values.append(kama)

        df['KAMA'] = kama_values
        return df

    @staticmethod
    def mcginley_dynamic(df, period=13, column='收盘'):
        """
        McGinley动态指标
        自动调整以适应市场速度

        Args:
            df: DataFrame
            period: 周期
            column: 列名

        Returns:
            添加MG列的DataFrame
        """
        df = df.copy()

        mg = df[column].iloc[0]
        mg_values = [mg]

        k = 0.6

        for i in range(1, len(df)):
            ratio = (df[column].iloc[i] - mg) / (mg * k)
            mg = mg + max(min(ratio, 1.25), 0.8) * k * (df[column].iloc[i] - mg)
            mg_values.append(mg)

        df['MG'] = mg_values
        return df

    @staticmethod
    def vwap(df):
        """
        成交量加权平均价 (Volume Weighted Average Price)
        当日累积计算

        Args:
            df: DataFrame (单日数据)

        Returns:
            添加VWAP列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']
        volume = df['成交量']

        # 典型价格
        tp = (high + low + close) / 3

        # VWAP = 累积(TP * Volume) / 累积Volume
        df['VWAP'] = (tp * volume).cumsum() / volume.cumsum()

        return df

    @staticmethod
    def ichimoku(df, tenkan=9, kijun=26, senkou=52):
        """
        一目均衡表 (Ichimoku Kinko Hyo)
        日本技术分析方法

        Args:
            df: DataFrame
            tenkan: 转换线周期
            kijun: 基准线周期
            senkou: 先行带周期

        Returns:
            添加Ichimoku各列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']

        # 转换线 (Tenkan-sen)
        df['Tenkan'] = (high.rolling(window=tenkan).max() +
                       low.rolling(window=tenkan).min()) / 2

        # 基准线 (Kijun-sen)
        df['Kijun'] = (high.rolling(window=kijun).max() +
                      low.rolling(window=kijun).min()) / 2

        # 先行带A (Senkou Span A)
        df['Senkou_A'] = ((df['Tenkan'] + df['Kijun']) / 2).shift(kijun)

        # 先行带B (Senkou Span B)
        df['Senkou_B'] = ((high.rolling(window=senkou).max() +
                          low.rolling(window=senkou).min()) / 2).shift(kijun)

        # 滞后跨度 (Chikou Span)
        df['Chikou'] = close.shift(-kijun)

        return df

    @staticmethod
    def triple_screen(df, trend_period=20, momentum_period=7):
        """
        三屏过滤系统 (Triple Screen Trading)
        结合趋势和动量

        Args:
            df: DataFrame
            trend_period: 趋势周期 (周线)
            momentum_period: 动量周期 (日线)

        Returns:
            添加信号列的DataFrame
        """
        df = df.copy()

        # 第一屏: 趋势 (MACD柱状图)
        close = df['收盘']
        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()
        macd_hist = (ema_fast - ema_slow) - (ema_fast - ema_slow).ewm(span=9, adjust=False).mean()

        df['Trend_Force'] = macd_hist

        # 第二屏: 动量 (RSI)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['Momentum_Oscillator'] = 100 - (100 / (1 + rs))

        # 第三屏: 突破 (价格突破)
        df['Breakout_Level'] = close.rolling(window=trend_period).max()

        # 生成信号
        df['Triple_Screen_Signal'] = 0
        df.loc[(df['Trend_Force'] > 0) & (df['Momentum_Oscillator'] < 30), 'Triple_Screen_Signal'] = 1
        df.loc[(df['Trend_Force'] < 0) & (df['Momentum_Oscillator'] > 70), 'Triple_Screen_Signal'] = -1

        return df

    @staticmethod
    def abands(df, period=20, multiplier=3):
        """
        Abohar Bands (类似布林带，但使用ATR)
        使用ATR代替标准差

        Args:
            df: DataFrame
            period: 周期
            multiplier: ATR倍数

        Returns:
            添加Abohar Bands列的DataFrame
        """
        df = df.copy()

        # 计算ATR
        high = df['最高']
        low = df['最低']
        close = df['收盘']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()

        # 中轨 = EMA
        middle = close.ewm(span=period, adjust=False).mean()

        # 上下轨
        upper = middle + multiplier * atr
        lower = middle - multiplier * atr

        df['ABands_Middle'] = middle
        df['ABands_Upper'] = upper
        df['ABands_Lower'] = lower

        return df

    @staticmethod
    def all_trend_indicators(df):
        """
        计算所有趋势指标

        Args:
            df: OHLCV数据

        Returns:
            添加所有趋势指标的DataFrame
        """
        df = TrendIndicators.ema(df, 20)
        df = TrendIndicators.ema(df, 50)
        df = TrendIndicators.dema(df, 20)
        df = TrendIndicators.tema(df, 20)
        df = TrendIndicators.vwma(df, 20)
        df = TrendIndicators.hull_ma(df, 20)
        df = TrendIndicators.adaptive_ma(df)
        df = TrendIndicators.mcginley_dynamic(df)
        df = TrendIndicators.vwap(df)
        df = TrendIndicators.ichimoku(df)
        df = TrendIndicators.abands(df)

        return df


# 便捷函数
def add_ema(df, period=20):
    return TrendIndicators.ema(df, period)

def add_dema(df, period=20):
    return TrendIndicators.dema(df, period)

def add_hull_ma(df, period=20):
    return TrendIndicators.hull_ma(df, period)

def add_ichimoku(df, tenkan=9, kijun=26, senkou=52):
    return TrendIndicators.ichimoku(df, tenkan, kijun, senkou)


if __name__ == "__main__":
    print("Trend Indicators Library")
    print("\nAvailable indicators:")
    print("- EMA: Exponential Moving Average")
    print("- DEMA: Double EMA")
    print("- TEMA: Triple EMA")
    print("- VWMA: Volume Weighted MA")
    print("- HMA: Hull Moving Average")
    print("- KAMA: Kaufman's Adaptive MA")
    print("- MG: McGinley Dynamic")
    print("- VWAP: Volume Weighted Average Price")
    print("- Ichimoku: Ichimoku Kinko Hyo")
    print("- Triple Screen: Triple Screen Trading")
    print("- ABands: Abohar Bands")
