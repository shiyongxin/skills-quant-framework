# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Chinese stock quantitative analysis framework (量化交易框架). It provides a 7-stage pipeline: data acquisition → technical indicators → pattern recognition → scoring → risk assessment → backtesting → position sizing.

**Primary entry point**: `quant_analysis_workflow.py` contains `QuantAnalysisWorkflow` which orchestrates all stages.

**Skills modules**: All core modules live in `.claude/skills/`

## Common Commands

```bash
# Run full analysis workflow
python quant_analysis_workflow.py --mode portfolio --file 持仓.csv --cash 100000

# Run backtest web interface
python web_backtest.py  # then open http://localhost:5000

# Streamlit web app
python run_web_app.py
# or
streamlit run .claude/skills/web_app.py

# Run tests
python -m pytest tests/ -v
python tests/test_signal_generator.py  # single test file

# Long-term stock selection
python .claude/skills/long_term_selector.py --file 股票列表.csv --top 20

# Random stock picking
python stock_selector_100.py --n 100 --top 15
```

## Architecture

```
.claude/skills/
├── stock_data_fetcher.py    # Data acquisition (akshare + Tencent API)
├── signal_generator.py      # Trading signal generation
├── technical_analyzer.py    # Technical indicators (MA, MACD, KDJ, RSI, etc.)
├── advanced_indicators.py   # Advanced indicators (Bollinger, ATR, Ichimoku)
├── trend_indicators.py      # Trend detection
├── pattern_recognition.py   # Candlestick + price pattern recognition
├── risk_management.py       # Risk metrics, position sizing, stop-loss
├── backtest_framework.py    # Backtesting engine
├── multi_factor_selection.py # Multi-factor stock selection
├── portfolio_manager.py     # Portfolio management
├── realtime_quote.py        # Real-time stock quotes (Tencent API)
├── long_term_selector.py    # Medium/long-term stock selection
├── web_app.py               # Streamlit web interface
└── chart_visualizer.py      # Charting utilities

quant_analysis_workflow.py    # Orchestrates the 7-stage pipeline
web_backtest.py              # Flask-based backtest web UI
stock_selector_100.py         # Random stock picker
```

## Data Flow

The `QuantAnalysisWorkflow` class implements 7 stages:

1. **Data Acquisition** → `stock_data_fetcher.py` (Tencent API via akshare)
2. **Technical Indicators** → `advanced_indicators.py` / `trend_indicators.py` (30+ indicators)
3. **Pattern Recognition** → `pattern_recognition.py` (candlestick + support/resistance)
4. **Scoring** → `signal_generator.py` (100-point scoring system, 7 signal types)
5. **Risk Assessment** → `risk_management.py` (VaR, Sharpe, max drawdown)
6. **Backtesting** → `backtest_framework.py` (multiple built-in strategies)
7. **Position Sizing** → `risk_management.py` (Kelly formula, fixed ratio, ATR-based)

## Dependencies

**Required**: `pandas`, `numpy`, `akshare`, `matplotlib`

**Optional**: `streamlit`, `redis`, `psycopg2-binary`, `scikit-learn`, `scipy` — framework degrades gracefully if missing.

## Key Patterns

- Stock codes use 6-digit format, prefixed with exchange: `sh600036` (Shanghai) or `sz000001` (Shenzhen)
- CSV files for stock lists use columns: `股票代码,股票名称` or `code,name`
- Data cached in `stock_data/quotes/` directory as CSV files
- Test files follow `test_*.py` naming, with unit tests also in `tests/` directory