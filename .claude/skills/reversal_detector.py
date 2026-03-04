# -*- coding: utf-8 -*-
"""
转折点预警系统
Reversal Point Alert System

目标：买在低点，卖在高点
方法：使用领先指标预判转折，而非等待滞后信号确认

核心逻辑：
1. 超买超卖预警 (RSI、KDJ)
2. 量价背离检测
3. 支撑压力位识别
4. 趋势减速监测
5. 综合预警评分
"""

import sys
sys.path.append('.claude/skills')

import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')


@dataclass
class ReversalAlert:
    """转折点预警"""
    code: str
    name: str
    price: float

    # 预警类型
    alert_type: str  # 'BUY' / 'SELL' / 'WATCH'

    # 预警信号
    signals: List[str]

    # 置信度 (0-100)
    confidence: float

    # 预计转折时间
    timing: str  # '即将' / '1-2天' / '3-5天'

    # 风险提示
    risk_note: str

    # 操作建议
    action: str


class ReversalDetector:
    """转折点检测器"""

    def __init__(self):
        pass

    def get_stock_data(self, code: str, days: int = 250) -> Optional[pd.DataFrame]:
        """获取股票数据"""
        try:
            if len(str(code)) == 6:
                full_code = f'sh{code}' if str(code).startswith('6') else f'sz{code}'
            else:
                full_code = code

            end_date = datetime.now()
            start_date = end_date - timedelta(days=days * 2)

            df = ak.stock_zh_a_daily(
                symbol=full_code,
                start_date=start_date.date(),
                end_date=end_date.date()
            )

            if df is None or len(df) < 60:
                return None

            column_mapping = {
                'date': '日期', 'open': '开盘', 'high': '最高',
                'low': '最低', 'close': '收盘', 'volume': '成交量'
            }
            df = df.rename(columns=column_mapping)
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.sort_values('日期').reset_index(drop=True)

            return df

        except Exception as e:
            return None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        close = df['收盘']
        high = df['最高']
        low = df['最低']
        volume = df['成交量']

        # 均线
        df['MA5'] = close.rolling(5).mean()
        df['MA10'] = close.rolling(10).mean()
        df['MA20'] = close.rolling(20).mean()
        df['MA60'] = close.rolling(60).mean()

        # RSI (多个周期)
        for period in [6, 14, 24]:
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            rs = gain / loss
            df[f'RSI{period}'] = 100 - (100 / (1 + rs))

        # KDJ
        low_n = low.rolling(9).min()
        high_n = high.rolling(9).max()
        rsv = (close - low_n) / (high_n - low_n) * 100
        df['K'] = rsv.ewm(3).mean()
        df['D'] = df['K'].ewm(3).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

        # 布林带
        df['BB_Middle'] = close.rolling(20).mean()
        df['BB_Std'] = close.rolling(20).std()
        df['BB_Upper'] = df['BB_Middle'] + 2 * df['BB_Std']
        df['BB_Lower'] = df['BB_Middle'] - 2 * df['BB_Std']
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle'] * 100

        # 成交量均线
        df['Vol_MA5'] = volume.rolling(5).mean()
        df['Vol_MA20'] = volume.rolling(20).mean()

        # 价格变化率
        df['ROC5'] = close.pct_change(5) * 100
        df['ROC10'] = close.pct_change(10) * 100

        # ATR
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()

        return df

    def detect_oversold(self, df: pd.DataFrame) -> Tuple[bool, List[str], float]:
        """检测超卖状态（买入机会）"""
        signals = []
        score = 0

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 1. RSI超卖
        rsi14 = latest['RSI14']
        if rsi14 < 20:
            signals.append(f'RSI严重超卖({rsi14:.1f})')
            score += 30
        elif rsi14 < 30:
            signals.append(f'RSI超卖({rsi14:.1f})')
            score += 20
        elif rsi14 < 40:
            signals.append(f'RSI偏低({rsi14:.1f})')
            score += 10

        # 2. KDJ超卖
        j = latest['J']
        if j < 0:
            signals.append(f'KDJ-J负值({j:.1f})')
            score += 20
        elif j < 20:
            signals.append(f'KDJ超卖(J={j:.1f})')
            score += 15

        # 3. 触及布林下轨
        if latest['收盘'] <= latest['BB_Lower'] * 1.02:
            signals.append('触及布林下轨')
            score += 15

        # 4. 价格远离均线
        if latest['收盘'] < latest['MA20'] * 0.9:
            signals.append('价格低于MA20超10%')
            score += 15

        # 5. 连续下跌
        down_days = sum(1 for i in range(1, min(6, len(df))) if df['收盘'].iloc[-i] < df['收盘'].iloc[-i-1])
        if down_days >= 4:
            signals.append(f'连续下跌{down_days}天')
            score += 10

        # 6. 量能萎缩（卖盘枯竭）
        if latest['成交量'] < latest['Vol_MA20'] * 0.5:
            signals.append('量能萎缩')
            score += 10

        return score > 30, signals, min(100, score)

    def detect_overbought(self, df: pd.DataFrame) -> Tuple[bool, List[str], float]:
        """检测超买状态（卖出机会）"""
        signals = []
        score = 0

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 1. RSI超买
        rsi14 = latest['RSI14']
        if rsi14 > 80:
            signals.append(f'RSI严重超买({rsi14:.1f})')
            score += 30
        elif rsi14 > 70:
            signals.append(f'RSI超买({rsi14:.1f})')
            score += 20
        elif rsi14 > 60:
            signals.append(f'RSI偏高({rsi14:.1f})')
            score += 10

        # 2. KDJ超买
        j = latest['J']
        if j > 100:
            signals.append(f'KDJ-J超100({j:.1f})')
            score += 20
        elif j > 80:
            signals.append(f'KDJ超买(J={j:.1f})')
            score += 15

        # 3. 触及布林上轨
        if latest['收盘'] >= latest['BB_Upper'] * 0.98:
            signals.append('触及布林上轨')
            score += 15

        # 4. 价格远离均线
        if latest['收盘'] > latest['MA20'] * 1.15:
            signals.append('价格高于MA20超15%')
            score += 15

        # 5. 连续上涨
        up_days = sum(1 for i in range(1, min(6, len(df))) if df['收盘'].iloc[-i] > df['收盘'].iloc[-i-1])
        if up_days >= 4:
            signals.append(f'连续上涨{up_days}天')
            score += 10

        # 6. 量价背离（价涨量缩）
        if latest['收盘'] > prev['收盘'] and latest['成交量'] < prev['成交量'] * 0.7:
            signals.append('量价背离')
            score += 15

        return score > 30, signals, min(100, score)

    def detect_divergence(self, df: pd.DataFrame) -> Tuple[str, List[str], float]:
        """检测背离（最强转折信号）"""
        signals = []
        score = 0
        divergence_type = 'NONE'

        if len(df) < 20:
            return divergence_type, signals, score

        # 取最近20天数据
        recent = df.tail(20)

        # 底背离：价格新低但RSI不创新低
        price_low_idx = recent['收盘'].idxmin()
        rsi_low_idx = recent['RSI14'].idxmin()

        if price_low_idx == recent.index[-1] or price_low_idx == recent.index[-2]:
            # 当前价格接近最低点
            recent_prices = recent['收盘'].values
            recent_rsi = recent['RSI14'].values

            # 找前一个低点
            for i in range(len(recent_prices) - 3, 5, -1):
                if recent_prices[i] < recent_prices[i-1] and recent_prices[i] < recent_prices[i+1]:
                    # 找到前一个低点
                    if recent_rsi[-1] > recent_rsi[i] and recent_prices[-1] < recent_prices[i]:
                        signals.append('RSI底背离')
                        score += 25
                        divergence_type = 'BULLISH'
                        break

        # 顶背离：价格新高但RSI不创新高
        price_high_idx = recent['收盘'].idxmax()
        rsi_high_idx = recent['RSI14'].idxmax()

        if price_high_idx == recent.index[-1] or price_high_idx == recent.index[-2]:
            recent_prices = recent['收盘'].values
            recent_rsi = recent['RSI14'].values

            for i in range(len(recent_prices) - 3, 5, -1):
                if recent_prices[i] > recent_prices[i-1] and recent_prices[i] > recent_prices[i+1]:
                    if recent_rsi[-1] < recent_rsi[i] and recent_prices[-1] > recent_prices[i]:
                        signals.append('RSI顶背离')
                        score += 25
                        divergence_type = 'BEARISH'
                        break

        return divergence_type, signals, score

    def detect_trend_exhaustion(self, df: pd.DataFrame) -> Tuple[str, List[str], float]:
        """检测趋势衰竭"""
        signals = []
        score = 0
        exhaustion_type = 'NONE'

        if len(df) < 10:
            return exhaustion_type, signals, score

        latest = df.iloc[-1]
        recent = df.tail(10)

        # 上涨衰竭
        # 1. 涨幅收窄
        roc5 = latest['ROC5']
        roc10 = latest['ROC10']

        if roc10 > 10 and roc5 < roc10 * 0.5:
            signals.append('上涨动能衰减')
            score += 15
            exhaustion_type = 'UP_EXHAUSTION'

        # 2. 连续上影线
        upper_shadows = 0
        for i in range(-3, 0):
            row = df.iloc[i]
            upper_shadow = row['最高'] - max(row['开盘'], row['收盘'])
            body = abs(row['收盘'] - row['开盘'])
            if upper_shadow > body * 0.5:
                upper_shadows += 1

        if upper_shadows >= 2:
            signals.append('连续上影线(抛压)')
            score += 15

        # 下跌衰竭
        # 1. 跌幅收窄
        if roc10 < -10 and roc5 > roc10 * 0.5:
            signals.append('下跌动能衰减')
            score += 15
            exhaustion_type = 'DOWN_EXHAUSTION'

        # 2. 连续下影线
        lower_shadows = 0
        for i in range(-3, 0):
            row = df.iloc[i]
            lower_shadow = min(row['开盘'], row['收盘']) - row['最低']
            body = abs(row['收盘'] - row['开盘'])
            if lower_shadow > body * 0.5:
                lower_shadows += 1

        if lower_shadows >= 2:
            signals.append('连续下影线(承接)')
            score += 15

        return exhaustion_type, signals, score

    def find_support_resistance(self, df: pd.DataFrame) -> Dict:
        """识别支撑压力位"""
        recent = df.tail(60)

        # 支撑位
        support_levels = []
        lows = recent['最低'].values
        for i in range(5, len(lows) - 5):
            if lows[i] == min(lows[i-5:i+5]):
                support_levels.append(lows[i])

        # 压力位
        resistance_levels = []
        highs = recent['最高'].values
        for i in range(5, len(highs) - 5):
            if highs[i] == max(highs[i-5:i+5]):
                resistance_levels.append(highs[i])

        latest_price = df['收盘'].iloc[-1]

        # 最近的支撑压力
        valid_supports = [s for s in support_levels if s < latest_price]
        valid_resistances = [r for r in resistance_levels if r > latest_price]

        nearest_support = max(valid_supports) if valid_supports else None
        nearest_resistance = min(valid_resistances) if valid_resistances else None

        return {
            'supports': sorted(set(support_levels), reverse=True)[:3],
            'resistances': sorted(set(resistance_levels))[:3],
            'nearest_support': nearest_support,
            'nearest_resistance': nearest_resistance,
            'support_distance': (latest_price - nearest_support) / latest_price * 100 if nearest_support else None,
            'resistance_distance': (nearest_resistance - latest_price) / latest_price * 100 if nearest_resistance else None
        }

    def analyze_reversal(self, code: str, name: str = '') -> Optional[ReversalAlert]:
        """分析转折点"""
        df = self.get_stock_data(code)
        if df is None:
            return None

        df = self.calculate_indicators(df)
        latest = df.iloc[-1]

        # 检测各种信号
        oversold, oversold_signals, oversold_score = self.detect_oversold(df)
        overbought, overbought_signals, overbought_score = self.detect_overbought(df)
        div_type, div_signals, div_score = self.detect_divergence(df)
        exhaust_type, exhaust_signals, exhaust_score = self.detect_trend_exhaustion(df)
        sr_levels = self.find_support_resistance(df)

        # 综合判断
        all_signals = []
        total_score = 0
        alert_type = 'WATCH'

        # 买入信号
        buy_score = oversold_score + (div_score if div_type == 'BULLISH' else 0) + \
                    (exhaust_score if exhaust_type == 'DOWN_EXHAUSTION' else 0)

        # 卖出信号
        sell_score = overbought_score + (div_score if div_type == 'BEARISH' else 0) + \
                     (exhaust_score if exhaust_type == 'UP_EXHAUSTION' else 0)

        if buy_score > sell_score and buy_score >= 40:
            alert_type = 'BUY'
            all_signals = oversold_signals + [s for s in div_signals if '底' in s] + \
                         [s for s in exhaust_signals if '下跌' in s or '下影' in s]
            total_score = buy_score
        elif sell_score > buy_score and sell_score >= 40:
            alert_type = 'SELL'
            all_signals = overbought_signals + [s for s in div_signals if '顶' in s] + \
                         [s for s in exhaust_signals if '上涨' in s or '上影' in s]
            total_score = sell_score
        else:
            alert_type = 'WATCH'
            all_signals = oversold_signals + overbought_signals + div_signals + exhaust_signals
            total_score = max(buy_score, sell_score)

        # 判断时机
        if total_score >= 70:
            timing = '即将'
        elif total_score >= 50:
            timing = '1-2天'
        else:
            timing = '3-5天'

        # 风险提示
        risk_note = ''
        if alert_type == 'BUY':
            if sr_levels['nearest_support']:
                risk_note = f"支撑位: {sr_levels['nearest_support']:.2f} (距离{sr_levels['support_distance']:.1f}%)"
        elif alert_type == 'SELL':
            if sr_levels['nearest_resistance']:
                risk_note = f"压力位: {sr_levels['nearest_resistance']:.2f} (距离{sr_levels['resistance_distance']:.1f}%)"

        # 操作建议
        if alert_type == 'BUY':
            if total_score >= 60:
                action = '分批建仓'
            else:
                action = '观望，准备'
        elif alert_type == 'SELL':
            if total_score >= 60:
                action = '分批减仓'
            else:
                action = '注意风险'
        else:
            action = '继续观望'

        return ReversalAlert(
            code=code,
            name=name,
            price=latest['收盘'],
            alert_type=alert_type,
            signals=all_signals[:5],  # 最多显示5个信号
            confidence=total_score,
            timing=timing,
            risk_note=risk_note,
            action=action
        )

    def analyze_stocks(self, stock_pool: Dict[str, str]) -> List[ReversalAlert]:
        """批量分析股票"""
        print()
        print('*' * 80)
        print('转折点预警系统 - 买在低点，卖在高点')
        print(f'分析时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'股票数量: {len(stock_pool)}')
        print('*' * 80)
        print()

        results = []

        for i, (code, name) in enumerate(stock_pool.items(), 1):
            print(f'[{i}/{len(stock_pool)}] 分析 {name}({code})...', end=' ')

            alert = self.analyze_reversal(code, name)
            if alert:
                results.append(alert)
                print(f'{alert.alert_type} ({alert.confidence:.0f}分)')
            else:
                print('FAILED')

        # 按置信度排序
        results = sorted(results, key=lambda x: x.confidence, reverse=True)

        # 显示结果
        self._display_results(results)

        return results

    def _display_results(self, results: List[ReversalAlert]):
        """显示分析结果"""
        print()
        print('=' * 100)
        print('转折点预警结果')
        print('=' * 100)
        print()

        # 买入信号
        buy_alerts = [r for r in results if r.alert_type == 'BUY']
        if buy_alerts:
            print('[买入机会 - 可能见底]')
            print('-' * 80)
            for r in buy_alerts:
                print(f'  {r.name}({r.code}) 价格:{r.price:.2f}')
                print(f'    信号: {", ".join(r.signals)}')
                print(f'    置信度: {r.confidence:.0f} | 时机: {r.timing}')
                print(f'    {r.risk_note} | 建议: {r.action}')
                print()

        # 卖出信号
        sell_alerts = [r for r in results if r.alert_type == 'SELL']
        if sell_alerts:
            print('[卖出预警 - 可能见顶]')
            print('-' * 80)
            for r in sell_alerts:
                print(f'  {r.name}({r.code}) 价格:{r.price:.2f}')
                print(f'    信号: {", ".join(r.signals)}')
                print(f'    置信度: {r.confidence:.0f} | 时机: {r.timing}')
                print(f'    {r.risk_note} | 建议: {r.action}')
                print()

        # 观望
        watch_alerts = [r for r in results if r.alert_type == 'WATCH']
        if watch_alerts:
            print('[观望 - 无明确信号]')
            print('-' * 80)
            for r in watch_alerts[:5]:  # 只显示前5个
                signals_str = ', '.join(r.signals[:2]) if r.signals else '无'
                print(f'  {r.name}({r.code}): {signals_str}')

        print()
        print('=' * 100)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='转折点预警系统 - 买在低点，卖在高点')
    parser.add_argument('--file', '-f', type=str, default=None,
                        help='股票列表CSV文件')
    parser.add_argument('--code', '-c', type=str, default=None,
                        help='分析单只股票')
    parser.add_argument('--top', type=int, default=20,
                        help='显示Top N')

    args = parser.parse_args()

    detector = ReversalDetector()

    if args.code:
        # 分析单只股票
        alert = detector.analyze_reversal(args.code, args.code)
        if alert:
            results = [alert]
            detector._display_results(results)
    elif args.file:
        # 从文件读取
        import pandas as pd
        df = pd.read_csv(args.file, encoding='utf-8-sig')

        column_map = {'股票代码': 'code', 'code': 'code', '股票名称': 'name', 'name': 'name'}
        df = df.rename(columns=column_map)

        stock_pool = {}
        for _, row in df.iterrows():
            code = str(row['code']).zfill(6)
            name = row.get('name', f'股票{code}')
            stock_pool[code] = name

        detector.analyze_stocks(stock_pool)
    else:
        print('请使用 --file 指定股票列表，或使用 --code 分析单只股票')


if __name__ == '__main__':
    main()
