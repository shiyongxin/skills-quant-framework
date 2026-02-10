"""
快速测试脚本 - 验证股票数据工具是否正常工作
"""

from stock_data_fetcher import StockDataFetcher, quick_fetch

print("[TEST] 开始测试股票数据工具...\n")

# 测试1: 创建数据获取器
print("测试1: 创建数据获取器")
try:
    fetcher = StockDataFetcher(data_dir="./test_data")
    print("[PASS] 数据获取器创建成功\n")
except Exception as e:
    print(f"[FAIL] 失败: {e}\n")
    exit(1)

# 测试2: 获取股票列表
print("测试2: 获取A股列表（前10只）")
try:
    stock_list = fetcher.get_stock_list()
    print(f"[PASS] 成功获取 {len(stock_list)} 只股票")
    print(stock_list.head(10))
    print()
except Exception as e:
    print(f"[FAIL] 失败: {e}\n")

# 测试3: 获取行情数据
print("测试3: 获取平安银行(000001)最近10天行情")
try:
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    data = fetcher.get_quote_data("000001", start_date, end_date)

    if not data.empty:
        print(f"[PASS] 成功获取 {len(data)} 条记录")
        print(data.head(10))
        print()
    else:
        print("[WARN] 数据为空\n")
except Exception as e:
    print(f"[FAIL] 失败: {e}\n")

# 测试4: 计算技术指标
print("测试4: 计算技术指标")
try:
    if not data.empty:
        data = fetcher.calculate_technical_indicators(data)
        print("[PASS] 技术指标计算完成")
        print(data[['日期', '收盘', 'MA5', 'MA10', 'MA20']].tail(5))
        print()
except Exception as e:
    print(f"[FAIL] 失败: {e}\n")

# 测试5: 快速获取函数
print("测试5: 使用 quick_fetch 快速获取")
try:
    quick_data = quick_fetch("600519", start_date, end_date)
    if not quick_data.empty:
        print(f"[PASS] 快速获取成功，{len(quick_data)} 条记录")
        print()
    else:
        print("[WARN] 数据为空\n")
except Exception as e:
    print(f"[FAIL] 失败: {e}\n")

print("="*60)
print("[PASS] 测试完成!")
print("="*60)
print("\n[TIPS] 提示:")
print("  - 数据已保存到 ./test_data/ 目录")
print("  - 运行主程序获取更多数据: python stock_data_fetcher.py")
print("  - 查看使用文档: README_股票数据工具.md")
