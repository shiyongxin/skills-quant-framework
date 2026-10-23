# Skills 框架分层架构

> 审计路线图 C-P2-16 产物。基于源码 AST/签名核实（2026-10）。
> 规则来源：`skills-quant-framework-analysis-extracted/analysis/C-signals-selection.md` 第 270 行。
> 核心约束：**三层信号不得互相覆盖**；组合时择时层只做仓位调节，不做选股。

## 分层定义

```
┌────────────────────────────────────────────────────────┐
│ 编排/UI      quant_workflow (facade), web_app (Streamlit)│
├────────────────────────────────────────────────────────┤
│ L3 执行/风控  execution_model, portfolio_manager,        │
│              risk_management, position_analyzer          │
├────────────────────────────────────────────────────────┤
│ L2 择时层    daily_signal_generator (日频 BUY/HOLD/SELL), │
│  (日频)      reversal_detector/reversal_rules (反转 alert),│
│              market_regime_classifier (市场状态→仓位系数)  │
├────────────────────────────────────────────────────────┤
│ L1 选股层    multi_factor_selection (多因子, 季度调仓),    │
│  (横截面)    stock_selector (评分选股),                    │
│              long_term_selector (基本面长期)               │
├────────────────────────────────────────────────────────┤
│ 信号/分析     signal_generator (日频技术信号/分层),         │
│              technical_analyzer (单股综合技术分析)          │
├────────────────────────────────────────────────────────┤
│ 指标层       core/indicators (RSI/ATR 权威口径),           │
│              advanced_indicators, trend_indicators,       │
│              pattern_recognition                          │
├────────────────────────────────────────────────────────┤
│ 回测/优化    backtest_framework (引擎A), vectorized_backtest│
│              (引擎B), optimization_engine, strategy_optimizer│
├────────────────────────────────────────────────────────┤
│ 数据层       stock_data_fetcher (FetchResult 契约),        │
│              realtime_quote, historical_data_manager,     │
│              cache_manager, database_manager(孤岛)         │
└────────────────────────────────────────────────────────┘
```

## 各层职责与边界

### L1 选股层（横截面，低频）

回答"买什么"。输入横截面数据（财务/价格矩阵），输出排序后的股票池。

| 模块 | 入口 | 输出 | 调仓频率 |
|---|---|---|---|
| `multi_factor_selection` | `MultiFactorSelector.select_stocks(financial_df, price_df, top_n, as_of)` | top_n 股票列表 | 季度 |
| `stock_selector` | `StockSelector` / `select_stocks(stock_list, min_score, max_count)` | 评分≥阈值的股票 | 按调用 |
| `long_term_selector` | `LongTermSelector` | 长期持仓候选 | 季度 |

契约（C-P0-7 已落地）：MFS 的 `select_stocks`/`multi_factor_select` **强制要求**
财务数据含『公告日』列并显式传 `as_of`，经 `filter_point_in_time` 过滤——
禁止用未来公告的财务数据选股。

因子库统一（C-P1-11 已落地）：`factor_library.py` 是 L1 原始因子计算的
单一真相源（动量/波动率/下行波动/最大回撤/量比 + `FACTOR_REGISTRY`
方向元数据）。MFS 与 SS 的 raw 计算全部委托该库；**打分引擎保持分立**——
MFS 用横截面 z-score（回答"比同池好多少"），SS 用 0-100 绝对分（回答
"本身好不好"），二者刻度不同、`min_score` 语义不同，不合并（用户决策）。
权重/阈值外置 JSON：`config/multi_factor.json`（factor_weights）与
`config/stock_selector.json`（趋势阶梯/RSI 带/动量断点/量比/波动带），
出厂值与内置默认逐位一致。`long_term_selector` 原样保留（用户决策）。

### L2 择时层（时序，日频）

回答"什么时候买/卖、仓位多重"。**只对 L1 给出的股票池做时序判断，
不得新增/剔除股票**。

| 模块 | 信号 | 说明 |
|---|---|---|
| `daily_signal_generator` | `BUY`/`HOLD`/`SELL` + strength(-1~1) | 多指标打分（MACD/均线/量能等） |
| `reversal_detector` + `reversal_rules` | `BUY`/`SELL`/`WATCH` alert | 反转规则单一真相源（C-P1-13），实盘/回测共用同一 `reversal_rules.py` |
| `market_regime_classifier` | regime 标签 | 驱动 `daily_signal_generator.get_params_for_regime` 调参数，本身不产买卖信号 |

组合规则：同一股票同时出现 L2 的 BUY 与 SELL 时属**层内冲突**，按
strength 绝对值择一（`daily_signal_generator.generate_signal` 输出互斥单信号，
不会同时 BUY+SELL）；L1 入选但 L2 为 SELL → 空仓等待，而非换股。

### 信号/分析层（日频，单股）

- `signal_generator.SignalGenerator`：日频技术信号，输出含 tier 分层（强势/普通/观察）。
- `technical_analyzer.TechnicalAnalyzer.analyze(symbol, days)`：单股综合技术分析
  （趋势/支撑压力/形态/评分），输出 dict 报告，供 UI 与人工决策，不直接下单。

### L3 执行/风控层

- `execution_model`：t+1 成交、涨跌停限制、手续费/印花税（四引擎共用）。
- `portfolio_manager`：集中度/现金闸门，超限阻断下单（项 20）。
- `risk_management`：`StopLossManager`/`PortfolioRiskMonitor` 接线至下单路径。
- `position_analyzer`：单股持仓分析（盈亏/技术状态），`days` 参数全链路透传。

## 指标层契约

### 单一真相源（不得另写本地实现）

| 指标 | 权威位置 | 口径 |
|---|---|---|
| RSI | `core/indicators.rsi` | Cutler SMA 平滑；无亏损→100，无波动→50 |
| ATR / True Range | `core/indicators.atr` / `true_range` | Wilder RMA, alpha=1/period |
| profit_factor / MDD / Sharpe | `core/metrics` | 求和式 PF；MDD 正值%；sharpe rf=0.03, ddof=1 |
| 数据获取结果 | `core/fetch_result.FetchResult` | 失败必须 `ok=False`+`error`，禁止静默空 DF |

### DataFrame 列名契约（审计 B-C7，#11 已修）

- `EMA20` 为规范名；`EMA_20` 为 `technical_analyzer` 保留的向后兼容别名（两列同值）。
- `MACD_Hist` 由 `technical_analyzer`、`position_analyzer`、`stock_data_fetcher`、
  `daily_signal_generator` 全部产出；`chart_visualizer` 读取处有兜底
  （缺列时 `MACD - MACD_Signal`），兼容历史数据路径。
- K 线形态列（`scan_all_patterns` 产出）：布尔列 + `Pattern_Hammer`/`Pattern_HangingMan`
  为 True/None 对象列。形态判定函数统一 dict 返回
  （`{'is_xxx': bool}` / `{'is_xxx': bool, 'type': ...}`）。

## 回测与优化

| 引擎 | 模块 | 特点 |
|---|---|---|
| A | `backtest_framework` | 逐笔事件驱动，经 `core/metrics` |
| B | `vectorized_backtest` | 向量化，日频 mark-to-market 权益曲线 |
| D | `reversal_backtest` | 反转策略专用，复用 `reversal_rules` |
| E | `optimization_engine` | GA 优化，`seed=` 可复现（阶段子流派生），结果落盘参数空间指纹 |

所有引擎 t+1 成交、成本、涨跌停经 `execution_model` 统一；黄金指标快照见
`tests/test_backtest_honesty.py::TestGoldenMetrics`。

## 孤岛模块（项 15，已决策）

2026-10 决策已执行：`web_backtest.py`（Flask 第二套回测 UI，与 web_app 零复用、本机
CSV 路径死代码）、`database_manager.py`（无 psycopg2 驱动、0 生产调用方）、
`concurrent_fetcher.py` + `cache_manager.py`（并行取数/缓存从未接入主链）、
`batch_query_sectors.py`（纯死代码）**已删除**，连同对应测试与文档入口。

保留的孤岛：无。`realtime_quote.py`（与 stock_data_fetcher 的实时接口同源但为真批量
解析；A-P1-4 修复成果保留）已接入 web_app 实时监控页（审计 #18 批次）。

## 变更守则

1. 新增指标 → 进 `advanced_indicators`/`trend_indicators` 或 `core/`，不得在业务模块内联重写 RSI/ATR。
2. 新增选股逻辑 → 先读项 21 决策；不要复制第四套。
3. 改列名 → 全仓库 grep 消费方（`chart_visualizer`/`web_app`/`multi_factor_selector`），
   保留旧名别名至少一个版本。
4. L1/L2 信号合并 → 择时层输出只能调仓位系数，不得改 L1 的股票池成员。
