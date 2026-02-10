# -*- coding: utf-8 -*-
"""
集成测试套件
Integration Test Suite

端到端测试所有模块的集成功能
"""

import sys
import os
sys.path.append('.')
sys.path.append(os.path.join(os.path.dirname(__file__), '.claude', 'skills'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time


# =============================================================================
# 集成测试套件
# =============================================================================

class IntegrationTestSuite:
    """集成测试套件"""

    def __init__(self):
        """初始化测试套件"""
        self.test_results = []
        self.start_time = time.time()

    def add_result(self, test_name: str, passed: bool, duration: float, message: str = ""):
        """添加测试结果"""
        self.test_results.append({
            'test': test_name,
            'passed': passed,
            'duration': duration,
            'message': message
        })

    def test_data_pipeline(self):
        """测试数据获取流程"""
        print("\n" + "=" * 60)
        print("[Test 1] 数据获取流程集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from stock_data_fetcher import StockDataFetcher

            fetcher = StockDataFetcher()

            # 测试单只股票获取
            print("  测试单只股票获取...")
            data = fetcher.get_quote_data('600519', days=120)

            if data is None or len(data) == 0:
                self.add_result("数据获取流程", False, time.time() - start, "无法获取数据")
                return

            print(f"    [OK] 获取到 {len(data)} 条记录")

            # 测试技术指标计算
            print("  测试技术指标计算...")
            data = fetcher.calculate_technical_indicators(data)
            print(f"    [OK] 添加了 {len(data.columns)} 列")

            # 测试并发获取
            print("  测试并发数据获取...")
            from concurrent_fetcher import ConcurrentDataFetcher

            concurrent_fetcher = ConcurrentDataFetcher(max_workers=5)
            results = concurrent_fetcher.fetch_stocks_parallel(
                ['600519', '000858', '002415'],
                days=120,
                show_progress=False
            )
            print(f"    [OK] 并发获取 {len(results)} 只股票")

            duration = time.time() - start
            self.add_result("数据获取流程", True, duration, "所有测试通过")

        except Exception as e:
            duration = time.time() - start
            self.add_result("数据获取流程", False, duration, f"失败: {str(e)}")

    def test_signal_pipeline(self):
        """测试信号生成流程"""
        print("\n" + "=" * 60)
        print("[Test 2] 信号生成流程集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from stock_data_fetcher import StockDataFetcher
            from signal_generator import SignalGenerator

            fetcher = StockDataFetcher()
            generator = SignalGenerator()

            # 获取数据
            data = fetcher.get_quote_data('600519', days=120)
            if data is None or len(data) == 0:
                self.add_result("信号生成流程", False, time.time() - start, "无法获取数据")
                return

            data = fetcher.calculate_technical_indicators(data)

            # 生成信号
            print("  生成交易信号...")
            data_with_signals = generator.generate_signals(data)
            print(f"    [OK] 添加了信号列")

            # 获取最新信号
            print("  获取最新信号...")
            signal = generator.get_latest_signal(data)
            print(f"    [OK] 买入: {signal['buy_signal']}, 卖出: {signal['sell_signal']}")
            print(f"    [OK] 信号强度: {signal['strength']:+.1f}")

            duration = time.time() - start
            self.add_result("信号生成流程", True, duration, "所有测试通过")

        except Exception as e:
            duration = time.time() - start
            self.add_result("信号生成流程", False, duration, f"失败: {str(e)}")

    def test_backtest_pipeline(self):
        """测试回测流程"""
        print("\n" + "=" * 60)
        print("[Test 3] 回测流程集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from stock_data_fetcher import StockDataFetcher
            from signal_generator import SignalGenerator
            from backtest_framework import BacktestEngine, PositionConfig

            fetcher = StockDataFetcher()
            generator = SignalGenerator()

            # 获取数据
            data = fetcher.get_quote_data('600519', days=252)
            if data is None or len(data) == 0:
                self.add_result("回测流程", False, time.time() - start, "无法获取数据")
                return

            data = fetcher.calculate_technical_indicators(data)
            data_with_signals = generator.generate_signals(data)

            # 创建回测引擎
            print("  创建回测引擎...")
            engine = BacktestEngine(
                initial_cash=1000000,
                position_config=PositionConfig(
                    sizing_value=0.2,
                    max_position_pct=0.5
                )
            )

            # 运行回测
            print("  运行回测...")
            # 简单策略：当signal_buy为1时买入，signal_sell为1时卖出
            def simple_strategy(data):
                if len(data) < 2:
                    return 0
                latest = data.iloc[-1]
                if latest.get('signal_buy', 0) == 1:
                    return 1  # 买入
                elif latest.get('signal_sell', 0) == 1:
                    return -1  # 卖出
                return 0  # 持有

            result = engine.run(data_with_signals, simple_strategy, symbol='600519')

            # 检查结果
            print(f"    [OK] 总收益率: {result.get('total_return', 0):.2%}")
            print(f"    [OK] 夏普比率: {result.get('sharpe_ratio', 0):.2f}")
            print(f"    [OK] 最大回撤: {result.get('max_drawdown', 0):.2%}")
            print(f"    [OK] 交易次数: {len(result.get('trades', []))}")

            duration = time.time() - start
            self.add_result("回测流程", True, duration, "所有测试通过")

        except Exception as e:
            duration = time.time() - start
            self.add_result("回测流程", False, duration, f"失败: {str(e)}")

    def test_portfolio_pipeline(self):
        """测试组合管理流程"""
        print("\n" + "=" * 60)
        print("[Test 4] 组合管理流程集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from portfolio_manager import PortfolioManager

            manager = PortfolioManager()

            # 创建组合
            print("  创建投资组合...")
            portfolio = manager.create_portfolio("测试组合", 1000000)
            portfolio_name = portfolio.name
            print(f"    [OK] 组合名称: {portfolio_name}")

            # 添加持仓
            print("  添加持仓...")
            manager.add_position(portfolio_name, '600519', '贵州茅台', 100, 1800)
            manager.add_position(portfolio_name, '000858', '五粮液', 200, 150)
            print("    [OK] 添加了2个持仓")

            # 获取绩效
            print("  获取绩效分析...")
            performance = manager.get_performance(portfolio_name)
            print(f"    [OK] 总资产: {performance.get('total_value', 0):,.2f}")

            # 获取风险指标
            print("  获取风险指标...")
            risk = manager.get_risk_metrics(portfolio_name)
            print(f"    [OK] 波动率: {risk.get('volatility', 0):.2%}")

            duration = time.time() - start
            self.add_result("组合管理流程", True, duration, "所有测试通过")

        except Exception as e:
            duration = time.time() - start
            self.add_result("组合管理流程", False, duration, f"失败: {str(e)}")

    def test_monitor_pipeline(self):
        """测试实时监控流程"""
        print("\n" + "=" * 60)
        print("[Test 5] 实时监控流程集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from real_time_monitor import RealTimeMonitor, AlertCondition, AlertType, AlertPriority

            monitor = RealTimeMonitor()

            # 添加股票
            print("  添加监控股票...")
            monitor.add_stock('600519', '贵州茅台')
            monitor.add_stock('000858', '五粮液')
            print("    [OK] 添加了2只股票")

            # 添加告警条件
            print("  添加告警条件...")
            alert = AlertCondition(
                alert_type=AlertType.PRICE_ABOVE,
                threshold=2000,
                priority=AlertPriority.HIGH
            )
            monitor.add_condition('600519', alert)
            print("    [OK] 添加了告警条件")

            # 检查条件
            print("  检查告警条件...")
            alerts = monitor.check_conditions('600519')
            print(f"    [OK] 触发 {len(alerts)} 个告警")

            # 生成报告
            print("  生成监控报告...")
            report = monitor.generate_monitor_report()
            print("    [OK] 报告生成成功")

            duration = time.time() - start
            self.add_result("实时监控流程", True, duration, "所有测试通过")

        except Exception as e:
            duration = time.time() - start
            self.add_result("实时监控流程", False, duration, f"失败: {str(e)}")

    def test_visualization_pipeline(self):
        """测试可视化流程"""
        print("\n" + "=" * 60)
        print("[Test 6] 可视化流程集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from stock_data_fetcher import StockDataFetcher
            from chart_visualizer import ChartVisualizer

            fetcher = StockDataFetcher()
            visualizer = ChartVisualizer(output_dir="test_charts")

            # 获取数据
            data = fetcher.get_quote_data('600519', days=120)
            if data is None or len(data) == 0:
                self.add_result("可视化流程", False, time.time() - start, "无法获取数据")
                return

            data = fetcher.calculate_technical_indicators(data)

            # 测试K线图
            print("  测试K线图生成...")
            path = visualizer.plot_candlestick(data, '600519', save_path='test_charts/test_candlestick.png')
            print(f"    [OK] {path}")

            # 测试MACD图
            print("  测试MACD图生成...")
            path = visualizer.plot_macd(data, '600519', save_path='test_charts/test_macd.png')
            print(f"    [OK] {path}")

            # 测试综合分析图
            print("  测试综合分析图生成...")
            path = visualizer.plot_combined_analysis(data, '600519', save_path='test_charts/test_combined.png')
            print(f"    [OK] {path}")

            duration = time.time() - start
            self.add_result("可视化流程", True, duration, "所有测试通过")

        except Exception as e:
            duration = time.time() - start
            self.add_result("可视化流程", False, duration, f"失败: {str(e)}")

    def test_ml_pipeline(self):
        """测试机器学习流程"""
        print("\n" + "=" * 60)
        print("[Test 7] 机器学习流程集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from stock_data_fetcher import StockDataFetcher
            from ml_predictor import MLPredictor

            fetcher = StockDataFetcher()

            # 获取数据
            data = fetcher.get_quote_data('600519', days=500)
            if data is None or len(data) < 200:
                self.add_result("机器学习流程", False, time.time() - start, "数据不足")
                return

            data = fetcher.calculate_technical_indicators(data)

            # 创建预测器
            print("  创建ML预测器...")
            predictor = MLPredictor(model_type="random_forest")

            # 训练
            print("  训练模型...")
            evaluation = predictor.train(data, test_size=0.3, forward_days=5, threshold=0.02)
            print(f"    [OK] 准确率: {evaluation.accuracy:.2%}")

            # 预测
            print("  执行预测...")
            result = predictor.predict(data)
            print(f"    [OK] 预测: {result.prediction}, 概率: {result.probability:.2%}")

            duration = time.time() - start
            self.add_result("机器学习流程", True, duration, "所有测试通过")

        except ImportError:
            duration = time.time() - start
            self.add_result("机器学习流程", False, duration, "scikit-learn未安装")
        except Exception as e:
            duration = time.time() - start
            self.add_result("机器学习流程", False, duration, f"失败: {str(e)}")

    def test_cache_integration(self):
        """测试缓存集成"""
        print("\n" + "=" * 60)
        print("[Test 8] 缓存集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from cache_manager import CacheManager
            from concurrent_fetcher import ConcurrentDataFetcher

            # 测试缓存
            print("  测试Redis缓存...")
            cache = CacheManager()

            if not cache.is_enabled():
                self.add_result("缓存集成", False, time.time() - start, "Redis未连接")
                return

            # 基础操作
            cache.set("test_key", {"data": "test"}, ttl=60)
            value = cache.get("test_key")
            if value is not None:
                print("    [OK] 基础缓存操作正常")

            # 股票数据缓存
            print("  测试股票数据缓存...")
            test_data = pd.DataFrame({
                '日期': [datetime.now()],
                '收盘': [100.0],
                '开盘': [99.0],
                '最高': [101.0],
                '最低': [98.0],
                '成交量': [1000000]
            })
            cache.cache_stock_data('TEST', test_data)
            cached = cache.get_stock_data('TEST')
            if cached is not None:
                print("    [OK] 股票数据缓存正常")

            # 并发+缓存集成
            print("  测试并发+缓存集成...")
            fetcher = ConcurrentDataFetcher(max_workers=5, use_cache=True)
            fetcher.reset_stats()

            results = fetcher.fetch_stocks_parallel(
                ['600519', '000858'],
                days=120,
                show_progress=False
            )

            stats = fetcher.get_stats()
            print(f"    [OK] 缓存命中: {stats['cache_hits']}/{stats['cache_hits'] + stats['api_calls']}")

            duration = time.time() - start
            self.add_result("缓存集成", True, duration, "所有测试通过")

        except ImportError:
            duration = time.time() - start
            self.add_result("缓存集成", False, duration, "Redis未安装")
        except Exception as e:
            duration = time.time() - start
            self.add_result("缓存集成", False, duration, f"失败: {str(e)}")

    def test_database_integration(self):
        """测试数据库集成"""
        print("\n" + "=" * 60)
        print("[Test 9] 数据库集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from database_manager import DatabaseManager

            # 测试连接
            print("  测试数据库连接...")
            db = DatabaseManager()

            if not db.is_connected():
                self.add_result("数据库集成", False, time.time() - start, "数据库未连接")
                return

            print("    [OK] 数据库连接成功")

            # 测试表操作
            print("  测试数据表操作...")
            db.create_tables()
            print("    [OK] 数据表创建成功")

            # 测试保存股票信息
            print("  测试保存股票信息...")
            db.save_stock_info('TEST001', '测试股票', market='SH', industry='测试')
            print("    [OK] 保存成功")

            # 获取统计
            print("  获取数据库统计...")
            stats = db.get_table_stats()
            print(f"    [OK] 股票数: {stats.get('stocks', 0)}")

            duration = time.time() - start
            self.add_result("数据库集成", True, duration, "所有测试通过")

        except ImportError:
            duration = time.time() - start
            self.add_result("数据库集成", False, duration, "SQLAlchemy未安装")
        except Exception as e:
            duration = time.time() - start
            self.add_result("数据库集成", False, duration, f"失败: {str(e)}")

    def test_strategy_optimization(self):
        """测试策略优化流程"""
        print("\n" + "=" * 60)
        print("[Test 10] 策略优化集成测试")
        print("=" * 60)

        start = time.time()

        try:
            from stock_data_fetcher import StockDataFetcher
            from strategy_optimizer import StrategyOptimizer, MAStrategy, OptimizationConfig

            fetcher = StockDataFetcher()

            # 获取数据
            data = fetcher.get_quote_data('600519', days=252)
            if data is None or len(data) == 0:
                self.add_result("策略优化", False, time.time() - start, "无法获取数据")
                return

            data = fetcher.calculate_technical_indicators(data)

            # 创建优化器
            print("  创建策略优化器...")
            optimizer = StrategyOptimizer(
                strategy=MAStrategy(),
                config=OptimizationConfig(target_metric="sharpe_ratio")
            )

            # 网格搜索
            print("  执行网格搜索...")
            result = optimizer.grid_search(
                data,
                param_grid={
                    'short_period': [5, 10],
                    'long_period': [20, 30]
                },
                verbose=False
            )

            print(f"    [OK] 最佳夏普比率: {result.score:.4f}")
            print(f"    [OK] 最佳参数: {result.parameters}")

            duration = time.time() - start
            self.add_result("策略优化", True, duration, "所有测试通过")

        except ImportError:
            duration = time.time() - start
            self.add_result("策略优化", False, duration, "scipy未安装")
        except Exception as e:
            duration = time.time() - start
            self.add_result("策略优化", False, duration, f"失败: {str(e)}")

    def run_all_tests(self):
        """运行所有测试"""
        print("\n")
        print("╔" + "═" * 58 + "╗")
        print("║" + " " * 20 + "集成测试套件" + " " * 30 + "║")
        print("╚" + "═" * 58 + "╝")
        print()

        # 运行所有测试
        self.test_data_pipeline()
        self.test_signal_pipeline()
        self.test_backtest_pipeline()
        self.test_portfolio_pipeline()
        self.test_monitor_pipeline()
        self.test_visualization_pipeline()
        self.test_ml_pipeline()
        self.test_cache_integration()
        self.test_database_integration()
        self.test_strategy_optimization()

        # 生成报告
        self.generate_report()

    def generate_report(self):
        """生成测试报告"""
        print("\n" + "=" * 60)
        print("集成测试报告")
        print("=" * 60)

        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r['passed'])
        failed_tests = total_tests - passed_tests

        total_duration = time.time() - self.start_time

        print(f"\n总测试数: {total_tests}")
        print(f"通过: {passed_tests}")
        print(f"失败: {failed_tests}")
        print(f"通过率: {passed_tests/total_tests*100:.1f}%")
        print(f"总耗时: {total_duration:.2f}秒")

        print("\n详细结果:")
        print("-" * 60)

        for i, result in enumerate(self.test_results, 1):
            status = "[PASS] 通过" if result['passed'] else "[FAIL] 失败"
            print(f"{i}. {result['test']}: {status} ({result['duration']:.2f}s)")

            if not result['passed'] and result['message']:
                print(f"   错误: {result['message']}")

        print("-" * 60)

        if failed_tests == 0:
            print("\n[SUCCESS] 所有测试通过！")
        else:
            print(f"\n[WARNING] 有 {failed_tests} 个测试失败")


# =============================================================================
# 主程序
# =============================================================================

if __name__ == "__main__":
    suite = IntegrationTestSuite()
    suite.run_all_tests()
