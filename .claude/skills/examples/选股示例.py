"""
股票选股策略示例
基于财务指标的量化选股
"""

import sys
sys.path.append('..')
from stock_data_fetcher import StockDataFetcher
import pandas as pd

def value_stock_strategy():
    """
    价值选股策略
    条件: PE<20, PB<3, ROE>15%
    """
    print("="*60)
    print("🔍 价值选股策略: PE<20, PB<3, ROE>15%")
    print("="*60)

    fetcher = StockDataFetcher()
    stock_list = fetcher.get_stock_list()

    selected_stocks = []

    # 测试前50只股票
    for i, code in enumerate(stock_list['code'].head(50), 1):
        print(f"[{i}/50] 分析 {code}...")

        financial = fetcher.get_financial_indicator(code)

        if not financial.empty:
            latest = financial.iloc[0]

            try:
                pe = latest.get('市盈率-动态', 999)
                pb = latest.get('市净率', 999)
                roe = latest.get('净资产收益率', 0)

                if pe < 20 and pb < 3 and roe > 15:
                    selected_stocks.append({
                        'code': code,
                        'name': latest.get('名称', ''),
                        'PE': pe,
                        'PB': pb,
                        'ROE': roe
                    })
                    print(f"  ✅ 符合条件! PE={pe:.2f}, PB={pb:.2f}, ROE={roe:.2f}%")
            except:
                pass

    # 结果
    if selected_stocks:
        result_df = pd.DataFrame(selected_stocks)
        print("\n" + "="*60)
        print(f"✅ 找到 {len(selected_stocks)} 只符合价值策略的股票:")
        print("="*60)
        print(result_df)

        # 保存结果
        result_df.to_csv('value_stocks.csv', index=False, encoding='utf-8-sig')
        print("\n📁 结果已保存到: value_stocks.csv")
    else:
        print("\n⚠️ 没有找到符合条件的股票")


def growth_stock_strategy():
    """
    成长选股策略
    条件: 营收增长率>20%, 净利润增长率>20%
    """
    print("="*60)
    print("🚀 成长选股策略: 营收增长>20%, 利润增长>20%")
    print("="*60)

    fetcher = StockDataFetcher()
    stock_list = fetcher.get_stock_list()

    selected_stocks = []

    for i, code in enumerate(stock_list['code'].head(30), 1):
        print(f"[{i}/30] 分析 {code}...")

        financial = fetcher.get_financial_indicator(code, indicator="按年度")

        if not financial.empty and len(financial) >= 2:
            # 对比最近两年
            latest = financial.iloc[0]
            last_year = financial.iloc[1]

            try:
                revenue_growth = (latest.get('营业总收入', 0) / last_year.get('营业总收入', 1) - 1) * 100
                profit_growth = (latest.get('净利润', 0) / last_year.get('净利润', 1) - 1) * 100

                if revenue_growth > 20 and profit_growth > 20:
                    selected_stocks.append({
                        'code': code,
                        'revenue_growth': revenue_growth,
                        'profit_growth': profit_growth
                    })
                    print(f"  ✅ 符合条件! 营收增长={revenue_growth:.2f}%, 利润增长={profit_growth:.2f}%")
            except:
                pass

    if selected_stocks:
        result_df = pd.DataFrame(selected_stocks)
        print("\n" + "="*60)
        print(f"✅ 找到 {len(selected_stocks)} 只高成长股票:")
        print("="*60)
        print(result_df)


def technical_strategy():
    """
    技术选股策略
    条件: 金叉信号(MA5上穿MA10) + 成交量放大
    """
    print("="*60)
    print("📊 技术选股策略: MA金叉 + 成交量放大")
    print("="*60)

    fetcher = StockDataFetcher()

    # 测试几只热门股票
    test_stocks = ["000001", "600519", "000858", "600036", "601318"]

    for code in test_stocks:
        print(f"\n分析 {code}...")

        data = fetcher.get_quote_data(code, "20231001", "20231231")

        if not data.empty:
            data = fetcher.calculate_technical_indicators(data)
            latest = data.iloc[-1]
            yesterday = data.iloc[-2]

            # 金叉判断
            golden_cross = yesterday['MA5'] <= yesterday['MA10'] and latest['MA5'] > latest['MA10']

            # 成交量放大
            volume_surge = latest['成交量'] > latest['VOL_MA5'] * 1.5

            if golden_cross and volume_surge:
                print(f"  ✅ {code} 出现金叉+放量信号!")
                print(f"     收盘价: {latest['收盘']:.2f}")
                print(f"     MA5: {latest['MA5']:.2f}, MA10: {latest['MA10']:.2f}")
            elif golden_cross:
                print(f"  ⚠️ {code} 金叉，但成交量不足")
            else:
                print(f"  ❌ {code} 无信号")


if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════╗
    ║          股票选股策略示例                              ║
    ║  1. 价值选股 (低估值高ROE)                              ║
    ║  2. 成长选股 (高增长)                                   ║
    ║  3. 技术选股 (金叉信号)                                 ║
    ╚════════════════════════════════════════════════════════╝
    """)

    # 运行策略
    # value_stock_strategy()
    # growth_stock_strategy()
    technical_strategy()

    print("\n✅ 分析完成!")
