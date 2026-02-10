# -*- coding: utf-8 -*-
"""
批量查询股票板块属性
查询stock_list.csv中所有股票的板块信息并保存
"""
import akshare as ak
import pandas as pd
from datetime import datetime
import time
import warnings
warnings.filterwarnings('ignore')


def load_stock_list(csv_path='stock_list.csv'):
    """加载股票列表"""
    df = pd.read_csv(csv_path, header=None, names=['code', 'name', 'market'])
    stocks = []
    for _, row in df.iterrows():
        code = str(row['code']).zfill(6)
        stocks.append({
            'code': code,
            'name': row['name'],
            'market': row['market']
        })
    return stocks


def get_stock_sectors(stock_code):
    """查询单只股票的板块属性"""
    sectors = {
        'industry': [],      # 行业板块
        'concept': []        # 概念板块
    }

    try:
        # 获取股票基本信息获取行业
        info = ak.stock_individual_info_em(symbol=stock_code)
        industry_row = info[info['item'] == '行业']
        if len(industry_row) > 0:
            sectors['industry'].append({
                'name': industry_row['value'].values[0],
                'type': '所属行业',
                'change_pct': 0
            })
    except:
        pass

    return sectors


def batch_query_sectors(output_file='stock_sectors_result.csv'):
    """批量查询股票板块"""

    print("=" * 80)
    print("批量查询股票板块属性")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    # 加载股票列表
    print("[1] 加载股票列表...")
    stocks = load_stock_list('stock_list.csv')
    total = len(stocks)
    print(f"    共 {total} 只股票")
    print()

    # 结果存储
    results = []

    # 分批处理
    batch_size = 50
    for i in range(0, total, batch_size):
        batch = stocks[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        print(f"[2] 处理第 {batch_num}/{total_batches} 批 (股票 {i+1}-{min(i+batch_size, total)})...")

        for stock in batch:
            code = stock['code']
            name = stock['name']

            print(f"    查询 {name}({code})...", end=' ')

            # 查询板块
            sectors = get_stock_sectors(code)

            # 记录结果
            industry_list = sectors.get('industry', [])
            concept_list = sectors.get('concept', [])

            industry_str = '; '.join([s['name'] for s in industry_list])
            concept_str = '; '.join([s['name'] for s in concept_list])

            results.append({
                'code': code,
                'name': name,
                'market': stock['market'],
                'industry': industry_str,
                'concept': concept_str
            })

            if industry_str or concept_str:
                print(f"OK (行业:{len(industry_list)}, 概念:{len(concept_list)})")
            else:
                print("SKIP")

            # 延迟避免请求过快
            time.sleep(0.1)

        # 每批保存一次
        df = pd.DataFrame(results)
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"    [已保存 {len(results)} 条记录]")
        print()

    print()
    print("=" * 80)
    print("查询完成")
    print(f"结果文件: {output_file}")
    print(f"共处理: {len(results)} 只股票")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return results


if __name__ == "__main__":
    batch_query_sectors('stock_sectors_result.csv')
