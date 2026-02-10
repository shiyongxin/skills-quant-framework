# -*- coding: utf-8 -*-
"""
测试获取601698数据并进行技术分析 - 直接版
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import sys

def calculate_macd(df, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    close = df['收盘']
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    df['MACD'] = ema_fast - ema_slow
    df['MACD_Signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    return df

def calculate_rsi(df, period=14):
    """计算RSI相对强弱指标"""
    close = df['收盘']
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def calculate_bollinger_bands(df, period=20, std_dev=2):
    """计算布林带"""
    close = df['收盘']
    df['BB_Middle'] = close.rolling(window=period).mean()
    df['BB_Std'] = close.rolling(window=period).std()
    df['BB_Upper'] = df['BB_Middle'] + (df['BB_Std'] * std_dev)
    df['BB_Lower'] = df['BB_Middle'] - (df['BB_Std'] * std_dev)
    return df

def calculate_ma(df):
    """计算移动平均线"""
    df['MA5'] = df['收盘'].rolling(window=5).mean()
    df['MA10'] = df['收盘'].rolling(window=10).mean()
    df['MA20'] = df['收盘'].rolling(window=20).mean()
    df['MA60'] = df['收盘'].rolling(window=60).mean()
    df['VOL_MA5'] = df['成交量'].rolling(window=5).mean()
    df['涨跌幅'] = df['收盘'].pct_change() * 100
    return df

def technical_analysis(stock_code, start_date, end_date):
    """综合技术分析"""
    # 创建输出文件
    output_file = f"analysis_{stock_code}_result.txt"
    original_stdout = sys.stdout

    with open(output_file, 'w', encoding='utf-8') as f:
        sys.stdout = f

        print("=" * 70)
        print(f"[分析] {stock_code} 技术分析报告")
        print("=" * 70)

        print(f"\n[日期] 分析时间范围: {start_date} ~ {end_date}")

        # 获取数据
        print(f"\n[获取] 正在获取股票数据...")

        try:
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )

            if df is None or len(df) == 0:
                print("[错误] 没有获取到数据")
                return None

            print(f"[成功] 获取到 {len(df)} 条数据")
            print(f"[列名] {df.columns.tolist()}")

            # 计算技术指标
            df = calculate_ma(df)
            df = calculate_macd(df)
            df = calculate_rsi(df)
            df = calculate_bollinger_bands(df)

            # 最新数据
            latest = df.iloc[-1]
            previous = df.iloc[-2]

            print(f"\n{'='*70}")
            print(f"[最新] 交易日: {latest['日期']}")
            print(f"[价格] 收盘: {latest['收盘']:.2f}")
            print(f"[涨跌] 涨跌幅: {latest['涨跌幅']:.2f}%")
            print(f"[成交] 成交量: {latest['成交量']:,.0f}")
            print(f"{'='*70}")

            # 趋势分析
            print(f"\n{'='*70}")
            print("[趋势] 均线系统")
            print(f"{'='*70}")

            ma_trend = "多头排列 UP" if latest['MA5'] > latest['MA10'] > latest['MA20'] else ("空头排列 DOWN" if latest['MA5'] < latest['MA10'] < latest['MA20'] else "震荡")
            print(f"状态: {ma_trend}")
            print(f"  MA5:  {latest['MA5']:.2f}")
            print(f"  MA10: {latest['MA10']:.2f}")
            print(f"  MA20: {latest['MA20']:.2f}")
            print(f"  MA60: {latest['MA60']:.2f}")

            # MACD分析
            macd_signal = "金叉" if latest['MACD'] > latest['MACD_Signal'] else "死叉"
            macd_trend = "UP" if latest['MACD'] > previous['MACD'] else "DOWN"
            print(f"\n[MACD] 指标")
            print(f"  DIF: {latest['MACD']:.4f} {macd_trend}")
            print(f"  DEA: {latest['MACD_Signal']:.4f}")
            print(f"  MACD柱: {latest['MACD_Hist']:.4f}")
            print(f"  信号: {macd_signal}")

            # RSI分析
            rsi_status = "超买>70" if latest['RSI'] > 70 else ("超卖<30" if latest['RSI'] < 30 else "正常30-70")
            print(f"\n[RSI] 强弱指标")
            print(f"  数值: {latest['RSI']:.2f}")
            print(f"  状态: {rsi_status}")

            # 布林带分析
            bb_width = ((latest['BB_Upper'] - latest['BB_Lower']) / latest['BB_Middle'] * 100)
            bb_position = (latest['收盘'] - latest['BB_Lower']) / (latest['BB_Upper'] - latest['BB_Lower']) * 100
            print(f"\n[布林带] BOLL")
            print(f"  上轨: {latest['BB_Upper']:.2f}")
            print(f"  中轨: {latest['BB_Middle']:.2f}")
            print(f"  下轨: {latest['BB_Lower']:.2f}")
            print(f"  带宽: {bb_width:.2f}%")
            print(f"  位置: {bb_position:.1f}% (0=下轨, 100=上轨)")

            # 综合评分
            print(f"\n{'='*70}")
            print("[综合] 评分分析")
            print(f"{'='*70}")

            score = 0
            signals = []

            # 均线信号
            if latest['MA5'] > latest['MA10'] > latest['MA20']:
                score += 2
                signals.append("[OK] 多头排列")
            elif latest['MA5'] > latest['MA10']:
                score += 1
                signals.append("[WAIT] 短期向上")
            elif latest['MA5'] < latest['MA10'] < latest['MA20']:
                signals.append("[BAD] 空头排列")

            # MACD信号
            if latest['MACD'] > latest['MACD_Signal'] and latest['MACD_Hist'] > previous['MACD_Hist']:
                score += 2
                signals.append("[OK] MACD金叉向上")
            elif latest['MACD'] > latest['MACD_Signal']:
                score += 1
                signals.append("[WAIT] MACD金叉")
            else:
                signals.append("[BAD] MACD死叉")

            # RSI信号
            if 40 < latest['RSI'] < 60:
                score += 1
                signals.append("[OK] RSI适中")
            elif latest['RSI'] < 30:
                signals.append("[WAIT] RSI超卖可能反弹")
            elif latest['RSI'] > 70:
                signals.append("[WAIT] RSI超买可能回调")

            # 成交量信号
            if latest['成交量'] > latest['VOL_MA5'] * 1.2:
                score += 1
                signals.append("[OK] 放量")
            elif latest['成交量'] < latest['VOL_MA5'] * 0.8:
                signals.append("[WAIT] 缩量")

            print(f"\n综合评分: {score}/6")
            print(f"\n信号列表:")
            for s in signals:
                print(f"  {s}")

            # 操作建议
            print(f"\n{'='*70}")
            print("[建议] 操作策略")
            print(f"{'='*70}")

            if score >= 4:
                print("  [GREEN] 建议关注 - 多个积极信号")
            elif score >= 2:
                print("  [YELLOW] 观望 - 信号中性")
            else:
                print("  [RED] 谨慎 - 多个消极信号")

            # 保存详细数据
            csv_file = f"technical_analysis_{stock_code}.csv"
            df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"\n[文件] 详细数据已保存: {csv_file}")

            print(f"\n{'='*70}")
            print("[完成] 分析结束")
            print(f"{'='*70}")

        except Exception as e:
            print(f"[错误] {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    # 恢复标准输出
    sys.stdout = original_stdout

    # 打印结果到屏幕
    with open(output_file, 'r', encoding='utf-8') as f:
        content = f.read()
        # 移除emoji，只保留基本ASCII字符用于显示
        import re
        # 将内容输出，移除可能导致问题的字符
        safe_content = content.encode('ascii', 'ignore').decode('ascii')
        print(safe_content)

    print(f"\n[文件] 完整报告已保存到: {output_file}")
    return df

if __name__ == "__main__":
    stock_code = "601698"

    # 获取最近半年数据
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

    print(f"开始分析股票 {stock_code}...")
    print(f"时间范围: {start_date} ~ {end_date}")
    print("正在获取数据并分析...\n")

    data = technical_analysis(stock_code, start_date, end_date)

    if data is not None:
        print(f"\n[成功] 分析完成!")
    else:
        print(f"\n[失败] 分析失败")
