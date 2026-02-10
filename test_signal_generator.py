# -*- coding: utf-8 -*-
"""
信号生成器详细测试报告
测试4只股票：000568, 600893, 002236, 600056
"""
import sys
sys.path.append('.claude/skills')

from stock_data_fetcher import StockDataFetcher
from signal_generator import SignalGenerator, format_signal_report
from technical_analyzer import TechnicalAnalyzer
from stock_list_manager import get_stock_name

def main():
    print('='*120)
    print('*'*120)
    print('                    信号生成器详细测试报告 - 4只股票对比分析')
    print('*'*120)
    print('='*120)
    print()

    stocks = ['000568', '600893', '002236', '600056']

    fetcher = StockDataFetcher()
    signal_gen = SignalGenerator()
    tech_analyzer = TechnicalAnalyzer()

    results = []

    # 第一部分：汇总表格
    print('【第一部分：信号汇总】')
    print()

    for symbol in stocks:
        name = get_stock_name(symbol) or '未知'

        try:
            # 获取数据
            data = fetcher.get_quote_data(symbol, days=120)
            data = fetcher.calculate_technical_indicators(data)

            # 技术分析
            tech = tech_analyzer.analyze(symbol, days=120)

            # 信号生成
            signal = signal_gen.get_latest_signal(data)

            results.append({
                'symbol': symbol,
                'name': name,
                'price': signal['price'],
                'buy_signal': signal['buy_signal'],
                'sell_signal': signal['sell_signal'],
                'strength': signal['strength'],
                'score': tech['score'] if tech else 0,
                'trend': tech['trend']['direction'] if tech else 'unknown',
                'ma_cross': signal['ma_cross'],
                'macd': signal['macd'],
                'kdj': signal['kdj'],
                'rsi': signal['rsi'],
                'bb': signal['bb'],
                'breakout': signal['breakout']
            })

        except Exception as e:
            results.append({
                'symbol': symbol,
                'name': name,
                'error': str(e)
            })

    # 打印汇总表格
    header = '{:<10} {:<12} {:<10} {:<8} {:<8} {:<8} {:<10} {:<12}'.format(
        '代码', '名称', '价格', '买入', '卖出', '强度', '评分', '趋势'
    )
    print(header)
    print('-'*120)

    trend_map = {
        'strong_up': '强势上涨',
        'up': '上涨',
        'consolidation': '整理',
        'down': '下跌',
        'weak_down': '弱势下跌'
    }

    for r in results:
        if 'error' not in r:
            trend = trend_map.get(r['trend'], r['trend'])
            buy = 'Y' if r['buy_signal'] else 'N'
            sell = 'Y' if r['sell_signal'] else 'N'
            row = '{:<10} {:<12} {:<10.2f} {:<8} {:<8} {:+<8.1f} {:<10.0f}/100 {:<12}'.format(
                r['symbol'], r['name'], r['price'], buy, sell, r['strength'], r['score'], trend
            )
            print(row)

    print()
    print('='*120)
    print()

    # 第二部分：详细信号报告
    print('【第二部分：详细信号报告】')
    print()

    for i, r in enumerate(results, 1):
        if 'error' in r:
            continue

        print(f'#'*120)
        print(f'#  [{i}] {r["symbol"]} - {r["name"]}')
        print(f'#'*120)
        print()

        print(f'当前价格: {r["price"]:.2f} 元')
        print(f'技术评分: {r["score"]:.0f}/100')
        print(f'趋势方向: {trend_map.get(r["trend"], r["trend"])}')
        print()

        print('信号明细:')
        print(f'  综合信号: {"买入" if r["buy_signal"] else "卖出" if r["sell_signal"] else "中性"}')
        print(f'  信号强度: {r["strength"]:+.1f}/10')
        print()

        print('分项信号:')

        # 均线
        ma = r['ma_cross']
        if ma > 0:
            print(f'  [买入] 均线: 金叉 (MA5 > MA20)')
        elif ma < 0:
            print(f'  [卖出] 均线: 死叉 (MA5 < MA20)')
        else:
            print(f'  [中性] 均线: 纠缠')

        # MACD
        macd = r['macd']
        if macd > 0:
            print(f'  [买入] MACD: 金叉 (DIF > DEA)')
        elif macd < 0:
            print(f'  [卖出] MACD: 死叉 (DIF < DEA)')
        else:
            print(f'  [中性] MACD: 平衡')

        # KDJ
        kdj = r['kdj']
        if kdj > 0:
            print(f'  [买入] KDJ: 金叉或超卖区')
        elif kdj < 0:
            print(f'  [卖出] KDJ: 死叉或超买区')
        else:
            print(f'  [中性] KDJ: 中性')

        # RSI
        rsi = r['rsi']
        if rsi > 0:
            print(f'  [买入] RSI: 超卖或强势')
        elif rsi < 0:
            print(f'  [卖出] RSI: 超买或弱势')
        else:
            print(f'  [中性] RSI: 中性')

        # 布林带
        bb = r['bb']
        if bb > 0:
            print(f'  [买入] 布林带: 触及下轨')
        elif bb < 0:
            print(f'  [卖出] 布林带: 突破上轨')
        else:
            print(f'  [中性] 布林带: 中轨')

        # 突破
        bo = r['breakout']
        if bo > 0:
            print(f'  [买入] 突破: 突破近期高点')
        elif bo < 0:
            print(f'  [卖出] 突破: 跌破近期低点')
        else:
            print(f'  [中性] 突破: 无明显突破')

        print()
        print('操作建议:')

        # 根据综合情况给出建议
        if r['buy_signal'] and r['score'] >= 70:
            print('  [强烈推荐] 技术面强势，多个买入信号，可考虑逢低介入')
        elif r['buy_signal'] and r['score'] >= 50:
            print('  [谨慎买入] 有买入信号，建议分批建仓')
        elif r['sell_signal']:
            print('  [建议卖出] 出现卖出信号，注意风险')
        elif r['strength'] > 1:
            print('  [偏多] 信号偏多，可关注')
        elif r['strength'] < -1:
            print('  [偏空] 信号偏空，建议观望')
        else:
            print('  [中性] 信号不明确，建议等待')

        print()
        print()

    # 第三部分：对比分析
    print('='*120)
    print('【第三部分：对比分析】')
    print('='*120)
    print()

    # 按信号强度排序
    valid_results = [r for r in results if 'error' not in r]
    sorted_results = sorted(valid_results, key=lambda x: x['strength'], reverse=True)

    print('按信号强度排名:')
    print()
    print(f"{'排名':<6} {'代码':<10} {'名称':<12} {'强度':<10} {'评分':<10} {'建议':<20}")
    print('-'*120)

    for i, r in enumerate(sorted_results, 1):
        advice = ''
        if r['buy_signal'] and r['score'] >= 70:
            advice = '强烈推荐'
        elif r['buy_signal'] and r['score'] >= 50:
            advice = '可考虑'
        elif r['sell_signal']:
            advice = '建议观望'
        else:
            advice = '中性'

        print(f'{i:<6} {r["symbol"]:<10} {r["name"]:<12} {r["strength"]:+<10.1f} {r["score"]:<10.0f}/100 {advice:<20}')

    print()
    print('='*120)
    print('                        测试完成')
    print('='*120)
    print()


if __name__ == '__main__':
    main()
