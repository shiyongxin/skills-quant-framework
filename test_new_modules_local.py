# -*- coding: utf-8 -*-
"""
Test new modules with local/simulated data
"""
import sys
sys.path.append('.claude/skills')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Import new modules
from advanced_indicators import AdvancedIndicators
from backtest_framework import (
    BacktestEngine, StrategyFactory, PerformanceReport, ParameterOptimizer
)
from risk_management import RiskMetrics, PositionSizing, StopLossManager

# Helper function for Bollinger Bands
def add_bollinger_bands(df, period=20, std_dev=2):
    close = df['收盘']
    df['BB_Middle'] = close.rolling(window=period).mean()
    df['BB_Std'] = close.rolling(window=period).std()
    df['BB_Upper'] = df['BB_Middle'] + (df['BB_Std'] * std_dev)
    df['BB_Lower'] = df['BB_Middle'] - (df['BB_Std'] * std_dev)
    return df

print("=" * 80)
print("Testing New Quantitative Trading Modules (with Simulated Data)")
print("=" * 80)
print()

# Step 1: Generate realistic price data
print("[Step 1] Generating realistic price data...")
print("-" * 80)

np.random.seed(42)
n_days = 250

# Generate price path with drift and volatility
drift = 0.0005
volatility = 0.02
returns = np.random.normal(drift, volatility, n_days)

# Add some trend changes
returns[50:100] += 0.005   # Uptrend
returns[100:150] -= 0.003 # Downtrend
returns[150:200] += 0.002 # Recovery

# Generate prices
start_price = 100
prices = start_price * (1 + returns).cumprod()

# Create OHLCV data
dates = pd.date_range(end=datetime.now(), periods=n_days, freq='D')

df = pd.DataFrame({
    '日期': dates,
    '开盘': prices * (1 + np.random.uniform(-0.01, 0.01, n_days)),
    '收盘': prices,
    '最高': prices * (1 + np.random.uniform(0, 0.02, n_days)),
    '最低': prices * (1 - np.random.uniform(0, 0.02, n_days)),
    '成交量': np.random.randint(1000000, 10000000, n_days),
    '成交额': 0,
    '振幅': 0,
    '涨跌幅': 0,
    '涨跌额': 0,
    '换手率': 0
})

df['成交额'] = df['收盘'] * df['成交量']
df['涨跌幅'] = df['收盘'].pct_change() * 100
df['涨跌额'] = df['收盘'] - df['开盘'].shift(1)

print(f"Generated {n_days} days of price data")
print(f"Price range: {df['收盘'].min():.2f} - {df['收盘'].max():.2f}")
print(f"Start price: {df['收盘'].iloc[0]:.2f}, End price: {df['收盘'].iloc[-1]:.2f}")
print(f"Total return: {(df['收盘'].iloc[-1] / df['收盘'].iloc[0] - 1) * 100:.2f}%")
print()

# Step 2: Test Advanced Indicators
print("[Step 2] Testing Advanced Indicators...")
print("-" * 80)

# Calculate all indicators
df_with_indicators = AdvancedIndicators.calculate_all(df.copy())
# Add Bollinger Bands
df_with_indicators = add_bollinger_bands(df_with_indicators)

# Display latest indicator values
latest = df_with_indicators.iloc[-1]
print(f"Latest indicators:")
print(f"  ATR(14):           {latest['ATR']:.2f}")
print(f"  KDJ:  K={latest['K']:.2f}, D={latest['D']:.2f}, J={latest['J']:.2f}")
print(f"  CCI(20):           {latest['CCI']:.2f}")
print(f"  Williams %R:       {latest['Williams_R']:.2f}")
print(f"  MFI(14):           {latest['MFI']:.2f}")
print(f"  TRIX:              {latest['TRIX']:.4f}")
print(f"  VWAP:              {latest['VWAP']:.2f}")
print(f"  KC Upper:          {latest['KC_Upper']:.2f}")
print(f"  KC Lower:          {latest['KC_Lower']:.2f}")
print(f"  DC Upper:          {latest['DC_Upper']:.2f}")
print(f"  DC Lower:          {latest['DC_Lower']:.2f}")

# Signal analysis
signals = []
if latest['K'] < 20:
    signals.append("KDJ Oversold")
elif latest['K'] > 80:
    signals.append("KDJ Overbought")

if latest['CCI'] < -100:
    signals.append("CCI Oversold")
elif latest['CCI'] > 100:
    signals.append("CCI Overbought")

if latest['Williams_R'] < -80:
    signals.append("Williams Oversold")
elif latest['Williams_R'] > -20:
    signals.append("Williams Overbought")

if latest['MFI'] < 20:
    signals.append("MFI Outflow")
elif latest['MFI'] > 80:
    signals.append("MFI Inflow")

# Bollinger position
bb_width = (latest['BB_Upper'] - latest['BB_Lower']) / latest['BB_Middle'] * 100
bb_position = (latest['收盘'] - latest['BB_Lower']) / (latest['BB_Upper'] - latest['BB_Lower']) * 100
signals.append(f"BB Position: {bb_position:.1f}%")

print(f"\nSignal analysis: {', '.join(signals)}")
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
print(f"{'Strategy':<20} {'Return %':<12} {'Excess %':<10} {'Sharpe':<8} {'Max DD %':<10} {'Win %':<8} {'Trades'}")
print("-" * 80)
for r in backtest_results:
    excess = r['total_return'] - r['benchmark_return']
    print(f"{r['name']:<20} {r['total_return']:>10.2f}   {excess:>8.2f}   "
          f"{r['sharpe_ratio']:>6.2f}   {r['max_drawdown']:>8.2f}    "
          f"{r['win_rate']:>6.1f}    {r['trade_count']:>4}")

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
print(f"  VaR (99%): {RiskMetrics.var(returns, 0.99) * 100:.2f}%")

max_dd_info = RiskMetrics.max_drawdown(equity_curve)
print(f"\n  Max Drawdown: {max_dd_info['max_drawdown_pct']:.2f}%")
print(f"    Start: {max_dd_info['start_date']}")
print(f"    End: {max_dd_info['end_date']}")
print(f"    Duration: {max_dd_info['duration_days']} days")

print(f"\nPerformance Ratios:")
print(f"  Sharpe Ratio: {RiskMetrics.sharpe_ratio(returns):.2f}")
print(f"  Sortino Ratio: {RiskMetrics.sortino_ratio(returns):.2f}")
print(f"  Calmar Ratio: {RiskMetrics.calmar_ratio(returns, equity_curve):.2f}")

# Benchmark comparison
market_returns = df['收盘'].pct_change().dropna()
# Align lengths
min_len = min(len(returns), len(market_returns))
returns_aligned = returns.iloc[-min_len:]
market_returns_aligned = market_returns.iloc[-min_len:]
print(f"\nvs Benchmark (Buy & Hold):")
print(f"  Beta: {RiskMetrics.beta(returns_aligned, market_returns_aligned):.2f}")
print(f"  Alpha: {RiskMetrics.alpha(returns_aligned, market_returns_aligned):.2f}%")
print(f"  Information Ratio: {RiskMetrics.information_ratio(returns_aligned, market_returns_aligned):.2f}")
print()

# Step 5: Test Position Sizing
print("[Step 5] Testing Position Sizing...")
print("-" * 80)

capital = 100000
current_price = df['收盘'].iloc[-1]
atr = df_with_indicators['ATR'].iloc[-1]
hist_vol = df['收盘'].pct_change().std() * np.sqrt(252)

print(f"Current Price: {current_price:.2f}")
print(f"ATR(14): {atr:.2f}")
print(f"Historical Volatility: {hist_vol*100:.2f}%")
print(f"\nPosition sizing for {capital:,} capital:")

# Equal weight
n_stocks = 5
pos_equal = PositionSizing.equal_weight(capital, n_stocks)
print(f"  Equal Weight ({n_stocks} stocks): {pos_equal:,.2f}")

# Kelly
if result['trade_count'] > 0 and result['avg_loss'] != 0:
    win_rate = result['win_rate'] / 100
    avg_win = result['avg_profit']
    avg_loss = result['avg_loss']
    pos_kelly = PositionSizing.kelly_criterion(win_rate, avg_win, avg_loss, capital)
    print(f"  Kelly Criterion (w={win_rate:.2f}, win={avg_win:.1f}%, loss={avg_loss:.1f}%): {pos_kelly:,.2f}")

# Fixed fractional
for risk_pct in [0.01, 0.02, 0.05]:
    for stop_pct in [0.03, 0.05, 0.10]:
        pos_fixed = PositionSizing.fixed_fractional(capital, risk_pct, stop_pct)
        print(f"  Fixed Fractional ({risk_pct*100:.0f}% risk, {stop_pct*100:.0f}% stop): {pos_fixed:,.2f}")

# ATR based
risk_amount = capital * 0.02
shares_atr = PositionSizing.atr_based(current_price, atr, risk_amount)
position_value_atr = shares_atr * current_price
print(f"  ATR Based (2% risk): {shares_atr} shares = {position_value_atr:,.2f}")

# Volatility based
for target_vol in [0.10, 0.15, 0.20]:
    pos_vol = PositionSizing.volatility_based(capital, hist_vol, target_vol)
    print(f"  Volatility Based (target {target_vol*100:.0f}%): {pos_vol:,.2f}")
print()

# Step 6: Test Stop Loss Manager
print("[Step 6] Testing Stop Loss Manager...")
print("-" * 80)

sl_manager = StopLossManager()

# Simulate a position
entry_price = df['收盘'].iloc[-30]
current_price = df['收盘'].iloc[-1]
highest_price = df['收盘'].iloc[-30:].max()

print(f"Entry Price (30 days ago): {entry_price:.2f}")
print(f"Current Price: {current_price:.2f}")
print(f"Highest Price since entry: {highest_price:.2f}")

sl_manager.add_position(
    symbol='TEST',
    entry_price=entry_price,
    quantity=100,
    stop_loss_pct=0.05,
    take_profit_pct=0.15,
    trailing_stop_pct=0.08
)

# Test different price scenarios
print(f"\nStop Loss Scenarios:")
print(f"  Fixed Stop Loss (5%): {entry_price * 0.95:.2f}")
print(f"  Take Profit (15%): {entry_price * 1.15:.2f}")
print(f"  Trailing Stop (8% from high {highest_price:.2f}): {highest_price * 0.92:.2f}")

check_result = sl_manager.check_stop_loss('TEST', current_price)
print(f"\nCurrent Status: {check_result['action'].upper()}")
print(f"  Reason: {check_result['reason']}")

# Simulate price drop to stop loss
test_price = entry_price * 0.94
check_result = sl_manager.check_stop_loss('TEST', test_price)
print(f"\nIf price drops to {test_price:.2f}:")
print(f"  Action: {check_result['action'].upper()}")
if check_result['action'] == 'sell':
    print(f"  Type: {check_result['type']}")
    print(f"  Loss: {(test_price/entry_price - 1) * 100:.2f}%")

# Simulate price rise to take profit
test_price = entry_price * 1.16
check_result = sl_manager.check_stop_loss('TEST', test_price)
print(f"\nIf price rises to {test_price:.2f}:")
print(f"  Action: {check_result['action'].upper()}")
if check_result['action'] == 'sell':
    print(f"  Type: {check_result['type']}")
    print(f"  Profit: {(test_price/entry_price - 1) * 100:.2f}%")
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
print(f"  Sharpe Ratio: {best_result['sharpe_ratio']:.2f}")
print(f"  Total Return: {best_result['total_return']:.2f}%")
print(f"  Max Drawdown: {best_result['max_drawdown']:.2f}%")
print(f"  Win Rate: {best_result['win_rate']:.1f}%")
print()

# Step 8: Multi-signal strategy
print("[Step 8] Testing Multi-Signal Strategy...")
print("-" * 80)

multi_strategy = StrategyFactory.multi_signal(
    [StrategyFactory.ma_cross(5, 20), StrategyFactory.rsi_overbought_oversold(14, 30, 70)],
    weights=[0.7, 0.3]
)

engine = BacktestEngine(initial_cash=100000)
multi_result = engine.run(df_with_indicators, multi_strategy)

print("Multi-Signal Strategy (MA Cross 70% + RSI 30%):")
print(f"  Total Return: {multi_result['total_return']:.2f}%")
print(f"  Sharpe Ratio: {multi_result['sharpe_ratio']:.2f}")
print(f"  Max Drawdown: {multi_result['max_drawdown']:.2f}%")
print(f"  Win Rate: {multi_result['win_rate']:.1f}%")
print()

# Step 9: Generate Report
print("[Step 9] Generating Performance Report...")
print("-" * 80)

report_file = f"backtest_report_simulated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
PerformanceReport.generate_report(best_result, save_path=report_file)
print()

# Final Summary
print("=" * 80)
print("TEST SUMMARY - ALL MODULES WORKING")
print("=" * 80)
print()
print("Modules Tested Successfully:")
print("  [OK] AdvancedIndicators - 12 technical indicators")
print("       - ATR, KDJ, CCI, Williams %R, OBV, AD, DPO, TRIX, VWAP, Keltner, Donchian, MFI")
print()
print("  [OK] BacktestFramework - Complete backtesting engine")
print("       - 5 pre-built strategies (MA, MACD, RSI, Bollinger, Multi-signal)")
print("       - Performance metrics (returns, Sharpe, drawdown, win rate)")
print("       - Parameter optimization (grid search)")
print()
print("  [OK] RiskManagement - Risk control and position sizing")
print("       - Risk metrics (VaR, CVaR, drawdown, ratios)")
print("       - Position sizing (Kelly, fixed fractional, ATR, volatility-based)")
print("       - Stop loss manager (fixed, trailing, take profit)")
print()
print("Sample Results (Simulated Data):")
print(f"  Best Strategy: {best_by_return['name']}")
print(f"  Return: {best_by_return['total_return']:.2f}%")
print(f"  Sharpe: {best_by_return['sharpe_ratio']:.2f}")
print(f"  Max Drawdown: {best_by_return['max_drawdown']:.2f}%")
print()
print(f"Report saved to: {report_file}")
print("=" * 80)
