# -*- coding: utf-8 -*-
"""
趋势指标库
Trend Indicators Library

包含: EMA, DEMA, TEMA, VWMA, Hull MA, 自适应MA等
"""

import numpy as np

from core.indicators import ema as _core_ema, vwap as _core_vwap


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
        df[f'EMA_{period}'] = _core_ema(df[column], period)
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
        ema1 = _core_ema(df[column], period)
        ema2 = _core_ema(ema1, period)
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
        ema1 = _core_ema(df[column], period)
        ema2 = _core_ema(ema1, period)
        ema3 = _core_ema(ema2, period)
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
    def vwap(df):
        """
        成交量加权平均价 (Volume Weighted Average Price) —— **累积口径**

        公式 (core 单一真相源 `core.indicators.vwap`):
        `VWAP = cumsum(TP × Volume) / cumsum(Volume)`, TP = (H+L+C)/3
        → **锚定传入序列的起点**, 逐根累积, 不是"当日单日 VWAP"。

        审计 L10: 旧文档声称按每根 bar 单独计算且只接受单行数据, 与实现
        不符 (实现一直是全序列累积) → 文档漂移会让调用方误以为拿到的是
        单根 bar 的值。调用方若喂 120 根日线, 得到的是**该 120 根的
        锚定 VWAP 序列**。

        Args:
            df: DataFrame (含 最高/最低/收盘/成交量 的**序列**, 非单行)

        Returns:
            添加 VWAP 列的 DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']
        volume = df['成交量']

        # VWAP = 累积(TP * Volume) / 累积Volume (core 单一真相源)
        df['VWAP'] = _core_vwap(high, low, close, volume)

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

        # 滞后跨度 (Chikou Span): 值即当根收盘; 图上回移 kijun 是展示层职责
        df['Chikou'] = close

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
    print("- VWAP: Volume Weighted Average Price")
    print("- Ichimoku: Ichimoku Kinko Hyo")
