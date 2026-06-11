# Stock Analysis Skills Library

Comprehensive Claude skills library for Chinese A-share stock market quantitative analysis.

## Overview

This library provides a complete framework for analyzing Chinese stocks, including data fetching, technical analysis, stock screening, position management, backtesting, and visualization.

## Skills Included

### Main Entry Point
- **stock-analysis** - Unified entry point for all stock analysis tasks

### Specialized Skills
- **stock-data-fetcher** - Real-time and historical data fetching
- **stock-technical-analysis** - Technical indicators and pattern recognition
- **stock-selection** - Multi-factor stock screening
- **stock-position-analysis** - Position and portfolio analysis
- **stock-backtesting** - Strategy backtesting and optimization
- **stock-visualization** - Chart generation and visualization

## Installation

### Option 1: Install Individual Skills

```bash
# Install main skill
claude skills install stock-analysis-skills/stock-analysis/

# Install specialized skills as needed
claude skills install stock-analysis-skills/stock-data-fetcher/
claude skills install stock-analysis-skills/stock-technical-analysis/
```

### Option 2: Install All Skills

```bash
# From the stock-analysis-skills directory
for skill in stock-analysis stock-data-fetcher stock-technical-analysis stock-selection stock-position-analysis stock-backtesting stock-visualization; do
    claude skills install $skill/
done
```

## Quick Start

### Analyze a Single Stock

```
Use the stock-analysis skill to analyze stock 600519
```

### Screen Stock Pool

```
Use stock-selection to filter stocks from my stock pool with minimum score 60
```

### Check Position P&L

```
Use stock-position-analysis to analyze my portfolio
```

## Skill Dependencies

```
stock-analysis (main)
├── stock-data-fetcher
├── stock-technical-analysis
├── stock-selection
├── stock-position-analysis
├── stock-backtesting
└── stock-visualization
```

## Python Requirements

```
pandas>=1.5.0
numpy>=1.23.0
akshare>=1.9.0
matplotlib>=3.6.0
```

Optional:
```
streamlit>=1.28.0  # For web interface
redis>=4.5.0       # For caching
```

## File Structure

```
stock-analysis-skills/
├── README.md
├── stock-analysis/
│   ├── SKILL.md
│   └── references/
│       ├── workflows.md
│       └── api_reference.md
├── stock-data-fetcher/
│   ├── SKILL.md
│   └── references/
│       └── data_sources.md
├── stock-technical-analysis/
│   ├── SKILL.md
│   └── references/
│       └── indicators.md
├── stock-selection/
│   ├── SKILL.md
│   └── references/
│       └── selection_criteria.md
├── stock-position-analysis/
│   ├── SKILL.md
│   └── references/
│       └── portfolio_management.md
├── stock-backtesting/
│   ├── SKILL.md
│   └── references/
│       └── strategies.md
└── stock-visualization/
    ├── SKILL.md
    └── references/
        └── chart_types.md
```

## Version

v1.0.0 - Initial release

## License

MIT License
