# -*- coding: utf-8 -*-
"""
信号生成器模块
根据技术指标生成买卖信号
"""
import sys
sys.path.append('.')
import pandas as pd
import numpy as np
from datetime import datetime


class SignalGenerator:
    """信号生成器类"""

    def __init__(self):
        """初始化"""
        pass

    def generate_signals(self, data):
        """
        生成交易信号

        Args:
            data: 包含技术指标的DataFrame

        Returns:
            DataFrame: 添加了信号列的DataFrame
        """
        df = data.copy()

        # 生成各类信号
        df['signal_ma_cross'] = self._ma_cross_signal(df)
        df['signal_macd'] = self._macd_signal(df)
        df['signal_kdj'] = self._kdj_signal(df)
        df['signal_rsi'] = self._rsi_signal(df)
        df['signal_bb'] = self._bollinger_signal(df)
        df['signal_volume'] = self._volume_signal(df)
        df['signal_breakout'] = self._breakout_signal(df)

        # 综合信号
        df['signal_buy'] = self._combine_buy_signals(df)
        df['signal_sell'] = self._combine_sell_signals(df)
        df['signal_strength'] = self._calculate_signal_strength(df)

        return df

    def _ma_cross_signal(self, df):
        """均线交叉信号"""
        if 'MA5' not in df or 'MA20' not in df:
            return pd.Series(0, index=df.index)

        ma5 = df['MA5']
        ma20 = df['MA20']
        close = df['收盘']

        # 金叉：MA5上穿MA20
        golden_cross = (ma5 > ma20) & (ma5.shift(1) <= ma20.shift(1))

        # 死叉：MA5下穿MA20
        death_cross = (ma5 < ma20) & (ma5.shift(1) >= ma20.shift(1))

        signal = pd.Series(0, index=df.index)
        signal[golden_cross] = 1   # 买入信号
        signal[death_cross] = -1  # 卖出信号

        # 趋势确认
        trend_up = (close > ma5) & (ma5 > ma20)
        trend_down = (close < ma5) & (ma5 < ma20)

        signal[trend_up] = signal[trend_up].fillna(0.5)
        signal[trend_down] = signal[trend_down].fillna(-0.5)

        return signal

    def _macd_signal(self, df):
        """MACD信号"""
        if 'MACD' not in df or 'MACD_Signal' not in df:
            return pd.Series(0, index=df.index)

        macd = df['MACD']
        signal_line = df['MACD_Signal']

        # 金叉
        golden_cross = (macd > signal_line) & (macd.shift(1) <= signal_line.shift(1))

        # 死叉
        death_cross = (macd < signal_line) & (macd.shift(1) >= signal_line.shift(1))

        signal = pd.Series(0, index=df.index)
        signal[golden_cross] = 1
        signal[death_cross] = -1

        # 零轴上方
        above_zero = (macd > 0) & (signal_line > 0)
        below_zero = (macd < 0) & (signal_line < 0)

        signal[above_zero] = signal[above_zero].fillna(0.3)
        signal[below_zero] = signal[below_zero].fillna(-0.3)

        return signal

    def _kdj_signal(self, df):
        """KDJ信号"""
        if 'K' not in df or 'D' not in df:
            return pd.Series(0, index=df.index)

        k = df['K']
        d = df['D']

        # 金叉
        golden_cross = (k > d) & (k.shift(1) <= d.shift(1))

        # 死叉
        death_cross = (k < d) & (k.shift(1) >= d.shift(1))

        signal = pd.Series(0, index=df.index)
        signal[golden_cross] = 1
        signal[death_cross] = -1

        # 超买超卖
        overbought = k > 80
        oversold = k < 20

        signal[overbought] = signal[overbought].fillna(-0.5)  # 超买考虑卖出
        signal[oversold] = signal[oversold].fillna(0.5)     # 超卖考虑买入

        return signal

    def _rsi_signal(self, df):
        """RSI信号"""
        if 'RSI' not in df:
            return pd.Series(0, index=df.index)

        rsi = df['RSI']

        signal = pd.Series(0, index=df.index)

        # 超卖区买入信号
        oversold = (rsi < 30) & (rsi.shift(1) >= 30)
        signal[oversold] = 1

        # 超买区卖出信号
        overbought = (rsi > 70) & (rsi.shift(1) <= 70)
        signal[overbought] = -1

        # 强势区
        strong = rsi > 50
        weak = rsi < 50

        signal[strong] = signal[strong].fillna(0.2)
        signal[weak] = signal[weak].fillna(-0.2)

        return signal

    def _bollinger_signal(self, df):
        """布林带信号"""
        required_cols = ['BB_Upper', 'BB_Lower', '收盘']
        if not all(col in df for col in required_cols):
            return pd.Series(0, index=df.index)

        close = df['收盘']
        upper = df['BB_Upper']
        lower = df['BB_Lower']

        signal = pd.Series(0, index=df.index)

        # 突破上轨
        break_upper = close > upper
        signal[break_upper] = 0.5

        # 触及下轨
        touch_lower = close < lower
        signal[touch_lower] = -0.5

        # 回归中轨
        middle = df.get('BB_Middle', close)
        return_from_upper = (close < upper) & (close.shift(1) >= upper.shift(1))
        return_from_lower = (close > lower) & (close.shift(1) <= lower.shift(1))

        signal[return_from_lower] = 1   # 从下轨回归买入
        signal[return_from_upper] = -1  # 从上轨回归卖出

        return signal

    def _volume_signal(self, df):
        """成交量信号"""
        if '成交量' not in df:
            return pd.Series(0, index=df.index)

        volume = df['成交量']
        volume_ma5 = volume.rolling(5).mean()
        volume_ma20 = volume.rolling(20).mean()

        signal = pd.Series(0, index=df.index)

        # 放量
        high_volume = volume > volume_ma5 * 1.5
        signal[high_volume] = 0.3

        # 缩量
        low_volume = volume < volume_ma5 * 0.7
        signal[low_volume] = -0.2

        # 量价配合
        close = df['收盘']
        price_up = close > close.shift(1)
        volume_up = volume > volume_ma5

        price_down = close < close.shift(1)
        volume_down = volume < volume_ma5

        # 量增价涨
        if price_up.iloc[-1] and volume_up.iloc[-1]:
            signal.iloc[-1] = 0.5

        # 量增价跌
        if price_down.iloc[-1] and volume_up.iloc[-1]:
            signal.iloc[-1] = -0.5

        return signal

    def _breakout_signal(self, df):
        """突破信号"""
        close = df['收盘']
        high = df['最高']
        low = df['最低']

        # 20日新高
        high_20 = high.rolling(20).max()
        low_20 = low.rolling(20).min()

        signal = pd.Series(0, index=df.index)

        # 突破20日高点
        break_high = close > high_20.shift(1)
        signal[break_high] = 1

        # 跌破20日低点
        break_low = close < low_20.shift(1)
        signal[break_low] = -1

        return signal

    def _combine_buy_signals(self, df):
        """综合买入信号"""
        signals = [
            'signal_ma_cross',
            'signal_macd',
            'signal_kdj',
            'signal_rsi',
            'signal_bb',
            'signal_volume',
            'signal_breakout'
        ]

        # 只统计正信号
        buy_score = 0
        for sig in signals:
            if sig in df:
                buy_score += df[sig].apply(lambda x: max(0, x))

        # 买入阈值
        buy_signal = (buy_score >= 2).astype(int)

        return buy_signal

    def _combine_sell_signals(self, df):
        """综合卖出信号"""
        signals = [
            'signal_ma_cross',
            'signal_macd',
            'signal_kdj',
            'signal_rsi',
            'signal_bb',
            'signal_volume',
            'signal_breakout'
        ]

        # 只统计负信号
        sell_score = 0
        for sig in signals:
            if sig in df:
                sell_score += df[sig].apply(lambda x: max(0, -x))

        # 卖出阈值
        sell_signal = (sell_score >= 2).astype(int)

        return sell_signal

    def _calculate_signal_strength(self, df):
        """计算信号强度"""
        signals = [
            'signal_ma_cross',
            'signal_macd',
            'signal_kdj',
            'signal_rsi',
            'signal_bb',
            'signal_volume',
            'signal_breakout'
        ]

        strength = pd.Series(0, index=df.index)

        for sig in signals:
            if sig in df:
                strength += df[sig]

        # 归一化到-10到10
        strength = strength.clip(-10, 10)

        return strength

    def get_latest_signal(self, data):
        """
        获取最新信号

        Args:
            data: 包含技术指标的DataFrame

        Returns:
            dict: 最新信号信息
        """
        df = self.generate_signals(data)
        latest = df.iloc[-1]

        return {
            'date': latest.name if hasattr(latest.name, 'strftime') else latest['日期'],
            'price': latest['收盘'],
            'buy_signal': bool(latest['signal_buy']),
            'sell_signal': bool(latest['signal_sell']),
            'strength': latest['signal_strength'],
            'ma_cross': latest['signal_ma_cross'],
            'macd': latest['signal_macd'],
            'kdj': latest['signal_kdj'],
            'rsi': latest['signal_rsi'],
            'bb': latest['signal_bb'],
            'volume': latest['signal_volume'],
            'breakout': latest['signal_breakout']
        }

    def format_signal_report(self, signal_info):
        """格式化信号报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("交易信号报告")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"日期: {signal_info['date']}")
        lines.append(f"价格: {signal_info['price']:.2f} 元")
        lines.append("")

        lines.append("综合信号:")
        lines.append(f"  买入信号: {'是' if signal_info['buy_signal'] else '否'}")
        lines.append(f"  卖出信号: {'是' if signal_info['sell_signal'] else '否'}")
        lines.append(f"  信号强度: {signal_info['strength']:+.1f}")
        lines.append("")

        lines.append("分项信号:")

        # 均线信号
        ma = signal_info['ma_cross']
        if ma > 0:
            lines.append(f"  均线: 买入 (金叉)")
        elif ma < 0:
            lines.append(f"  均线: 卖出 (死叉)")
        else:
            lines.append(f"  均线: 中性")

        # MACD信号
        macd = signal_info['macd']
        if macd > 0:
            lines.append(f"  MACD: 买入 (金叉)")
        elif macd < 0:
            lines.append(f"  MACD: 卖出 (死叉)")
        else:
            lines.append(f"  MACD: 中性")

        # KDJ信号
        kdj = signal_info['kdj']
        if kdj > 0:
            lines.append(f"  KDJ: 买入 (金叉)")
        elif kdj < 0:
            lines.append(f"  KDJ: 卖出 (死叉)")
        else:
            lines.append(f"  KDJ: 中性")

        # RSI信号
        rsi = signal_info['rsi']
        if rsi > 0:
            lines.append(f"  RSI: 买入 (超卖)")
        elif rsi < 0:
            lines.append(f"  RSI: 卖出 (超买)")
        else:
            lines.append(f"  RSI: 中性")

        # 布林带信号
        bb = signal_info['bb']
        if bb > 0:
            lines.append(f"  布林带: 买入 (触及下轨)")
        elif bb < 0:
            lines.append(f"  布林带: 卖出 (突破上轨)")
        else:
            lines.append(f"  布林带: 中性")

        # 突破信号
        bo = signal_info['breakout']
        if bo > 0:
            lines.append(f"  突破: 买入 (突破新高)")
        elif bo < 0:
            lines.append(f"  突破: 卖出 (跌破新低)")
        else:
            lines.append(f"  突破: 无明显突破")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


# 便捷函数
def generate_signals(data):
    """生成交易信号"""
    generator = SignalGenerator()
    return generator.generate_signals(data)


def get_latest_signal(data):
    """获取最新信号"""
    generator = SignalGenerator()
    return generator.get_latest_signal(data)


def format_signal_report(signal_info):
    """格式化信号报告"""
    generator = SignalGenerator()
    return generator.format_signal_report(signal_info)


# 测试
if __name__ == "__main__":
    from stock_data_fetcher import StockDataFetcher

    fetcher = StockDataFetcher()

    # 测试信号生成
    print("测试信号生成器...")
    print()

    data = fetcher.get_quote_data('600519', days=120)
    if data is not None and len(data) > 0:
        # 计算技术指标
        data = fetcher.calculate_technical_indicators(data)

        # 生成信号
        generator = SignalGenerator()
        signal_info = generator.get_latest_signal(data)

        report = generator.format_signal_report(signal_info)
        print(report)
    else:
        print("无法获取数据")
