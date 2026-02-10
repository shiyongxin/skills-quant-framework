"""
股票数据自动更新脚本
用于定期更新自选股数据
"""

import sys
sys.path.append('..')
from stock_data_fetcher import StockDataFetcher
from datetime import datetime, timedelta
import schedule
import time


# 配置自选股列表
MY_STOCKS = [
    "000001",  # 平安银行
    "000002",  # 万科A
    "000858",  # 五粮液
    "600519",  # 贵州茅台
    "600036",  # 招商银行
    "601318",  # 中国平安
]


def update_daily_data():
    """更新日线数据"""
    print(f"\n{'='*60}")
    print(f"🔄 开始更新数据 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    fetcher = StockDataFetcher()

    # 计算日期范围（最近3个月）
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

    print(f"\n📅 更新时间范围: {start_date} ~ {end_date}")
    print(f"📊 股票数量: {len(MY_STOCKS)}")

    # 批量更新
    data = fetcher.batch_get_quotes(
        symbols=MY_STOCKS,
        start_date=start_date,
        end_date=end_date,
        delay=1
    )

    # 统计
    success_count = sum(1 for v in data.values() if not v.empty)
    fail_count = len(MY_STOCKS) - success_count

    print(f"\n{'='*60}")
    print(f"✅ 更新完成!")
    print(f"  成功: {success_count} 只")
    print(f"  失败: {fail_count} 只")
    print(f"{'='*60}\n")


def update_financial_data():
    """更新财务数据（每月一次）"""
    print(f"\n{'='*60}")
    print(f"💰 更新财务数据 - {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*60}")

    fetcher = StockDataFetcher()

    for code in MY_STOCKS:
        print(f"\n更新 {code} 财务指标...")
        fetcher.get_financial_indicator(code)
        time.sleep(1)  # 避免请求过快

    print(f"\n✅ 财务数据更新完成!")


def export_weekly_report():
    """导出周报（Excel）"""
    print(f"\n{'='*60}")
    print(f"📊 生成周报 - {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*60}")

    fetcher = StockDataFetcher()
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

    for code in MY_STOCKS:
        print(f"\n生成 {code} 分析报告...")
        fetcher.export_to_excel(code, start_date, end_date)

    print(f"\n✅ 周报生成完成!")


def one_time_update():
    """一次性更新所有数据"""
    print("🚀 执行一次性数据更新...")
    update_daily_data()
    update_financial_data()


def scheduled_update():
    """定时更新任务"""
    print("🕐 启动定时更新服务...")
    print("⏰ 每天收盘后(15:30)更新行情数据")
    print("📅 每周日晚上20:00更新财务数据")
    print("📊 每周五晚上20:00生成周报")
    print("按 Ctrl+C 停止\n")

    # 定时任务
    schedule.every().monday至周五.at="15:30".do(update_daily_data)
    schedule.every().sunday.at="20:00".do(update_financial_data)
    schedule.every().friday.at="20:00".do(export_weekly_report)

    # 运行
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
    except KeyboardInterrupt:
        print("\n\n⏹️ 定时任务已停止")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "now":
            # 立即更新
            one_time_update()

        elif command == "schedule":
            # 启动定时任务
            scheduled_update()

        elif command == "financial":
            # 只更新财务数据
            update_financial_data()

        elif command == "report":
            # 只生成周报
            export_weekly_report()

        else:
            print("未知命令")
            print_usage()
    else:
        print_usage()


def print_usage():
    """打印使用说明"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                    股票数据更新工具                              ║
╠══════════════════════════════════════════════════════════════════╣
║  使用方法:                                                      ║
║    python 自动更新数据.py [命令]                                 ║
║                                                                ║
║  命令:                                                          ║
║    now        - 立即更新所有数据（行情+财务）                    ║
║    schedule   - 启动定时更新服务（每天收盘后自动更新）            ║
║    financial  - 只更新财务数据                                   ║
║    report     - 只生成Excel周报                                  ║
║                                                                ║
║  示例:                                                          ║
║    python 自动更新数据.py now                                    ║
║    python 自动更新数据.py schedule                               ║
║                                                                ║
║  注意: 使用 schedule 模式需要安装 schedule 库                    ║
║    pip install schedule                                         ║
╚══════════════════════════════════════════════════════════════════╝
    """)
