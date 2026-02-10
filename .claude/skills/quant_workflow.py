# -*- coding: utf-8 -*-
"""
统一量化分析工作流
整合所有Skills模块，提供标准化分析流程
"""
import sys
sys.path.append('.')
import pandas as pd
from datetime import datetime


class QuantWorkflow:
    """量化分析工作流类"""

    def __init__(self):
        """初始化工作流"""
        # 导入所有模块
        from stock_data_fetcher import StockDataFetcher
        from stock_list_manager import StockList
        from stock_selector import StockSelector
        from technical_analyzer import TechnicalAnalyzer
        from position_analyzer import PositionAnalyzer
        from signal_generator import SignalGenerator
        from risk_management import RiskMetrics

        self.fetcher = StockDataFetcher()
        self.stock_list = StockList()
        self.selector = StockSelector()
        self.technical_analyzer = TechnicalAnalyzer()
        self.position_analyzer = PositionAnalyzer()
        self.signal_generator = SignalGenerator()
        self.risk_metrics = RiskMetrics()

    def quick_analysis(self, symbol, days=120):
        """
        快速分析单只股票

        Args:
            symbol: 股票代码
            days: 分析天数

        Returns:
            dict: 快速分析结果
        """
        # 获取股票名称
        name = self.stock_list.get_name(symbol)

        # 技术分析
        tech_analysis = self.technical_analyzer.analyze(symbol, days=days)

        if tech_analysis is None:
            return {
                'symbol': symbol,
                'name': name,
                'error': '无法获取数据'
            }

        # 信号生成
        data = self.fetcher.get_quote_data(symbol, days=days)
        data = self.fetcher.calculate_technical_indicators(data)
        signal = self.signal_generator.get_latest_signal(data)

        # 综合判断
        recommendation = self._generate_recommendation(tech_analysis, signal)

        return {
            'symbol': symbol,
            'name': name,
            'price': tech_analysis['latest_price'],
            'change_1d': tech_analysis['change_1d'],
            'score': tech_analysis['score'],
            'trend': tech_analysis['trend']['direction'],
            'risk_level': tech_analysis['risk']['level'],
            'buy_signal': signal['buy_signal'],
            'sell_signal': signal['sell_signal'],
            'signal_strength': signal['strength'],
            'recommendation': recommendation,
            'analysis_date': tech_analysis['analysis_date']
        }

    def full_analysis(self, symbol, shares=None, cost_price=None, days=120):
        """
        完整分析（包含持仓分析）

        Args:
            symbol: 股票代码
            shares: 持股数量（可选）
            cost_price: 成本价（可选）
            days: 分析天数

        Returns:
            dict: 完整分析结果
        """
        result = self.quick_analysis(symbol, days)

        # 如果有持仓信息，添加持仓分析
        if shares and cost_price:
            position_analysis = self.position_analyzer.analyze_position(
                symbol, shares, cost_price, result['name']
            )
            result['position'] = position_analysis

        return result

    def screen_stocks(self, stock_list, min_score=60, max_count=10):
        """
        批量选股

        Args:
            stock_list: 股票代码列表
            min_score: 最低评分
            max_count: 最多返回数量

        Returns:
            list: 筛选结果
        """
        return self.selector.screen_stocks(stock_list, min_score, max_count)

    def hot_stocks_analysis(self, market='all', count=10):
        """
        热门股票分析

        Args:
            market: 市场范围
            count: 返回数量

        Returns:
            list: 热门股票分析结果
        """
        hot_stocks = self.selector.get_hot_stocks(market, count)

        results = []
        for stock_info in hot_stocks:
            symbol = stock_info['symbol']
            quick_result = self.quick_analysis(symbol, days=60)
            results.append({
                **stock_info,
                **quick_result
            })

        # 按评分排序
        results.sort(key=lambda x: x.get('score', 0), reverse=True)

        return results

    def batch_analysis(self, stock_list, days=120):
        """
        批量分析股票

        Args:
            stock_list: 股票代码列表
            days: 分析天数

        Returns:
            list: 分析结果列表
        """
        results = []

        for symbol in stock_list:
            try:
                result = self.quick_analysis(symbol, days)
                if 'error' not in result:
                    results.append(result)
            except Exception as e:
                # 跳过出错的股票
                continue

        return results

    def portfolio_analysis(self, positions):
        """
        组合分析

        Args:
            positions: 持仓列表 [{'symbol': '', 'shares': '', 'cost': ''}, ...]

        Returns:
            dict: 组合分析结果
        """
        portfolio_value = 0
        total_cost = 0
        total_profit_loss = 0

        positions_analysis = []

        for pos in positions:
            symbol = pos['symbol']
            shares = pos['shares']
            cost_price = pos['cost']

            # 完整分析
            analysis = self.full_analysis(symbol, shares, cost_price)

            if 'position' in analysis:
                pos_analysis = analysis['position']
                portfolio_value += pos_analysis['market_value']
                total_cost += pos_analysis['total_cost']
                total_profit_loss += pos_analysis['profit_loss']

            positions_analysis.append(analysis)

        # 组合汇总
        total_profit_loss_pct = (portfolio_value / total_cost - 1) * 100 if total_cost > 0 else 0

        return {
            'total_value': portfolio_value,
            'total_cost': total_cost,
            'total_profit_loss': total_profit_loss,
            'total_profit_loss_pct': total_profit_loss_pct,
            'positions': positions_analysis,
            'position_count': len(positions)
        }

    def generate_report(self, analysis_result, report_type='quick'):
        """
        生成分析报告

        Args:
            analysis_result: 分析结果
            report_type: 报告类型 (quick/full/portfolio)

        Returns:
            str: 格式化的报告文本
        """
        if report_type == 'quick':
            return self._format_quick_report(analysis_result)
        elif report_type == 'full':
            return self._format_full_report(analysis_result)
        elif report_type == 'portfolio':
            return self._format_portfolio_report(analysis_result)
        else:
            return "不支持的报告类型"

    def _generate_recommendation(self, tech_analysis, signal):
        """生成操作建议"""
        score = tech_analysis['score']
        trend = tech_analysis['trend']['direction']
        risk = tech_analysis['risk']['level']
        buy_signal = signal['buy_signal']
        sell_signal = signal['sell_signal']
        strength = signal['strength']

        # 评级
        if score >= 80 and buy_signal and strength > 1:
            level = '强烈推荐'
            action = '技术面强势，多个买入信号，建议逢低介入'
        elif score >= 70 and buy_signal:
            level = '推荐'
            action = '技术面良好，可考虑介入'
        elif score >= 60 and trend in ['up', 'strong_up']:
            level = '谨慎推荐'
            action = '技术面中性偏强，建议分批建仓'
        elif score >= 50:
            level = '中性'
            action = '技术面中性，建议观望等待'
        elif sell_signal or trend in ['down', 'weak_down']:
            level = '谨慎'
            action = '技术面偏弱，建议谨慎'
        else:
            level = '回避'
            action = '技术面疲弱，建议回避'

        return {
            'level': level,
            'action': action
        }

    def _format_quick_report(self, result):
        """格式化快速报告"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"                {result['symbol']} {result['name']} 快速分析")
        lines.append("=" * 60)
        lines.append("")

        lines.append("【基本信息】")
        lines.append(f"  分析日期: {result['analysis_date']}")
        lines.append(f"  当前价格: {result['price']:.2f} 元")
        lines.append(f"  日涨跌幅: {result['change_1d']:+.2f}%")
        lines.append("")

        lines.append("【技术评估】")
        lines.append(f"  技术评分: {result['score']:.0f}/100")
        lines.append(f"  趋势方向: {result['trend']}")
        lines.append(f"  风险等级: {result['risk_level']}")
        lines.append("")

        lines.append("【交易信号】")
        lines.append(f"  买入信号: {'是' if result['buy_signal'] else '否'}")
        lines.append(f"  卖出信号: {'是' if result['sell_signal'] else '否'}")
        lines.append(f"  信号强度: {result['signal_strength']:+.1f}")
        lines.append("")

        lines.append("【操作建议】")
        rec = result['recommendation']
        lines.append(f"  评级: {rec['level']}")
        lines.append(f"  建议: {rec['action']}")
        lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def _format_full_report(self, result):
        """格式化完整报告"""
        lines = []
        lines.append("=" * 80)
        lines.append(f"                    {result['symbol']} {result['name']} 完整分析报告")
        lines.append("=" * 80)
        lines.append("")

        # 快速分析部分
        lines.append("【一、基本信息】")
        lines.append(f"  分析日期: {result['analysis_date']}")
        lines.append(f"  当前价格: {result['price']:.2f} 元")
        lines.append(f"  日涨跌幅: {result['change_1d']:+.2f}%")
        lines.append("")

        lines.append("【二、技术评估】")
        lines.append(f"  技术评分: {result['score']:.0f}/100")
        lines.append(f"  趋势方向: {result['trend']}")
        lines.append(f"  风险等级: {result['risk_level']}")
        lines.append("")

        lines.append("【三、交易信号】")
        lines.append(f"  买入信号: {'是' if result['buy_signal'] else '否'}")
        lines.append(f"  卖出信号: {'是' if result['sell_signal'] else '否'}")
        lines.append(f"  信号强度: {result['signal_strength']:+.1f}")
        lines.append("")

        lines.append("【四、操作建议】")
        rec = result['recommendation']
        lines.append(f"  评级: {rec['level']}")
        lines.append(f"  建议: {rec['action']}")
        lines.append("")

        # 持仓分析部分
        if 'position' in result:
            pos = result['position']
            lines.append("【五、持仓分析】")
            lines.append(f"  持股数量: {pos['shares']} 股")
            lines.append(f"  成本价格: {pos['cost_price']:.2f} 元")
            lines.append(f"  持仓市值: {pos['market_value']:,.2f} 元")
            lines.append(f"  浮动盈亏: {pos['profit_loss']:+,.2f} 元 ({pos['profit_loss_pct']:+.2f}%)")
            lines.append(f"  回本需要: +{pos['recover_gain']:.2f}%")
            lines.append(f"  亏损等级: {pos['loss_level']}")
            lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)

    def _format_portfolio_report(self, result):
        """格式化组合报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("                        投资组合分析报告")
        lines.append("=" * 80)
        lines.append("")

        lines.append("【组合概况】")
        lines.append(f"  持仓数量: {result['position_count']} 只")
        lines.append(f"  组合市值: {result['total_value']:,.2f} 元")
        lines.append(f"  组合成本: {result['total_cost']:,.2f} 元")
        lines.append(f"  浮动盈亏: {result['total_profit_loss']:+,.2f} 元")
        lines.append(f"  盈亏比例: {result['total_profit_loss_pct']:+.2f}%")
        lines.append("")

        lines.append("【持仓明细】")
        for i, pos in enumerate(result['positions'], 1):
            lines.append(f"  {i}. {pos['symbol']} {pos['name']}")
            if 'position' in pos:
                p = pos['position']
                lines.append(f"     持仓: {p['shares']} 股 / {p['cost_price']:.2f} 元")
                lines.append(f"     市值: {p['market_value']:,.2f} 元")
                lines.append(f"     盈亏: {p['profit_loss']:+,.2f} 元 ({p['profit_loss_pct']:+.2f}%)")
            else:
                lines.append(f"     价格: {pos['price']:.2f} 元")
                lines.append(f"     评分: {pos['score']:.0f}/100")
            lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)


# 便捷函数
def quick_analyze(symbol, days=120):
    """快速分析单只股票"""
    workflow = QuantWorkflow()
    return workflow.quick_analysis(symbol, days)


def full_analyze(symbol, shares=None, cost_price=None, days=120):
    """完整分析单只股票"""
    workflow = QuantWorkflow()
    return workflow.full_analysis(symbol, shares, cost_price, days)


def screen_stocks(stock_list, min_score=60, max_count=10):
    """批量选股"""
    workflow = QuantWorkflow()
    return workflow.screen_stocks(stock_list, min_score, max_count)


def analyze_portfolio(positions):
    """分析投资组合"""
    workflow = QuantWorkflow()
    return workflow.portfolio_analysis(positions)


# 测试
if __name__ == "__main__":
    print("统一量化分析工作流测试")
    print("=" * 60)

    workflow = QuantWorkflow()

    # 测试快速分析
    print("\n[测试1] 快速分析 600519")
    result = workflow.quick_analysis('600519', days=120)
    if 'error' not in result:
        print(workflow.generate_report(result, 'quick'))

    # 测试持仓分析
    print("\n[测试2] 持仓分析 002415")
    result = workflow.full_analysis('002415', shares=500, cost_price=30.0)
    if 'error' not in result:
        print(workflow.generate_report(result, 'full'))

    # 测试选股
    print("\n[测试3] 批量选股")
    test_stocks = ['600519', '000858', '002415', '600036']
    screened = workflow.screen_stocks(test_stocks, min_score=50, max_count=5)
    print(f"筛选结果: {len(screened)} 只")
    for s in screened:
        print(f"  {s['symbol']} 评分: {s['score']}")
