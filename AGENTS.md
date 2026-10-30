# AGENTS.md

## What this is

Chinese A-share quantitative analysis framework ("Skills 股票量化分析框架" v2.0). ~27k LOC Python. Built as a Claude Code skills collection — not a conventional installable package. Disclaimer in README: test project, not production advice.

## Two parallel systems (do not confuse them)

1. **`.claude/skills/`** — main analysis chain (38+ modules + `core/`). Entry: `quant_workflow.py` (facade), `web_app.py` (Streamlit), `signal_generator.py`, `technical_analyzer.py`.
2. **`optimization_package/optimization_package/`** — 离线部署包 (Parquet-based GA pipeline)。**2026-10-26 治理决策: 主链是唯一真相源, 本目录的 `skills/` 是构建产物** —— 由主链内 `.claude/skills/tools/pack.py` (**受版本控制**) 按依赖闭包自动生成, **请勿手改**; 每次打包写 `PROVENANCE.json` (源 commit + 每文件 sha256) → 陈旧产物无法冒充最新。改代码只改主链, 再重跑 `python .claude/skills/tools/pack.py`。决策依据与落地记录: 台账 §5.1; 门禁 `tests/test_package_parity.py`。

`optimization_package/` is **gitignored** (整个目录 0 文件被跟踪) → 克隆后需重跑打包脚本才有包; 工作区副本陈旧可用 `PROVENANCE.json` 的 `source_commit` 检出。

## How modules import each other

Modules import each other by **bare module name** (`from stock_data_fetcher import StockDataFetcher`), relying on `sys.path.append('.')` or `sys.path.append('.claude/skills')` hacks. **Always run scripts from the repo root.** Running from any other directory breaks all intra-project imports.

`pytest.ini` has `pythonpath = . .claude/skills`, so pytest imports skill modules directly.

## Single source of truth (`core/`, audit roadmap items 8/9)

- `core/indicators.py` — authoritative `rsi()` (Cutler SMA; 0-div: no-loss→100, no-movement→50) and `atr()`/`true_range()` (Wilder RMA, alpha=1/period). **All** RSI and ATR computations across the repo route through it (RSI: 13 sites incl. chart_visualizer/ml_predictor/reversal_backtest/strategy_optimizer; ATR: 8 sites incl. pattern_recognition's single-bar-TR bug). **Do not write a new local RSI or ATR.**
- `core/metrics.py` — `profit_factor` (sum-of-pnls formula), `max_drawdown_pct` (**positive** magnitude), `sharpe_ratio` (decimal returns, rf=0.03, ddof=1), **`win_rate`** (盈利笔/全部笔; breakeven 计分母不算赢), **`consecutive_streaks`** (**交易序列**上的连胜/连亏笔数; breakeven 两者都不算并打断连段), **`max_consecutive_true`** (布尔序列连段, 供日频连涨/连跌). 引擎 A/B/D 的胜率与连段统计全部走此处 (审计 M1/B48: 旧引擎 A 在日频净值序列上统计、引擎 B 统计的是"亏损起始点间隔" → 已统一为交易序列口径). Engines A (`backtest_framework`), B (`vectorized_backtest`) and `optimization_engine` all route through it. B's MDD/Sharpe use a daily mark-to-market equity curve (trade spans), not the per-trade compounding curve.
- `core/fetch_result.py` — `FetchResult{ok, data, error, source, as_of}` (项 11). New data-path code should return it (see `stock_data_fetcher.get_quote_result`); failures must set `ok=False` + `error`, never silently return an empty DF.
- `core/trading_calendar.py` — **交易日历与停牌识别** (审计 C-P1-12 遗留项): `TradingCalendar.from_index()` 由**指数行情**反推交易日集合 (指数每交易日有行 → 个股缺行 = 真停牌, 不误伤节假日); `trade_constraints` 借此做真停牌阻断 + "数据过期"改按**交易日**计 (无日历时降级为自然日并如实记 skipped)。日历来源三级: 显式注入 / 本地 `stock_data/calendar/trading_days.json` / 本地指数 parquet 现算 (`ensure_calendar()`, 不联网)。**根本限制仍在**: 无指数数据即无日历 (此时停牌检查如实跳过, 只剩零成交启发式)。
- `core/indicators.py` + `core/indicator_engine.py` — **共享指标单一真相源** (审计 C #10): 纯函数层 `sma/ema/macd/kdj/bollinger/volume_ma/obv/vwap` + 既有 `rsi/atr/true_range`; 引擎层 `IndicatorEngine` (规范列名 + `to_legacy`/`to_canonical` 列名映射)。全仓 19 个模块的 MA/EMA/MACD/KDJ/BOLL/量均线/OBV/VWAP 全部改调此处，**模块内不得再出现裸 `.ewm(...)`/`.rolling(...).mean()` 指标公式**（门禁测试 `tests/test_indicator_engine.py`）。口径固化：EMA 递归 (`adjust=False`)、MACD `HIST=DIF-DEA`（不 ×2）、KDJ `α=0.5`（span=3；国内教科书 α=1/3 未采纳，属策略决策非重构）、BOLL `ddof=1`。

## 已落地的口径契约 (勿回退)

审计修复引入的硬约束 —— **改这些模块前先读台账对应条目**, 改完必须让门禁继续绿:

| 契约 | 约束 | 门禁 |
|---|---|---|
| IS/OOS 隔离 (H1) | 适应度**只由 IS 窗口计算**; OOS 指标只报告, 从不参与参数选择 | `test_h1_oos_isolation.py` |
| confidence 证据派生 (H2) | `confidence = clamp01(适应度)` (`optimization_engine.confidence_from_fitness`); 禁止硬编码常数 | `test_h2_confidence.py` |
| 稳健性证据 (H10) | 证据只在 GA 返回后组装 (不扰动搜索); 不落"校正后 p 值" | `test_h10_robustness.py` |
| 因子点时 (H6) | 配对只走 `FactorWeightingMethod._align` (同期); 标签用 `forward_returns(close)`; 配对/检验函数内禁 `.shift(` | `test_h6_factor_point_in_time.py` |
| 股票池 PIT (H4) | 股票池函数内禁 `.now()`; 参考日 = 缓存最新日; 幸存者偏差必须标记 | `test_h4_point_in_time_universe.py` |
| 停牌建模 (H5) | 4 引擎签名含 `trading_calendar=`, 默认 None = 不建模 (不隐式取全局日历) | `test_h5_suspension.py` |
| 验证链 (H3) | 默认严格: 无样本外日期 → **不出验证结论**; 每-pick PIT 池默认开 | `test_h3_validation_chain.py` |
| 容量约束 (H7) | A: `PositionConfig.max_volume_participation`; B: `params['max_volume_participation']` + `capital` | `test_backtest_honesty.py::TestH7*` |
| 引擎 B 持仓状态机 (H8) | `min_holding_days` 默认 **0** (不隐式锁退出); 持仓中的新买讯忽略 | `test_backtest_honesty.py::TestH8*` |
| 引擎 A walk-forward (H9) | `run(warmup_data=)` 预热; `walk_forward` 返回 `{windows,oos,oos_equity_curve}` | `test_backtest_honesty.py::TestH9*` |
| 指标口径 (M1) | 胜率/连段一律走 `core/metrics`; 交易序列口径与日频口径字段名不得混用 | `test_backtest_honesty.py::TestM1*` |
| 指数命名空间 (M12) | 指数代码走 `load_index()` / `historical/index/`, 不得走个股 `load()` | `test_index_namespace.py` |
| 读路径降级 (M13) | 共享 `_read_local()`; 全文件只允许 1 处 `pd.read_parquet` | `test_optional_deps.py` |
| 死 import (L12) | 全仓无未用 import (两个 `# noqa: F401` 豁免) | `test_source_hygiene.py::TestUnusedImportsRepoWide` |
| 日线列名/涨跌幅 (M19) | 列名映射只走 `core/dataframe.OHLCV_COLUMN_MAP`; `涨跌幅` 只能由 `ensure_change_pct` 派生 (禁直接赋值); 不消费涨跌幅的模块不补该列 | `test_m19_column_standardization.py` |
| 评估失败可见 (M5) | 逐股回测失败必须记账 (`n_stocks_failed`/`success_rate`) + 受罚 (`fitness *= success_rate`; 成功率 < `min_success_rate` → 归零); 评估路径禁静默 `except: continue` | `test_m5_evaluation_failures.py` |
| 共享数据层 (M20) | 取数一律走 `HistoricalDataManager.get_daily_result` (复权维度 + 参考日 + FetchResult + 交易日历窗口); 禁各模块自行取数/用 wall clock 划窗口; 缓存键须含口径维度 | `test_m20_shared_data_layer.py` |
| 复权默认口径 (P0-4/M20 收口) | 数据入口默认 `adjust=DEFAULT_ADJUST` (`core/fetch_result`, **hfq 后复权**, 产品决策 2026-10-30); 真实价格场景 (持仓成本对比 `position_analyzer` / 实时监控 `real_time_monitor`) 必须显式 `adjust=''`; 股票池/元数据按 `_base_symbol` 剥口径标签, 补齐判定按 `_has_stock_any_adjust` (任一口径) | `test_data_adjust_dimension.py::TestDefaultHfqWiring` |
| 窗口预热 (M4) | 预热长度按**参数** (`required_warmup_bars`), 不得写死; 窗口比 `min_holding_days` 短 → 跳过并记账 (`regime_window_stats`) | `test_m4_regime_warmup.py` |
| 部署包 (批次 4) | 副本 = 构建产物; 打包脚本必须在主链且**被 git 跟踪** | `test_package_parity.py` |
| 幸存者偏差证据 (D1) | `survivorship_bias` 只由四条证据得出 (清单可用/在范围退市股全部缓存/≤90天新鲜/参考日≥覆盖起点且沪深记录齐, 任一不满足保守 True); akshare 回退**仅限**股本步骤确定性崩溃 (demjson), 网络错误不得回退 | `test_delisted_stocks.py` |

## JS runtime gate (V8)

- `js_runtime.py` — **进程级 V8 闸门**。新浪 KLC 载荷是 JS 加密的, 解密要跑 V8 (`py_mini_racer`): akshare `stock_zh_a_daily` / `stock_zh_index_daily` + 本仓 `sina_daily._decode_klc` (北交所直连)。V8 isolate **不是线程安全**的 —— 批量取数 (`historical_data_manager.py batch`, 默认 4 线程) 并发建 isolate → `address_pool_manager.cc: Check failed: !pool->IsInitialized()` → **SIGTRAP 打死进程** (不是 Python 异常, `try/except`/线程池都拦不住, 整批数据当场全丢)。
- 闸门做法: 用代理类替换 `py_mini_racer.MiniRacer`, 把建 isolate / eval / call / 释放 isolate 全部串到一把 `RLock` 上; **网络 I/O 仍在各线程并行** (JS 解密 ~10ms vs 网络 ~1s)。akshare 内部自建 context, 调用点散落全包 → 只能在类本身收口。**语义不变**: 每次仍是独立 context (共享 context 会让不同库的同名 JS 函数互相顶掉 → 静默解密出错)。
- 接线: `sina_daily` (个股 + bj 直连) / `historical_data_manager` / `market_regime_classifier` / `historical_backtest_validator` (后三者走 `js_guard()` 整段串行 = 闸门失效时的深度防御)。导入 `js_runtime` 即自动装闸门, 不靠"记得调用安装"。门禁 `tests/test_js_runtime.py` 9 用例。

## Running things

```bash
# Web app (Streamlit, port 8501)
python run_web_app.py

# Test suite (offline, from repo root)
python3 -m pytest tests/ -q
```

CI exists: `.github/workflows/tests.yml` (push/PR → 离线套件, 矩阵 3.11/3.12; 依赖装自 `.claude/skills/requirements.txt`).
No lint/typecheck config. No pre-commit. `pyproject.toml` 存在 (项目元数据 + 可安装布局), 但**不写** `[tool.pytest.ini_options]` → `pytest.ini` 是 pytest 配置唯一真相源.

## Dependencies

- Core (顶层 import, 缺失即 ImportError): `pandas numpy scipy akshare` — 分析层清单见 `.claude/skills/requirements.txt` (B-P2; `multi_factor_selection` 顶层 `from scipy import stats`)
- Runtime/guarded: `pyarrow` (historical_data_manager parquet 读写), `matplotlib` (chart_visualizer 绘图, ImportError 守卫降级), `scikit-learn` (ml_predictor, try 守卫)
- Web 层: `streamlit scikit-learn scipy altair plotly` (见 `web_requirements.txt`; `web_app.py` 是 skills 目录中唯一 streamlit 调用方)
- Optional-dep guards (`_AVAILABLE` / `MODULES_AVAILABLE`): use **separate try blocks** per import (pattern set when concurrent_fetcher existed; that module has since been deleted). No remaining sqlalchemy/redis/psycopg2-dependent modules.

## Testing

- `tests/` is tracked; `pytest.ini` `testpaths = tests`. **984 offline tests** (984 pass, 0 skip — 装齐 `pyarrow` + `matplotlib` + `sklearn` 后全部用例实跑; 缺任一时相应用例因 `importorskip` 跳过). Run from repo root: `python3 -m pytest tests/ -q`.
- **每条审计修复都配了门禁** (源码级 AST + 行为断言), 按主题分文件:

| 主题 | 测试文件 |
|---|---|
| 回测诚实度 (H7 容量 / H8 持仓状态机 / H9 walk-forward / M1 指标口径 + 黄金快照) | `test_backtest_honesty.py` |
| 短窗口冷启动 (M4) | `test_m4_regime_warmup.py` |
| 优化器 (H1 样本外 / H2 confidence / H10 稳健性 / M5 失败惩罚 + 配置接线 / 评分制 / 参数下发) | `test_h1_oos_isolation.py` `test_h2_confidence.py` `test_h10_robustness.py` `test_m5_evaluation_failures.py` `test_optimizer_config_wiring.py` `test_optimizer_honesty.py` `test_optimizer_reproducibility.py` `test_weighted_scoring.py` `test_params_delivery.py` |
| 研究有效性 (H3 验证链 / H4 PIT 股票池 / H6 因子点时) | `test_h3_validation_chain.py` `test_h4_point_in_time_universe.py` `test_h6_factor_point_in_time.py` |
| 停牌与日历 (H5 + C-P1-12) | `test_h5_suspension.py` `test_trading_calendar.py` `test_trade_constraints.py` |
| 指标引擎 (审计 #10) | `test_indicator_engine.py` `test_indicator_convergence.py` `test_core_unification.py` |
| 信号/选股契约 (审计 #9 + 项 21) | `test_signal_contract.py` `test_selection_contract.py` `test_signal_merge.py` `test_signal_semantics.py` |
| 数据层 (P0-4/5 + M12/M13/M16/M17/M19/M20/M22) | `test_data_layer_p0.py` `test_data_adjust_dimension.py` `test_index_namespace.py` `test_realtime_quote.py` `test_batch1_m22_m15_m18_m16.py` `test_m19_column_standardization.py` `test_m20_shared_data_layer.py` |
| 源码卫生 + 可选依赖降级契约 | `test_source_hygiene.py` `test_optional_deps.py` |
| 部署包一致性 (批次 4) | `test_package_parity.py` |
| 工程基座 (L1/L2/L3/L5/L9/L10/L11) | `test_project_metadata.py` |
| 退市股清单 + 幸存者偏差证据 (D1) | `test_delisted_stocks.py` |
| 其余 | `test_b_report_p2.py` `test_e2e_regression.py` `test_execution_model.py` `test_factor_library.py` `test_indicator_skill_p0.py` `test_js_runtime.py` `test_ml_predictor_timeseries.py` `test_reversal_unification.py` `test_risk_wiring.py` `test_stage1_regressions.py` `test_stage2_fix_regressions.py` `test_web_presentation_p2.py` |

  → 逐条修复的**证据 / 复验置信度 / 归因**在台账 `docs/OPEN_ITEMS_PLAN_2026-10-25.md` §2/§3/§4/§5.1 (本文不重复)。
- **Golden-metric snapshots**: `tests/test_backtest_honesty.py::TestGoldenMetrics` (seed=3, n=300) 是回测数值的回归基线。漂移先怀疑撮合逻辑, 重评必须写归因 (归因记录在台账 §3)。引擎 A/B 最近两次重评 = H7 (成交容量约束) / H8 (`min_holding_days` 默认 20→0) —— 两者都留了"关闭该特性即逐位复现旧值"的固化用例。
- Root-level `test_*.py` files are legacy ad-hoc scripts (network-hitting); not part of the suite.
- **测试隔离 (交易日历)**: `tests/conftest.py` 在**导入期**屏蔽 `core.trading_calendar` 对 CWD 相对默认目录 `./stock_data` 的日历读写 (`get_calendar()` 的隐式回退 + `ensure_calendar()` 的默认目录) —— 否则本地一旦存过指数行情 (**正常用法**: `historical_data_manager.py fetch --index 000001`), 28 个"无日历"用例 (停牌阻断 / 数据过期 / 限价约束) 全部翻转; 且测试自身算出的日历 JSON 会写回仓库目录 (web_app 导入即触发) → 污染仓库, 此前已发生过一次 (29 用例连环失败)。显式 `path`/`data_dir` 的调用照常生效 → 本地缓存读写仍有用例覆盖 (一律传 `tmp_path`); 每个用例前后清空进程级日历 (全局单例串味)。

## Audit fix status (vs `skills-quant-framework-analysis-extracted/analysis/`, baseline `14b2f59`)

**台账 `docs/OPEN_ITEMS_PLAN_2026-10-25.md` 是审计 backlog 的唯一真相源** (逐条证据 + 复验置信度 + 归因 + 对应门禁)。批次 1 之前的已修项见台账 §9 附录; 提交级细节见 `git log --oneline`。

**已收口**: **复权默认口径已拍板并落地 (默认 hfq 后复权, 2026-10-30, 台账 §5.4; 门禁 `TestDefaultHfqWiring` + 早退补登记, 基线 971→984)**; **D1 退市股数据基建 (幸存者偏差由「只能标记」变「可消除」, 2026-10-30, 台账 §5.3)**; 批次 1 (确凿小 bug, 15 条) / 批次 2 (回测数值口径: H7 容量约束 / H8 持仓状态机 / H9 walk-forward 预热 / M1 指标口径) / 批次 3 (研究有效性: H1 样本外隔离 / H10 稳健性证据 / H2 confidence 证据派生 / H5 引擎侧停牌建模 / H6 因子点时 / H4 PIT 股票池 / H3 验证链重做) / 批次 4.1 (副本治理 → 副本降级为构建产物)。

**仍开** (完整条目与证据见台账 §3/§5.2/§5.3/§6):

- **批次 2 已全部收口** (M13/M12/M17/M14/L6-L12/M2/M3/M9/M22/M15/M18/M16 → 批次1; H8/H9/H7/M1/M5/M19/M20/M4 → 批次2)。
- **批次 4.2 工程基座已收口** (2026-10-29: L1/L2/L3/L5/L9/L10/L11 已修 + 门禁 `test_project_metadata.py`; L4/L5 的旧证据已过时)。
- **停牌建模根本限制**: 日历来源依赖指数数据 → **无指数数据即无日历** (停牌检查如实跳过, 只剩零成交启发式)。
- **幸存者偏差: D1 基建已落地 (2026-10-30)**: 退市清单 (`delisted refresh`) + klc 直连回退 + **四条证据规则** (`_universe_meta` 判 `survivorship_bias=False`) + CLI 补数 (`delisted fetch`); 本地已补 **337/337** → meta 可判 False。残余如实: 北交所退市无名录接口、清单覆盖起点 沪2001/深1999 (更早参考日仍保守 True)、清单需 90 天内刷新、B股 30 只在股票池范围外 (台账 §5.3)。
- **线上历史数据批量重取**: 除权跳空只标记不改写, 需按复权口径重新取数 (依赖网络与磁盘; `data_cleaner.py` 已就位)。
- `technical_analyzer` signals 缺 `shift(1)` 保护 (advisory-only, 已文档化)。

## `.gitignore` gotchas

- `*.csv` ignored **except** `!.claude/skills/stock_list.csv` (tracked, 5523 rows).
- `tests/` and `test_*.py` have negation patterns (`!tests/`, `!tests/test_*.py`) so the real suite is tracked. Root-level legacy `test_*.py` remain ignored.
- `*.txt` ignored except `requirements.txt` and `web_requirements.txt`.

## Architecture docs

- `skills-quant-framework-analysis-extracted/analysis/` — external deep audit (7 Chinese MD reports) against upstream `14b2f59`. Claims about files present locally are accurate as of that baseline; many have since been fixed — see "Audit fix status" above.
- `docs/OPEN_ITEMS_PLAN_2026-10-25.md` — **审计台账 (唯一真相源)**: 审计 7 份报告逐条对照当前代码复核后的 ~43 条未落地项, 分 4 个批次 (确凿小 bug / 回测数值口径 / 研究有效性 / 工程基座与副本治理), 每条带证据行号 + 复验置信度 (✅已实测 / ⚠️需再核); 批次 1/2/3/4.1 已全部收口 (§9 附录记批次 1 之前的已修项). 修完一条即划掉并回写本文件; ⚠️ 条目动手前必须先复验 (审计基线距今已 30+ 提交).
- Root keeps only 8 entry docs (`README` / `CLAUDE` / `AGENTS` / `CHANGELOG` / `QUICK_START_GUIDE` / `API_REFERENCE*` / `DEPLOYMENT_GUIDE`); 29 legacy reports/manuals moved to `docs/` (audit F-P2 — links from entry docs now use `docs/` prefix). `README.md` is the entry point.
