# -*- coding: utf-8 -*-
"""
选股模块
基于技术分析和多因子模型进行股票筛选
"""
import sys
sys.path.append('.')

import pandas as pd

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

    def __init__(self, fetcher=None, config: dict = None,
                 data_dir: str = './stock_data'):
        """
        初始化

        Args:
            fetcher: StockDataFetcher实例
            config: 打分配置 dict; None 时读 config/stock_selector.json (C-P1-11 Step2),
                配置缺失回退内置默认 (与历史硬编码逐位一致)
            data_dir: 本地缓存目录 (审计 H4: 热门榜改数据驱动 → 读本地缓存)
        """
        self.fetcher = fetcher if fetcher else StockDataFetcher()
        self.analyzer = PositionAnalyzer(fetcher)
        self.data_dir = data_dir
        self._dm = None
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

    def get_hot_stocks(self, market='all', count=10, as_of=None,
                       period=20, universe=None):
        """
        获取"热门"股票 (近期表现前列者)

        审计 H4: 旧实现是**手写的 35 只热门板块名单** (ai/chip/new_energy/
        military/consumer/finance/tmt 各 5 只) —— 人工挑的名单与**任何
        日期无关** → 历史回测里等于"用今天的名单回测过去", 是硬编码
        前视 + 幸存者偏差; 且名单会随时间腐化 (无人维护)。

        现改为**数据驱动**: 从**本地缓存股票池**按最近 period 个交易日的
        涨幅排序 (无网络, 可复现)。缓存不可用 → 如实返回空列表 + 告警,
        不用手写名单顶替。

        Args:
            market: 市场范围 ('sh'=上海, 'sz'=深圳, 'all'=全部)
            count: 返回数量
            as_of: point-in-time 截止日 (None = 最新视角); 给出时只用
                该日之前的数据排序 (审计 H4)
            period: 排名周期(交易日)
            universe: 候选池 (None → 取本地缓存股票池)

        Returns:
            list: 热门股票列表 [{symbol, change_pct, price, volume}, ...]
        """
        pool = self._hot_candidate_pool(universe, as_of=as_of)

        if not pool:
            print("[WARN] 本地缓存无可用股票 → 热门股票列表为空 "
                  "(不再用手写名单顶替)")
            return []

        # 市场范围过滤 (保留原参数语义)
        if market == 'sh':
            pool = [s for s in pool if str(s).startswith('6')]
        elif market == 'sz':
            pool = [s for s in pool if not str(s).startswith('6')]

        results = []
        for symbol in pool:
            try:
                data = self._cached_data(symbol, as_of=as_of)
                if data is None or len(data) < period + 1:
                    continue
                close = data['收盘']
                change_pct = (float(close.iloc[-1]) /
                              float(close.iloc[-period - 1]) - 1) * 100
                results.append({
                    'symbol': symbol,
                    'change_pct': change_pct,
                    'price': float(close.iloc[-1]),
                    'volume': float(data['成交量'].iloc[-1])
                    if '成交量' in data.columns else 0.0,
                })
            except Exception:
                continue

        results.sort(key=lambda x: x['change_pct'], reverse=True)
        return results[:count]

    def _hot_candidate_pool(self, universe=None, as_of=None) -> list:
        """热门榜候选池 = 本地缓存股票池 (审计 H4: 不用手写名单)。"""
        if universe is not None:
            pool = list(universe)
        else:
            try:
                from historical_data_manager import HistoricalDataManager
                dm = HistoricalDataManager(getattr(self, 'data_dir',
                                                    './stock_data'))
                pool = dm.get_universe(min_history_days=60, min_rows=30,
                                       as_of=as_of)
            except Exception as e:
                print(f"[WARN] 读取本地缓存股票池失败: {str(e)[:80]}")
                pool = []

        if not pool:
            return []

        if as_of is None:
            return pool
        # point-in-time: 池子必须覆盖 as_of (否则部分覆盖 = 静默有偏)
        return pool

    def _cached_data(self, symbol, as_of=None):
        """取本地缓存行情 (None → 无缓存); as_of → 截断到该日之前。"""
        try:
            from historical_data_manager import HistoricalDataManager
            dm = getattr(self, '_dm', None)
            if dm is None:
                dm = HistoricalDataManager(getattr(self, 'data_dir',
                                                    './stock_data'))
                self._dm = dm
            df = dm.load(symbol)
        except Exception:
            return None
        if df is None or len(df) == 0:
            return None
        if as_of is not None and '日期' in df.columns:
            df = df[pd.to_datetime(df['日期']) <= pd.Timestamp(as_of)]
        return df if len(df) else None

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


def get_hot_stocks(market='all', count=10, as_of=None, period=20,
                   universe=None, data_dir='./stock_data'):
    """
    获取热门股票 (近期表现前列者; 审计 H4: 数据驱动, 不用手写名单)

    Args:
        market: 市场范围
        count: 返回数量
        as_of: point-in-time 截止日 (None = 最新视角)
        period: 排名周期(交易日)
        universe: 候选池 (None → 本地缓存股票池)
        data_dir: 本地缓存目录

    Returns:
        list: 热门股票列表
    """
    selector = StockSelector(data_dir=data_dir)
    return selector.get_hot_stocks(market, count, as_of=as_of, period=period,
                                   universe=universe)


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

