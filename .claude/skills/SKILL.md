---
name: stock-visualization
description: Stock chart visualization for Chinese markets with candlestick charts, technical indicators, and multi-chart layouts. Use when needing to visualize stock price patterns, display technical indicators, create comparison charts, or generate analysis reports for A-share stocks.
---

# Stock Visualization

Comprehensive chart generation for Chinese stock analysis (`chart_visualizer.py`).

## Quick Start

Run from the repo root (imports rely on repo-relative paths):

```python
import sys
sys.path.append('.claude/skills')

import pandas as pd
from chart_visualizer import ChartVisualizer

# 所有 plot_* 方法接收 DataFrame (列: 日期/开盘/最高/最低/收盘/成交量),
# 不自己拉数据 — 先用 StockDataFetcher.get_quote_data(symbol) 取数:
# from stock_data_fetcher import StockDataFetcher
# data = StockDataFetcher().get_quote_data('600519', days=120)

visualizer = ChartVisualizer()
visualizer.plot_candlestick(data, symbol='600519', save_path='chart.png')
```

## Chart Types

### Candlestick Chart

```python
visualizer.plot_candlestick(
    data,                      # OHLCV DataFrame
    symbol='600519',
    title=None,                # 默认自动生成
    ma_periods=[5, 10, 20, 60],  # 均线周期列表, None 用默认
    save_path='candlestick.png'
)
```

### MACD Chart

```python
visualizer.plot_macd(data, symbol='600519', save_path='macd.png')
# data 需含 MACD/MACD_Signal/MACD_Hist 列
# (technical_analyzer._calculate_indicators 或 stock_data_fetcher.add_technical_indicators 可生成)
```

### RSI Chart

```python
visualizer.plot_rsi(
    data,
    symbol='600519',
    period=14,
    oversold=30,
    overbought=70,
    save_path='rsi.png'
)
```

### Bollinger Bands

```python
visualizer.plot_bollinger_bands(
    data, symbol='600519',
    period=20, std=2,
    save_path='bollinger.png'
)
```

### Combined Analysis (multi-panel)

KDJ、RSI、成交量等内联在此图中 — 没有独立的 KDJ 绘图方法:

```python
visualizer.plot_combined_analysis(data, symbol='600519', save_path='combined.png')
```

### Signals Overlay

```python
visualizer.plot_signals(
    data,                      # OHLCV DataFrame
    signals,                   # 含买卖信号标注的 DataFrame
    symbol='600519',
    save_path='signals.png'
)
```

## Backtest Charts

```python
# equity_curve: 含 date 与 value 列的 DataFrame
visualizer.plot_equity_curve(
    equity_curve, symbol='组合A',
    benchmark_return=10.0,     # 基准收益率(%), 可选
    save_path='equity_curve.png'
)

visualizer.plot_drawdown(equity_curve, symbol='组合A', save_path='drawdown.png')
```

## Convenience Function

```python
from chart_visualizer import plot_stock_chart

plot_stock_chart(
    data, symbol='600519',
    chart_type='candlestick',  # candlestick/macd/rsi/bollinger/equity/drawdown/signals/combined
    save_dir='charts'
)
```

## Styling

样式通过 `ChartStyle` 对象传入 (不接受样式名字符串):

```python
from chart_visualizer import ChartVisualizer, ChartStyle

style = ChartStyle()
style.figure_size = (14, 8)
style.dpi = 100
# 可改: up_color/down_color/bg_color/grid_color/text_color/font_family/...

visualizer = ChartVisualizer(style=style, output_dir='charts')
```
