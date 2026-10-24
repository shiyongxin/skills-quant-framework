# -*- coding: utf-8 -*-
"""
选股模块
基于技术分析和多因子模型进行股票筛选
"""
import sys
sys.path.append('.')
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from stock_data_fetcher import StockDataFetcher
from position_analyzer import PositionAnalyzer
import factor_library
import trade_constraints

# 打分内置默认 (与 config/stock_selector.json 出厂值逐位一致; 配置文件缺失时的回退)
DEFAULT_SCORE_CONFIG = {
    'trend_points': [30, 25, 20, 10, 5],
    'macd_both_positive_points': 20,
    'macd_bullish_cross_points': 10,
    'rsi_sweet_band': [40, 65],
    'rsi_sweet_points': 15,
    'rsi_oversold_deep_max': 30,
    'rsi_oversold_deep_points': 10,
    'rsi_oversold_max': 40,
    'rsi_oversold_points': 8,
    'momentum_20d_breakpoints_pct': [10, 5, 0],
    'momentum_20d_points': [15, 12, 8],
    'volume_surge_ratio': 1.2,
    'volume_surge_points': 10,
    'volume_above_avg_points': 5,
    'volatility_annualized_band_pct': [15, 40],
    'volatility_in_band_points': 10,
    'volatility_low_points': 6,
}


class StockSelector:
    """选股类"""

    def __init__(self, fetcher=None, config: dict = None):
        """
        初始化

        Args:
            fetcher: StockDataFetcher实例
            config: 打分配置 dict; None 时读 config/stock_selector.json (C-P1-11 Step2),
                配置缺失回退内置默认 (与历史硬编码逐位一致)
        """
        self.fetcher = fetcher if fetcher else StockDataFetcher()
        self.analyzer = PositionAnalyzer(fetcher)
        self.score_config = config if config is not None else (
            factor_library.load_config('stock_selector') or DEFAULT_SCORE_CONFIG)

    def screen_stocks(self, stock_list, min_score=60, max_count=5):
        """
        筛选股票

        Args:
            stock_list: 股票代码列表
            min_score: 最低评分要求
            max_count: 最多返回数量

        Returns:
            list: 筛选结果列表
        """
        results = []

        for symbol in stock_list:
            try:
                data = self.analyzer.get_stock_data(symbol, days=60)
                if data is None or len(data) < 40:
                    continue

                # 审计 C-P1-12: 前置过滤 — 一字涨停/停牌嫌疑/最低价不进推荐
                if not trade_constraints.check_last_bar(
                        data, code=symbol, side='buy').ok:
                    continue

                latest = data.iloc[-1]
                score = self._calculate_stock_score(data, latest)

                if score >= min_score:
                    results.append({
                        'symbol': symbol,
                        'score': score,
                        'price': latest['收盘'],
                        'change_1d': latest['涨跌幅'],
                        'change_5d': (latest['收盘'] / data['收盘'].iloc[-6] - 1) * 100 if len(data) > 5 else 0
                    })
            except Exception as e:
                continue

        # 按评分排序
        results.sort(key=lambda x: x['score'], reverse=True)

        return results[:max_count]

    def filter_by_criteria(self, stock_list, criteria):
        """
        按条件筛选股票

        Args:
            stock_list: 股票代码列表
            criteria: 筛选条件字典

        Returns:
            list: 筛选结果
        """
        results = []

        for symbol in stock_list:
            try:
                data = self.analyzer.get_stock_data(symbol, days=60)
                if data is None or len(data) < 40:
                    continue

                # 审计 C-P1-12: 前置过滤 — 一字涨停/停牌嫌疑/最低价不进推荐
                if not trade_constraints.check_last_bar(
                        data, code=symbol, side='buy').ok:
                    continue

                latest = data.iloc[-1]
                if self._match_criteria(data, latest, criteria):
                    results.append({
                        'symbol': symbol,
                        'price': latest['收盘'],
                        'change_1d': latest['涨跌幅']
                    })
            except Exception as e:
                continue

        return results

    def rank_by_performance(self, stock_list, period=20):
        """
        按表现排名

        Args:
            stock_list: 股票代码列表
            period: 排名周期 (天数)

        Returns:
            list: 排名结果
        """
        results = []

        for symbol in stock_list:
            try:
                data = self.analyzer.get_stock_data(symbol, days=period + 10)
                if data is None or len(data) < period:
                    continue

                latest = data.iloc[-1]
                start_price = data['收盘'].iloc[-period - 1]

                change_pct = (latest['收盘'] / start_price - 1) * 100

                results.append({
                    'symbol': symbol,
                    'change_pct': change_pct,
                    'price': latest['收盘'],
                    'volume': latest['成交量']
                })
            except Exception as e:
                continue

        # 按涨跌幅排序
        results.sort(key=lambda x: x['change_pct'], reverse=True)

        return results

    def get_hot_stocks(self, market='all', count=10):
        """
        获取热门股票

        Args:
            market: 市场范围 ('sh'=上海, 'sz'=深圳, 'all'=全部)
            count: 返回数量

        Returns:
            list: 热门股票列表
        """
        # 定义热门板块股票池
        hot_stocks = {
            'ai': ['002415', '300059', '002230', '300474', '002405'],
            'chip': ['600584', '002156', '300661', '688981', '002049'],
            'new_energy': ['300750', '002594', '688111', '002460', '601012'],
            'military': ['000725', '002025', '600893', '000547', '002475'],
            'consumer': ['000568', '000596', '600809', '000858', '002304'],
            'finance': ['600030', '601318', '601166', '000001', '601398'],
            'tmt': ['002475', '002241', '300433', '002600', '000063'],
        }

        all_stocks = []
        if market == 'all':
            for stocks in hot_stocks.values():
                all_stocks.extend(stocks)
        elif market == 'sh':
            for stocks in hot_stocks.values():
                all_stocks.extend([s for s in stocks if s.startswith('6')])
        elif market == 'sz':
            for stocks in hot_stocks.values():
                all_stocks.extend([s for s in stocks if not s.startswith('6')])

        # 按表现排名
        ranked = self.rank_by_performance(all_stocks, period=20)

        return ranked[:count]

    def _calculate_stock_score(self, data, latest):
        """计算股票综合评分 (数值读 self.score_config, 控制流留代码)"""
        cfg = self.score_config
        score = 0
        current_price = latest['收盘']

        # 1. 趋势评分
        tp = cfg['trend_points']
        if current_price > latest['MA5'] > latest['MA10'] > latest['MA20']:
            score += tp[0]
        elif current_price > latest['MA5'] > latest['MA20']:
            score += tp[1]
        elif current_price > latest['MA20']:
            score += tp[2]
        elif latest['MA5'] > latest['MA20']:
            score += tp[3]
        elif current_price > latest['MA60']:
            score += tp[4]

        # 2. MACD评分
        if latest['MACD'] > 0 and latest['MACD_Signal'] > 0:
            score += cfg['macd_both_positive_points']
        elif latest['MACD'] > latest['MACD_Signal']:
            score += cfg['macd_bullish_cross_points']

        # 3. RSI评分
        rsi = latest['RSI']
        band_lo, band_hi = cfg['rsi_sweet_band']
        if band_lo <= rsi <= band_hi:
            score += cfg['rsi_sweet_points']
        elif rsi < cfg['rsi_oversold_deep_max']:
            score += cfg['rsi_oversold_deep_points']
        elif rsi < cfg['rsi_oversold_max']:
            score += cfg['rsi_oversold_points']

        # 4. 近期表现 (20日动量)
        change_20d = factor_library.momentum_pct(data['收盘'], 20)
        bp = cfg['momentum_20d_breakpoints_pct']
        pts = cfg['momentum_20d_points']
        if change_20d > bp[0]:
            score += pts[0]
        elif change_20d > bp[1]:
            score += pts[1]
        elif change_20d > bp[2]:
            score += pts[2]

        # 5. 成交量
        vol_ma5 = factor_library.volume_ma(data['成交量'], 5)
        if latest['成交量'] > vol_ma5 * cfg['volume_surge_ratio']:
            score += cfg['volume_surge_points']
        elif latest['成交量'] > vol_ma5:
            score += cfg['volume_above_avg_points']

        # 6. 波动率控制 - 不喜欢过高波动
        volatility = factor_library.annualized_volatility_pct(data['收盘'])
        vol_lo, vol_hi = cfg['volatility_annualized_band_pct']
        if vol_lo <= volatility <= vol_hi:
            score += cfg['volatility_in_band_points']
        elif volatility < vol_lo:
            score += cfg['volatility_low_points']

        return min(score, 100)

    def _match_criteria(self, data, latest, criteria):
        """检查是否符合筛选条件"""
        # 价格区间
        if 'min_price' in criteria and latest['收盘'] < criteria['min_price']:
            return False
        if 'max_price' in criteria and latest['收盘'] > criteria['max_price']:
            return False

        # 涨跌幅
        change = criteria.get('min_change', -100)
        if latest['涨跌幅'] < change:
            return False

        # 技术指标
        if 'trend' in criteria:
            if criteria['trend'] == 'up':
                if not (latest['MA5'] > latest['MA20']):
                    return False
            elif criteria['trend'] == 'down':
                if not (latest['MA5'] < latest['MA20']):
                    return False

        # MACD
        if 'macd' in criteria:
            if criteria['macd'] == 'golden_cross':
                if not (latest['MACD'] > latest['MACD_Signal']):
                    return False
            elif criteria['macd'] == 'death_cross':
                if not (latest['MACD'] < latest['MACD_Signal']):
                    return False

        return True


# 便捷函数
def select_stocks(stock_list, min_score=60, max_count=5):
    """
    筛选股票

    Args:
        stock_list: 股票代码列表
        min_score: 最低评分
        max_count: 最大返回数量

    Returns:
        list: 筛选结果
    """
    selector = StockSelector()
    return selector.screen_stocks(stock_list, min_score, max_count)


def get_hot_stocks(market='all', count=10):
    """
    获取热门股票

    Args:
        market: 市场范围
        count: 返回数量

    Returns:
        list: 热门股票列表
    """
    selector = StockSelector()
    return selector.get_hot_stocks(market, count)


def rank_by_performance(stock_list, period=20):
    """
    按表现排名

    Args:
        stock_list: 股票代码列表
        period: 周期(天)

    Returns:
        list: 排名结果
    """
    selector = StockSelector()
    return selector.rank_by_performance(stock_list, period)


# 测试
def to_selections(results: list, as_of=None) -> list:
    """screen_stocks 结果 → 统一契约 Selection 列表 (审计 C #9b).

    Args:
        results: `screen_stocks` 返回的 list[dict]
            ({symbol, score, price, change_1d, change_5d}, 已按分排序)
        as_of: 选股基准日; None = 实盘实时筛选, 契约记 ''
            (SS 用当日实时数据, 无 point-in-time 语义 — 如实留空)

    Returns:
        list[core.signal.Selection]; screen_stocks 已在入口丢弃
        交易约束阻断标的 (C-P1-12), 故入选项 executable=True。
    """
    from core.signal import SCALE_SCORE, Selection, normalize_date

    out = []
    for rank, r in enumerate(results or [], start=1):
        out.append(Selection(
            symbol=str(r.get('symbol', '')),
            as_of=normalize_date(as_of),
            score=float(r.get('score', 0.0)),
            scale=SCALE_SCORE,
            rank=rank,
            selected=True,
            source='stock_selector',
            extra={k: r[k] for k in ('price', 'change_1d', 'change_5d')
                   if k in r},
        ))
    return out


def to_selections(results: list, as_of=None) -> list:
    """screen_stocks 结果 → 统一契约 Selection 列表 (审计 C #9b).

    Args:
        results: `screen_stocks` 返回的 list[dict]
            ({symbol, score, price, change_1d, change_5d}, 已按分降序)
        as_of: 选股基准日; None = '' — SS 用实盘实时数据, 无 point-in-time
            语义 (审计 L10 待修), 契约如实留空不伪造基准日

    Returns:
        list[core.signal.Selection]; screen_stocks 已在入口丢弃交易约束
        阻断标的 (C-P1-12), 故入选项 executable=True。
    """
    from core.signal import SCALE_SCORE, Selection, normalize_date

    out = []
    for rank, r in enumerate(results or [], start=1):
        out.append(Selection(
            symbol=str(r.get('symbol', '')),
            as_of=normalize_date(as_of),
            score=float(r.get('score', 0.0)),
            scale=SCALE_SCORE,
            rank=rank,
            selected=True,
            source='stock_selector',
            extra={k: r[k] for k in ('price', 'change_1d', 'change_5d')
                   if k in r},
        ))
    return out


if __name__ == "__main__":
    print("股票筛选模块测试")
    print("=" * 60)

    # 测试热门股票
    hot = get_hot_stocks('all', 5)
    print("\n热门股票 Top 5:")
    for i, stock in enumerate(hot, 1):
        print(f"  {i}. {stock['symbol']} 涨幅:{stock['change_pct']:+.2f}%")

    # 测试筛选
    test_stocks = ['600519', '000858', '002415', '600036', '000001']
    selected = select_stocks(test_stocks, min_score=50, max_count=3)
    print(f"\n筛选结果 (评分>=50):")
    for stock in selected:
        print(f"  {stock['symbol']} 评分:{stock['score']} 现价:{stock['price']:.2f}")

