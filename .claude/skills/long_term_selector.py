# -*- coding: utf-8 -*-
"""
中长期选股策略
Long-Term Stock Selection Strategy

基于多周期趋势分析，适合中长期持有（3-12个月）

选股逻辑：
1. 当前价格相对各周期均线位置
2. 3个月趋势（短期）
3. 6个月趋势（中期）
4. 1年趋势（长期）
5. 各周期趋势一致性
6. 基本面筛选（可选）
"""

import sys
sys.path.append('.claude/skills')

import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')


@dataclass
class StockAnalysis:
    """股票分析结果"""
    code: str
    name: str
    current_price: float

    # 各周期收益率
    return_1m: float      # 1个月收益率
    return_3m: float      # 3个月收益率
    return_6m: float      # 6个月收益率
    return_1y: float      # 1年收益率

    # 趋势评分 (0-100)
    trend_score_3m: float
    trend_score_6m: float
    trend_score_1y: float

    # 综合评分
    total_score: float

    # 技术指标
    ma20: float
    ma60: float
    ma120: float
    ma250: float

    # 趋势状态
    short_trend: str     # 短期趋势: UP/DOWN/SIDE
    mid_trend: str       # 中期趋势: UP/DOWN/SIDE
    long_trend: str      # 长期趋势: UP/DOWN/SIDE

    # 买入建议
    recommendation: str  # STRONG_BUY/BUY/HOLD/AVOID


class LongTermSelector:
    """中长期选股器"""

    def __init__(self):
        self.cache = {}

    def get_stock_data(self, code: str, days: int = 500) -> Optional[pd.DataFrame]:
        """
        获取股票历史数据

        Args:
            code: 股票代码
            days: 获取天数

        Returns:
            DataFrame or None
        """
        if code in self.cache:
            return self.cache[code]

        if len(str(code)) == 6:
            full_code = f'sh{code}' if str(code).startswith('6') else f'sz{code}'
        else:
            full_code = code

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days * 2)

        try:
            df = ak.stock_zh_a_daily(
                symbol=full_code,
                start_date=start_date.date(),
                end_date=end_date.date()
            )

            if df is None or len(df) < 250:
                return None

            # 标准化列名
            column_mapping = {
                'date': '日期', 'open': '开盘', 'high': '最高',
                'low': '最低', 'close': '收盘', 'volume': '成交量',
                'amount': '成交额'
            }
            df = df.rename(columns=column_mapping)
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.sort_values('日期').reset_index(drop=True)

            self.cache[code] = df
            return df

        except Exception as e:
            return None

    def calculate_returns(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        计算各周期收益率

        Args:
            df: 股票数据

        Returns:
            各周期收益率字典
        """
        current_price = df['收盘'].iloc[-1]

        returns = {}

        # 计算各周期收益率
        periods = {
            '1m': 20,    # 约1个月
            '3m': 60,    # 约3个月
            '6m': 120,   # 约6个月
            '1y': 240    # 约1年
        }

        for period_name, days in periods.items():
            if len(df) > days:
                past_price = df['收盘'].iloc[-days]
                ret = (current_price / past_price - 1) * 100
                returns[f'return_{period_name}'] = ret
            else:
                returns[f'return_{period_name}'] = 0

        return returns

    def calculate_trend_score(self, df: pd.DataFrame, period: int) -> float:
        """
        计算趋势得分 (0-100)

        考虑因素：
        1. 价格均线排列
        2. 趋势斜率
        3. 波动率
        4. 连续涨跌

        Args:
            df: 股票数据
            period: 周期天数

        Returns:
            趋势得分
        """
        if len(df) < period:
            return 50

        recent = df.tail(period)
        close = recent['收盘']

        score = 0

        # 1. 线性回归趋势 (40分)
        x = np.arange(len(close))
        z = np.polyfit(x, close.values, 1)
        slope = z[0] / close.mean() * 100  # 标准化斜率

        if slope > 0.5:
            score += 40
        elif slope > 0.2:
            score += 30
        elif slope > 0:
            score += 20
        elif slope > -0.2:
            score += 10

        # 2. 价格相对位置 (30分)
        period_high = close.max()
        period_low = close.min()
        current_price = close.iloc[-1]

        price_position = (current_price - period_low) / (period_high - period_low) * 100
        score += price_position * 0.3

        # 3. 连续性 (30分)
        # 计算近期上涨天数占比
        daily_change = close.diff().dropna()
        up_days = (daily_change > 0).sum()
        up_ratio = up_days / len(daily_change)
        score += up_ratio * 30

        return min(100, max(0, score))

    def determine_trend(self, df: pd.DataFrame, period: int) -> str:
        """
        判断趋势方向

        Args:
            df: 股票数据
            period: 周期天数

        Returns:
            'UP' / 'DOWN' / 'SIDE'
        """
        if len(df) < period:
            return 'SIDE'

        recent = df.tail(period)
        ma_short = recent['收盘'].rolling(window=period//5).mean().iloc[-1]
        ma_long = recent['收盘'].rolling(window=period//2).mean().iloc[-1]

        # 计算趋势强度
        if ma_short > ma_long * 1.05:
            return 'UP'
        elif ma_short < ma_long * 0.95:
            return 'DOWN'
        else:
            return 'SIDE'

    def analyze_stock(self, code: str, name: str = '') -> Optional[StockAnalysis]:
        """
        分析单只股票

        Args:
            code: 股票代码
            name: 股票名称

        Returns:
            StockAnalysis 对象
        """
        df = self.get_stock_data(code)
        if df is None:
            return None

        current_price = df['收盘'].iloc[-1]

        # 计算各周期收益率
        returns = self.calculate_returns(df)

        # 计算各周期趋势得分
        trend_score_3m = self.calculate_trend_score(df, 60)
        trend_score_6m = self.calculate_trend_score(df, 120)
        trend_score_1y = self.calculate_trend_score(df, 240)

        # 判断趋势
        short_trend = self.determine_trend(df, 60)
        mid_trend = self.determine_trend(df, 120)
        long_trend = self.determine_trend(df, 240)

        # 计算均线
        ma20 = df['收盘'].rolling(20).mean().iloc[-1]
        ma60 = df['收盘'].rolling(60).mean().iloc[-1]
        ma120 = df['收盘'].rolling(120).mean().iloc[-1]
        ma250 = df['收盘'].rolling(250).mean().iloc[-1]

        # 综合评分计算
        total_score = self._calculate_total_score(
            returns, trend_score_3m, trend_score_6m, trend_score_1y,
            short_trend, mid_trend, long_trend, current_price, ma20, ma60, ma120, ma250
        )

        # 给出建议
        recommendation = self._get_recommendation(
            total_score, short_trend, mid_trend, long_trend,
            returns.get('return_3m', 0), returns.get('return_6m', 0)
        )

        return StockAnalysis(
            code=code,
            name=name,
            current_price=current_price,
            return_1m=returns.get('return_1m', 0),
            return_3m=returns.get('return_3m', 0),
            return_6m=returns.get('return_6m', 0),
            return_1y=returns.get('return_1y', 0),
            trend_score_3m=trend_score_3m,
            trend_score_6m=trend_score_6m,
            trend_score_1y=trend_score_1y,
            total_score=total_score,
            ma20=ma20,
            ma60=ma60,
            ma120=ma120,
            ma250=ma250,
            short_trend=short_trend,
            mid_trend=mid_trend,
            long_trend=long_trend,
            recommendation=recommendation
        )

    def _calculate_total_score(self, returns: dict, ts_3m: float, ts_6m: float, ts_1y: float,
                               short_t: str, mid_t: str, long_t: str,
                               price: float, ma20: float, ma60: float, ma120: float, ma250: float) -> float:
        """计算综合评分"""

        score = 0

        # 1. 趋势一致性 (30分)
        # 三个周期趋势一致加分
        trend_consistency = 0
        if short_t == mid_t == long_t == 'UP':
            trend_consistency = 30
        elif short_t == mid_t == 'UP':
            trend_consistency = 25
        elif mid_t == long_t == 'UP':
            trend_consistency = 20
        elif short_t == 'UP':
            trend_consistency = 10
        score += trend_consistency

        # 2. 各周期收益率 (30分)
        ret_3m = returns.get('return_3m', 0)
        ret_6m = returns.get('return_6m', 0)
        ret_1y = returns.get('return_1y', 0)

        if ret_3m > 10:
            score += 10
        elif ret_3m > 5:
            score += 8
        elif ret_3m > 0:
            score += 5

        if ret_6m > 20:
            score += 10
        elif ret_6m > 10:
            score += 8
        elif ret_6m > 0:
            score += 5

        if ret_1y > 30:
            score += 10
        elif ret_1y > 15:
            score += 8
        elif ret_1y > 0:
            score += 5

        # 3. 趋势得分 (20分)
        score += (ts_3m + ts_6m + ts_1y) / 3 * 0.2

        # 4. 价格位置 (20分)
        # 当前价格在长期均线之上
        if price > ma250:
            score += 10
        if price > ma120:
            score += 5
        if price > ma60:
            score += 3
        if price > ma20:
            score += 2

        return min(100, score)

    def _get_recommendation(self, score: float, short_t: str, mid_t: str, long_t: str,
                           ret_3m: float, ret_6m: float) -> str:
        """给出买入建议"""

        if score >= 75 and short_t == mid_t == long_t == 'UP':
            return 'STRONG_BUY'
        elif score >= 60 and mid_t == long_t == 'UP':
            return 'BUY'
        elif score >= 50:
            return 'HOLD'
        else:
            return 'AVOID'

    def select_stocks(self, stock_pool: Dict[str, str], top_k: int = 20) -> List[StockAnalysis]:
        """
        从股票池中选股

        Args:
            stock_pool: {代码: 名称} 字典
            top_k: 返回前K只

        Returns:
            推荐股票列表
        """
        print()
        print('*' * 80)
        print('中长期选股分析')
        print(f'分析时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'股票池: {len(stock_pool)} 只')
        print('*' * 80)
        print()

        results = []
        failed = 0

        for i, (code, name) in enumerate(stock_pool.items(), 1):
            print(f'[{i}/{len(stock_pool)}] 分析 {name}({code})...', end=' ')

            analysis = self.analyze_stock(code, name)
            if analysis:
                results.append(analysis)
                print(f'OK ({analysis.recommendation})')
            else:
                print('FAILED')
                failed += 1

        print()
        print(f'分析完成: 成功 {len(results)} 只, 失败 {failed} 只')
        print()

        # 按得分排序
        results = sorted(results, key=lambda x: x.total_score, reverse=True)

        # 显示结果
        self._display_results(results[:top_k])

        return results[:top_k]

    def _display_results(self, results: List[StockAnalysis]):
        """显示选股结果"""

        print('=' * 120)
        print('中长期推荐股票 TOP {}'.format(len(results)))
        print('=' * 120)
        print()

        # 表头
        header = '{:<6}{:<8}{:<10}{:<8}{:<8}{:<8}{:<8}{:<8}{:<6}{:<6}{:<6}{:<10}{:<8}'.format(
            '排名', '代码', '名称', '现价', '1月%', '3月%', '6月%', '1年%',
            '短', '中', '长', '得分', '建议'
        )
        print(header)
        print('-' * 120)

        for i, stock in enumerate(results, 1):
            trend_icon = {'UP': '^', 'DOWN': 'v', 'SIDE': '-'}
            rec_icon = {
                'STRONG_BUY': '★★买入',
                'BUY': '★关注',
                'HOLD': '持有',
                'AVOID': '回避'
            }

            line = '{:<6}{:<8}{:<10}{:>7.2f} {:>7.2f} {:>7.2f} {:>7.2f} {:>7.2f} {:<5}{:<5}{:<5}{:<10.1f} {:<8}'.format(
                i,
                stock.code,
                stock.name,
                stock.current_price,
                stock.return_1m,
                stock.return_3m,
                stock.return_6m,
                stock.return_1y,
                trend_icon[stock.short_trend],
                trend_icon[stock.mid_trend],
                trend_icon[stock.long_trend],
                stock.total_score,
                rec_icon[stock.recommendation]
            )
            print(line)

        print()

        # 统计
        strong_buy = sum(1 for s in results if s.recommendation == 'STRONG_BUY')
        buy = sum(1 for s in results if s.recommendation == 'BUY')
        hold = sum(1 for s in results if s.recommendation == 'HOLD')
        avoid = sum(1 for s in results if s.recommendation == 'AVOID')

        print('建议统计:')
        print(f'  强烈买入 (★★买入): {strong_buy} 只')
        print(f'  买入关注 (★关注): {buy} 只')
        print(f'  持有观望: {hold} 只')
        print(f'  建议回避: {avoid} 只')
        print()

        # 趋势统计
        up_all = sum(1 for s in results if s.short_trend == s.mid_trend == s.long_trend == 'UP')
        print(f'三周期趋势向上: {up_all} 只')
        print()


def load_stock_pool(filepath: str = '.claude/skills/stock_list.csv',
                     limit: int = 500) -> Dict[str, str]:
    """
    加载股票池

    Args:
        filepath: 股票列表文件路径
        limit: 限制数量

    Returns:
        {代码: 名称} 字典

    CSV格式支持:
    - 股票代码,股票名称 (标准格式)
    - code,name (英文列名)
    - 只有代码列也可以
    """
    try:
        df = pd.read_csv(filepath, encoding='utf-8-sig')
        df = df.head(limit)

        # 标准化列名
        column_map = {
            '股票代码': 'code', 'code': 'code', '代码': 'code',
            '股票名称': 'name', 'name': 'name', '名称': 'name'
        }
        df = df.rename(columns=column_map)

        # 确保有code列
        if 'code' not in df.columns:
            # 尝试使用第一列作为代码列
            first_col = df.columns[0]
            df['code'] = df[first_col]

        # 确保有name列
        if 'name' not in df.columns:
            df['name'] = df['code'].apply(lambda x: f'股票{x}')

        stock_pool = {}
        for _, row in df.iterrows():
            code = str(row['code']).zfill(6)
            name = str(row['name']) if pd.notna(row['name']) else f'股票{code}'
            stock_pool[code] = name

        return stock_pool

    except Exception as e:
        print(f'加载股票池失败: {e}')
        return {}


def load_stock_list_from_file(filepath: str) -> Dict[str, str]:
    """
    从CSV文件加载股票列表（简化版）

    支持格式:
    1. 股票代码,股票名称
    2. code,name
    3. 只有代码列

    Args:
        filepath: CSV文件路径

    Returns:
        {代码: 名称} 字典
    """
    return load_stock_pool(filepath, limit=10000)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='中长期选股策略 - 基于多周期趋势分析')
    parser.add_argument('--file', '-f', type=str, default=None,
                        help='股票列表CSV文件路径 (格式: 股票代码,股票名称)')
    parser.add_argument('--pool', type=str, default='.claude/skills/stock_list.csv',
                        help='股票池文件路径 (默认: 全部A股)')
    parser.add_argument('--top', type=int, default=30,
                        help='显示Top N只股票 (默认: 30)')
    parser.add_argument('--limit', type=int, default=200,
                        help='分析股票数量限制 (默认: 200)')

    args = parser.parse_args()

    # 加载股票池
    if args.file:
        # 使用指定的股票列表文件
        print(f'使用股票列表: {args.file}')
        stock_pool = load_stock_list_from_file(args.file)
    else:
        # 使用默认股票池
        stock_pool = load_stock_pool(args.pool, args.limit)

    if not stock_pool:
        print('股票池为空，退出')
        return

    # 执行选股
    selector = LongTermSelector()
    results = selector.select_stocks(stock_pool, top_k=args.top)

    # 保存结果
    if results:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f'long_term_selection_{timestamp}.csv'

        data = []
        for r in results:
            data.append({
                'code': r.code,
                'name': r.name,
                'price': r.current_price,
                'return_1m': r.return_1m,
                'return_3m': r.return_3m,
                'return_6m': r.return_6m,
                'return_1y': r.return_1y,
                'total_score': r.total_score,
                'short_trend': r.short_trend,
                'mid_trend': r.mid_trend,
                'long_trend': r.long_trend,
                'recommendation': r.recommendation
            })

        df = pd.DataFrame(data)
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f'结果已保存: {output_file}')


if __name__ == '__main__':
    main()
