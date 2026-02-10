"""
技术分析与回测示例
包含常用技术指标和简单策略回测
"""

import sys
sys.path.append('..')
from stock_data_fetcher import StockDataFetcher
import pandas as pd
import numpy as np

def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    计算MACD指标

    Args:
        df: 包含收盘价的数据
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期

    Returns:
        添加MACD指标的DataFrame
    """
    close = df['收盘']

    # 计算EMA
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    # MACD线
    df['MACD'] = ema_fast - ema_slow

    # 信号线
    df['MACD_Signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()

    # 柱状图
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    return df


def calculate_rsi(df, period=14):
    """
    计算RSI相对强弱指标

    Args:
        df: 包含收盘价的数据
        period: 周期

    Returns:
        添加RSI的DataFrame
    """
    close = df['收盘']
    delta = close.diff()

    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    return df


def calculate_bollinger_bands(df, period=20, std_dev=2):
    """
    计算布林带

    Args:
        df: 包含收盘价的数据
        period: 周期
        std_dev: 标准差倍数

    Returns:
        添加布林带的DataFrame
    """
    close = df['收盘']

    df['BB_Middle'] = close.rolling(window=period).mean()
    df['BB_Std'] = close.rolling(window=period).std()
    df['BB_Upper'] = df['BB_Middle'] + (df['BB_Std'] * std_dev)
    df['BB_Lower'] = df['BB_Middle'] - (df['BB_Std'] * std_dev)

    return df


def technical_analysis(stock_code, start_date, end_date):
    """
    综合技术分析

    Args:
        stock_code: 股票代码
        start_date: 开始日期
        end_date: 结束日期
    """
    print("="*70)
    print(f"📊 {stock_code} 技术分析报告")
    print("="*70)

    fetcher = StockDataFetcher()

    # 获取数据
    data = fetcher.get_quote_data(stock_code, start_date, end_date)

    if data.empty:
        print("❌ 没有数据")
        return

    # 计算技术指标
    data = fetcher.calculate_technical_indicators(data)
    data = calculate_macd(data)
    data = calculate_rsi(data)
    data = calculate_bollinger_bands(data)

    # 最新数据
    latest = data.iloc[-1]

    print(f"\n📅 最新日期: {latest['日期']}")
    print(f"💰 收盘价: {latest['收盘']:.2f}")

    # 趋势分析
    print("\n" + "-"*70)
    print("📈 趋势分析")
    print("-"*70)

    ma_trend = "↑" if latest['MA5'] > latest['MA10'] > latest['MA20'] else "↓"
    print(f"均线排列: MA5={latest['MA5']:.2f}, MA10={latest['MA10']:.2f}, MA20={latest['MA20']:.2f} {ma_trend}")

    macd_signal = "金叉" if latest['MACD'] > latest['MACD_Signal'] else "死叉"
    print(f"MACD: {latest['MACD']:.4f}, 信号线: {latest['MACD_Signal']:.4f} ({macd_signal})")

    rsi_status = "超买" if latest['RSI'] > 70 else ("超卖" if latest['RSI'] < 30 else "正常")
    print(f"RSI: {latest['RSI']:.2f} ({rsi_status})")

    bb_position = "上轨附近" if latest['收盘'] > latest['BB_Upper'] * 0.98 else ("下轨附近" if latest['收盘'] < latest['BB_Lower'] * 1.02 else "中轨")
    print(f"布林带: 上轨={latest['BB_Upper']:.2f}, 下轨={latest['BB_Lower']:.2f}, 当前位置: {bb_position}")

    # 综合评分
    score = 0
    signals = []

    if latest['MA5'] > latest['MA10']:
        score += 1
        signals.append("MA5>MA10")
    if latest['MACD'] > latest['MACD_Signal']:
        score += 1
        signals.append("MACD金叉")
    if 30 < latest['RSI'] < 70:
        score += 1
        signals.append("RSI正常区间")
    if latest['收盘'] > latest['BB_Lower']:
        score += 1
        signals.append("价格在布林带下轨之上")

    print("\n" + "-"*70)
    print(f"🎯 综合评分: {score}/4")
    print(f"积极信号: {', '.join(signals) if signals else '无明显信号'}")

    # 保存分析结果
    result_file = f"technical_analysis_{stock_code}.csv"
    data.to_csv(result_file, index=False, encoding='utf-8-sig')
    print(f"\n📁 详细数据已保存: {result_file}")


def backtest_ma_cross_strategy(stock_code, start_date, end_date, ma_short=5, ma_long=20):
    """
    均线交叉策略回测

    Args:
        stock_code: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        ma_short: 短均线周期
        ma_long: 长均线周期
    """
    print("="*70)
    print(f"🔬 {stock_code} 均线交叉策略回测 (MA{ma_short} vs MA{ma_long})")
    print("="*70)

    fetcher = StockDataFetcher()
    data = fetcher.get_quote_data(stock_code, start_date, end_date)

    if data.empty:
        return

    # 计算均线
    data[f'MA{ma_short}'] = data['收盘'].rolling(window=ma_short).mean()
    data[f'MA{ma_long}'] = data['收盘'].rolling(window=ma_long).mean()

    # 生成交易信号
    data['signal'] = 0
    data.loc[data[f'MA{ma_short}'] > data[f'MA{ma_long}'], 'signal'] = 1  # 买入
    data.loc[data[f'MA{ma_short}'] < data[f'MA{ma_long}'], 'signal'] = -1  # 卖出

    # 找出买卖点
    data['signal_change'] = data['signal'].diff()
    buy_points = data[data['signal_change'] == 2]  # 金叉
    sell_points = data[data['signal_change'] == -2]  # 死叉

    print(f"\n交易统计:")
    print(f"  买入次数: {len(buy_points)}")
    print(f"  卖出次数: {len(sell_points)}")

    if len(buy_points) > 0:
        print(f"\n最近买入信号:")
        for _, row in buy_points.tail(3).iterrows():
            print(f"  {row['日期']}: 价格 {row['收盘']:.2f}")

    if len(sell_points) > 0:
        print(f"\n最近卖出信号:")
        for _, row in sell_points.tail(3).iterrows():
            print(f"  {row['日期']}: 价格 {row['收盘']:.2f}")

    # 计算收益率
    if len(buy_points) > 0 and len(sell_points) > 0:
        trades = min(len(buy_points), len(sell_points))
        total_return = 0

        for i in range(trades):
            buy_price = buy_points.iloc[i]['收盘']
            sell_price = sell_points.iloc[i]['收盘']
            trade_return = (sell_price / buy_price - 1) * 100
            total_return += trade_return

        avg_return = total_return / trades
        print(f"\n策略表现:")
        print(f"  平均收益率: {avg_return:.2f}%")
        print(f"  总交易次数: {trades}")

    # 买入持有策略对比
    buy_hold_return = (data['收盘'].iloc[-1] / data['收盘'].iloc[0] - 1) * 100
    print(f"\n买入持有收益率: {buy_hold_return:.2f}%")


def backtest_breakout_strategy(stock_code, start_date, end_date, days=20):
    """
    突破策略回测
    策略: 价格突破N日最高点买入，跌破N日最低点卖出

    Args:
        stock_code: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        days: 突破周期
    """
    print("="*70)
    print(f"🔬 {stock_code} 突破策略回测 ({days}日突破)")
    print("="*70)

    fetcher = StockDataFetcher()
    data = fetcher.get_quote_data(stock_code, start_date, end_date)

    if data.empty:
        return

    # 计算高低点
    data['Highest'] = data['最高'].rolling(window=days).max()
    data['Lowest'] = data['最低'].rolling(window=days).min()

    # 生成信号
    data['buy_signal'] = data['收盘'] > data['Highest'].shift(1)
    data['sell_signal'] = data['收盘'] < data['Lowest'].shift(1)

    buy_points = data[data['buy_signal']]
    sell_points = data[data['sell_signal']]

    print(f"\n交易统计:")
    print(f"  买入信号: {len(buy_points)} 次")
    print(f"  卖出信号: {len(sell_points)} 次")

    if len(buy_points) > 0:
        print(f"\n最近突破:")
        for _, row in buy_points.tail(3).iterrows():
            print(f"  {row['日期']}: 突破 {row['Highest']:.2f}, 收盘 {row['收盘']:.2f}")


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║              技术分析与回测示例                                   ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║  1. 综合技术分析 - MA, MACD, RSI, 布林带                         ║
    ║  2. 均线交叉策略回测                                              ║
    ║  3. 突破策略回测                                                  ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)

    stock = "000001"  # 平安银行
    start = "20230101"
    end = "20231231"

    # 运行分析
    technical_analysis(stock, start, end)
    print("\n")

    backtest_ma_cross_strategy(stock, start, end, ma_short=5, ma_long=20)
    print("\n")

    backtest_breakout_strategy(stock, start, end, days=20)

    print("\n✅ 分析完成!")
