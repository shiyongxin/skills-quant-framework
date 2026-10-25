# -*- coding: utf-8 -*-
"""
技术分析综合模块
提供全面的技术分析功能，包括趋势分析、买卖信号、形态识别等
"""
import sys
sys.path.append('.')
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List

from stock_data_fetcher import StockDataFetcher
from trend_indicators import TrendIndicators
from pattern_recognition import CandlestickPatterns, PricePatterns
from advanced_indicators import AdvancedIndicators
from risk_management import RiskMetrics
from core.indicator_engine import IndicatorEngine


class TechnicalAnalyzer:
    """技术分析综合类"""

    def __init__(self, fetcher=None):
        """
        初始化

        Args:
            fetcher: StockDataFetcher实例
        """
        self.fetcher = fetcher if fetcher else StockDataFetcher()

    def analyze(self, symbol, days=120):
        """
        全面技术分析

        Args:
            symbol: 股票代码
            days: 分析天数

        Returns:
            dict: 完整的技术分析结果
        """
        # 获取数据 (FetchResult: 失败携带原因, 不再静默None)
        result = self.fetcher.get_quote_result(symbol, days=days)
        if not result.ok:
            print(f"[WARN] {symbol} 技术分析取消: 数据获取失败 ({result.error})")
            return None
        data = result.data
        if len(data) < 60:
            print(f"[WARN] {symbol} 数据不足60根 ({len(data)}根), 无法分析")
            return None

        # 计算各种指标
        data = self._calculate_indicators(data)

        latest = data.iloc[-1]

        # 趋势分析
        trend = self._analyze_trend(data)

        # 买卖信号 (描述性: 收盘后成立, 次一交易日开盘可执行)
        signals, signals_unavailable = self._analyze_signals(data)

        # 形态识别
        patterns = self._analyze_patterns(data)

        # 风险评估
        risk = self._assess_risk(data)

        # 支撑压力
        levels = self._find_levels(data)

        # 综合评分
        score = self._calculate_composite_score(data, latest)

        return {
            'symbol': symbol,
            'latest_price': latest['收盘'],
            'change_1d': latest['涨跌幅'],
            'analysis_date': latest['日期'],
            'trend': trend,
            'signals': signals,
            'signals_unavailable': signals_unavailable,
            'signal_timing': '信号基于最新bar收盘成立, 次一交易日开盘可执行 (t+1)',
            'patterns': patterns,
            'risk': risk,
            'levels': levels,
            'score': score
        }

    def _calculate_indicators(self, data):
        """计算技术指标"""
        # 共享指标引擎 (审计 #10): 公式唯一来源 core.indicators
        eng = IndicatorEngine(data)

        # 基础均线指标
        for p in [5, 10, 20, 60]:
            data[f'MA{p}'] = eng.ma(p)

        # MACD
        dif, dea, hist = eng.macd()
        data['MACD'], data['MACD_Signal'], data['MACD_Hist'] = dif, dea, hist

        # RSI（core 权威口径，消灭 fill_value=100 分歧）
        data['RSI'] = eng.rsi(14)

        # KDJ
        k, d, _j = eng.kdj()
        data['K'], data['D'] = k, d

        # 布林带
        upper, middle, lower, std = eng.bollinger(20, 2.0)
        data['BB_Middle'], data['BB_Std'] = middle, std
        data['BB_Upper'], data['BB_Lower'] = upper, lower

        # 趋势指标
        data = TrendIndicators.ema(data, 20)
        # 列名契约 (审计 B-C7): 统一 EMA20, EMA_20 保留为别名
        data['EMA20'] = data['EMA_20']
        data = TrendIndicators.hull_ma(data, 20)
        data = TrendIndicators.vwap(data)

        # 高级指标
        data = AdvancedIndicators.atr(data)
        data = AdvancedIndicators.kdj(data)
        data = AdvancedIndicators.calculate_all(data)

        return data

    def _analyze_trend(self, data):
        """分析趋势"""
        latest = data.iloc[-1]
        close = latest['收盘']  # 使用scalar值

        # 均线排列
        ma5 = latest['MA5']
        ma10 = latest.get('MA10', ma5)
        ma20 = latest['MA20']
        ma60 = latest['MA60']

        if close > ma5 > ma10 > ma20:
            trend = 'strong_up'  # 强势上涨
        elif close > ma5 > ma20:
            trend = 'up'  # 上涨
        elif ma5 > ma20:
            trend = 'consolidation'  # 整理
        elif close < ma5 < ma20:
            trend = 'down'  # 下跌
        else:
            trend = 'weak_down'  # 弱势下跌

        # 趋势强度
        if trend in ['strong_up', 'up']:
            strength = (close / ma20 - 1) * 100
        elif trend in ['weak_down', 'down']:
            strength = (ma20 / close - 1) * 100
        else:
            strength = 0

        return {
            'direction': trend,
            'strength': strength,
            'ma_alignment': self._get_ma_alignment(latest)
        }

    def _get_ma_alignment(self, latest):
        """获取均线排列"""
        mas = [
            latest['MA5'],
            latest.get('MA10', latest['MA5']),
            latest['MA20'],
            latest['MA60']
        ]

        if all(mas[i] <= mas[i+1] for i in range(len(mas)-1)):
            return '多头排列'
        elif all(mas[i] >= mas[i+1] for i in range(len(mas)-1)):
            return '空头排列'
        else:
            return '纠缠'

    def _analyze_signals(self, data):
        """分析买卖信号 (最新 bar 收盘后成立 → 次一交易日开盘可执行)

        口径约定 (审计 B10 / 审计 C #9b 诚实性):
        - **真交叉**: MACD/KDJ 的"金叉/死叉"只在**当根与前一根发生交叉**时
          报出 (与 signal_generator 的 shift(1) 交叉检测同源), 水平状态
          (K>D / DIF>DEA) 一律用中性标签, 不冒充"金叉"。
        - **NaN 不等于无信号**: 指标不可用 (数据不足) 时不静默跳过, 记入
          `unavailable` 返回, 由调用方展示"数据不足", 不冒充"无信号"。
        - **t+1 语义**: 信号基于最新 bar 收盘价成立, 最早只能在**次一交易日
          开盘**执行 (与 execution_model 的 t+1 成交规则一致); 本模块是
          描述性分析 (advisory), 不直接产生可成交指令。
        """
        latest = data.iloc[-1]
        signals: List[str] = []
        unavailable: List[str] = []

        def _val(col: str):
            """取末根指标值; NaN 记入 unavailable 并返回 None"""
            if col not in data.columns:
                unavailable.append(f'{col}(缺列)')
                return None
            v = latest[col]
            if v is None or pd.isna(v):
                unavailable.append(f'{col}(数据不足)')
                return None
            return float(v)

        # MACD信号（真交叉: 与前一根比较, 消除"水平比较当金叉"的口径冲突）
        macd = data['MACD']
        macd_signal = data['MACD_Signal']
        cross_up = (macd > macd_signal) & (macd.shift(1) <= macd_signal.shift(1))
        cross_down = (macd < macd_signal) & (macd.shift(1) >= macd_signal.shift(1))
        macd_v = _val('MACD')
        signal_v = _val('MACD_Signal')
        if macd_v is None or signal_v is None:
            pass
        elif bool(cross_up.iloc[-1]):
            signals.append('MACD金叉')
        elif bool(cross_down.iloc[-1]):
            signals.append('MACD死叉')
        elif macd_v > signal_v:
            signals.append('MACD多头(未交叉)')
        elif macd_v < signal_v:
            signals.append('MACD空头(未交叉)')

        # KDJ信号 (真交叉 + 中性档位标签, 不把水平状态叫"金叉")
        k = _val('K')
        d = _val('D')
        if k is None or d is None:
            pass
        else:
            prev_k = data['K'].iloc[-2] if len(data) >= 2 else None
            prev_d = data['D'].iloc[-2] if len(data) >= 2 else None
            k_cross_up = (prev_k is not None and not pd.isna(prev_k)
                          and not pd.isna(prev_d)
                          and k > d and prev_k <= prev_d)
            k_cross_down = (prev_k is not None and not pd.isna(prev_k)
                            and not pd.isna(prev_d)
                            and k < d and prev_k >= prev_d)
            if k_cross_up:
                signals.append('KDJ金叉')
            elif k_cross_down:
                signals.append('KDJ死叉')
            elif k > d:
                signals.append('KDJ多头(未交叉)')
            elif k < d:
                signals.append('KDJ空头(未交叉)')
            if k > 80:
                signals.append('KDJ超买')
            elif k < 20:
                signals.append('KDJ超卖')

        # RSI信号
        rsi = _val('RSI')
        if rsi is not None:
            if rsi > 70:
                signals.append('RSI超买')
            elif rsi < 30:
                signals.append('RSI超卖')

        # 布林带信号
        bb_upper = _val('BB_Upper')
        bb_lower = _val('BB_Lower')
        close = latest['收盘']
        if bb_upper is not None and bb_lower is not None:
            if close >= bb_upper:
                signals.append('突破上轨')
            elif close <= bb_lower:
                signals.append('触及下轨')

        # 均线信号
        ma5 = _val('MA5')
        ma20 = _val('MA20')
        if ma5 is not None and ma20 is not None:
            if close > ma5 and ma5 > ma20:
                signals.append('多头排列')
            elif close < ma5 and ma5 < ma20:
                signals.append('空头排列')

        return signals, unavailable

    def _analyze_patterns(self, data):
        """识别形态"""
        patterns = []

        # K线形态
        candlestick = CandlestickPatterns.scan_all_patterns(data.tail(10))
        if candlestick is not None and len(candlestick) > 0:
            # 检查最近的形态
            for col in candlestick.columns:
                if col.startswith('Pattern_') and candlestick[col].iloc[-1]:
                    pattern_name = col.replace('Pattern_', '')
                    patterns.append(f"K线: {pattern_name}")

        # 价格形态
        # 这里可以添加双底、双顶、头肩底等形态识别

        return patterns

    def _assess_risk(self, data):
        """评估风险"""
        returns = data['收盘'].pct_change().dropna()

        # 波动率
        volatility = returns.std() * np.sqrt(252) * 100

        # 最大回撤
        cummax = data['收盘'].cummax()
        drawdown = (cummax - data['收盘']) / cummax
        max_dd = drawdown.max() * 100

        # VaR
        var_95 = RiskMetrics.var(returns, 0.95) * 100

        # 风险等级
        if volatility > 50 or max_dd > 30:
            level = '高风险'
        elif volatility > 30 or max_dd > 20:
            level = '中风险'
        else:
            level = '低风险'

        return {
            'volatility': volatility,
            'max_drawdown': max_dd,
            'var_95': var_95,
            'level': level
        }

    def _find_levels(self, data):
        """查找支撑压力位"""
        latest = data.iloc[-1]
        current_price = latest['收盘']

        # 近期支撑压力
        support_levels = []
        resistance_levels = []

        # 5日、10日、20日、60日支撑
        for period in [5, 10, 20, 60]:
            if len(data) >= period:
                support = data['最低'].tail(period).min()
                resistance = data['最高'].tail(period).max()

                # 距离当前价格的百分比
                support_dist = (current_price - support) / current_price * 100
                resistance_dist = (resistance - current_price) / current_price * 100

                if support < current_price:
                    support_levels.append({
                        'period': f'{period}日',
                        'price': support,
                        'distance': support_dist
                    })

                if resistance > current_price:
                    resistance_levels.append({
                        'period': f'{period}日',
                        'price': resistance,
                        'distance': resistance_dist
                    })

        return {
            'support': support_levels,
            'resistance': resistance_levels
        }

    def _calculate_composite_score(self, data, latest, scoring_params=None):
        """
        计算综合评分

        Parameters:
        -----------
        data : DataFrame
            历史数据
        latest : Series
            最新一行数据
        scoring_params : dict or None
            评分参数，None则使用默认值
            - w_trend: 趋势权重 (默认30)
            - w_momentum: 动量权重 (默认25)
            - w_risk: 风险权重 (默认15)
            - w_performance: 近期表现权重 (默认30)
        """
        if scoring_params is None:
            scoring_params = {}

        w_trend = scoring_params.get('w_trend', 30)
        w_momentum = scoring_params.get('w_momentum', 25)
        w_risk = scoring_params.get('w_risk', 15)
        w_performance = scoring_params.get('w_performance', 30)

        score = 0
        close = data['收盘']
        current_price = latest['收盘']

        # 1. 趋势
        trend = self._analyze_trend(data)
        if trend['direction'] == 'strong_up':
            score += w_trend
        elif trend['direction'] == 'up':
            score += w_trend * 0.83
        elif trend['direction'] == 'consolidation':
            score += w_trend * 0.5
        elif trend['direction'] == 'down':
            score += w_trend * 0.17
        else:
            score += 0

        # 2. 动量
        signals = self._analyze_signals(data)
        bullish_signals = ['MACD金叉', 'KDJ金叉', 'RSI超卖', '多头排列', '突破上轨']
        signal_count = sum(1 for s in signals if any(b in s for b in bullish_signals))
        per_signal = w_momentum / 2.5  # 最多2.5个信号就能满分
        score += min(signal_count * per_signal, w_momentum)

        # 3. 风险调整
        risk = self._assess_risk(data)
        if risk['level'] == '低风险':
            score += w_risk
        elif risk['level'] == '中风险':
            score += w_risk * 0.67

        # 4. 近期表现
        change_20d = (current_price / data['收盘'].iloc[-21] - 1) * 100 if len(data) > 20 else 0

        if change_20d > 15:
            score += w_performance
        elif change_20d > 10:
            score += w_performance * 0.83
        elif change_20d > 5:
            score += w_performance * 0.67
        elif change_20d > 0:
            score += w_performance * 0.33
        elif change_20d > -5:
            score += w_performance * 0.17

        return min(score, 100)

    def generate_report(self, analysis_result):
        """生成技术分析报告"""
        if not analysis_result:
            return "无法进行分析"

        lines = []
        lines.append("=" * 80)
        lines.append(f"                    {analysis_result['symbol']} 技术分析报告")
        lines.append("=" * 80)
        lines.append("")

        # 基本信息
        lines.append("【基本信息】")
        lines.append(f"  分析日期: {analysis_result['analysis_date']}")
        lines.append(f"  最新价格: {analysis_result['latest_price']:.2f} 元")
        lines.append(f"  日涨跌幅: {analysis_result['change_1d']:+.2f}%")
        lines.append("")

        # 趋势分析
        lines.append("【趋势分析】")
        trend = analysis_result['trend']
        trend_desc = {
            'strong_up': '强势上涨',
            'up': '上涨',
            'consolidation': '整理',
            'down': '下跌',
            'weak_down': '弱势下跌'
        }
        lines.append(f"  趋势方向: {trend_desc[trend['direction']]}")
        lines.append(f"  趋势强度: {trend['strength']:+.2f}%")
        lines.append(f"  均线排列: {trend['ma_alignment']}")
        lines.append("")

        # 买卖信号
        lines.append("【交易信号】")
        signals = analysis_result['signals']
        if signals:
            for signal in signals:
                lines.append(f"  - {signal}")
        else:
            lines.append("  无明显信号")
        unavailable = analysis_result.get('signals_unavailable') or []
        if unavailable:
            lines.append(f"  [数据不足, 未判定] {', '.join(unavailable)}")
        lines.append(f"  * {analysis_result.get('signal_timing', '')}")
        lines.append("")

        # 形态识别
        lines.append("【形态识别】")
        patterns = analysis_result['patterns']
        if patterns:
            for pattern in patterns:
                lines.append(f"  - {pattern}")
        else:
            lines.append("  无明显形态")
        lines.append("")

        # 风险评估
        lines.append("【风险评估】")
        risk = analysis_result['risk']
        lines.append(f"  风险等级: {risk['level']}")
        lines.append(f"  年化波动率: {risk['volatility']:.2f}%")
        lines.append(f"  最大回撤: {risk['max_drawdown']:.2f}%")
        lines.append(f"  VaR(95%): {risk['var_95']:.2f}%")
        lines.append("")

        # 支撑压力
        lines.append("【关键位置】")
        levels = analysis_result['levels']
        lines.append("  支撑位:")
        for s in levels['support'][:3]:
            lines.append(f"    {s['period']}: {s['price']:.2f}元 ({s['distance']:+.2f}%)")
        lines.append("  压力位:")
        for r in levels['resistance'][:3]:
            lines.append(f"    {r['period']}: {r['price']:.2f}元 ({r['distance']:+.2f}%)")
        lines.append("")

        # 综合评分
        lines.append("【综合评分】")
        score = analysis_result['score']
        lines.append(f"  技术面评分: {score}/100")

        if score >= 80:
            rating = '优秀'
        elif score >= 60:
            rating = '良好'
        elif score >= 40:
            rating = '一般'
        else:
            rating = '较差'

        lines.append(f"  评级: {rating}")
        lines.append("")

        # 操作建议
        lines.append("【操作建议】")
        if score >= 70:
            lines.append("  技术面强势，可考虑逢低介入")
        elif score >= 50:
            lines.append("  技术面中性，建议观望等待")
        elif score >= 30:
            lines.append("  技术面偏弱，建议谨慎")
        else:
            lines.append("  技术面疲弱，建议回避")
        lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)


# 便捷函数
def analyze_technical(symbol, days=120):
    """
    技术分析

    Args:
        symbol: 股票代码
        days: 分析天数

    Returns:
        dict: 分析结果
    """
    analyzer = TechnicalAnalyzer()
    return analyzer.analyze(symbol, days)


def generate_technical_report(analysis_result):
    """
    生成技术分析报告

    Args:
        analysis_result: analyze_technical的返回结果

    Returns:
        str: 格式化的报告文本
    """
    analyzer = TechnicalAnalyzer()
    return analyzer.generate_report(analysis_result)


# 测试
if __name__ == "__main__":
    # 测试技术分析
    result = analyze_technical('600519', days=120)
    if result:
        print(generate_technical_report(result))
    else:
        print("分析失败")
