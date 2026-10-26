# 后续待办计划（审计项复核）

> **生成日期**: 2026-10-25（星期日）
> **代码基线**: `e9ea505` — 死代码清理 + 依赖契约修正 (ml_predictor.FeatureEngineer) + 源码卫生门禁
> **测试基线**: 531 passed / 0 skipped（装齐 `pyarrow` + `matplotlib`）
> **最近更新**: 2026-10-26 — 批次 1 的 **M22 + M15 + M18 + M16 已修**（测试基线 560 → **599**，新建 `tests/test_batch1_m22_m15_m18_m16.py` 39 例 + `test_data_layer_p0.py` 2 例改打 `fetch_daily` 新缝）；同日早些 M2 + M3 + M9（553 → 560）、L6 + L7 + L8（549 → 553）、M12 + M13 + M17 + M14（2026-10-25，531 → 549）
> **来源**: 外部深度审计 7 份报告 `skills-quant-framework-analysis-extracted/analysis/`（基线 `14b2f59`）逐条对照当前代码复核
> **性质**: 这不是"新 bug 报告"，而是**审计 backlog 的清理台账** —— 记录哪些已修、哪些还没动、哪些需要产品决策

---

## 0. 一句话结论

代码里**没有任何 TODO/FIXME 注释**（0 处）；`AGENTS.md` 的 "Audit fix status" 只记了 3 条 "Still open"，但把审计 7 份报告逐条对照当前代码核一遍后，**还有约 43 条未落地项**。

分两类，性质完全不同：

- **代码正确性类**（约 25 条）：确凿 bug / 死代码 / 文档漂移 —— 可以直接修，风险低
- **研究有效性类**（约 10 条，高影响）：不是"写错了"，是**方法论层面这套系统的回测结论目前不能当真** —— 需要拍板，不是改几行代码

---

## 1. 复验方法与置信度标注

| 标记 | 含义 |
|---|---|
| ✅ | **本次逐条实测复验**（有当前代码的行号证据） |
| ⚠️ | 来自审计报告的对照扫描，**未逐条复验** —— 动手前需再核一次 |

> 重要：审计基线是 `14b2f59`，距当前 HEAD 已积累 30+ 提交。标 ⚠️ 的条目**有可能是审计方看的是旧代码**。

---

## 2. 批次 1 —— 确凿小 bug（低风险，建议立刻做）

全部 ✅ 实测复验。共同特征：改对了只会让行为更诚实，**不动回测数值**。
其中 ~~M12 / M13 / M17 / M14~~ 已于 2026-10-25 修复、~~L6 / L7 / L8 / M2 / M3 / M9 / M22 / M15 / M18 / M16~~ 已于 2026-10-26 修复（划线条目 = 已修，详见表内证据列）。**批次 1 仅剩 L12 未动**（74 个死 import 需逐个核实，不宜机械删除）。

| # | 问题 | 证据（当前代码） | 影响 |
|---|---|---|---|
| ~~**M13**~~ | ~~**读路径无 CSV 降级**~~ → **✅ 已修** | 原 `:187`/`:322` 裸 `pd.read_parquet`；现共享 `_read_local()`（Parquet→同口径 CSV，两侧对称），`load`/`fetch_and_cache`/`load_index` 全走它；门禁：全文件只允许 1 处 `pd.read_parquet`（`_read_local` 内）。附带修掉"CSV 降级存的数据每轮全量重取"（增量判定此前只认 Parquet） | 已修 + 4 回归用例（`test_optional_deps.py`） |
| ~~**M12**~~ | ~~指数代码前缀映射错~~ → **✅ 已修** | 原 `:73-80`；现 `is_index` 显式声明（不猜：000001/000905 等与个股代码互相占用）+ 指数走 `stock_zh_index_daily` 接口 + 独立命名空间 `historical/index/` + 新 API `load_index()` + CLI `fetch --index`。下游 3 个消费方同步改读指数命名空间（`daily_signal_generator`、`historical_backtest_validator`、`get_trading_calendar`/`core.ensure_calendar`）。**顺带修**：DSG `detect_current_regime` 建日历时写死 CWD `./stock_data`（应跟随实例 `data_dir`；曾因此在测试里写出假 2024 日历，致 29 用例连环失败） | 已修 + 13 回归用例（`tests/test_index_namespace.py` 新建，含源码级门禁：指数代码不得走个股 `load()`） |
| ~~**M17**~~ | ~~`get_cash_flow()` 调的是财务指标 API，不是现金流量表~~ → **✅ 已修（删除）** | 原 `:309` 调 `ak.stock_financial_analysis_indicator`（与 `get_financial_indicator` 同 API）；**零调用方 + 文档零记载**，属"名不副实的死代码"→ 直接删除而非改语义（改语义会新增未被任何生产路径需要的财务接口，且无法离线测） | 已删；若后续需要真现金流量表，应新增明确命名的方法并配 FetchResult |
| ~~**M14**~~ | ~~裸 `except:` 静默失败~~ → **✅ 已修** | 实测 **13 处**（审计记 11，`examples/选股示例.py:48/:101` 另漏计 2）：MFS 8 处（因子附着 5 处 + 权重优化回退 3 处）改 `except Exception as e:` + WARN；`historical_data_manager.py` 元数据损坏改 `(json.JSONDecodeError, OSError)` + WARN（**顺带修掉元数据损坏静默重置**——此前会把"元数据损坏"伪装成"空股票池"）；`get_universe` 日期解析改 `(TypeError, ValueError)`；`realtime_quote._safe_float` 改 `(TypeError, ValueError)`；示例 2 处同理 | 已修 + **门禁**: `tests/test_source_hygiene.py::TestNoBareExcept` AST 扫描 `.claude/skills/**`，新增裸 `except:` 即失败 |
| ~~**L6**~~ | ~~web_app 死 import：`ChartStyle`、`RealTimeMonitor` 各只出现于 import 行~~ → **✅ 已修** | 复验实为 **5 个**（审计记 2，漏计 `numpy as np`、`datetime`/`timedelta`，`:19-20`）；全部删除（`ChartStyle`/`RealTimeMonitor` 亦从 import 中摘除）。顺带核实：仓库根 `run_web_app.py` 的 4 个 import 全在用 | 已修 + 门禁 `TestWebAppImportHygiene`（web_app + run_web_app 任一 import 名不再被 Name 引用即失败） |
| ~~**L7**~~ | ~~`run_web_app.py --run` **解析了从不判断**~~ → **✅ 已修** | `--run` 删除（运行本就是默认行为，解析了却不判断的 flag 纯误导）；**复验新发现**：全仓 argparse AST 扫描另捕 `reversal_detector.py --top` 同病（`--top` 解析后从未生效，"显示Top N"是假的）→ 已接线 `analyze_stocks(stock_pool, top=)`（排序后截断，显示与返回一致，`top=None` 不限保持既有调用兼容） | 已修 + 门禁 `TestArgparseFlagsAreRead`（`.claude/skills/**` + `run_web_app.py` 所有 add_argument dest 必须出现在 `args.<attr>` 读取中） |
| ~~**L8**~~ | ~~`parameter_space` 文档漂移：docstring 说"25个参数 / 指标12个"，实际 **26 个**~~ → **✅ 已修** | 复验三个数互不相等：声明"共25个"、分项和 24（12+4+4+4）、实际 **26**（indicator 13 / scoring 4 / signal 4 / position 5）→ docstring 改 26/13/4/4/5 | 已修 + 门禁 `TestParameterSpaceDocstringCounts`（docstring 总计与分项计数必须与 AST 实际 `ParamDef` 分组数一致，漂移即失败） |
| ~~**M2**~~ | ~~`FitnessConfig.target_probability` 接收并存入 `self`，`_compute_fitness` **从不使用**~~ → **✅ 已修（删除）** | 复验确认零计算路径引用（`optimization_engine.py:108` 存，`:293-354` 从不读）；按 C-P1-17/M17"死代码删除"惯例移除 `FitnessConfig` 字段 + `FitnessEvaluator.__init__` 参数 + `validate` 校验 + `get_fitness_params` 项。**配套**：`_from_dict` 加 `_filter_known` 存量 JSON 兼容层（旧配置文件带该键 → 过滤 + WARN 提示，不再 TypeError 拒载）。若将来真要机会约束型适应度，应显式设计并接入 fitness 公式 | 已删 + 门禁 `test_indicator_skill_p0.py::test_target_probability_dead_field_removed`（字段/属性不存在 + 存量 JSON 兼容加载） |
| ~~**M3**~~ | ~~`generations_run` 记的是**配置上限**而非实际代数~~ → **✅ 已修** | 复验确认三处 `OptimizationResult` 构造（global/regime/robust）全记 `ga_cfg['max_generations']`；`GeneticAlgorithm.run` 循环可提前 break 却只返回 `(best, pop, conv_gen)`，实际代数无处可取 → run 改返回 4 元组加 `generations_run`（= 实际迭代次数）；4 个调用点接线；迭代聚合 `sum(convergence_gen)` 求和是双重错（最后改善代号 ≠ 跑了几代）→ 改 `sum(各轮 generations_run)`；`_record_ga_run`/`save_results` 落盘增 `generations_run` 键，`load_results` 优先读它（旧 JSON 无键退回 convergence_gen 并注明近似）；`_print_result_summary` 增"实际运行代数"行 | 已修 + `tests/test_optimizer_honesty.py::TestM3GenerationsRunActual` 4 用例（提前收敛报实际代数 4≠上限 50 / 无提前收敛==上限 / 源码级门禁禁记配置上限 / 迭代聚合门禁） |
| ~~**M9**~~ | ~~`risk_parity_position(risk_budget=...)` 声明后**函数体从未使用**~~ → **✅ 已修（删参）** | 复验确认零调用方 + 函数体为等风险贡献迭代（无逐资产预算维度）→ 删 `risk_budget` 参数与文档行（默认参数删除，不影响任何调用方） | 已删 + `tests/test_optimizer_honesty.py::TestM9RiskParityDeadParamRemoved` 2 用例（签名无该参 + 等权解行为回归） |
| ~~**M22**~~ | ~~聚合器语义错 + 不可复现：`max_drawdown = max(各股回撤)`（非组合口径）、`random.sample` 无种子、`_get_dominant_regime` 取**全历史**众数体制~~ → **✅ 已修** | 字段改名 `worst_drawdown`（`:51`，不冒充组合回撤），`compare_systems` 列 `'最大回撤%'`→`'最差个股回撤%'`（`:233`），`format_report` 增口径脚注 "最差=…%(最差个股, 非组合回撤)"+"无组合净值曲线"（`:322`）；`evaluate_system(..., seed: int = 42)` + `random.Random(seed).sample`（`:85`），`compare_systems(seed=42)` 透传；`_get_dominant_regime(symbol, regime_labels, window=None)`（`:273`）窗口对齐（调用点 `window=window`，`:144`），窗口内无标签→`"UNKNOWN"`；CLI 加 `--seed` 接到 `args.seed`（`:401`，argparse 门禁要求必读） | 已修 + `tests/test_batch1_m22_m15_m18_m16.py::TestM22*` 4 组（聚合语义/seed 可复现/窗口对齐/源码级 `window=window`） |
| ~~**M15**~~ | ~~`historical_data_manager.get_stock_name` 用 CWD 相对硬编码路径，未复用 `stock_list_manager`~~ → **✅ 已修** | 顶层 `from stock_list_manager import get_stock_name as _lookup_stock_name`（`:38`），`get_stock_name` 走 `__file__` 基准单例（`:731`）；digit 入参 `zfill(6)`（兼容 `int` 1 → 平安银行），查不到返回 `str(symbol)`；batch CLI 改 `get_stock_list().get_all_stocks()`（`:792-793`）。docstring 删掉 `Path(".claude` 字面（防源码级断言误报） | 已修 + `TestM15StockListPath` 3 用例（任意 cwd/整数入参/源码无 CWD 硬编码） |
| ~~**M18**~~ | ~~北交所（8xx/4xx）代码不加 `bj` 前缀 → 裸 6 位码请求新浪，必然取不到数据且异常被吞~~ → **✅ 已修（方案升级）** | **复验推翻原"补 bj 分支"简单方案**：① `ak.stock_zh_a_daily` 对 bj **不可用**（主行情有数据，但 `getAmountBySymbol` 返回 `(null)` → demjson "No value to decode"，实测 bj430047/bj836247）；② 腾讯 fqkline 对 bj `day:[]`、东财 push2his 全 host ConnectionError；③ 股票池无 4/8 码但有 **315 只 920xxx 新码段** → bj 规则 = `4/8/92`。新真相源 `sina_daily.py`：`format_symbol()`（sh/sz/bj，900xxx 等不猜前缀原样返回）+ `fetch_daily()`（bj→新浪 klc 直连解码 + 新浪 qfq/hfq 因子 API，与 akshare 列契约对齐 outstanding_share/turnover 置 NaN 不拿 0 冒充；sh/sz→原样透传 akshare）。因子事件假行（outer+ffill 引入的无价行）按 ffill 前掩码剔除——**与 akshare 的有意差异**（akshare 保留假行）。**5 个调用方全部接线**（SDF `:68` / HDM `:93` / LTS / reversal_backtest / reversal_detector，后 3 个删掉内联 `f'sh{code}'` 与 `import akshare`）。无模块级 ImportError 守卫 → 不触发 `test_optional_deps` 登记门禁 | 已修 + 实网验证（bj920002 raw/qfq/hfq 各 20 行、bj430047 宽窗 1912→2024Q1 38 行、sh600000 透传、未知口径 ValueError）+ `TestM18*` 3 组（前缀规则/路由打桩/bj 离线解码） |
| ~~**M16**~~ | ~~`stock_data_fetcher` 每次取数写一个 `{symbol}_{起}_{止}.csv`，文件数无上限、同内容大量重叠~~ → **✅ 已修（按口径去重，非删写入）** | `_dedupe_quote_cache(symbol, adjust, keep=filename)`（`:83`）先写后删：同 (股票, 口径) 只保留最新一次的文件；文件名 `{symbol}[_qfq\|_hfq]_{起}_{止}.csv`（raw 保持旧格式兼容）→ `get_quote_data` 写入处接线（`:215`）。`market_regime_classifier` 的 glob `{index_code}_*.csv` 两种命名都命中 → **MRC 源码无需改动**（实测兼容） | 已修 + 实网（`get_quote_data('920002')` 两区间 → 仅 1 个 raw + qfq 标签文件；其他股票/qfq 口径不误删）+ `TestM16QuoteCacheDedupe` |
| **L12** | **全仓死 import**（L6 复验时全仓扫描新发现）：**32 个文件共 74 个** import 名未被 Name 引用（如 `ml_predictor` 的 `GridSearchCV/LinearRegression/classification_report`、`vectorized_backtest` 的 `limit_pct_for`、多文件的 `datetime/timedelta/typing` 类） | AST 扫描 2026-10-26，见 `tests/test_source_hygiene.py::_unused_imports` 逻辑 | 低。**动手前需逐个核实**再导出豁免 / `TYPE_CHECKING` / 字符串注解用途；核实后可把 `TestWebAppImportHygiene` 门禁放宽到全仓 |

**建议**：这一批每条都能配一条回归测试，沿用 `tests/test_optional_deps.py` 的"源码级门禁 + 行为断言"模式。

---

## 3. 批次 2 —— 回测数值口径（会改数值，需重新评估黄金快照）

| # | 问题 | 证据 | 备注 |
|---|---|---|---|
| **H8** | 引擎 B 三处结构性偏差：① 重叠买入信号 → 0 持仓日伪交易（`:548-551` 无持仓状态机）② 最小持有期屏蔽退出条件（`min_holding_days` 默认 20，`:492`）③ warmup 吃掉 OOS 窗口 1/3（`:448-450`） | `vectorized_backtest.py` | ⚠️ 需再核 |
| **H9** | 引擎 A 的 walk-forward 无预热、**OOS 结果未拼成净值曲线**（返回每窗 dict 列表，拿不到真正 OOS 绩效） | `backtest_framework.py:748-788` | ⚠️ 需再核 |
| **H7** | 回测引擎内**无流动性/容量约束**（ADV/成交额 0 命中）→ 可在成交量百万股的票上买 1 亿元无惩罚。`trade_constraints` 的 ADV 门槛只作用在信号层 | `backtest_framework.py`、`vectorized_backtest.py` | ⚠️ 需再核 |
| **M1** | 残余指标口径分歧：`win_rate` 分母（B `pnl<=0` 全算输 vs A `len(win)/len(profits)`）、`max_consecutive_losses` 基准（交易序列 vs 日频净值序列） | `vectorized_backtest.py:71-73,112-117` vs `backtest_framework.py:455,495-507` | `core/metrics.py` 只统一了 3 个函数 |
| **M5** | 优化器逐股回测失败**静默 `except Exception: continue`**，无失败计数、无惩罚 → 参数组可能在更少样本上被评估而不受罚 | `optimization_engine.py:161-162,219-220,236-237` | ⚠️ 需再核 |
| **M4** | 短体制窗口冷启动（`ma_slow` 可达 120 > warmup 60）；`min_hold_end` 使止盈/移动止损在体制窗内永不触发 | `vectorized_backtest.py:448-450`、`optimization_engine.py:194-195` | ⚠️ 需再核 |
| **M19** | 日线列名标准化 + `pct_change` 块从 2 处扩散到 **4 处**（从未抽公共函数） | `stock_data_fetcher.py:160-180`、`historical_data_manager.py:265-272`、`long_term_selector.py:194-201`、`reversal_detector.py:179-185` | 低风险，可抽 `core/` 公共函数 |
| **M20** | `long_term_selector` / `reversal_detector` **绕过共享数据层**自行调 `ak.stock_zh_a_daily`：无 adjust 维度、无 as_of、无 FetchResult、无交易日历接入 | `long_term_selector.py:180-207`、`reversal_detector.py:167-189` | 中。与 P0-4 口径矛盾 |

**注意**：这一批会**改变回测数值** → `tests/test_backtest_honesty.py::TestGoldenMetrics` 黄金快照必须重新评估，不能默默更新。

---

## 4. 批次 3 —— 研究有效性（高影响，**需先拍板再动手**）

> 这一批不是"写错了"，是"**这套系统的回测结论目前不能当真**"。改完之后历史结论与现有产出**不可比**。

| # | 问题 | 证据 | 性质 |
|---|---|---|---|
| **H1** ✅ | 优化器**无真样本外验证**：`vectorized_backtest.walk_forward` 已有 `param_space` 分支（IS 拟合能力**已备**），但生产路径不传 → GA 仍在同一批窗口上既评估又取最大 | `optimization_engine.py:156` 调 `walk_forward(...)` **无** `param_space`；`vectorized_backtest.py:669-710` 分支存在但无人调用 | **能力已备、链路未接** —— 接线成本最低的一条 |
| **H3** ✅ | `historical_backtest_validator` 的回测引擎是**死属性**（全文仅 `:86` 一处）；验证参数来自"全历史优化出的"产物 → IS/OOS 隔离仍破；样本按评估结果过滤（`:449-453` `forward_returns[hd] != 0`）；报告区间硬编码（`:504`） | `historical_backtest_validator.py` | 需重做验证链 |
| **H4** ✅ | 幸存者偏差：`get_universe()` **无 `as_of` 参数**，用 `datetime.now()` 回溯到 1996；`stock_selector.get_hot_stocks` 硬编码热门股字典 | `historical_data_manager.py:433-434` `get_universe(min_history_days=5000, min_rows=2000)` —— **无 as_of 参数** | 与 C-P0-7 的 point-in-time 止血契约同源，但因子层没跟上 |
| **H6** ✅ | 多因子权重拟合仍**样本内 + 前瞻收益**（`shift(-1)`），且与 `shift(1)` 的打分口径**互相矛盾** | `multi_factor_selection.py:176`/`:239` `shift(-1)` vs `:411` `shift(1)` —— 口径自相矛盾 | 因子层是选股入口，影响面大 |
| **H2** ✅ | `confidence` 是**硬编码常数**（`0.7`/`min(0.9, fitness*1.2)`/`0.6`/`0.75`），却被 `daily_signal_generator` 当作**生产参数体系的唯一挑选依据** | `optimization_engine.py:810` `confidence=0.7` / `:919` `min(0.9, best.fitness*1.2)` / `:1045` `0.6` / `:1156` `0.75` | 编造的数参与决策 |
| **H10** ✅ | 优化结果无**多重检验校正 / 稳健性证据**：`save_results` 落盘无试验次数、最优 fitness 在随机基线上的分位数、Top-10 参数离散度、bootstrap 置信区间。而 `optimize_global` 3200 次 / `iterative` ~7000 次回测量级 | `optimization_engine.py:1282-1294` 落盘仅 `seed`/`n_stocks`/`fitness_weights`/`param_space`/`ga_runs` —— 无试验次数/分位数/bootstrap | 落盘层补字段成本低 |
| **H5** | 停牌建模**只落在信号层**（`trade_constraints` + `core/trading_calendar.py`），4 套回测引擎侧**完全没接** —— "停牌期间持仓无法平仓"未建模 | `rg 停牌\|suspend` 在 `backtest_framework`/`vectorized_backtest`/`reversal_backtest`/`historical_backtest_validator` → **0 命中**；`execution_model.py:13-14` docstring 自述"停牌: 数据侧无停牌标记" | ✅ 已复验 |

**建议决策点**：H1（接线成本最低、收益最高）与 H10（只改落盘）建议先做；H4/H6 涉及因子层改造，工作量大；H3 需要重做验证链设计。

---

## 5. 批次 4 —— 工程基座与副本治理（需先定方向）

### 5.1 `optimization_package/` 副本已严重分叉 ⚠️

该目录 **gitignored**，`git status` 看不见，但仍在被使用。实测分歧行数：

```
optimization_engine    546 行分歧      signal_generator       509 行
vectorized_backtest    336 行分歧      trend_indicators       206 行
pattern_recognition    185 行分歧      stock_data_fetcher     157 行
historical_data_mgr    189 行分歧      backtest_framework      70 行
```

主链这批改动（IndicatorEngine / Signal 契约 / trade_constraints / adjust 维度）**一行都没过去**。

**决策项**：① 正式废弃（则删除，并在 AGENTS.md 移除相关约定）② 继续维护（则需要一个同步脚本 + 明确的"哪些能力不回灌"清单）③ 改为依赖主链（最干净，但要破它的"自包含"约束）

### 5.2 工程基座 ⚠️

| # | 问题 |
|---|---|
| **L3** | 无 `pyproject.toml` / `setup.py` / `setup.cfg` / `MANIFEST.in`；无 CI（无 `.github/`）→ 无法 `pip install -e .`，也解释了所有路径补丁 |
| **L4** | **11 处 CWD 依赖 `sys.path.append`** 残留（`web_app` 已修）：`sys.path.append('.')` 把整个 CWD 插进全局搜索路径（同名文件可静默劫持导入） |
| **L5** | `test_tool.py` 仍是"import 即执行"脚本：模块级打 akshare 网络、模块级 `exit(1)`、在 CWD 造 `./test_data/`，且文件名匹配 `pytest.ini` 的 `python_files = test_*.py` |
| **L2** | `stock-analysis-skills/package_skills.py` 硬编码他人机器绝对路径 `F:/Users/shiyo/...`，其声明的 7 个技能目录在仓库中一个都不存在 |
| **L9** | `OptimizationConfig` 类名仍双份定义（`optimization_config.py:84` vs `strategy_optimizer.py:41`）→ 遮蔽风险 |
| **L11** | 体制表示混用：`classify()` 返回**字符串**，而 `RegimeWindow.regime` / `RegimeStats.regime` 是**枚举实例**（`Regime.BULL == "BULL"` 为 False） |
| **L10** | VWAP 语义仍错：`core/indicators.py` 是**全样本累积 VWAP**，而 `trend_indicators.vwap` 的 docstring 写"当日累积计算 / 单日数据"，`technical_analyzer.py:122` 却喂 120 根日线 |
| **L1** | `strategy_optimizer` 5 处 `get_param_grid` 与 `ParameterSpace` 仍不一致（参数名 5 处不同、范围 6 处不同、**`sell_threshold` 符号冲突**：grid 用 −5..−2，ParamDef 用 +1..+6）；缺 9 个维度 |

---

## 6. 与 `AGENTS.md` "Still open" 三条的对应

| AGENTS.md 记载 | 本文档对应 | 状态 |
|---|---|---|
| 停牌建模根本限制（无指数数据即无日历） | §2 H5 | 仍开（信号层已落地，撮合层未落地） |
| 线上历史数据批量重取（除权跳空只标记不改写） | — | 仍开。依赖网络与磁盘；`data_cleaner.py` 已就位 |
| 3-way stock-selection unification | §4 H4/H6 | 部分落地（打分引擎按用户决策保持分立）；残留 = 因子层 point-in-time + 权重拟合口径 |
| `technical_analyzer` signals 缺 shift(1) | ⚠️ B L3/L4（`position_analyzer` 连声明都没有） | 仍开（advisory-only，已文档化） |

---

## 7. 建议执行顺序

1. **批 1**（~14 条小 bug）→ 低风险，逐条配回归测试，沿用 `tests/test_optional_deps.py` 的门禁模式
2. **H1 接线** + **H10 落盘字段** → 批次 3 里成本最低、收益最高的两条
3. **批 4.1 决策**（副本：废弃 / 维护 / 依赖主链）→ 阻塞后续所有改动
4. **批 2**（回测数值）→ 一次性做完 + 重新评估黄金快照
5. **H4 / H6 / H3**（研究有效性核心）→ 需先定方案再动

---

## 8. 维护约定

- 本文档是**活台账**：修完一条就划掉（改状态列 / 移到已修区），并同步更新 `AGENTS.md` 的 "Audit fix status"
- 标 ⚠️ 的条目**动手前必须先复验**（审计基线 `14b2f59` 距今已 30+ 提交，可能已过时或误报）
- 每条修复应配**回归测试**，否则下一个 30 提交后又会退回原样 —— 参见 `tests/test_optional_deps.py` 的门禁思路
- 相关入口：`AGENTS.md`（分层/依赖/测试约定）、`docs/skills_layers.md`（三层边界）
