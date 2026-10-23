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

- Core (顶层 import, 缺失即 ImportError): `pandas numpy scipy akshare` — 分析层清单见 `.claude/skills/requirements.txt` (B-P2; `multi_factor_selection` 顶层 `from scipy import stats`)
- Runtime/guarded: `pyarrow` (historical_data_manager parquet 读写), `matplotlib` (chart_visualizer 绘图, ImportError 守卫降级), `scikit-learn` (ml_predictor, try 守卫)
- Web 层: `streamlit scikit-learn scipy altair plotly` (见 `web_requirements.txt`; `web_app.py` 是 skills 目录中唯一 streamlit 调用方)
- Optional-dep guards (`_AVAILABLE` / `MODULES_AVAILABLE`): use **separate try blocks** per import (pattern set when concurrent_fetcher existed; that module has since been deleted). No remaining sqlalchemy/redis/psycopg2-dependent modules.

## Testing

- `tests/` is tracked; `pytest.ini` `testpaths = tests`. **240 offline tests** (235 pass + 5 skip without pyarrow/matplotlib): honesty suite (engines A/B/D/E + web routes), core metric/RSI/ATR unification, data-layer P0 (FetchResult/failure counting/stale warnings + caller migration), regime classifier, SKILL.md API honesty, ML time-series split, stage1/stage2 fix regressions, execution model, risk wiring (项 20), reversal rules unification + reproducibility (C-P1-13/15/17), 7-module e2e regression (C-P2-19), optimizer seed/repair reproducibility + point-in-time 财务契约 (E-P0-3/4, C-P0-7), realtime quote content-matching (A-P1-4), B-report P2 batch (position_analyzer days 透传, price_position 语义, EMA20/MACD_Hist 列契约, OBV 向量化, scan_all_patterns 向量化 + 形态函数 dict 统一; `tests/test_b_report_p2.py`), web presentation P2 batch (Streamlit 假数据/桩清除 + chart_visualizer 接入 + plot_signals int/bool 语义; `tests/test_web_presentation_p2.py`, 源码级诚实性 + importorskip matplotlib 绘图用例), factor library unification (C-P1-11: `factor_library.py` 共享原始因子 + JSON 配置外置; `tests/test_factor_library.py` 等价断言), quick-win batch (C-P1-14 growth/quality 因子列不相交 + E-P1 random_sampling 更名/死配置/源码诚实性; `tests/test_factor_library.py` 27 用例, `tests/test_stage2_fix_regressions.py` 23 用例). Island-module cleanup (项 15) removed `web_backtest`/`database_manager`/`concurrent_fetcher`/`cache_manager`/`batch_query_sectors` + their tests (−23 cases).
- Golden-metric snapshots live in `tests/test_backtest_honesty.py::TestGoldenMetrics` (seed=3, n=300). If they drift, suspect a backtest-logic change first; update snapshots only with justification.
- Root-level `test_*.py` files are legacy ad-hoc scripts (network-hitting); not part of the suite.

## Audit fix status (vs `skills-quant-framework-analysis-extracted/analysis/`, baseline `14b2f59`)

Fixed (commits `34e6a41`→`HEAD`): pattern-recognition layer, Flask duplicate route, optional-dep guards, `strategy_optimizer` executability, `signal_generator` pandas≥3 + tier signals, 4-engine t+1 fills + costs + limit-up/down (`execution_model.py`), ml_predictor time-series split, `database_manager:667` precedence, RSI/profit-factor/MDD unification (`core/`), walk-forward IS/OOS (`param_space` arg), Chikou lookahead, MACD true-cross, cache key `days` dimension, `batch_save_stock_quotes` symbol param, `FetchResult` type + `get_quote_result` (项 11), `concurrent_fetcher` empty-data counts as failed, `historical_data_manager` API failure warns (no silent stale-as-fresh), `optimization_engine.load_data` raises on 0 loaded (no more false "[OK] 成功加载 0 只"), `market_regime_classifier` trend thresholds live + min_segment hysteresis + adaptive first-year NaN fix, ATR 4-way divergence → core Wilder (incl. `pattern_recognition` single-bar-TR bug + `keltner_channel` ATR overwrite guard), remaining 8 RSI sites → core, realtime quote 成交额 万元→元 + 日期/时间字段语义, fallback `adjust`/volume-unit alignment, `FitnessConfig.w_*` wired into `FitnessEvaluator` (项 19), `SKILL.md` rewritten against real API (P0-7), FetchResult caller migration (technical_analyzer/position_analyzer/quant_workflow/web_app/real_time_monitor/multi_stock_backtester/cache_manager warm_up surface failure reasons + skip counts), risk wiring into order path (项 20: `PortfolioManager` 集中度/现金闸门阻断下单 + rebalance 超限阻断 + `StopLossManager`/`PortfolioRiskMonitor` 接线 + HHI 双刻度统一; `vectorized_backtest` `max_position_pct` clamp (默认1.0不改黄金快照); `PositionConfig` 无上限警告 + 工厂配置显式约束), `reversal_rules.py` 单一真相源统一实盘/回测反转规则 (C-P1-13: 阈值/背离窗口/判定闸门互斥一致, 回测补齐 RSI24/Vol_MA20/ROC/ATR/趋势衰竭, 删自比较死代码块), 可复现性种子+manifest 落盘 (C-P1-15), 死代码删除 (C-P1-17: MFS `technical_factor`、SS `min_market_cap` 空分支、DSG `top_n` 参数、SG `middle` 变量; `--top` CLI 接通 `format_report`), 7 模块端到端回归 (C-P2-19: 输出结构契约 + 点时截断无未来函数 + 训练/测试无重叠, `tests/test_e2e_regression.py`), 优化器可复现 (E-P0-3/4: `OptimizationEngine(seed=)` 按阶段派生独立子流、CLI `--seed` 默认42、`save_results` 落盘 seed/适应度权重/参数空间指纹/数据起止/GA 运行元数据; GA 初始种群/交叉变异子代/最优解全部 `ParameterSpace.repair` + validate 断言), 财务 point-in-time 止血契约 (C-P0-7: MFS `select_stocks`/`multi_factor_select` 强制『公告日』列 + `as_of` 参数, 缺列即 `ValueError`, 按公告日≤as_of 过滤且 NaT 剔除, `filter_point_in_time` 单一入口), MFS 因子修复 (C-P0-4/5, 落于 `34e6a41`; 合成数据实测验证 2026-10-22: momentum/volatility 经 `_price_cross_section` 横截面非 NaN, `weighting_method` 默认 `'custom'` 真读 `factor_weights` 且全 NaN 列跳过+缺因子重归一化, `optimize_weights` 真返回), 杂项清扫批次 (F-P1/F-P2/A-P1-4/A-P2-6: 删零引用死模板 `templates/backtest_ui.html`; `web_app.py` sys.path 改 `__file__` 基准 + 导入失败显式错误页含完整 traceback (st.stop), 不再静默降级; 根目录 29 篇遗留报告/手册 `git mv` 进 `docs/` 只留 8 篇入口文档并修链接; `stock_data_fetcher` 历史行情文档"腾讯接口"订正为新浪源 `stock_zh_a_daily` (腾讯仅实时行情), CLAUDE/README 移除无支撑的"10倍性能"宣称并标注 database_manager/concurrent_fetcher/realtime_quote 无生产调用方; `realtime_quote.get_quotes` 行号下标 → 按内容 `v_(\w{6})=` 正则匹配, 修缺行全体错位), B-report P2 批次 (审计 #9-14: `position_analyzer.analyze_position` `days` 参数透传修复 (便捷函数+类方法双层, 原静默失效恒 120); `pattern_recognition.analyze_patterns` `price_position` 改取价格下方最近支撑/上方最近压力 (修 vs_resistance=-30.9% 荒谬负值, 新增 nearest_support/nearest_resistance 字段); 列名契约统一 (technical_analyzer 补 `MACD_Hist` 产出 + `EMA20` 别名, position_analyzer 补 `MACD_Hist`, chart_visualizer 两处读取兜底缺列); `advanced_indicators.obv` O(n) 循环 → numpy cumsum 向量化 (首元素语义保留); `pattern_recognition.scan_all_patterns` 逐行 .loc O(n²) → 单次 numpy 向量化 (与逐条形态函数逐行等价断言), 5 个形态函数 (is_doji/is_morning_star/is_evening_star/is_piercing/is_dark_cloud) 返回类型统一 dict; trend_indicators 删 5 个 0 调用方孤儿 (adaptive_ma/KAMA, mcginley_dynamic, triple_screen, abands, all_trend_indicators, 连带清理 _core_* import); advanced_indicators.calculate_all 默认列表补 mass_index; `docs/skills_layers.md` 分层架构文档 (C-P2-16: L1 选股/L2 择时/信号层边界 + 列名契约 + 变更守则, README 文档导航接入), 孤岛模块清理 (项 15, 用户决策: 删 `web_backtest.py`/`database_manager.py`/`concurrent_fetcher.py`/`cache_manager.py`/`batch_query_sectors.py` 连同测试与文档入口, redis/psycopg2/SQLAlchemy 依赖移出 web_requirements; 保留 `realtime_quote.py` 待接入 web_app 实时监控页), web presentation P2 批次 (审计 #18-20: Streamlit 假数据/桩清除 — 仪表盘 3 个硬编码假指标改真实信号聚合+组合 manager 聚合, 监控页整页桩 (假指标 3/12/5/2 + 3 条假列表) 改接 `realtime_quote.RealTimeQuoteAPI.get_quotes(watchlist)` 真实行情+涨跌幅告警阈值, 组合页 3 个"开发中"按钮接 `rebalance`/`get_performance`/`generate_report` 真实 API, `get_stock_name` 硬编码 10 只改 stock_list.csv 懒加载全量 5523 只; `chart_visualizer` 上岗 — 分析页 95 行内联 matplotlib 4 图 + 回测页净值曲线内联图全部委托 `session_state.visualizer` (K线/MACD/RSI/布林带/综合分析/信号图 6 类, 综合分析占位符补实, matplotlib 缺失降级 None+提示), 实例化加 ImportError 守卫; 买卖点语义 — `plot_signals` `== True` 改 `fillna(0).astype(bool)` (int 0/1 信号列安全, 与回测引擎同源), web 信号图直接用 `generator.generate_signals` 同一真相源, 原 web_backtest 加权阈值错配随项15 删除消亡; `tests/test_web_presentation_p2.py` 14 用例), 因子库统一 (C-P1-11, 用户决策: 打分引擎分立不合并 — 新建 `factor_library.py` 叶子库收敛 MFS/SS 原始因子计算 (momentum/volatility/downside_vol/max_drawdown/volume + `FACTOR_REGISTRY` 方向元数据, z-score 留 MFS、0-100 绝对分留 SS), SS `min_score` 语义与单票场景保留; 权重/阈值外置 `config/stock_selector.json` + `config/multi_factor.json` (出厂值=内置默认, 显式传参最高优先), `LTS` 原样保留; `tests/test_factor_library.py` 24 用例含新旧内联逐位等价断言)), 速赢批 (C-P1-14: MFS `growth_factor` 删 ROE/毛利率双计 — 两指标原在 growth+quality 重复合计有效权重 18.3%, 归一 quality, 成长块留营收/利润增长率+净利率; E-P1: `strategy_optimizer.bayesian_optimize` → `random_sampling` 诚实更名 (旧实现为 random.uniform 均匀采样非贝叶斯), 保留兼容别名 + `optimize()` 分派 "bayesian" 历史名, 删 `OptimizationConfig` 零引用 `cv`/`n_jobs` 死字段, 模块 docstring/进度文案改随机采样; B-P2: `.claude/skills/requirements.txt` 分析层依赖清单 (scipy/akshare 顶层 import 核心 + pyarrow 运行时 + matplotlib/sklearn 守卫可选), web_requirements 陈旧依赖标注同步; `tests/test_factor_library.py` 增 3 用例 + `tests/test_stage2_fix_regressions.py::TestStrategyOptimizerHonesty` 增 5 用例)).

Still open (see audit): suspension modeling, `adjust` 落库维度 + 既有数据清洗 (单位修复已落代码, 历史 parquet 未清洗), 3-way stock-selection unification (项 21, 部分落地: C-P1-11 因子库+JSON 配置已完成, 打分引擎按用户决策保持分立, 剩余: Signal 契约/IndicatorEngine 等审计 #9/#10 未做), `technical_analyzer` signals lack shift(1) protection (advisory-only, documented).

## `.gitignore` gotchas

- `*.csv` ignored **except** `!.claude/skills/stock_list.csv` (tracked, 5523 rows).
- `tests/` and `test_*.py` have negation patterns (`!tests/`, `!tests/test_*.py`) so the real suite is tracked. Root-level legacy `test_*.py` remain ignored.
- `*.txt` ignored except `requirements.txt` and `web_requirements.txt`.

## Architecture docs

- `skills-quant-framework-analysis-extracted/analysis/` — external deep audit (7 Chinese MD reports) against upstream `14b2f59`. Claims about files present locally are accurate as of that baseline; many have since been fixed — see "Audit fix status" above.
- Root keeps only 8 entry docs (`README` / `CLAUDE` / `AGENTS` / `CHANGELOG` / `QUICK_START_GUIDE` / `API_REFERENCE*` / `DEPLOYMENT_GUIDE`); 29 legacy reports/manuals moved to `docs/` (audit F-P2 — links from entry docs now use `docs/` prefix). `README.md` is the entry point.
