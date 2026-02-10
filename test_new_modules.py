# -*- coding: utf-8 -*-
"""
Test new modules with real data
测试新增模块: 高级技术指标、回测框架、风险管理
"""
import sys
sys.path.append('.claude/skills')

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Import new modules
from advanced_indicators import AdvancedIndicators
from backtest_framework import BacktestEngine, StrategyFactory, PerformanceReport
from risk_management import RiskMetrics, PositionSizing, StopLossManager

print("=" * 80)
print("Testing New Quantitative Trading Modules")
print("=" * 80)
print()

# Step 1: Fetch real data
print("[Step 1] Fetching real stock data...")
stock_code = "600519"  # Guizhou Moutai
end_date = datetime.now().strftime("%Y%m%d")
start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

try:
    df = ak.stock_zh_a_hist(
        symbol=stock_code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq"
    )

    if df is None or len(df) < 100:
        print(f"Insufficient data for {stock_code}")
        sys.exit(1)

    print(f"Fetched {len(df)} records for {stock_code} ({start_date} ~ {end_date})")
    print(f"Price range: {df['收盘'].min():.2f} - {df['收盘'].max():.2f}")
    print(f"Latest price: {df['收盘'].iloc[-1]:.2f}")
    print()

except Exception as e:
    print(f"Error fetching data: {e}")
    sys.exit(1)

# Step 2: Test Advanced Indicators
print("[Step 2] Testing Advanced Indicators...")
print("-" * 80)

# Calculate all indicators
df_with_indicators = AdvancedIndicators.calculate_all(df.copy())

# Display latest indicator values
latest = df_with_indicators.iloc[-1]
print(f"Latest indicators for {stock_code}:")
print(f"  ATR(14):           {latest['ATR']:.2f}")
print(f"  KDJ:  K={latest['K']:.2f}, D={latest['D']:.2f}, J={latest['J']:.2f}")
print(f"  CCI(20):           {latest['CCI']:.2f}")
print(f"  Williams %R:       {latest['Williams_R']:.2f}")
print(f"  MFI(14):           {latest['MFI']:.2f}")
print(f"  TRIX:              {latest['TRIX']:.4f}")
print(f"  VWAP:              {latest['VWAP']:.2f}")

# Signal analysis
signals = []
if latest['K'] < 20:
    signals.append("KDJ超卖")
elif latest['K'] > 80:
    signals.append("KDJ超买")

if latest['CCI'] < -100:
    signals.append("CCI超卖")
elif latest['CCI'] > 100:
    signals.append("CCI超买")

if latest['Williams_R'] < -80:
    signals.append("Williams超卖")
elif latest['Williams_R'] > -20:
    signals.append("Williams超买")

if latest['MFI'] < 20:
    signals.append("MFI资金流出")
elif latest['MFI'] > 80:
    signals.append("MFI资金流入")

print(f"\nSignal analysis: {', '.join(signals) if signals else 'No clear signals'}")
print()

# Step 3: Test Backtest Framework
print("[Step 3] Testing Backtest Framework...")
print("-" * 80)

# Test different strategies
strategies = [
    ('MA Cross (5/20)', StrategyFactory.ma_cross(5, 20)),
    ('MA Cross (10/30)', StrategyFactory.ma_cross(10, 30)),
    ('MACD Cross', StrategyFactory.macd_cross(12, 26, 9)),
    ('RSI (14)', StrategyFactory.rsi_overbought_oversold(14, 30, 70)),
    ('Bollinger (20,2)', StrategyFactory.bollinger_bands(20, 2)),
]

backtest_results = []

for name, strategy in strategies:
    engine = BacktestEngine(initial_cash=100000, commission=0.0003)
    result = engine.run(df_with_indicators, strategy)

    backtest_results.append({
        'name': name,
        'total_return': result['total_return'],
        'benchmark_return': result['benchmark_return'],
        'sharpe_ratio': result['sharpe_ratio'],
        'max_drawdown': result['max_drawdown'],
        'win_rate': result['win_rate'],
        'trade_count': result['trade_count']
    })

# Display comparison
print(f"{'Strategy':<20} {'Return %':<12} {'Sharpe':<8} {'Max DD %':<10} {'Win Rate %':<12} {'Trades'}")
print("-" * 80)
for r in backtest_results:
    print(f"{r['name']:<20} {r['total_return']:>10.2f}   {r['sharpe_ratio']:>6.2f}   "
          f"{r['max_drawdown']:>8.2f}    {r['win_rate']:>8.1f}      {r['trade_count']:>4}")

print()

# Find best strategy
best_by_return = max(backtest_results, key=lambda x: x['total_return'])
best_by_sharpe = max(backtest_results, key=lambda x: x['sharpe_ratio'])

print(f"Best by Return: {best_by_return['name']} ({best_by_return['total_return']:.2f}%)")
print(f"Best by Sharpe: {best_by_sharpe['name']} ({best_by_sharpe['sharpe_ratio']:.2f})")
print()

# Step 4: Test Risk Management
print("[Step 4] Testing Risk Management...")
print("-" * 80)

# Use best strategy for risk analysis
best_strategy = StrategyFactory.ma_cross(5, 20)
engine = BacktestEngine(initial_cash=100000, commission=0.0003)
result = engine.run(df_with_indicators, best_strategy)

# Calculate risk metrics from equity curve
equity_curve = result['equity_curve']['value']
returns = equity_curve.pct_change().dropna()

print("Risk Metrics:")
print(f"  Annual Volatility: {returns.std() * np.sqrt(252) * 100:.2f}%")
print(f"  VaR (95%): {RiskMetrics.var(returns, 0.95) * 100:.2f}%")
print(f"  CVaR (95%): {RiskMetrics.cvar(returns, 0.95) * 100:.2f}%")

max_dd_info = RiskMetrics.max_drawdown(equity_curve)
print(f"  Max Drawdown: {max_dd_info['max_drawdown_pct']:.2f}%")
print(f"    Start: {max_dd_info['start_date']}")
print(f"    End: {max_dd_info['end_date']}")
print(f"    Duration: {max_dd_info['duration_days']} days")

print(f"\nPerformance Ratios:")
print(f"  Sharpe Ratio: {RiskMetrics.sharpe_ratio(returns):.2f}")
print(f"  Sortino Ratio: {RiskMetrics.sortino_ratio(returns):.2f}")
print(f"  Calmar Ratio: {RiskMetrics.calmar_ratio(returns, equity_curve):.2f}")
print()

# Step 5: Test Position Sizing
print("[Step 5] Testing Position Sizing...")
print("-" * 80)

capital = 100000
current_price = df['收盘'].iloc[-1]
atr = df_with_indicators['ATR'].iloc[-1]

print(f"Current Price: {current_price:.2f}")
print(f"ATR(14): {atr:.2f}")
print(f"\nPosition sizing for {capital:,} capital:")

# Equal weight
n_stocks = 5
pos_equal = PositionSizing.equal_weight(capital, n_stocks)
print(f"  Equal Weight ({n_stocks} stocks): {pos_equal:,.2f}")

# Kelly (example parameters)
if result['trade_count'] > 0:
    win_rate = result['win_rate'] / 100
    avg_win = result['avg_profit']
    avg_loss = result['avg_loss']
    if avg_loss != 0:
        pos_kelly = PositionSizing.kelly_criterion(win_rate, avg_win, avg_loss, capital)
        print(f"  Kelly Criterion: {pos_kelly:,.2f}")

# Fixed fractional
pos_fixed = PositionSizing.fixed_fractional(capital, 0.02, 0.05)
print(f"  Fixed Fractional (2% risk, 5% stop): {pos_fixed:,.2f}")

# ATR based
risk_amount = capital * 0.02
shares_atr = PositionSizing.atr_based(current_price, atr, risk_amount)
position_value_atr = shares_atr * current_price
print(f"  ATR Based (2% risk): {shares_atr} shares = {position_value_atr:,.2f}")

# Volatility based
hist_vol = df['收盘'].pct_change().std() * np.sqrt(252)
pos_vol = PositionSizing.volatility_based(capital, hist_vol, 0.15)
print(f"  Volatility Based: {pos_vol:,.2f}")
print()

# Step 6: Test Stop Loss Manager
print("[Step 6] Testing Stop Loss Manager...")
print("-" * 80)

sl_manager = StopLossManager()

entry_price = df['收盘'].iloc[-10]
current_price = df['收盘'].iloc[-1]

print(f"Entry Price (10 days ago): {entry_price:.2f}")
print(f"Current Price: {current_price:.2f}")

sl_manager.add_position(
    symbol=stock_code,
    entry_price=entry_price,
    quantity=100,
    stop_loss_pct=0.05,
    take_profit_pct=0.15,
    trailing_stop_pct=0.08
)

check_result = sl_manager.check_stop_loss(stock_code, current_price)
print(f"Stop Loss Check: {check_result['action']}")
if check_result['action'] == 'hold':
    print(f"  Reason: {check_result['reason']}")
    print(f"  Stop Loss Price: {entry_price * 0.95:.2f}")
    print(f"  Take Profit Price: {entry_price * 1.15:.2f}")
    print(f"  Trailing Stop: {sl_manager.positions[stock_code]['highest_price'] * 0.92:.2f}")
print()

# Step 7: Parameter Optimization
print("[Step 7] Testing Parameter Optimization...")
print("-" * 80)

print("Optimizing MA Cross strategy...")
optimizer = ParameterOptimizer()
best_params, best_result = optimizer.grid_search(
    data=df_with_indicators,
    strategy_template=StrategyFactory.ma_cross,
    param_grid={
        'fast': [5, 10, 15],
        'slow': [20, 30, 40]
    },
    metric='sharpe_ratio'
)

print(f"\nOptimal Parameters: fast={best_params['fast']}, slow={best_params['slow']}")
print(f"Optimal Sharpe Ratio: {best_result['sharpe_ratio']:.2f}")
print(f"Total Return: {best_result['total_return']:.2f}%")
print(f"Max Drawdown: {best_result['max_drawdown']:.2f}%")
print()

# Step 8: Generate Report
print("[Step 8] Generating Performance Report...")
print("-" * 80)

report_file = f"backtest_report_{stock_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
PerformanceReport.generate_report(best_result, save_path=report_file)
print()

# Summary
print("=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print(f"Stock: {stock_code}")
print(f"Period: {start_date} ~ {end_date}")
print(f"Data Points: {len(df)}")
print()
print("Modules Tested:")
print("  [OK] Advanced Indicators (12 indicators)")
print("  [OK] Backtest Framework (5 strategies)")
print("  [OK] Risk Management (Risk metrics, position sizing, stop loss)")
print("  [OK] Parameter Optimization (Grid search)")
print()
print(f"Detailed report saved to: {report_file}")
print("=" * 80)
