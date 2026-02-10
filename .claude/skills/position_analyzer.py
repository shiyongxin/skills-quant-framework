# -*- coding: utf-8 -*-
"""
持仓分析模块
分析单只股票的持仓状况，提供操作建议和做T策略
"""
import sys
sys.path.append('.')
import pandas as pd
import numpy as np
from datetime import datetime

from stock_data_fetcher import StockDataFetcher
from risk_management import RiskMetrics


class PositionAnalyzer:
    """持仓分析类"""

    def __init__(self, fetcher=None):
        """
        初始化

        Args:
            fetcher: StockDataFetcher实例，如果为None则创建新实例
        """
        self.fetcher = fetcher if fetcher else StockDataFetcher()

    def get_stock_data(self, symbol, days=120):
        """
        获取股票数据

        Args:
            symbol: 股票代码
            days: 获取天数

        Returns:
            DataFrame: 包含技术指标的股票数据
        """
        data = self.fetcher.get_quote_data(symbol, days=days)
        if data is None or len(data) < 60:
            return None

        # 计算技术指标
        close = data['收盘']
        high = data['最高']
        low = data['最低']
        volume = data['成交量']

        # MA
        for p in [5, 10, 20, 60]:
            data[f'MA{p}'] = close.rolling(window=p).mean()

        # EMA
        data['EMA20'] = close.ewm(span=20, adjust=False).mean()
        data['EMA50'] = close.ewm(span=50, adjust=False).mean()

        # MACD
        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()
        data['MACD'] = ema_fast - ema_slow
        data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()

        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain.div(loss, fill_value=100)  # 避免除以0
        data['RSI'] = 100 - (100 / (1 + rs))

        # KDJ
        low_n = low.rolling(window=9).min()
        high_n = high.rolling(window=9).max()
        rsv = (close - low_n) / (high_n - low_n) * 100
        data['K'] = rsv.ewm(span=3, adjust=False).mean()
        data['D'] = data['K'].ewm(span=3, adjust=False).mean()

        # Bollinger Bands
        data['BB_Middle'] = close.rolling(window=20).mean()
        data['BB_Std'] = close.rolling(window=20).std()
        data['BB_Upper'] = data['BB_Middle'] + 2 * data['BB_Std']
        data['BB_Lower'] = data['BB_Middle'] - 2 * data['BB_Std']

        # ATR
        data['TR'] = np.maximum(
            high - low,
            np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1)))
        )
        data['ATR'] = data['TR'].rolling(window=14).mean()

        # 涨跌幅
        data['涨跌幅'] = close.pct_change() * 100

        return data

    def analyze_position(self, symbol, shares, cost_price, stock_name=None):
        """
        分析持仓

        Args:
            symbol: 股票代码
            shares: 持股数量
            cost_price: 成本价格
            stock_name: 股票名称（可选）

        Returns:
            dict: 分析结果
        """
        # 获取数据
        data = self.get_stock_data(symbol)
        if data is None:
            return None

        latest = data.iloc[-1]
        current_price = latest['收盘']

        # 持仓信息
        total_cost = shares * cost_price
        market_value = shares * current_price
        profit_loss = (current_price - cost_price) * shares
        profit_loss_pct = (current_price / cost_price - 1) * 100

        # 回本分析
        recover_gain = (cost_price / current_price - 1) * 100

        # 技术分析
        ma5_dist = (current_price / latest['MA5'] - 1) * 100
        ma20_dist = (current_price / latest['MA20'] - 1) * 100
        ma60_dist = (current_price / latest['MA60'] - 1) * 100

        # MACD信号
        macd_signal = '金叉' if latest['MACD'] > latest['MACD_Signal'] else '死叉'

        # RSI状态
        rsi = latest['RSI']
        if rsi > 70:
            rsi_status = '超买'
        elif rsi < 30:
            rsi_status = '超卖'
        else:
            rsi_status = '中性'

        # 布林带位置
        bb_pos = (current_price - latest['BB_Lower']) / (latest['BB_Upper'] - latest['BB_Lower']) * 100

        # 波动率
        returns = data['收盘'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) * 100

        # 支撑压力位
        support_5 = data['最低'].tail(5).min()
        support_10 = data['最低'].tail(10).min()
        support_20 = data['最低'].tail(20).min()
        resistance_5 = data['最高'].tail(5).max()
        resistance_10 = data['最高'].tail(10).max()
        resistance_20 = data['最高'].tail(20).max()

        # 技术评分
        score = self._calculate_score(data, latest)

        # 亏损等级判断
        if profit_loss_pct >= 0:
            loss_level = '盈利'
        elif profit_loss_pct >= -10:
            loss_level = '小幅亏损'
        elif profit_loss_pct >= -20:
            loss_level = '中度亏损'
        else:
            loss_level = '严重亏损'

        # 操作建议
        advice = self._generate_advice(
            loss_level, score, latest, current_price,
            support_10, resistance_10
        )

        return {
            'symbol': symbol,
            'stock_name': stock_name,
            'shares': shares,
            'cost_price': cost_price,
            'current_price': current_price,
            'total_cost': total_cost,
            'market_value': market_value,
            'profit_loss': profit_loss,
            'profit_loss_pct': profit_loss_pct,
            'recover_gain': recover_gain,
            'loss_level': loss_level,
            'technical': {
                'ma5_dist': ma5_dist,
                'ma20_dist': ma20_dist,
                'ma60_dist': ma60_dist,
                'macd_signal': macd_signal,
                'rsi': rsi,
                'rsi_status': rsi_status,
                'bb_position': bb_pos,
                'volatility': volatility,
                'atr': latest['ATR']
            },
            'levels': {
                'support_5': support_5,
                'support_10': support_10,
                'support_20': support_20,
                'resistance_5': resistance_5,
                'resistance_10': resistance_10,
                'resistance_20': resistance_20
            },
            'score': score,
            'advice': advice
        }

    def _calculate_score(self, data, latest):
        """计算技术面评分"""
        score = 0
        close = data['收盘']
        current_price = latest['收盘']

        # 趋势评分 (30分)
        if current_price > latest['MA5'] > latest['MA10'] > latest['MA20']:
            score += 30
        elif current_price > latest['MA5'] > latest['MA20']:
            score += 25
        elif current_price > latest['MA20']:
            score += 20
        elif latest['MA5'] > latest['MA20']:
            score += 10
        elif current_price > latest['MA60']:
            score += 5

        # MACD评分 (20分)
        if latest['MACD'] > 0 and latest['MACD_Signal'] > 0:
            score += 20
        elif latest['MACD'] > latest['MACD_Signal']:
            score += 10

        # RSI评分 (15分)
        rsi = latest['RSI']
        if 40 <= rsi <= 65:
            score += 15
        elif rsi < 30:
            score += 10
        elif rsi < 40:
            score += 8

        # 近期表现 (15分)
        change_20d = (current_price / data['收盘'].iloc[-21] - 1) * 100
        if change_20d > 10:
            score += 15
        elif change_20d > 5:
            score += 12
        elif change_20d > 0:
            score += 8

        # 成交量 (10分)
        vol_ma5 = data['成交量'].tail(5).mean()
        if latest['成交量'] > vol_ma5 * 1.2:
            score += 10
        elif latest['成交量'] > vol_ma5:
            score += 5

        return min(score, 100)

    def _generate_advice(self, loss_level, score, latest, current_price, support, resistance):
        """生成操作建议"""
        advice = {
            'strategy': '',
            'action': '',
            'position_size': '',
            'stop_loss': '',
            'take_profit': '',
            't_trading': []
        }

        # 根据亏损等级给出策略
        if loss_level == '严重亏损':
            advice['strategy'] = '谨慎操作，可考虑小仓位做T降低成本'
            advice['action'] = '观望为主，不建议加仓'
        elif loss_level == '中度亏损':
            advice['strategy'] = '可考虑逢低补仓，但需要控制节奏'
            advice['action'] = '分批操作，等待反弹'
        elif loss_level == '小幅亏损':
            advice['strategy'] = '正常操作，等待回本'
            advice['action'] = '耐心持有'
        else:
            advice['strategy'] = '注意止盈，保护利润'
            advice['action'] = '考虑减仓'

        # 止损建议
        stop_loss_8pct = current_price * 0.92
        stop_loss_10pct = current_price * 0.90
        advice['stop_loss'] = f'建议止损: {stop_loss_8pct:.2f}元 (-8%) 或 {stop_loss_10pct:.2f}元 (-10%)'

        # 做T建议
        t_sell_price = resistance * 0.98
        t_buy_price = support * 1.02
        advice['t_trading'] = [
            f'反T: 反弹至{resistance:.2f}元附近卖出，回调至{support:.2f}元附近买回',
            f'正T: {support:.2f}元附近买入，反弹至{latest["MA20"]:.2f}元以上卖出'
        ]

        return advice

    def format_report(self, analysis_result):
        """格式化分析报告"""
        if not analysis_result:
            return "无法获取分析数据"

        lines = []
        lines.append("=" * 80)
        lines.append(f"                    {analysis_result['symbol']} {analysis_result['stock_name']} 持仓分析报告")
        lines.append("=" * 80)
        lines.append("")

        # 持仓信息
        lines.append("【持仓信息】")
        lines.append(f"  持股数量: {analysis_result['shares']} 股")
        lines.append(f"  成本价格: {analysis_result['cost_price']:.2f} 元")
        lines.append(f"  当前价格: {analysis_result['current_price']:.2f} 元")
        lines.append(f"  持仓市值: {analysis_result['market_value']:,.2f} 元")
        lines.append(f"  成本总值: {analysis_result['total_cost']:,.2f} 元")
        lines.append("")

        # 盈亏状况
        lines.append("【盈亏状况】")
        lines.append(f"  浮动盈亏: {analysis_result['profit_loss']:+,.2f} 元")
        lines.append(f"  浮动比例: {analysis_result['profit_loss_pct']:+.2f}%")
        lines.append(f"  亏损等级: {analysis_result['loss_level']}")
        lines.append(f"  回本需要: +{analysis_result['recover_gain']:.2f}%")
        lines.append("")

        # 技术面
        lines.append("【技术面分析】")
        tech = analysis_result['technical']
        lines.append(f"  趋势: MA5:{tech['ma5_dist']:+.2f}% MA20:{tech['ma20_dist']:+.2f}% MA60:{tech['ma60_dist']:+.2f}%")
        lines.append(f"  MACD: {tech['macd_signal']} RSI: {tech['rsi']:.1f} ({tech['rsi_status']})")
        lines.append(f"  布林带位置: {tech['bb_position']:.1f}%")
        lines.append(f"  波动率: {tech['volatility']:.2f}%")
        lines.append("")

        # 支撑压力
        lines.append("【支撑压力位】")
        levels = analysis_result['levels']
        lines.append(f"  10日支撑: {levels['support_10']:.2f} 元")
        lines.append(f"  10日压力: {levels['resistance_10']:.2f} 元")
        lines.append("")

        # 操作建议
        lines.append("【操作建议】")
        advice = analysis_result['advice']
        lines.append(f"  策略: {advice['strategy']}")
        lines.append(f"  操作: {advice['action']}")
        lines.append(f"  {advice['stop_loss']}")
        lines.append("")

        lines.append("【做T建议】")
        for t_tip in advice['t_trading']:
            lines.append(f"  {t_tip}")
        lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)


# 便捷函数
def analyze_position(symbol, shares, cost_price, stock_name=None, days=120):
    """
    分析持仓

    Args:
        symbol: 股票代码
        shares: 持股数量
        cost_price: 成本价格
        stock_name: 股票名称
        days: 分析天数

    Returns:
        dict: 分析结果
    """
    analyzer = PositionAnalyzer()
    return analyzer.analyze_position(symbol, shares, cost_price, stock_name)


def format_position_report(analysis_result):
    """
    格式化持仓分析报告

    Args:
        analysis_result: analyze_position的返回结果

    Returns:
        str: 格式化的报告文本
    """
    analyzer = PositionAnalyzer()
    return analyzer.format_report(analysis_result)


# 测试
if __name__ == "__main__":
    # 示例：分析大华股份持仓
    result = analyze_position(
        symbol='002236',
        shares=700,
        cost_price=23.83,
        stock_name='大华股份',
        days=120
    )

    if result:
        report = format_position_report(result)
        print(report)
    else:
        print("分析失败")
