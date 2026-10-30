"""
快速测试脚本 - 验证股票数据工具是否正常工作

审计 L5: 旧实现是**模块级脚本** —— import 即打 akshare 网络 / 在 CWD 建
`./test_data/` / 失败时 `exit(1)` 直接终止进程; 且文件名匹配 pytest 的
`python_files = test_*.py` → 一旦被 pytest 收集 (或被别的模块 import),
副作用发生在**导入期** (最坏的时机: 连报错都难定位)。

现改为 `main()` + `__main__` 守卫 → import 安全 (无副作用); 文件名也改为
`smoke_test_tool.py` (不再匹配 `test_*.py`, 双保险)。

注意: 本脚本**会联网取数**, 只适合手动跑, 不适合进测试套件。
"""
import sys
from datetime import datetime, timedelta

from stock_data_fetcher import StockDataFetcher, quick_fetch


def main() -> int:
    """跑一遍数据工具冒烟测试 (会联网取数; 返回进程退出码)。"""
    print("[TEST] 开始测试股票数据工具...\n")

    # 测试1: 创建数据获取器
    print("测试1: 创建数据获取器")
    try:
        fetcher = StockDataFetcher(data_dir="./test_data")
        print("[PASS] 数据获取器创建成功\n")
    except Exception as e:
        print(f"[FAIL] 失败: {e}\n")
        return 1

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
    data = None
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    try:
        data = fetcher.get_quote_data("000001", start_date, end_date)

        if data is not None and not data.empty:
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
        if data is not None and not data.empty:
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
        if quick_data is not None and not quick_data.empty:
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
