# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A-share (Chinese stock market) quantitative analysis framework — a 7-stage pipeline: data acquisition → technical indicators → pattern recognition → scoring → risk assessment → backtesting → position sizing.

**Disclaimer:** Algorithms produce reference signals only; this is a test project, not investment advice.

## Verified Entry Points

The previous version of this file referenced `quant_analysis_workflow.py` and `stock_selector_100.py` at the repository root, but **those files do not exist there**. The real entry points are:

| Purpose | Path |
|---|---|
| 7-stage workflow orchestrator | `.claude/skills/quant_workflow.py` (`QuantWorkflow` class) |
| Streamlit web app (entry script) | `run_web_app.py` (root) → `.claude/skills/web_app.py` |
| Flask backtest web UI | `web_backtest.py` (root) — `http://localhost:5000` |
| Stock picking | `.claude/skills/stock_selector.py`, `.claude/skills/long_term_selector.py` |
| Position analysis | `.claude/skills/position_analyzer.py` |
| One-off analysis scripts | `temp/` directory (ad-hoc scripts — not part of the core framework) |

`temp/` contains throwaway scripts and a copy of `quant_analysis_workflow.py` for reference; treat it as scratch space, not a load-bearing module.

## Common Commands

```bash
# Install dependencies (core only)
pip install pandas numpy akshare matplotlib
# Optional but recommended
pip install streamlit redis psycopg2-binary scikit-learn scipy
# Web stack
pip install -r web_requirements.txt

# Run Streamlit app (port 8501)
python run_web_app.py
# or directly
streamlit run .claude/skills/web_app.py

# Run Flask backtest UI (port 5000)
python web_backtest.py

# Run all tests
python -m pytest tests/ -v
# Single test file
python -m pytest tests/test_signal_generator.py -v
# Single test by name pattern
python -m pytest tests/ -v -k "test_buy_signal"
# With coverage
python -m pytest --cov=.claude/skills --cov-report=term

# Direct usage from CLI
python -c "from stock_data_fetcher import StockDataFetcher; f=StockDataFetcher(); print(f.get_quote_data('600519', days=120).tail())"
```

Pytest is configured via `pytest.ini` with `pythonpath = .` and `testpaths = tests/`, so modules under `.claude/skills/` import directly by filename (e.g. `from stock_data_fetcher import StockDataFetcher` — no package prefix).

## Module Layout (`.claude/skills/`)

All core modules live flat in `.claude/skills/`. The framework imports them by bare filename (relies on `sys.path` / `pythonpath = .`), **not** as a package — there is no `__init__.py`.

**Data layer**
- `stock_data_fetcher.py` — historical quotes via akshare + Tencent API; cache in `stock_data/quotes/`
- `concurrent_fetcher.py` — multi-threaded fetcher (10x speedup)
- `cache_manager.py` — Redis cache with 7 strategies; degrades without Redis
- `database_manager.py` — PostgreSQL persistence (6 tables, optional)
- `realtime_quote.py` — Tencent real-time quotes
- `stock_list_manager.py` / `stock_list.csv` — A-share universe

**Analysis layer**
- `technical_analyzer.py` — MA, MACD, KDJ, RSI (base indicators)
- `advanced_indicators.py` — Bollinger, ATR, Ichimoku, etc.
- `trend_indicators.py` — trend detection helpers
- `pattern_recognition.py` — `CandlestickPatterns`, `PricePatterns` (support/resistance)
- `signal_generator.py` — 7 signal types, 100-point scoring
- `multi_factor_selection.py` — 5 factor categories + effectiveness tests
- `ml_predictor.py` — scikit-learn based prediction (optional dep)
- `market_regime_classifier.py` — bull/bear/sideways classification

**Trading layer**
- `backtest_framework.py` — `BacktestEngine` with multiple built-in strategies
- `vectorized_backtest.py` / `multi_stock_backtester.py` — faster batch backtests
- `reversal_backtest.py` / `reversal_detector.py` — reversal-based strategies
- `portfolio_manager.py` — no cash cap; tracks positions + P/L
- `risk_management.py` — `RiskMetrics` (VaR, Sharpe, max DD), `PositionSizing` (Kelly / fixed-ratio / ATR), `StopLossManager`
- `strategy_optimizer.py` — parameter optimization (3 algorithms)
- `historical_data_manager.py` / `historical_backtest_validator.py` — backtest over real history

**Output / display**
- `chart_visualizer.py` — 8 chart types (candlestick, multi-chart layout)
- `web_app.py` — Streamlit 5-page UI (dashboard, analysis, backtest, portfolio, monitor)
- `daily_signal_generator.py` — batch signal generation
- `real_time_monitor.py` — 8 alert types, custom callbacks

**Orchestration / utilities**
- `quant_workflow.py` — `QuantWorkflow` class wires all 7 stages end-to-end
- `position_analyzer.py` — analyzes an existing portfolio CSV
- `parameter_space.py` / `optimization_config.py` / `optimization_engine.py` — optuna-style search
- `cache_manager.py`, `concurrent_fetcher.py` — perf infra

## 7-Stage Pipeline (in `quant_workflow.py`)

1. **Data acquisition** — `stock_data_fetcher.StockDataFetcher.get_quote_data(code, days)` returns OHLCV DataFrame; CSVs cached at `stock_data/quotes/{code}.csv`
2. **Indicators** — `technical_analyzer.TechnicalAnalyzer.add_all_indicators(df)` produces 30+ columns
3. **Patterns** — `pattern_recognition.CandlestickPatterns` + `PricePatterns` annotate the DataFrame
4. **Scoring** — `signal_generator.SignalGenerator.generate_signals(df)` → 7 binary signals + composite score
5. **Risk** — `risk_management.RiskMetrics.compute_all(df)` → VaR, Sharpe, max drawdown
6. **Backtest** — `backtest_framework.BacktestEngine.run(df, strategy_fn)` where `strategy_fn(df) -> {-1, 0, 1}`
7. **Sizing** — `risk_management.PositionSizing.kelly(...)` / `fixed_ratio(...)` / `atr_based(...)`

## Key Conventions

- **Stock codes:** 6-digit string, exchange-prefixed when fetched: `sh600036` (Shanghai) or `sz000001` (Shenzhen). Pass to user-facing functions without prefix (`'600036'`); the prefix is added inside `StockDataFetcher`.
- **CSV inputs:** stock lists use `股票代码,股票名称` (Chinese headers) or `code,name` (English). Both are accepted by `stock_list_manager`.
- **Cache layout:** `stock_data/quotes/{code}.csv` (historical), `stock_data/` also holds `portfolio_data/`, `backtest_results/`, `test_charts/`.
- **Date handling:** all data uses `pd.Timestamp`; default lookback is 252 trading days (~1 year).
- **Strategy signature:** `def strategy(data: pd.DataFrame) -> int` returning `1` (buy), `-1` (sell), `0` (hold). Latest row is `data.iloc[-1]`.
- **Graceful degradation:** every module that touches an optional dep (Redis, PostgreSQL, sklearn, scipy, streamlit) wraps imports in try/except and falls back to a no-op or local equivalent — missing optional deps should never crash imports.
- **Language:** docstrings, comments, and UI strings are mixed Chinese/English; the README, signals, and report files are primarily Chinese.

## Test Layout

- Root: `test_signal_generator.py` (legacy single-file test)
- `tests/` — pytest suite, 20+ files. Use `python -m pytest tests/ -v` (config in `pytest.ini`).
- Markers defined: `unit`, `integration`, `slow`, `data` (apply via `@pytest.mark.integration` etc.).
- Integration tests (`test_integration.py`, `test_new_modules*.py`) are known to skip when optional deps are absent — this is expected, not a failure.
- Some `test_*.py` files in the repo root and `tests/` are scheduled for deletion (currently in the ` D ` state per `git status`); safe to drop on sight.

## Settings / Hooks

- `.claude/settings.json` and `.claude/settings.local.json` define `permissions.allow` for: `python`, `pip install`, `dir`, `ls`, `powershell`, `netstat`, `findstr`, `git push`, and the specific Streamlit launch command for the web app. Bash commands outside this allowlist will prompt.
- Pre-approved command: `Bash(timeout 10 streamlit run .claude/skills/web_app.py --server.headless true --server.port 8501)`.

## Dependencies Summary

| Category | Package | Required? |
|---|---|---|
| Core | `pandas`, `numpy`, `akshare`, `matplotlib` | yes |
| Web | `streamlit`, `altair`, `plotly` | for `web_app.py` only |
| Persistence | `redis`, `psycopg2-binary`, `SQLAlchemy` | optional |
| ML/Opt | `scikit-learn`, `scipy` | optional |

Pinned versions in `web_requirements.txt`; framework imports succeed even if all optional deps are missing.

## Documentation Map

- `README.md` — primary entry, v2.0 module index
- `QUICK_START_GUIDE.md` — 5-minute onboarding
- `API_REFERENCE_V2.md` / `API_REFERENCE.md` — full API
- `USER_MANUAL_V2.md` / `USAGE_EXAMPLES.md` — recipes
- `DEPLOYMENT_GUIDE.md` — install + ops
- `FAQ.md` — common questions
- `CHANGELOG.md` — version history
- `SKILLS_DEVELOPMENT_SUMMARY.md` / `MARCH_COMPLETION_REPORT.md` — design rationale
- Per-skill docs: `.claude/skills/SKILL.md`, `.claude/skills/USER_GUIDE.md`, `.claude/skills/ROADMAP.md`

## Important Notes for Future Sessions

- **Don't trust the old CLAUDE.md entry points** — they were stale; only the paths in the table above are real.
- The repo contains parallel copies of some skills under `optimization_package/skills/` and `stock-*-skills/` directories — these are packaging artifacts, not sources of truth. Edit files in `.claude/skills/`.
- Ad-hoc analysis scripts in `temp/` are scratch work; the user expects them to come and go.
- Cache files under `stock_data/quotes/` are safe to delete to force a refetch; tests do not depend on them.
- When adding a new skill module, follow the bare-filename import pattern (no package); add it to `.claude/skills/`, then register it in the `QuantWorkflow` class in `quant_workflow.py`.
