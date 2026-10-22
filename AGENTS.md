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

- `core/indicators.py` — authoritative `rsi()` (Cutler SMA; 0-div: no-loss→100, no-movement→50) and `atr()`/`true_range()` (Wilder RMA, alpha=1/period). **All** RSI and ATR computations across the repo route through it (RSI: 13 sites incl. chart_visualizer/ml_predictor/reversal_backtest/strategy_optimizer; ATR: 8 sites incl. pattern_recognition's single-bar-TR bug). **Do not write a new local RSI or ATR.**
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

- `tests/` is tracked; `pytest.ini` `testpaths = tests`. **217 offline tests** (216 pass + 1 skip without pyarrow): honesty suite (engines A/B/D/E + web routes), core metric/RSI/ATR unification, data-layer P0 (FetchResult/failure counting/stale warnings + caller migration), regime classifier, SKILL.md API honesty, ML time-series split, stage1/stage2 fix regressions, execution model, risk wiring (项 20), reversal rules unification + reproducibility (C-P1-13/15/17), 7-module e2e regression (C-P2-19), optimizer seed/repair reproducibility + point-in-time 财务契约 (E-P0-3/4, C-P0-7), realtime quote content-matching (A-P1-4), B-report P2 batch (position_analyzer days 透传, price_position 语义, EMA20/MACD_Hist 列契约, OBV 向量化, scan_all_patterns 向量化 + 形态函数 dict 统一; `tests/test_b_report_p2.py`).
- Golden-metric snapshots live in `tests/test_backtest_honesty.py::TestGoldenMetrics` (seed=3, n=300). If they drift, suspect a backtest-logic change first; update snapshots only with justification.
- Root-level `test_*.py` files are legacy ad-hoc scripts (network-hitting); not part of the suite.

## Audit fix status (vs `skills-quant-framework-analysis-extracted/analysis/`, baseline `14b2f59`)

Fixed (commits `34e6a41`→`HEAD`): pattern-recognition layer, Flask duplicate route, optional-dep guards, `strategy_optimizer` executability, `signal_generator` pandas≥3 + tier signals, 4-engine t+1 fills + costs + limit-up/down (`execution_model.py`), ml_predictor time-series split, `database_manager:667` precedence, RSI/profit-factor/MDD unification (`core/`), walk-forward IS/OOS (`param_space` arg), Chikou lookahead, MACD true-cross, cache key `days` dimension, `batch_save_stock_quotes` symbol param, `FetchResult` type + `get_quote_result` (项 11), `concurrent_fetcher` empty-data counts as failed, `historical_data_manager` API failure warns (no silent stale-as-fresh), `optimization_engine.load_data` raises on 0 loaded (no more false "[OK] 成功加载 0 只"), `market_regime_classifier` trend thresholds live + min_segment hysteresis + adaptive first-year NaN fix, ATR 4-way divergence → core Wilder (incl. `pattern_recognition` single-bar-TR bug + `keltner_channel` ATR overwrite guard), remaining 8 RSI sites → core, realtime quote 成交额 万元→元 + 日期/时间字段语义, fallback `adjust`/volume-unit alignment, `FitnessConfig.w_*` wired into `FitnessEvaluator` (项 19), `SKILL.md` rewritten against real API (P0-7), FetchResult caller migration (technical_analyzer/position_analyzer/quant_workflow/web_app/real_time_monitor/multi_stock_backtester/cache_manager warm_up surface failure reasons + skip counts), risk wiring into order path (项 20: `PortfolioManager` 集中度/现金闸门阻断下单 + rebalance 超限阻断 + `StopLossManager`/`PortfolioRiskMonitor` 接线 + HHI 双刻度统一; `vectorized_backtest` `max_position_pct` clamp (默认1.0不改黄金快照); `PositionConfig` 无上限警告 + 工厂配置显式约束), `reversal_rules.py` 单一真相源统一实盘/回测反转规则 (C-P1-13: 阈值/背离窗口/判定闸门互斥一致, 回测补齐 RSI24/Vol_MA20/ROC/ATR/趋势衰竭, 删自比较死代码块), 可复现性种子+manifest 落盘 (C-P1-15), 死代码删除 (C-P1-17: MFS `technical_factor`、SS `min_market_cap` 空分支、DSG `top_n` 参数、SG `middle` 变量; `--top` CLI 接通 `format_report`), 7 模块端到端回归 (C-P2-19: 输出结构契约 + 点时截断无未来函数 + 训练/测试无重叠, `tests/test_e2e_regression.py`), 优化器可复现 (E-P0-3/4: `OptimizationEngine(seed=)` 按阶段派生独立子流、CLI `--seed` 默认42、`save_results` 落盘 seed/适应度权重/参数空间指纹/数据起止/GA 运行元数据; GA 初始种群/交叉变异子代/最优解全部 `ParameterSpace.repair` + validate 断言), 财务 point-in-time 止血契约 (C-P0-7: MFS `select_stocks`/`multi_factor_select` 强制『公告日』列 + `as_of` 参数, 缺列即 `ValueError`, 按公告日≤as_of 过滤且 NaT 剔除, `filter_point_in_time` 单一入口), 杂项清扫批次 (F-P1/F-P2/A-P1-4/A-P2-6: 删零引用死模板 `templates/backtest_ui.html`; `web_app.py` sys.path 改 `__file__` 基准 + 导入失败显式错误页含完整 traceback (st.stop), 不再静默降级; 根目录 29 篇遗留报告/手册 `git mv` 进 `docs/` 只留 8 篇入口文档并修链接; `stock_data_fetcher` 历史行情文档"腾讯接口"订正为新浪源 `stock_zh_a_daily` (腾讯仅实时行情), CLAUDE/README 移除无支撑的"10倍性能"宣称并标注 database_manager/concurrent_fetcher/realtime_quote 无生产调用方; `realtime_quote.get_quotes` 行号下标 → 按内容 `v_(\w{6})=` 正则匹配, 修缺行全体错位), B-report P2 批次 (审计 #9-14: `position_analyzer.analyze_position` `days` 参数透传修复 (便捷函数+类方法双层, 原静默失效恒 120); `pattern_recognition.analyze_patterns` `price_position` 改取价格下方最近支撑/上方最近压力 (修 vs_resistance=-30.9% 荒谬负值, 新增 nearest_support/nearest_resistance 字段); 列名契约统一 (technical_analyzer 补 `MACD_Hist` 产出 + `EMA20` 别名, position_analyzer 补 `MACD_Hist`, chart_visualizer 两处读取兜底缺列); `advanced_indicators.obv` O(n) 循环 → numpy cumsum 向量化 (首元素语义保留); `pattern_recognition.scan_all_patterns` 逐行 .loc O(n²) → 单次 numpy 向量化 (与逐条形态函数逐行等价断言), 5 个形态函数 (is_doji/is_morning_star/is_evening_star/is_piercing/is_dark_cloud) 返回类型统一 dict; trend_indicators 删 5 个 0 调用方孤儿 (adaptive_ma/KAMA, mcginley_dynamic, triple_screen, abands, all_trend_indicators, 连带清理 _core_* import); advanced_indicators.calculate_all 默认列表补 mass_index; `docs/skills_layers.md` 分层架构文档 (C-P2-16: L1 选股/L2 择时/信号层边界 + 列名契约 + 变更守则, README 文档导航接入)).

Still open (see audit): suspension modeling, `adjust` 落库维度 + 既有数据清洗 (单位修复已落代码, 历史 parquet 未清洗), island-module decisions (项 15), 3-way stock-selection unification (项 21, 用户决定暂缓), hardcoded `持仓.csv` paths in `web_backtest.py` (upstream file not present locally), `technical_analyzer` signals lack shift(1) protection (advisory-only, documented), MFS momentum/volatility 恒NaN + 因子权重配置失效 (C-P0-4/5, 归项 21 批次).

## `.gitignore` gotchas

- `*.csv` ignored **except** `!.claude/skills/stock_list.csv` (tracked, 5523 rows).
- `tests/` and `test_*.py` have negation patterns (`!tests/`, `!tests/test_*.py`) so the real suite is tracked. Root-level legacy `test_*.py` remain ignored.
- `*.txt` ignored except `requirements.txt` and `web_requirements.txt`.

## Architecture docs

- `skills-quant-framework-analysis-extracted/analysis/` — external deep audit (7 Chinese MD reports) against upstream `14b2f59`. Claims about files present locally are accurate as of that baseline; many have since been fixed — see "Audit fix status" above.
- Root keeps only 8 entry docs (`README` / `CLAUDE` / `AGENTS` / `CHANGELOG` / `QUICK_START_GUIDE` / `API_REFERENCE*` / `DEPLOYMENT_GUIDE`); 29 legacy reports/manuals moved to `docs/` (audit F-P2 — links from entry docs now use `docs/` prefix). `README.md` is the entry point.
