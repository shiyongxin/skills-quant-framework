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
| `daily_signal_generator` | `BUY`/`HOLD`/`SELL` + strength(-1~1) | **外壳**：体制检测 + 参数体系 + 批量日报 + manifest；内层打分已并入 `signal_generator`（项 21 合并，单一真相源） |
| `reversal_detector` + `reversal_rules` | `BUY`/`SELL`/`WATCH` alert | 反转规则单一真相源（C-P1-13），实盘/回测共用同一 `reversal_rules.py` |
| `market_regime_classifier` | regime 标签 | 驱动 `daily_signal_generator.get_params_for_regime` 调参数，本身不产买卖信号 |

组合规则：同一股票同时出现 L2 的 BUY 与 SELL 时属**层内冲突**。合并后
`daily_signal_generator.generate_signal` 与 `signal_generator` 都只输出互斥单信号
（S1 已做买卖互斥仲裁：两侧分值都过阈值时只保留分值高的一侧），不会出现 BUY+SELL；
L1 入选但 L2 为 SELL → 空仓等待，而非换股。

### 信号/分析层（日频，单股）

- `signal_generator.SignalGenerator`：**全项目唯一的信号打分真相源**（项 21 合并：
  `daily_signal_generator` 内层已并入此处）。输出 7 个 tier 分项列 +
  `signal_buy`/`signal_sell`（**互斥**：两侧分值都过阈值时只保留分值高的一侧）
  + `signal_buy_score`/`signal_sell_score` + `signal_strength`；报告措辞按档位值
  翻译（`SIGNAL_LABELS` 表，`daily_signal_generator` 的 reasons 同源）。
- `technical_analyzer.TechnicalAnalyzer.analyze(symbol, days)`：单股综合技术分析
  （趋势/支撑压力/形态/评分），输出 dict 报告，供 UI 与人工决策，不直接下单。

### L3 执行/风控层

- `execution_model`：t+1 成交、涨跌停限制、手续费/印花税（四引擎共用）。
- `portfolio_manager`：集中度/现金闸门，超限阻断下单（项 20）。
- `risk_management`：`StopLossManager`/`PortfolioRiskMonitor` 接线至下单路径。
- `position_analyzer`：单股持仓分析（盈亏/技术状态），`days` 参数全链路透传。

## 指标层契约

### 统一信号输出契约（审计 C #9，项 21 #9a）

`core/signal.py` 的 `Signal` dataclass 是所有信号/选股模块的**出口形状**：

```
{symbol, signal_date, action∈{BUY,HOLD,SELL}, strength, scale,
 reasons[], confidence, target_weight, execute_at,
 executable, blocked_reasons[], skipped_checks[], source, extra{}}
```

- **刻度显式声明**：`scale` ∈ `vote`（S1 分项求和 [-10,10]）/ `vote_norm`（S2 归一化 [-1,1]）/
  `weighted`（0-100 加权）/ `prob` / `score` / `zscore`；契约校验刻度量纲，
  **不做静默归一化** —— 跨模块比较前必须自己选刻度。
- **互斥**：`action` 单值；`action_from_flags` 对"买卖同时为真"直接抛错。
- **交易约束唯一挂载点**：`apply_constraints(signal, report)` +
  `trade_constraints.ConstraintReport.as_signal_fields()`（各模块不再手拼
  `executable`/`blocked_reasons`/`skipped_checks`）。
- `execute_at` 默认 `None` = 由执行层（`execution_model`，t+1 开盘）决定；
  仓库暂无交易日历，不推算"下一交易日"以免造假。
- 已接入：`signal_generator.to_signal()` / `get_signal()`、
  `daily_signal_generator.to_signal()` + `DailyReport.contract_signals`、
  `web_app` 全部信号展示。
- **选股结果契约 `Selection`**（#9b，与 `Signal` 分立）：`Selection` 回答"池内哪些标的
  排名如何/是否入选"，`Signal` 回答"何时买卖/能否执行"；两者都带交易约束字段，
  因此"选出来的票能不能买"是同一套语义。字段：
  `{symbol, as_of, score, scale, rank, selected, grade, reasons, executable,
  blocked_reasons, skipped_checks, source, extra}` + `is_selected`。
  - MFS `to_selections(df, as_of)`（z-score 刻度，**有真实 point-in-time 公告日语义**）
  - SS `to_selections(results, as_of)`（0-100 分，实盘实时筛选 → `as_of` 如实留空）
  - LTS `StockAnalysis.to_selection()`（total_score + `recommendation` 档位；
    实盘实时筛选 → `as_of` 如实留空，审计 L10 待修）
  - `reversal_detector.ReversalAlert.to_signal()`（WATCH→HOLD）
  - `ml_predictor.PredictionResult.to_signal()`（up/down/hold→BUY/SELL/HOLD）

### 单一真相源（不得另写本地实现）

| 指标 | 权威位置 | 口径 |
|---|---|---|
| RSI | `core/indicators.rsi` | Cutler SMA 平滑；无亏损→100，无波动→50 |
| ATR / True Range | `core/indicators.atr` / `true_range` | Wilder RMA, alpha=1/period |
| MA / EMA | `core/indicators.sma` / `ema` | SMA=rolling mean；EMA=**递归** `ewm(span, adjust=False)` |
| MACD | `core/indicators.macd` | DIF=EMA(f)-EMA(s)；DEA=EMA(sig)(DIF)；**HIST=DIF-DEA（不 ×2）** |
| KDJ | `core/indicators.kdj` | RSV(n=9)→EMA(span=3)→K→D；J=3K-2D；α=0.5（教科书 α=1/3 未采纳） |
| BOLL | `core/indicators.bollinger` | mid=SMA(period)；std=样本标准差(ddof=1)；±mult·std |
| 量均线 / OBV / VWAP | `core/indicators.volume_ma` / `obv` / `vwap` | rolling mean；方向符号×量累加；累积 TP·V/累积V |
| profit_factor / MDD / Sharpe | `core/metrics` | 求和式 PF；MDD 正值%；sharpe rf=0.03, ddof=1 |
| 数据获取结果 | `core/fetch_result.FetchResult` | 失败必须 `ok=False`+`error`，禁止静默空 DF；带 `adjust` 复权维度 |
| 交易日历 / 停牌 | `core/trading_calendar.TradingCalendar` | 由**指数行情**反推交易日集合（指数每交易日有行 → 个股缺行 = 真停牌） |
| 复权口径（落库维度） | `HistoricalDataManager` 文件名 + 元数据 + `FetchResult.adjust` | `{symbol}.parquet`=不复权 / `{symbol}_qfq.parquet` / `{symbol}_hfq.parquet`；缺口径时返回空 DF，不拿不复权冒充 |

**共享指标引擎**（审计 #10）：`core/indicator_engine.IndicatorEngine` 是业务模块
调用指标的统一入口 —— 只负责"取哪段、叫什么列名"，公式一律在 `core/indicators.py`：

```python
eng = IndicatorEngine(df)                  # df 含 收盘/最高/最低/成交量
df['MACD'], df['MACD_Signal'] = eng.macd() # 规范名 DIF/DEA/HIST 再 rename 回历史名
```

规范列名：`MA{p} / EMA{p} / DIF / DEA / HIST / RSI / K / D / J / BB_Upper /
BB_Middle / BB_Lower / BB_Std / TR / ATR / Vol_MA{p} / VWAP / OBV`；
`IndicatorEngine.to_legacy/to_canonical` 做列名双向映射。
**门禁**：业务模块内不得再出现裸 `.ewm(...)`/`.rolling(...).mean()` 指标公式
（`tests/test_indicator_engine.py` 源码级扫描）。

### DataFrame 列名契约（审计 B-C7，#11 已修）

- `EMA20` 为规范名；`EMA_20` 为 `technical_analyzer` 保留的向后兼容别名（两列同值）。
- `MACD_Hist` 由 `technical_analyzer`、`position_analyzer`、`stock_data_fetcher`、
  `daily_signal_generator` 全部产出；`chart_visualizer` 读取处有兜底
  （缺列时 `MACD - MACD_Signal`），兼容历史数据路径。
- K 线形态列（`scan_all_patterns` 产出）：布尔列 + `Pattern_Hammer`/`Pattern_HangingMan`
  为 True/None 对象列。形态判定函数统一 dict 返回
  （`{'is_xxx': bool}` / `{'is_xxx': bool, 'type': ...}`）。

## 停牌建模与复权维度（审计 C-P1-12 遗留项 / P0-4）

**停牌**：A 股停牌日**没有行情行**，数据侧无标记。解法是用**指数行情**当交易日历的
真相源 —— 上证指数每个交易日都有行，个股缺行即真停牌（不误伤节假日）：

```python
from core.trading_calendar import ensure_calendar
ensure_calendar()          # 显式注入 / 本地 JSON 缓存 / 本地指数 parquet 现算（不联网）
```

- `trade_constraints.check_last_bar(..., calendar=None)`：有日历时按**缺失交易日数**
  判定停牌 → 阻断买卖，原因写"最近 N 个交易日无行情（停牌或数据缺失）"；
  "数据过期"也改按**交易日**计（节假日不算过期）；无日历时降级为自然日 +
  零成交启发式，并在 `skipped_checks` **如实注明**"未检查"。
- `check_close_panel(..., calendar=...)`：横截面面板级停牌识别（个股最后有行情的
  交易日落后于市场最新交易日 → 剔除）。
- **根本限制**：无指数数据即无日历；此时停牌检查如实跳过。回测引擎侧的"停牌期间
  持仓无法平仓"尚未显式建模。

**复权**：复权是**数据维度**不是装饰 —— 不同口径混用会在除权日产生虚假跳空。

- 落库：`{symbol}.parquet`（不复权）/ `{symbol}_qfq.parquet` / `{symbol}_hfq.parquet`，
  元数据记 `adjust`；`load(adjust=...)` 只读对应口径，缺失时返回空 DF。
- 取数：`stock_data_fetcher.get_quote_data/get_quote_result(..., adjust=...)` 显式
  传参，随 `FetchResult.adjust` 记录。
- 存量清洗：`python .claude/skills/data_cleaner.py --data-dir stock_data [--apply]`
  —— 用 `成交额/成交量 ≈ 收盘价` 的中位数比值反推单位（股/手、元/万元）并归一；
  结构清洗（列名/日期/排序/去重/补涨跌幅）；除权跳空**只标记不改写**（无除权因子
  不可还原，正确处置是按复权口径重新取数）。

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

1. 新增指标 → 进 `core/indicators.py`（纯函数真相源）+ `advanced_indicators`/`trend_indicators`（封装），
   业务模块一律调 `core`，不得内联重写 RSI/ATR/MA/EMA/MACD/KDJ/BOLL。
2. 新增选股逻辑 → 先读项 21 决策；不要复制第四套。
3. 改列名 → 全仓库 grep 消费方（`chart_visualizer`/`web_app`/`multi_factor_selector`），
   保留旧名别名至少一个版本。
4. L1/L2 信号合并 → 择时层输出只能调仓位系数，不得改 L1 的股票池成员。
