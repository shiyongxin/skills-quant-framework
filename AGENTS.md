# AGENTS.md

## What this is

Chinese A-share quantitative analysis framework ("Skills 股票量化分析框架" v2.0). ~27k LOC Python. Built as a Claude Code skills collection — not a conventional installable package. Disclaimer in README: test project, not production advice.

## Two parallel systems (do not confuse them)

1. **`.claude/skills/`** — main analysis chain (38 modules). Entry: `quant_workflow.py` (facade), `web_app.py` (Streamlit), `signal_generator.py`, `technical_analyzer.py`.
2. **`optimization_package/optimization_package/`** — standalone GA optimization pipeline (17 modules, Parquet-based). Has its own `run_optimize.py`, `fetch_data.py`, `pack.py`. Shares ~8 copied files with `.claude/skills/` that have **diverged** (e.g. different realtime-quote impl, signal thresholds). Edit one → check the other.

`optimization_package/` is **gitignored**. Do not commit it.

## How modules import each other

Modules import each other by **bare module name** (`from stock_data_fetcher import StockDataFetcher`), relying on `sys.path.append('.')` or `sys.path.append('.claude/skills')` hacks. **Always run scripts from the repo root.** Running from any other directory breaks all intra-project imports.

`pytest.ini` has `pythonpath = .` but does **not** include `.claude/skills/` — pytest cannot import skill modules as-is.

## Running things

```bash
# Web app (Streamlit, port 8501)
python run_web_app.py

# Typical script usage — must be from repo root
python -c "import sys; sys.path.insert(0, '.claude/skills'); from stock_data_fetcher import StockDataFetcher; ..."
```

No lint/typecheck/CI config exists. No pre-commit.

## Dependencies

- Core: `pandas numpy akshare matplotlib pyarrow`
- Optional: `streamlit redis psycopg2-binary SQLAlchemy scikit-learn scipy` (see `web_requirements.txt`)
- Several modules use `_AVAILABLE` / `MODULES_AVAILABLE` guards for optional deps, but **the guards are buggy** — multiple imports bundled in one try block means a missing optional dep can cascade into `NameError` for unrelated symbols (e.g. `concurrent_fetcher` → `NameError: CacheManager`). See analysis docs.

## Testing

- `pytest.ini` points to `testpaths = tests` — **the `tests/` directory does not exist**. `pytest` discovers nothing.
- Root-level `test_*.py` files are ad-hoc manual scripts, not a real suite. Only `test_portfolio_manager.py` has genuine `def test_*` functions with asserts.
- `test_signal_generator.py`, `test_tool.py` hit the network via akshare — not offline-safe.

## Critical known bugs (verified in source, see `skills-quant-framework-analysis-extracted/` for full audit)

- `pattern_recognition.py:65` — `high = row['最低']` (self-commented as wrong). Entire pattern recognition layer silently returns empty.
- `technical_analyzer.py:242` — matches `'latest' in col` but `scan_all_patterns` produces `Pattern_*` columns. K-line pattern list is always empty.
- `strategy_optimizer.py:280-284` — passes `PositionConfig(max_positions=..., position_size_pct=...)`; those fields don't exist (real: `sizing_method/sizing_value/max_position_pct`). Also calls `engine.run_backtest()` but the method is `run()`. All 5 strategy grids are non-executable.
- `signal_generator.py` — 8 `fillna()` calls are dead code (target values have no NaN). Also breaks on pandas ≥ 3 (`TypeError: Invalid value '0.5' for dtype 'int64'`).
- `database_manager.py:667` — operator precedence bug: `(current_price or avg_cost - avg_cost) * shares`.
- All 4 backtest engines use same-bar signal + same-bar fill (look-ahead bias). No stamp duty, transfer fee, limit-up/down, or suspension constraints anywhere.
- Multiple RSI implementations with divergent zero-division handling (`technical_analyzer.py:104` uses `fill_value=100`; `vectorized_backtest.py:162` uses `replace(0, np.nan)`). Numbers are **not comparable across modules**.

## `.gitignore` gotchas

- `*.csv` is ignored (no exceptions for data files). `stock_list.csv` exists locally at `.claude/skills/stock_list.csv` but is **not tracked by git**. A fresh clone will not have it — code that reads it will silently get an empty stock list.
- `*.txt` is ignored except `requirements.txt` and `web_requirements.txt`.
- `tests/`, `test_*.py` are gitignored per the analysis (though root-level test scripts exist untracked).

## Architecture docs

- `skills-quant-framework-analysis-extracted/analysis/` — external deep audit (7 Chinese MD reports). References a **larger upstream snapshot** (`14b2f59`) that includes files not present locally (`web_backtest.py`, `historical_backtest_validator.py`, `templates/`, `CLAUDE.md`). Treat audit claims about those files as not applicable to this repo state. Claims about files that *do* exist locally are verified accurate.
- Root has 34+ Chinese MD docs (dev reports, API refs, user manuals). `README.md` is the entry point.
