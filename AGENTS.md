# AGENTS.md

## What this is

Chinese A-share quantitative analysis framework ("Skills 股票量化分析框架" v2.0). ~27k LOC Python. Built as a Claude Code skills collection — not a conventional installable package. Disclaimer in README: test project, not production advice.

## Two parallel systems (do not confuse them)

1. **`.claude/skills/`** — main analysis chain (38+ modules + `core/`). Entry: `quant_workflow.py` (facade), `web_app.py` (Streamlit), `signal_generator.py`, `technical_analyzer.py`.
2. **`optimization_package/optimization_package/`** — standalone GA optimization pipeline (17 modules, Parquet-based). Has its own `run_optimize.py`, `fetch_data.py`, `pack.py`. Shares ~8 copied files with `.claude/skills/` that have **diverged** (e.g. different realtime-quote impl, signal thresholds). Edit one → check the other.

`optimization_package/` is **gitignored**. Do not commit it.

## How modules import each other

Modules import each other by **bare module name** (`from stock_data_fetcher import StockDataFetcher`), relying on `sys.path.append('.')` or `sys.path.append('.claude/skills')` hacks. **Always run scripts from the repo root.** Running from any other directory breaks all intra-project imports.

`pytest.ini` has `pythonpath = . .claude/skills`, so pytest imports skill modules directly.

## Single source of truth (`core/`, audit roadmap items 8/9)

- `core/indicators.py` — authoritative `rsi()` (Cutler SMA; 0-div: no-loss→100, no-movement→50). All 5 former RSI implementations (`technical_analyzer`, `position_analyzer`, `daily_signal_generator`, `reversal_detector`, `vectorized_backtest`) call it. **Do not write a new local RSI.**
- `core/metrics.py` — `profit_factor` (sum-of-pnls formula), `max_drawdown_pct` (**positive** magnitude), `sharpe_ratio` (decimal returns, rf=0.03, ddof=1). Engines A (`backtest_framework`), B (`vectorized_backtest`) and `optimization_engine` all route through it. B's MDD/Sharpe use a daily mark-to-market equity curve (trade spans), not the per-trade compounding curve.
- `core/fetch_result.py` — `FetchResult{ok, data, error, source, as_of}` (项 11). New data-path code should return it (see `stock_data_fetcher.get_quote_result`); failures must set `ok=False` + `error`, never silently return an empty DF.

## Running things

```bash
# Web app (Streamlit, port 8501)
python run_web_app.py

# Test suite (offline, from repo root)
python3 -m pytest tests/ -q
```

No lint/typecheck/CI config exists. No pre-commit.

## Dependencies

- Core: `pandas numpy akshare matplotlib pyarrow`
- Optional: `streamlit redis psycopg2-binary SQLAlchemy scikit-learn scipy flask` (see `web_requirements.txt`)
- Optional-dep guards (`_AVAILABLE` / `MODULES_AVAILABLE`): `concurrent_fetcher` now uses **separate try blocks** per import (fixed); keep that pattern for new guards. `database_manager` still requires sqlalchemy (guarded, import-safe without it).

## Testing

- `tests/` is tracked; `pytest.ini` `testpaths = tests`. **105 offline tests** (no network): honesty suite (engines A/B/D/E + web routes), core metric/RSI unification, data-layer P0 (FetchResult/failure counting/stale warnings), regime classifier, ML time-series split, stage1/stage2 fix regressions, execution model.
- Golden-metric snapshots live in `tests/test_backtest_honesty.py::TestGoldenMetrics` (seed=3, n=300). If they drift, suspect a backtest-logic change first; update snapshots only with justification.
- Root-level `test_*.py` files are legacy ad-hoc scripts (network-hitting); not part of the suite.

## Audit fix status (vs `skills-quant-framework-analysis-extracted/analysis/`, baseline `14b2f59`)

Fixed (commits `34e6a41`→`HEAD`): pattern-recognition layer, Flask duplicate route, optional-dep guards, `strategy_optimizer` executability, `signal_generator` pandas≥3 + tier signals, 4-engine t+1 fills + costs + limit-up/down (`execution_model.py`), ml_predictor time-series split, `database_manager:667` precedence, RSI/profit-factor/MDD unification (`core/`), walk-forward IS/OOS (`param_space` arg), Chikou lookahead, MACD true-cross, cache key `days` dimension, `batch_save_stock_quotes` symbol param, `FetchResult` type + `get_quote_result` (项 11), `concurrent_fetcher` empty-data counts as failed, `historical_data_manager` API failure warns (no silent stale-as-fresh), `optimization_engine.load_data` raises on 0 loaded (no more false "[OK] 成功加载 0 只"), `market_regime_classifier` trend thresholds live + min_segment hysteresis + adaptive first-year NaN fix.

Still open (see audit): suspension modeling, volume/amount unit unification, `optimization_config.py` w_* dead params, island-module decisions, `risk_management` wiring into order path, 3-way stock-selection unification, `SKILL.md` false method claims (`plot_kdj` etc.), hardcoded `持仓.csv` paths in `web_backtest.py`, ATR 4-way divergence, `technical_analyzer` signals lack shift(1) protection (advisory-only, documented), FetchResult caller migration (10+ call sites still check `len(data)` instead of `result.ok`).

## `.gitignore` gotchas

- `*.csv` ignored **except** `!.claude/skills/stock_list.csv` (tracked, 5523 rows).
- `tests/` and `test_*.py` have negation patterns (`!tests/`, `!tests/test_*.py`) so the real suite is tracked. Root-level legacy `test_*.py` remain ignored.
- `*.txt` ignored except `requirements.txt` and `web_requirements.txt`.

## Architecture docs

- `skills-quant-framework-analysis-extracted/analysis/` — external deep audit (7 Chinese MD reports) against upstream `14b2f59`. Claims about files present locally are accurate as of that baseline; many have since been fixed — see "Audit fix status" above.
- Root has 34+ Chinese MD docs (dev reports, API refs, user manuals). `README.md` is the entry point.
