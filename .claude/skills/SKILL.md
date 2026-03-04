---
name: stock-visualization
description: Stock chart visualization for Chinese markets with candlestick charts, technical indicators, and multi-chart layouts. Use when needing to visualize stock price patterns, display technical indicators, create comparison charts, or generate analysis reports for A-share stocks.
---

# Stock Visualization

Comprehensive chart generation for Chinese stock analysis.

## Quick Start

```python
import sys
sys.path.append('F:/Users/shiyo/80.soft_dev/Stocks/.claude/skills')
from chart_visualizer import ChartVisualizer

visualizer = ChartVisualizer()
visualizer.plot_candlestick('600519', days=120, save_path='chart.png')
```

## Chart Types

### Candlestick Chart

```python
visualizer.plot_candlestick(
    symbol='600519',
    days=120,
    show_ma=True,      # Show moving averages
    show_volume=True,  # Show volume
    save_path='candlestick.png'
)
```

### MACD Chart

```python
visualizer.plot_macd(
    symbol='600519',
    days=120,
    save_path='macd.png'
)
```

### KDJ Chart

```python
visualizer.plot_kdj(
    symbol='600519',
    days=120,
    save_path='kdj.png'
)
```

### Combined Chart

```python
visualizer.plot_combined(
    symbol='600519',
    days=120,
    indicators=['ma', 'macd', 'volume'],
    save_path='combined.png'
)
```

## Multi-Stock Comparison

```python
# Compare multiple stocks
symbols = ['600519', '000858', '002415']
visualizer.plot_comparison(
    symbols=symbols,
    days=120,
    normalize=True,    # Normalize to percentage
    save_path='comparison.png'
)
```

## Equity Curve

```python
# For backtest results
equity_data = backtest_result['equity_curve']
visualizer.plot_equity_curve(
    equity_data=equity_data,
    save_path='equity_curve.png'
)
```

## Custom Styling

```python
visualizer = ChartVisualizer(
    style='dark',        # 'dark' or 'light'
    figsize=(14, 8),
    dpi=100
)
```

See [chart_types.md](references/chart_types.md) for all available chart options and styling.
