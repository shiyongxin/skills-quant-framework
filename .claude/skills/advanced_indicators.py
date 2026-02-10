# -*- coding: utf-8 -*-
"""
高级技术指标库
Advanced Technical Indicators Library

包含: ATR, KDJ, CCI, Williams %R, OBV, AD, DPO等
"""

import pandas as pd
import numpy as np


class AdvancedIndicators:
    """高级技术指标集合"""

    @staticmethod
    def atr(df, period=14):
        """
        平均真实波幅 (Average True Range)
        用于衡量波动性

        Args:
            df: 包含最高、最低、收盘价的DataFrame
            period: 计算周期

        Returns:
            添加ATR列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']

        # 计算真实波幅
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # ATR = TR的指数移动平均
        df['ATR'] = tr.ewm(span=period, adjust=False).mean()

        return df

    @staticmethod
    def kdj(df, n=9, m1=3, m2=3):
        """
        KDJ随机指标 (Stochastic Oscillator)
        超买超卖指标

        Args:
            df: 包含最高、最低、收盘价的DataFrame
            n: RSV周期
            m1: K值平滑周期
            m2: D值平滑周期

        Returns:
            添加K、D、J列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']

        # 计算RSV
        low_n = low.rolling(window=n).min()
        high_n = high.rolling(window=n).max()
        rsv = (close - low_n) / (high_n - low_n) * 100

        # 计算K、D、J
        df['K'] = rsv.ewm(span=m1, adjust=False).mean()
        df['D'] = df['K'].ewm(span=m2, adjust=False).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']

        return df

    @staticmethod
    def cci(df, period=20):
        """
        商品通道指标 (Commodity Channel Index)
        衡量价格偏离平均值的程度

        Args:
            df: 包含最高、最低、收盘价的DataFrame
            period: 计算周期

        Returns:
            添加CCI列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']

        # 典型价格
        tp = (high + low + close) / 3

        # CCI = (TP - MA(TP)) / (0.015 * MD)
        ma_tp = tp.rolling(window=period).mean()
        md = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)

        df['CCI'] = (tp - ma_tp) / (0.015 * md)

        return df

    @staticmethod
    def williams_r(df, period=14):
        """
        威廉指标 (Williams %R)
        动量指标，衡量超买超卖

        Args:
            df: 包含最高、最低、收盘价的DataFrame
            period: 计算周期

        Returns:
            添加Williams_R列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']

        # Williams %R = (Highest High - Close) / (Highest High - Lowest Low) * -100
        high_n = high.rolling(window=period).max()
        low_n = low.rolling(window=period).min()

        df['Williams_R'] = (high_n - close) / (high_n - low_n) * -100

        return df

    @staticmethod
    def obv(df):
        """
        能量潮 (On Balance Volume)
        成交量累积指标

        Args:
            df: 包含收盘价、成交量的DataFrame

        Returns:
            添加OBV列的DataFrame
        """
        df = df.copy()

        close = df['收盘']
        volume = df['成交量']

        # 价格上涨时OBV增加，下跌时减少
        obv = pd.Series(index=df.index, dtype=float)
        obv.iloc[0] = volume.iloc[0]

        for i in range(1, len(df)):
            if close.iloc[i] > close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + volume.iloc[i]
            elif close.iloc[i] < close.iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - volume.iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]

        df['OBV'] = obv

        return df

    @staticmethod
    def ad_line(df):
        """
        累积/派发线 (Accumulation/Distribution Line)
        衡量资金流入流出

        Args:
            df: 包含最高、最低、收盘、成交量的DataFrame

        Returns:
            添加AD列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']
        volume = df['成交量']

        # CLV = (Close - Low) - (High - Close) / (High - Low)
        clv = ((close - low) - (high - close)) / (high - low)
        clv = clv.fillna(0)

        # AD = CLV * Volume 的累积和
        df['AD'] = (clv * volume).cumsum()

        return df

    @staticmethod
    def dpo(df, period=14):
        """
        去势价格震荡指标 (Detrended Price Oscillator)
        消除趋势影响，显示周期性

        Args:
            df: 包含收盘价的DataFrame
            period: 计算周期

        Returns:
            添加DPO列的DataFrame
        """
        df = df.copy()

        close = df['收盘']

        # DPO = Close - Period/2+1日前的移动平均
        ma_offset = close.rolling(window=period // 2 + 1).mean().shift(period // 2 + 1)
        df['DPO'] = close - ma_offset

        return df

    @staticmethod
    def trix(df, period=14):
        """
        三重指数平滑平均线 (TRIX)
        过滤短期波动

        Args:
            df: 包含收盘价的DataFrame
            period: 计算周期

        Returns:
            添加TRIX、TRIX_Signal列的DataFrame
        """
        df = df.copy()

        close = df['收盘']

        # 三重EMA
        ema1 = close.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()

        # TRIX = EMA3的变化率
        df['TRIX'] = ema3.pct_change() * 100
        df['TRIX_Signal'] = df['TRIX'].ewm(span=9, adjust=False).mean()

        return df

    @staticmethod
    def mass_index(df, period=25, ema_period=9):
        """
        质量指数 (Mass Index)
        识别趋势反转

        Args:
            df: 包含最高、最低价的DataFrame
            period: 计算周期
            ema_period: EMA周期

        Returns:
            添加Mass_Index列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']

        # 价格幅度
        range_ = high - low

        # 双重EMA
        ema1 = range_.ewm(span=ema_period, adjust=False).mean()
        ema2 = ema1.ewm(span=ema_period, adjust=False).mean()

        # Mass Index = EMA1 / EMA2 的period日和
        df['Mass_Index'] = (ema1 / ema2).rolling(window=period).sum()

        return df

    @staticmethod
    def vwap(df):
        """
        成交量加权平均价 (Volume Weighted Average Price)

        Args:
            df: 包含最高、最低、收盘、成交量的DataFrame

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

        # VWAP = TP的成交量加权累积平均
        df['VWAP'] = (tp * volume).cumsum() / volume.cumsum()

        return df

    @staticmethod
    def keltner_channel(df, period=20, multiplier=2):
        """
        肯特纳通道 (Keltner Channel)
        基于ATR的通道

        Args:
            df: 包含最高、最低、收盘、成交量的DataFrame
            period: 计算周期
            multiplier: ATR倍数

        Returns:
            添加KC_Upper、KC_Middle、KC_Lower列的DataFrame
        """
        df = df.copy()

        # 计算ATR
        df = AdvancedIndicators.atr(df, period)

        # EMA作为中轨
        close = df['收盘']
        df['KC_Middle'] = close.ewm(span=period, adjust=False).mean()

        # ATR倍数作为上下轨
        df['KC_Upper'] = df['KC_Middle'] + multiplier * df['ATR']
        df['KC_Lower'] = df['KC_Middle'] - multiplier * df['ATR']

        return df

    @staticmethod
    def donchian_channel(df, period=20):
        """
        唐奇安通道 (Donchian Channel)
        基于N日高低点的通道

        Args:
            df: 包含最高、最低价的DataFrame
            period: 计算周期

        Returns:
            添加DC_Upper、DC_Lower、DC_Middle列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']

        df['DC_Upper'] = high.rolling(window=period).max()
        df['DC_Lower'] = low.rolling(window=period).min()
        df['DC_Middle'] = (df['DC_Upper'] + df['DC_Lower']) / 2

        return df

    @staticmethod
    def money_flow_index(df, period=14):
        """
        资金流量指数 (Money Flow Index)
        结合价格和成交量的动量指标

        Args:
            df: 包含最高、最低、收盘、成交量的DataFrame
            period: 计算周期

        Returns:
            添加MFI列的DataFrame
        """
        df = df.copy()

        high = df['最高']
        low = df['最低']
        close = df['收盘']
        volume = df['成交量']

        # 典型价格
        tp = (high + low + close) / 3

        # 资金流量
        mf = tp * volume

        # 上涨/下跌资金流量
        positive_mf = mf.where(tp > tp.shift(1), 0)
        negative_mf = mf.where(tp < tp.shift(1), 0)

        # 资金比率
        mf_ratio = positive_mf.rolling(window=period).sum() / negative_mf.rolling(window=period).sum()

        # MFI = 100 - 100 / (1 + 资金比率)
        df['MFI'] = 100 - 100 / (1 + mf_ratio)

        return df

    @staticmethod
    def calculate_all(df, indicators=None):
        """
        计算所有高级指标

        Args:
            df: 原始OHLCV数据
            indicators: 要计算的指标列表，None表示全部

        Returns:
            添加所有指标的DataFrame
        """
        if indicators is None:
            indicators = [
                'atr', 'kdj', 'cci', 'williams_r',
                'obv', 'ad_line', 'dpo', 'trix',
                'vwap', 'keltner', 'donchian', 'mfi'
            ]

        indicator_map = {
            'atr': lambda x: AdvancedIndicators.atr(x),
            'kdj': lambda x: AdvancedIndicators.kdj(x),
            'cci': lambda x: AdvancedIndicators.cci(x),
            'williams_r': lambda x: AdvancedIndicators.williams_r(x),
            'obv': lambda x: AdvancedIndicators.obv(x),
            'ad_line': lambda x: AdvancedIndicators.ad_line(x),
            'dpo': lambda x: AdvancedIndicators.dpo(x),
            'trix': lambda x: AdvancedIndicators.trix(x),
            'vwap': lambda x: AdvancedIndicators.vwap(x),
            'keltner': lambda x: AdvancedIndicators.keltner_channel(x),
            'donchian': lambda x: AdvancedIndicators.donchian_channel(x),
            'mfi': lambda x: AdvancedIndicators.money_flow_index(x),
        }

        for ind in indicators:
            if ind in indicator_map:
                df = indicator_map[ind](df)

        return df


# 便捷函数
def add_atr(df, period=14):
    """添加ATR指标"""
    return AdvancedIndicators.atr(df, period)

def add_kdj(df, n=9, m1=3, m2=3):
    """添加KDJ指标"""
    return AdvancedIndicators.kdj(df, n, m1, m2)

def add_cci(df, period=20):
    """添加CCI指标"""
    return AdvancedIndicators.cci(df, period)

def add_williams_r(df, period=14):
    """添加Williams %R指标"""
    return AdvancedIndicators.williams_r(df, period)

def add_obv(df):
    """添加OBV指标"""
    return AdvancedIndicators.obv(df)

def add_ad(df):
    """添加AD线指标"""
    return AdvancedIndicators.ad_line(df)

def add_mfi(df, period=14):
    """添加MFI指标"""
    return AdvancedIndicators.money_flow_index(df, period)


if __name__ == "__main__":
    # 测试示例
    print("Advanced Indicators Library")
    print("Available indicators:")
    print("- ATR: Average True Range")
    print("- KDJ: Stochastic Oscillator")
    print("- CCI: Commodity Channel Index")
    print("- Williams %R")
    print("- OBV: On Balance Volume")
    print("- AD: Accumulation/Distribution Line")
    print("- DPO: Detrended Price Oscillator")
    print("- TRIX: Triple Exponential Average")
    print("- VWAP: Volume Weighted Average Price")
    print("- Keltner Channel")
    print("- Donchian Channel")
    print("- MFI: Money Flow Index")
