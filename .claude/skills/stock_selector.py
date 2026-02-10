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


class StockSelector:
    """选股类"""

    def __init__(self, fetcher=None):
        """
        初始化

        Args:
            fetcher: StockDataFetcher实例
        """
        self.fetcher = fetcher if fetcher else StockDataFetcher()
        self.analyzer = PositionAnalyzer(fetcher)

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
        """计算股票综合评分"""
        score = 0
        close = data['收盘']
        current_price = latest['收盘']

        # 1. 趋势评分 (30分)
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

        # 2. MACD评分 (20分)
        if latest['MACD'] > 0 and latest['MACD_Signal'] > 0:
            score += 20
        elif latest['MACD'] > latest['MACD_Signal']:
            score += 10

        # 3. RSI评分 (15分)
        rsi = latest['RSI']
        if 40 <= rsi <= 65:
            score += 15
        elif rsi < 30:
            score += 10
        elif rsi < 40:
            score += 8

        # 4. 近期表现 (15分)
        change_20d = (current_price / data['收盘'].iloc[-21] - 1) * 100
        if change_20d > 10:
            score += 15
        elif change_20d > 5:
            score += 12
        elif change_20d > 0:
            score += 8

        # 5. 成交量 (10分)
        vol_ma5 = data['成交量'].tail(5).mean()
        if latest['成交量'] > vol_ma5 * 1.2:
            score += 10
        elif latest['成交量'] > vol_ma5:
            score += 5

        # 6. 波动率控制 (10分) - 不喜欢过高波动
        returns = data['收盘'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) * 100
        if 15 <= volatility <= 40:
            score += 10
        elif volatility < 15:
            score += 6

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

        # 市值
        if 'min_market_cap' in criteria:
            # 这里简化处理，实际应该获取市值数据
            pass

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
