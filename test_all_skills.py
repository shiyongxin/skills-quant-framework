# -*- coding: utf-8 -*-
"""
Skills综合测试脚本
测试所有更新后的skills模块
"""
import sys
sys.path.append('.claude/skills')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print("=" * 80)
print("                    Skills综合测试")
print(f"                    测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)
print()

test_results = []

# ============================================
# 测试1: 修正后的数据获取模块
# ============================================
print("[测试1] 数据获取模块 (stock_data_fetcher.py)")
print("-" * 80)

try:
    from stock_data_fetcher import StockDataFetcher

    fetcher = StockDataFetcher(data_dir='./test_data')

    # 测试单只股票
    print("  1.1 测试单只股票获取...", end=' ')
    data = fetcher.get_quote_data('600519', days=60)

    if not data.empty and len(data) > 0:
        print(f"OK ({len(data)}条记录)")
        test_results.append(('stock_data_fetcher_single', 'PASS', f'{len(data)}条'))
    else:
        print("FAILED")
        test_results.append(('stock_data_fetcher_single', 'FAIL', '无数据'))

    # 测试批量获取
    print("  1.2 测试批量获取...", end=' ')
    stocks = ['000001', '600519', '000858']
    batch_data = fetcher.batch_get_quotes(stocks, delay=0.3)

    if len(batch_data) == len(stocks):
        print(f"OK ({len(batch_data)}/{len(stocks)}只股票)")
        test_results.append(('stock_data_fetcher_batch', 'PASS', f'{len(batch_data)}/{len(stocks)}'))
    else:
        print(f"PARTIAL ({len(batch_data)}/{len(stocks)})")
        test_results.append(('stock_data_fetcher_batch', 'PARTIAL', f'{len(batch_data)}/{len(stocks)}'))

    # 测试技术指标计算
    print("  1.3 测试技术指标计算...", end=' ')
    if not data.empty:
        data_with_indicators = fetcher.calculate_technical_indicators(data)

        required_cols = ['MA5', 'MA20', 'MACD', 'RSI', 'K', 'D', 'BB_Upper', 'BB_Lower']
        has_all = all(col in data_with_indicators.columns for col in required_cols)

        if has_all:
            print(f"OK ({len(required_cols)}个指标)")
            test_results.append(('stock_data_fetcher_indicators', 'PASS', f'{len(required_cols)}个指标'))
        else:
            missing = [c for c in required_cols if c not in data_with_indicators.columns]
            print(f"FAILED (缺少: {missing})")
            test_results.append(('stock_data_fetcher_indicators', 'FAIL', f'缺少{len(missing)}个'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('stock_data_fetcher', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试2: 高级技术指标
# ============================================
print("[测试2] 高级技术指标 (advanced_indicators.py)")
print("-" * 80)

try:
    from advanced_indicators import AdvancedIndicators

    print("  2.1 测试ATR计算...", end=' ')
    if not data.empty:
        df = AdvancedIndicators.atr(data.copy())
        if 'ATR' in df.columns:
            print(f"OK (最新ATR: {df['ATR'].iloc[-1]:.2f})")
            test_results.append(('advanced_indicators_atr', 'PASS', 'ATR计算正常'))
        else:
            print("FAILED")
            test_results.append(('advanced_indicators_atr', 'FAIL', '无ATR列'))

    print("  2.2 测试KDJ计算...", end=' ')
    df = AdvancedIndicators.kdj(data.copy())
    if 'K' in df.columns and 'D' in df.columns:
        print(f"OK (K:{df['K'].iloc[-1]:.2f}, D:{df['D'].iloc[-1]:.2f})")
        test_results.append(('advanced_indicators_kdj', 'PASS', 'KDJ计算正常'))
    else:
        print("FAILED")
        test_results.append(('advanced_indicators_kdj', 'FAIL', '无KDJ列'))

    print("  2.3 测试批量计算...", end=' ')
    df = AdvancedIndicators.calculate_all(data.copy())
    if len(df.columns) > len(data.columns):
        new_cols = len(df.columns) - len(data.columns)
        print(f"OK (新增{new_cols}个指标)")
        test_results.append(('advanced_indicators_batch', 'PASS', f'{new_cols}个新指标'))
    else:
        print("FAILED")
        test_results.append(('advanced_indicators_batch', 'FAIL', '无新增列'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('advanced_indicators', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试3: 趋势指标
# ============================================
print("[测试3] 趋势指标 (trend_indicators.py)")
print("-" * 80)

try:
    from trend_indicators import TrendIndicators

    print("  3.1 测试EMA计算...", end=' ')
    df = TrendIndicators.ema(data.copy(), 20)
    if 'EMA_20' in df.columns:
        print(f"OK (EMA20: {df['EMA_20'].iloc[-1]:.2f})")
        test_results.append(('trend_indicators_ema', 'PASS', 'EMA计算正常'))
    else:
        print("FAILED")
        test_results.append(('trend_indicators_ema', 'FAIL', '无EMA列'))

    print("  3.2 测试HMA计算...", end=' ')
    df = TrendIndicators.hull_ma(data.copy(), 20)
    if 'HMA_20' in df.columns:
        print(f"OK (HMA20: {df['HMA_20'].iloc[-1]:.2f})")
        test_results.append(('trend_indicators_hma', 'PASS', 'HMA计算正常'))
    else:
        print("FAILED")
        test_results.append(('trend_indicators_hma', 'FAIL', '无HMA列'))

    print("  3.3 测试VWAP计算...", end=' ')
    df = TrendIndicators.vwap(data.copy())
    if 'VWAP' in df.columns:
        print(f"OK (VWAP: {df['VWAP'].iloc[-1]:.2f})")
        test_results.append(('trend_indicators_vwap', 'PASS', 'VWAP计算正常'))
    else:
        print("FAILED")
        test_results.append(('trend_indicators_vwap', 'FAIL', '无VWAP列'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('trend_indicators', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试4: 形态识别
# ============================================
print("[测试4] 形态识别 (pattern_recognition.py)")
print("-" * 80)

try:
    from pattern_recognition import CandlestickPatterns, PricePatterns

    print("  4.1 测试K线形态识别...", end=' ')
    patterns = CandlestickPatterns.scan_all_patterns(data.copy())
    if patterns is not None and len(patterns) > 0:
        pattern_count = len([c for c in patterns.columns if 'latest' in c])
        print(f"OK ({pattern_count}种形态)")
        test_results.append(('pattern_candlestick', 'PASS', f'{pattern_count}种形态'))
    else:
        print("FAILED")
        test_results.append(('pattern_candlestick', 'FAIL', '无形态数据'))

    print("  4.2 测试支撑压力识别...", end=' ')
    support = PricePatterns.detect_support_level(data.copy())
    resistance = PricePatterns.detect_resistance_level(data.copy())
    if support is not None and resistance is not None and len(support) > 0:
        print(f"OK (支撑:{len(support)}个, 压力:{len(resistance)}个)")
        test_results.append(('pattern_price_levels', 'PASS', f'支撑{len(support)}个,压力{len(resistance)}个'))
    else:
        print("FAILED")
        test_results.append(('pattern_price_levels', 'FAIL', '无支撑压力'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('pattern_recognition', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试5: 风险管理
# ============================================
print("[测试5] 风险管理 (risk_management.py)")
print("-" * 80)

try:
    from risk_management import RiskMetrics, PositionSizing, StopLossManager

    if not data.empty:
        returns = data['收盘'].pct_change().dropna()

        print("  5.1 测试VaR计算...", end=' ')
        var_95 = RiskMetrics.var(returns, 0.95)
        if not np.isnan(var_95):
            print(f"OK (VaR95%: {var_95*100:.2f}%)")
            test_results.append(('risk_var', 'PASS', f'VaR:{var_95*100:.2f}%'))
        else:
            print(f"FAILED (VaR: {var_95})")
            test_results.append(('risk_var', 'FAIL', f'VaR异常:{var_95}'))

        print("  5.2 测试夏普比率...", end=' ')
        sharpe = RiskMetrics.sharpe_ratio(returns)
        if not np.isnan(sharpe):
            print(f"OK (夏普: {sharpe:.2f})")
            test_results.append(('risk_sharpe', 'PASS', f'夏普:{sharpe:.2f}'))
        else:
            print("FAILED")
            test_results.append(('risk_sharpe', 'FAIL', '夏普异常'))

        print("  5.3 测试仓位计算...", end=' ')
        pos = PositionSizing.fixed_fractional(100000, 0.02, 0.08)
        if pos > 0 and pos <= 100000:
            print(f"OK (建议仓位: {pos:,.0f}元)")
            test_results.append(('risk_position', 'PASS', f'{pos:,.0f}元'))
        else:
            print(f"FAILED (仓位: {pos})")
            test_results.append(('risk_position', 'FAIL', f'仓位异常:{pos}'))

        print("  5.4 测试止损管理...", end=' ')
        stop_manager = StopLossManager()
        stop_manager.add_position('test', data['收盘'].iloc[-1], 0.08)
        check_result = stop_manager.check_stop_loss('test', data['收盘'].iloc[-1] * 0.95)
        if check_result is not None:
            print(f"OK (止损管理正常)")
            test_results.append(('risk_stoploss', 'PASS', '止损管理正常'))
        else:
            print("FAILED")
            test_results.append(('risk_stoploss', 'FAIL', '止损异常'))
    else:
        print("SKIP (无数据)")
        test_results.append(('risk_management', 'SKIP', '无数据'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('risk_management', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试6: 回测框架
# ============================================
print("[测试6] 回测框架 (backtest_framework.py)")
print("-" * 80)

try:
    from backtest_framework import BacktestEngine, StrategyFactory

    if not data.empty and len(data) > 50:
        # 创建简单策略
        def simple_strategy(df):
            if len(df) < 20:
                return 0
            # MA金叉策略
            if df['MA5'].iloc[-1] > df['MA20'].iloc[-1]:
                return 1
            elif df['MA5'].iloc[-1] < df['MA20'].iloc[-1]:
                return -1
            return 0

        print("  6.1 测试回测引擎...", end=' ')
        engine = BacktestEngine(initial_cash=100000)
        result = engine.run(data.copy(), simple_strategy)

        if result and 'total_return' in result:
            print(f"OK (收益率: {result['total_return']:.2f}%)")
            test_results.append(('backtest_engine', 'PASS', f'收益:{result["total_return"]:.2f}%'))
        else:
            print("FAILED")
            test_results.append(('backtest_engine', 'FAIL', '无结果'))

        print("  6.2 测试策略工厂...", end=' ')
        ma_strategy = StrategyFactory.ma_cross(5, 20)
        if callable(ma_strategy):
            print("OK (MA交叉策略创建成功)")
            test_results.append(('backtest_factory', 'PASS', '策略工厂正常'))
        else:
            print("FAILED")
            test_results.append(('backtest_factory', 'FAIL', '策略创建失败'))
    else:
        print("SKIP (数据不足)")
        test_results.append(('backtest_framework', 'SKIP', '数据不足'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('backtest_framework', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试7: 多因子选股
# ============================================
print("[测试7] 多因子选股 (multi_factor_selection.py)")
print("-" * 80)

try:
    from multi_factor_selection import MultiFactorSelector, SmartBetaStrategy

    print("  7.1 测试多因子选择器...", end=' ')
    selector = MultiFactorSelector()

    # 创建模拟财务数据
    financial_data = pd.DataFrame({
        'code': ['000001', '600519', '000858'],
        'pe': [10, 35, 25],
        'pb': [1.2, 10, 5],
        'roe': [0.12, 0.25, 0.20],
        'revenue_growth': [0.08, 0.15, 0.12]
    })

    result = selector.calculate_factors(financial_data)
    if result is not None:
        print(f"OK (因子计算完成)")
        test_results.append(('multi_factor_selector', 'PASS', '因子计算正常'))
    else:
        print("FAILED")
        test_results.append(('multi_factor_selector', 'FAIL', '无结果'))

    print("  7.2 测试Smart Beta策略...", end=' ')
    smart_beta = SmartBetaStrategy()

    # 测试低波动策略
    price_data = pd.DataFrame({
        'code': ['000001', '600519', '000858'],
        'volatility': [0.2, 0.35, 0.25]
    })

    result = smart_beta.low_volatility(price_data)
    if result is not None:
        print("OK (低波动策略执行成功)")
        test_results.append(('smart_beta', 'PASS', '策略执行正常'))
    else:
        print("FAILED")
        test_results.append(('smart_beta', 'FAIL', '无结果'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('multi_factor_selection', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试8: 集成工作流
# ============================================
print("[测试8] 集成工作流 (quant_analysis_workflow.py)")
print("-" * 80)

try:
    from quant_analysis_workflow import QuantAnalysisWorkflow

    print("  8.1 测试工作流初始化...", end=' ')
    workflow = QuantAnalysisWorkflow(initial_capital=100000)
    print("OK")
    test_results.append(('workflow_init', 'PASS', '初始化正常'))

    print("  8.2 测试数据获取阶段...", end=' ')
    test_stocks = {'600519': '贵州茅台', '000858': '五粮液'}

    # 只测试数据获取阶段
    data_dict = workflow.stage1_data_acquisition(test_stocks, days=60)

    if len(data_dict) > 0:
        print(f"OK ({len(data_dict)}/{len(test_stocks)}只股票)")
        test_results.append(('workflow_data', 'PASS', f'{len(data_dict)}/{len(test_stocks)}'))
    else:
        print("FAILED")
        test_results.append(('workflow_data', 'FAIL', '无数据'))

except Exception as e:
    print(f"ERROR: {str(e)[:100]}")
    test_results.append(('workflow', 'ERROR', str(e)[:50]))

print()

# ============================================
# 测试总结
# ============================================
print("=" * 80)
print("测试总结")
print("=" * 80)
print()

# 统计结果
total = len(test_results)
passed = sum(1 for _, status, _ in test_results if status == 'PASS')
failed = sum(1 for _, status, _ in test_results if status == 'FAIL')
error = sum(1 for _, status, _ in test_results if status == 'ERROR')
skipped = sum(1 for _, status, _ in test_results if status == 'SKIP' or status == 'PARTIAL')

print(f"总测试数: {total}")
print(f"  通过: {passed} ({passed/total*100:.1f}%)")
print(f"  失败: {failed} ({failed/total*100:.1f}%)")
print(f"  错误: {error} ({error/total*100:.1f}%)")
print(f"  跳过/部分: {skipped} ({skipped/total*100:.1f}%)")
print()

# 详细结果
print(f"{'模块':<30}{'状态':<10}{'说明'}")
print("-" * 80)

for name, status, desc in test_results:
    status_symbol = {
        'PASS': '[PASS]',
        'FAIL': '[FAIL]',
        'ERROR': '[ERROR]',
        'SKIP': '[SKIP]',
        'PARTIAL': '[PARTIAL]'
    }.get(status, '[?]')

    print(f"{name:<30}{status_symbol:<10}{desc}")

print()

# 最终评估
print("=" * 80)
if passed == total:
    print("[评估] 所有测试通过！Skills模块工作正常。")
elif passed >= total * 0.8:
    print("[评估] 大部分测试通过，Skills模块基本可用。")
elif passed >= total * 0.5:
    print("[评估] 部分测试通过，Skills模块需要修复。")
else:
    print("[评估] 多数测试失败，Skills模块需要检查。")
print("=" * 80)
print()

print(f"测试完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
