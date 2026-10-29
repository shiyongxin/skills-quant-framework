# 后续待办计划（审计项复核）

> **生成日期**: 2026-10-25（星期日）
> **代码基线**: `e9ea505` — 死代码清理 + 依赖契约修正 (ml_predictor.FeatureEngineer) + 源码卫生门禁
> **测试基线**: 531 passed / 0 skipped（装齐 `pyarrow` + `matplotlib`）
> **最近更新**: 2026-10-29 — **M20 已修 (两个选择器绕过共享数据层)**: 复验订正 (M18 已把它们改到取数层, 但仍绕过 `historical_data_manager`) → 数据层新增 `get_daily_result()` (复权维度 + 参考日 + FetchResult + 交易日历窗口), 两个选择器改走该入口, 缓存键含口径维度; 失败可见 + 无日历降级如实标记; **默认复权口径仍为不复权** (与全仓默认一致, 不改数值) —— "默认用哪个口径"是产品决策 (优化器自身也用不复权), 建议单独议; 测试基线 883 → **903**; 同日早些 **M5 已修** + **M19 已修** + **文档去重**; **2026-10-29** — **M5 已修 (优化器逐股回测失败静默丢弃)**: 复验发现静默 `except` 实为 **3 处** (逐股 walk-forward / 体制逐窗 / 短体制整股), 且"失败"与"体制数据不足(不适用)"被混为一谈 → 逐股记账 + 比例惩罚 (`fitness *= success_rate`) + 硬门槛 (`min_success_rate` 默认 0.5, 低于则归零) + 证据落盘 (`failure_policy` / `systems[].evaluation` / 控制台 `[评估覆盖]`); **零失败时适应度逐位不变** (黄金值 0.1775) → 门禁 17 用例; 测试基线 866 → **883**; 同日早些 **M19 已修** (日线列名标准化 + 涨跌幅派生收口) + **文档去重**; **2026-10-29** — **M19 已修 (日线列名标准化 + 涨跌幅派生收口)**: 复验发现审计严重低估 —— 实测 **9 份列名映射副本 + 6 处涨跌幅派生块** (审计只记 4 处), 且映射已漂移 (3 份含 `成交额` / 6 份不含) → 新建 `core/dataframe.py` 作唯一真相源, 9 站点全部改调, 行为逐位保持 (黄金快照未动); 测试基线 842 → **866**; 同日早些 **文档去重** + 删除 1 个重复测试文件; **2026-10-29** — **文档去重**: `AGENTS.md` 与本文档的重复内容已压缩 (`AGENTS.md` 只留"契约清单 + 指针", 逐条叙事全部留在本文档; 批次 1 之前的已修清单搬入 §9 附录); 同时删除 1 个重复测试文件 (`tests/test_h4_universe_point_in_time.py` = `test_h4_point_in_time_universe.py` 的遗留草稿, 断言为其子集) → 测试基线 861 → **842**; **2026-10-26** — 批次 3 首条 **H1 已修（优化器真样本外验证）**：新增 `optimization_engine.split_is_oos()`，walk-forward 窗口按时间顺序切成 IS（选择用）/ OOS（仅报告）；**适应度只由 IS 窗口计算**，末尾 30% 窗口（`WalkForwardConfig.oos_ratio`）留作样本外，其指标只进 `details['oos']` 与 `systems[].oos` 落盘，**从不参与参数选择** —— 切断"样本外窗口实为样本内"的选择偏差；IS/OOS 两套指标在 IndicatorSystem 字段、控制台摘要、落盘 manifest 三处分列；窗口数不足时如实标记 `available=False`；测试基线 641 → **662**；同日早些 **M1 已修（残余指标口径分歧）**：新增 `core/metrics.win_rate` / `consecutive_streaks` / `max_consecutive_true` 三个单一真相源，引擎 A/B/D 全部改调；A 的连胜/连亏由**日频净值**口径改为**交易序列**口径（与 B 一致，旧日频口径另存为 `max_consecutive_up_days`/`max_consecutive_down_days` 诚实字段），B 补 `max_consecutive_wins` 字段并修掉"连亏统计其实是亏损起始点间隔"的 bug；**引擎 A/B 收益/夏普/回撤/盈亏比等黄金主断言逐位不变**（只改报告字段口径）；测试基线 629 → **641**；同日早些 **H7 已修（回测引擎无流动性/容量约束）**：新增 `execution_model.bar_turnover_amount()` + `capacity_limit_notional()` 共享助手，A 引擎 `PositionConfig.max_volume_participation`（默认 5%）按 当日成交额×占比 截断买入股数，B 引擎 `params['max_volume_participation']` + `params['capital']` 支持逐笔部分成交（`metrics_from_trades` 支持逐笔仓位比例数组，全部相等时走标量路径 → 逐位兼容旧版）；**引擎 A 黄金快照已重评**（ret 20.03%→20.62%、Sharpe 0.810→0.838、MDD 14.19%→14.00%，归因：10 笔买入中 3 笔落在低量日被截断；关闭约束时逐位复现旧值），引擎 B 黄金不变；测试基线 618 → **629**；同日早些 **H9 已修（引擎 A walk-forward）**：测试窗口带预热（`run(warmup_data=)`，策略可见窗口前历史但账户空仓起步）+ 各窗口 OOS 净值曲线拼接（`_stitch_oos_equity`，OOS 总收益 = 各窗逐段复利），实测裸切片 OOS 仅 6 笔 → 带预热 12 笔；测试基线 611 → **618**；同日早些 **H8 已修（引擎 B 三处结构性偏差）**：持仓状态机（重叠买讯不再切出 0 持仓日伪交易）/ `min_holding_days` 默认 20→0（锁定期不再屏蔽退出）/ warmup 跨窗口继承（`backtest(history=)`，OOS 窗口不再被吃前 1/3）；**黄金快照已重评**（引擎 B ret 8.24→12.99、Sharpe 0.707→1.431、MDD 6.52→2.76，归因证明见下表），测试基线 602 → **611**；此前同日批次 1 全部清账（L12 收口 602、M22+M15+M18+M16 599、M2+M3+M9 560、L6+L7+L8 553、M12+M13+M17+M14 2026-10-25 531）
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
其中 ~~M12 / M13 / M17 / M14~~ 已于 2026-10-25 修复、~~L6 / L7 / L8 / M2 / M3 / M9 / M22 / M15 / M18 / M16 / L12~~ 已于 2026-10-26 修复（划线条目 = 已修，详见表内证据列）。**批次 1 至此全部清账**（15/15）。

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
| ~~**L12**~~ | ~~**全仓死 import**（L6 复验时全仓扫描新发现）：**32 个文件共 74 个** import 名未被 Name 引用~~ → **✅ 已修** | skills 树实测 **32 文件 74 名**（与审计一致）+ `tests/` 另扫出 **10 名** → 共删 84 个。**逐名核实先行**（三项阴性检查：无 `__all__` 收录、无 `from <module> import <name>` 重导出、无字符串注解引用 —— 仅 2 处 docstring 叙述提及 `datetime`/`BacktestMetrics` 属文字，删 import 不破文档）；两个**有意保留**改加 `# noqa: F401` 豁免（`tests/conftest.py` 的 `import streamlit` 存在性探测、`test_indicator_skill_p0.py` 的 `plot_stock_chart` 存在性断言）；`_unused_imports` 认 noqa 豁免。**门禁放宽到全仓**：`TestUnusedImportsRepoWide` 3 用例（skills 全树含 examples/ + tests/ + `run_web_app.py`；根级 `test_*.py` 是 gitignored 遗留脚本不入册） | 已修 + 3 门禁用例；编译通过 + 48 模块逐一 import 冒烟（唯 `examples/自动更新数据.py` 缺第三方 `schedule`，与本批无关） |

**建议**：这一批每条都能配一条回归测试，沿用 `tests/test_optional_deps.py` 的"源码级门禁 + 行为断言"模式。

---

## 3. 批次 2 —— 回测数值口径（会改数值，需重新评估黄金快照）

| # | 问题 | 证据 | 备注 |
|---|---|---|---|
| ~~**H8**~~ | ~~引擎 B 三处结构性偏差：① 重叠买入信号 → 0 持仓日伪交易（无持仓状态机）② 最小持有期屏蔽退出条件（`min_holding_days` 默认 20）③ warmup 吃掉 OOS 窗口 1/3~~ → **✅ 已修（黄金快照已重评）** | 复验确认三条全部属实（审计 D-backtest.md B21/B22/B23）：**①** 持仓期终点取"下一次买入信号"→ 密集买讯切出 0 持仓日伪交易；改为**持仓状态机**（空仓才开仓，持仓中新买讯忽略，出场只由止损/追踪/止盈/卖讯/期末决定，与 A 引擎"买入仅当无持仓"同口径）；**②** `min_holding_days` 默认 20 → **0（不锁）**，显式传值时锁定期语义保留（参数空间 `[10,90]` 本就已显式暴露该维，属审计建议的"或纳入参数空间"分支）；**③** warmup 公式提炼为 `warmup_bars()`，新增 `backtest(history=)` —— `walk_forward` 每窗带上**窗口前 60 根历史**，warmup 只落在历史段，OOS 窗口不再被清零前 1/3。**复现对照（同参数）**：① 旧 156 笔/均持仓 2.01 日/Sharpe -0.601 → 新 7 笔/85.7 日/+0.324；③ 旧 OOS 首窗 1 笔 → 新 3 笔 | 已修 + `tests/test_backtest_honesty.py::TestH8StructuralBiases` 9 用例（伪交易/买讯忽略/出场根再入场/默认不锁/显式锁/追踪止损不受锁/history 保活窗口信号/walk_forward 传 history）+ **黄金快照重评**（见下） |
| ~~**H9**~~ | ~~引擎 A 的 walk-forward 无预热、**OOS 结果未拼成净值曲线**（返回每窗 dict 列表，拿不到真正 OOS 绩效）~~ → **✅ 已修** | 复验确认属实（审计 D-backtest.md **B25**）：`test_data = data.iloc[train_end:test_end]` 裸切片，策略在 A 内实时算 MA → 63 根窗口配 `slow=20` 只剩 43 根可用 bar；各窗口结果未拼接 → 无整体 OOS 绩效。**修复**：① `BacktestEngine.run(..., warmup_data=)` —— 策略可见窗口前历史（指标预热）但**账户仍从窗口首根空仓起步**（不带入预热期盈亏），`grid_search`/`walk_forward` 逐层透传（默认 `warmup_period=60`）；② 新增 `_stitch_oos_equity()` —— 各窗口日频净值曲线按资金连续性缩放拼成一条曲线，**OOS 总收益 = 各窗收益逐段复利**（不是平均），并给出聚合 OOS 指标（总收益/年化/夏普/回撤/交易统计/窗口数/OOS bar 数）；`walk_forward` 返回值由"每窗 dict 列表"改为 `{'windows', 'oos', 'oos_equity_curve'}`（该函数**零调用方**，无兼容负担）。**实测对照**（750 根、train 252/test 63、`ma_cross(5,20)`）：裸切片 OOS 仅 **6 笔**（7 个窗口里 3 个零交易）→ 带预热 **12 笔**（仅首个窗口无历史可预热，如实零交易）；OOS 总收益 10.67%→4.98%、Sharpe 0.327→0.050、MDD 12.93%→15.73%（**↓悲观方向** = OOS 不再被结构性削弱，与审计标注一致） | 已修 + `tests/test_backtest_honesty.py::TestH9WalkForwardOS` 7 用例（策略可见预热历史/预热段不参与交易/walk_forward 预热后 OOS 交易更多/返回 OOS 聚合+曲线/OOS 总收益=各窗复利/曲线覆盖全部 OOS bar/无预热时 run() 逐位不变）；**引擎 A 黄金快照逐位不变**（`run()` 无预热路径未改） |
| ~~**H7**~~ | ~~回测引擎内**无流动性/容量约束**（ADV/成交额 0 命中）→ 可在成交量百万股的票上买 1 亿元无惩罚。`trade_constraints` 的 ADV 门槛只作用在信号层~~ → **✅ 已修（黄金快照已重评）** | 复验确认属实（审计 D-backtest.md **B14**）：`成交量` 只用于**信号打分**（放量/缩量），从不用于**成交容量**校验 —— A 的 `_calculate_position_size` 与 B 的 `position_size_pct` 均只受 `max_position_pct`/资金约束。**修复**：新增共享助手 `execution_model.bar_turnover_amount()`（当日成交额：优先 `成交额` 列，缺失时 `成交量×价格` 近似）与 `capacity_limit_notional()`（上限 = 成交额 × 参与率；数据缺失→不限制、当日零成交→上限 0 买不进）；**A** 新增 `PositionConfig.max_volume_participation`（默认 **0.05**）→ 买入股数按上限截断（不足 1 手不买）；**B** 新增 `params['max_volume_participation']`（默认 0.05）+ `params['capital']`（名义资金，默认 100 万，用于把仓位比例折算成金额）→ 逐笔**部分成交**，`metrics_from_trades` 支持逐笔仓位比例数组（全部相等时走标量路径 → 数值与旧版逐位一致）；`TradeDetail` 增 `position_pct` 字段。缺成交量/成交额列时 A 如实记 `capacity_checked=False`（不假装已受限） | 已修 + `tests/test_backtest_honesty.py::TestH7CapacityConstraint` 11 用例（共享助手口径/A 截断/关闭约束回旧行为/零成交日买不进/缺列如实标记/B 部分成交/B 零成交不成交/B 黄金不受影响）+ **引擎 A 黄金快照重评**（见下） |
| ~~**M1**~~ | ~~残余指标口径分歧：`win_rate` 分母（B `pnl<=0` 全算输 vs A `len(win)/len(profits)`）、`max_consecutive_losses` 基准（交易序列 vs 日频净值序列）~~ → **✅ 已修** | **复验订正台账原表述**：`win_rate` 两引擎**公式本就一致**（A 的 `len(profits)` 是全部平仓笔、不是盈利笔 → 两者都是 盈利笔/全部笔），真正分歧是 **breakeven (pnl==0) 的归类**（B 的连亏判定 `pnl<=0` 把 0 当亏、A 的 `lose_trades` 用 `p<0` 不当亏）；`max_consecutive_losses` **确为两套口径**（审计 B48）：A 统计在**日频净值**序列、B 统计在**交易**序列 → 同名字段两义。**修复**：① `core/metrics.py` 新增单一真相源 `win_rate()`（盈利笔/全部笔，breakeven 计分母不算赢）、`consecutive_streaks()`（**交易序列**上的连胜/连亏笔数：赢=pnl>0、亏=pnl<0、breakeven 两者都不算并打断连段）、`max_consecutive_true()`（布尔序列连段，供日频连涨/连跌用）；② 引擎 A/B/D 全部改调 core（A 的 `max_consecutive_wins/losses` 由日频净值口径改为**交易序列**口径，旧日频口径另以**诚实字段名** `max_consecutive_up_days`/`max_consecutive_down_days` 保留（持平 bar 不算涨，旧实现 `value>=prev` 把持平日算成涨）；③ 引擎 B `BacktestMetrics` 补 `max_consecutive_wins`（旧版字段缺失、与 A 不对等）；④ **顺带修掉引擎 B 的连亏统计 bug**：旧实现 `np.diff(np.where(is_loss))` 统计的是"亏损起始点之间的间隔"，既不是连亏笔数也不是连亏段数（两笔相邻亏损恒报 1、两笔不相邻的亏损反而报 2）；⑤ gitignored 的 `optimization_package/` 副本同步（自包含本地助手，无 core 依赖） | 已修 + `tests/test_backtest_honesty.py::TestM1MetricConventions` 12 用例（core 语义/breakeven 归类/gap bug 反证/引擎 A 交易级连段/诚实字段名/引擎 B 与 core 一致/跨引擎同一组交易同结论/引擎 D 语义不变/源码级门禁禁内联胜率与连段计算）+ **引擎 A 黄金快照增补连段数值**（见下） |
| ~~**M5**~~ | ~~优化器逐股回测失败**静默 `except Exception: continue`**，无失败计数、无惩罚 → 参数组可能在更少样本上被评估而不受罚~~ → **✅ 已修** | **复验: 属实且面更宽** —— 静默 `except` 共 **3 处** (审计只记逐股 1 处): ① `FitnessEvaluator.evaluate()` 逐股 walk-forward 失败 → `continue`; ② `_backtest_regime_windows()` 体制窗内逐窗失败 → `continue`; ③ `_backtest_by_trade_filter()` 整股失败 → `return []`。且"失败"与"该股体制数据不足(不适用)"被混为一谈 | 已修: ① **逐股记账** (失败/跳过分列: `n_stocks_failed`/`n_failed_events`/`n_stocks_skipped`/`success_rate`/`failures` 含 symbol+异常类型+消息); ② **比例惩罚** `fitness *= success_rate` + **硬门槛** (成功率 < `FitnessConfig.min_success_rate` (默认 0.5) → 归零, 避免"崩一半"的参数组挤掉"完整但平庸"的参数组); ③ 体制路径失败向上冒泡 (两处内部 helper 改返回 `(metrics, failures)`); ④ 证据落盘: manifest 顶层 `failure_policy` + `systems[].evaluation` + 控制台 `[评估覆盖]` 行 + `IndicatorSystem` 4 个覆盖字段; ⑤ 契约变更: 无 IS 窗口时 details 不再为空 (改为带覆盖记账; `is_metrics` 键仍不出现, H1 口径不变) → 门禁 `tests/test_m5_evaluation_failures.py` **17 用例** (计数/清单/跳过不计失败/比例惩罚/硬门槛/门槛可配/体制两路径上报/**零失败适应度逐位不变** (黄金值 0.1775)/覆盖字段/跨体制聚合/manifest 口径 + 源码级: 评估路径不得再出现静默 `except: continue`/`return []`) |
| **M4** | 短体制窗口冷启动（`ma_slow` 可达 120 > warmup 60）；`min_hold_end` 使止盈/移动止损在体制窗内永不触发 | `vectorized_backtest.py:448-450`、`optimization_engine.py:194-195` | ⚠️ 需再核 |
| ~~**M19**~~ | ~~日线列名标准化 + `pct_change` 块从 2 处扩散到 **4 处**（从未抽公共函数）~~ → **✅ 已修** | **复验: 审计严重低估** —— 审计记 4 处, 实测 **9 份列名映射副本** (`stock_data_fetcher` / `historical_data_manager` 个股+指数 / `long_term_selector` / `reversal_detector` / `historical_backtest_validator` ×2 / `market_regime_classifier` / `reversal_backtest` / `data_cleaner.COLUMN_ALIASES`) + **6 处 `涨跌幅` 派生块** (`stock_data_fetcher` ×2 / `historical_data_manager` ×2 / `position_analyzer` / `data_cleaner`); 且**已漂移**: 映射 3 份含 `成交额` / 6 份不含 (同一份数据经不同模块 → 不同列集), 涨跌幅 5 处不转数值 / 1 处 `to_numeric`, 5 处"缺失才补" / 1 处无条件覆盖 | 已修: 新建 `core/dataframe.py` (`OHLCV_COLUMN_MAP` 唯一映射 + `standardize_ohlcv_columns` / `sort_by_date` / `change_pct` / `ensure_change_pct` / `standardize_daily_frame`), **9 站点全部改调**; 行为**逐位保持** (三处语义差异显式保留: 不消费涨跌幅的模块 `add_change=False` 不补该列; `position_analyzer` `overwrite=True` 无条件重算; `data_cleaner` CSV 路径 `coerce=True` 转数值) → 门禁 `tests/test_m19_column_standardization.py` **24 用例** (AST 禁自带映射 + AST 禁直接赋 `涨跌幅` + 接线核对 9 站 + 行为语义 + **与旧内联实现逐位等价**) |
| ~~**M20**~~ | ~~`long_term_selector` / `reversal_detector` **绕过共享数据层**自行调 `ak.stock_zh_a_daily`：无 adjust 维度、无 as_of、无 FetchResult、无交易日历接入~~ → **✅ 已修** | **复验订正**: M18 已把两者从 `ak.stock_zh_a_daily` 改到 `sina_daily.fetch_daily`, 但仍**绕过 `historical_data_manager` 这一共享数据层** → 四项缺口属实: ① 无复权维度 (硬编码不复权 → 除权跳空进收益率/指标, 与 P0-4 矛盾); ② 无 as_of (窗口用 `datetime.now()` → 前视 + 不可复现); ③ 无 FetchResult (失败与"数据不足"一律 `return None`, 调用方无法区分); ④ 无交易日历 (窗口靠 `days*2` 自然日启发式) | 已修: ① 数据层新增 **`get_daily_result()`** (复权维度 + 参考日 + FetchResult + 交易日历窗口 + `meta` 口径); ② 两个选择器改走该入口 (缓存键含 `(code, adjust, as_of)` 维度 → 不按旧口径串味); ③ 取数窗口按**交易日**换算 (无本地指数日历 → 降级自然日并在 `meta['calendar_used']=False` **如实标记**, 不静默); ④ 失败可见 (FetchResult 带 error + `[WARN]` 打印原因); ⑤ 日历现算**不落盘** (不污染仓库目录) → 门禁 `tests/test_m20_shared_data_layer.py` **20 用例** (源码级: 不得再直接引取数层/自行划 wall clock 窗口 + 行为级: 口径落 result/窗口裁剪/参考日透传/交易日换算/无日历降级标记/失败可见/缓存按维度) |

**注意**：这一批会**改变回测数值** → `tests/test_backtest_honesty.py::TestGoldenMetrics` 黄金快照必须重新评估，不能默默更新。
（M19 是例外: 纯重构, **不改任何数值** → 黄金快照未动, 门禁用"与旧内联实现逐位等价"断言兜底。）

**H8 黄金快照重评记录（2026-10-26，引擎 B，seed=3 / n=300）**：

| 指标 | 旧快照 | 新快照 | 归因 |
|---|---|---|---|
| total_return | 8.2434717354 | **12.9931644423** | ② 默认不锁 |
| sharpe_ratio | 0.7067662023 | **1.4310959923** | ② |
| max_drawdown | 6.5168484346 | **2.7612192058** | ② |
| profit_factor | 2.4186901536 | **6.4859394632** | ② |
| num_trades / win_rate | 2 / 50.0 | 2 / 50.0（不变） | — |

归因证明（非猜测）：① 持仓状态机在黄金数据上**数值中性** —— 显式传 `min_holding_days=20` 时新实现与旧实现**逐位一致**（ret 8.2434717354 / sharpe 0.7067662023 / mdd 6.5168484346 / pf 2.4186901536，交易同为 143→158 stop_loss −8.17% 与 168→189 take_profit +19.77%），已固化为 `test_engine_b_golden_with_explicit_min_holding_lock`；③ history 只在 `walk_forward` 生效，`backtest()` 默认路径逐位不变。漂移**全部**来自 ②：同一笔持仓（bar143 入场）在旧默认下追踪止损被 20 日锁屏蔽 → 扛到 bar158 硬止损 −8.17%，新默认下 bar145 追踪止损 −3.05%（小亏不拖成大亏，回撤 6.52%→2.76%）。**新快照更诚实**：不再用"隐式锁定期"把止损出场推迟。

**M1 黄金快照说明（2026-10-26，引擎 A）**：M1 只改**报告字段口径**（连胜/连亏改为交易序列口径 + 新增日频连涨/连跌字段），**不触碰撮合与收益口径** → 引擎 A/B 的 `total_return`/`sharpe_ratio`/`max_drawdown`/`profit_factor`/`num_trades` **全部逐位不变**（黄金快照主断言未改）；仅新增/改写的连段字段被锁定：`max_consecutive_losses` 3（旧日频口径 4）、`max_consecutive_wins` 1（旧 35）、`max_consecutive_up_days` 8、`max_consecutive_down_days` 4（持平 bar 不算涨）。引擎 B 侧：`max_consecutive_losses` 因 gap bug 修正由旧值 1 → 正确值（黄金数据 2 笔交易，1 盈 1 亏 → 连亏 1、连胜 1），并新增 `max_consecutive_wins` 字段。

**H7 黄金快照重评记录（2026-10-26，引擎 A，seed=3 / n=300）**：

| 指标 | 旧快照 | 新快照 | 归因 |
|---|---|---|---|
| total_return | 20.0267552369 | **20.6168802842** | 容量约束 |
| sharpe_ratio | 0.8098904709 | **0.8380161593** | 容量约束 |
| max_drawdown | 14.1949051746 | **13.9992960062** | 容量约束 |
| trade_count / win_rate / profit_factor | 9 / 33.33 / 1.2589570136 | 9 / 33.33 / 1.2589570136（不变） | — |

归因证明：黄金数据 10 笔买入中 **3 笔落在低成交额日被截断**（2022-02-03: 97300→93100 股；2022-08-04: 89800→64800 股；2022-10-26: 85700→71800 股 —— 上限 = 当日成交额×5%），仓位变小 → 收益/夏普略升、回撤略降；**关闭容量约束（`max_volume_participation=0`）时新实现与修复前逐位一致**（ret 20.0267552369 / sharpe 0.8098904709 / mdd 14.1949051746 / trades 9 / len(trades) 19 / pf 1.2589570136），已固化为 `test_engine_a_golden_without_capacity_constraint` → 漂移**全部**来自容量约束本身，与撮合/指标口径无关。**引擎 B 黄金快照逐位不变**（两笔入场日成交额 ≈4856万/4156万，5% 上限 242万/207万 > 名义 80万 → 不截断；已固化为 `test_engine_b_golden_unaffected_by_capacity`）。**新快照更诚实**：低量日的买入不再按"想买多少买多少"成交。

---

## 4. 批次 3 —— 研究有效性（高影响，**需先拍板再动手**）

> 这一批不是"写错了"，是"**这套系统的回测结论目前不能当真**"。改完之后历史结论与现有产出**不可比**。
> 进度：**H1 已拍板并落地**（2026-10-26，见下方明细）；**H10 已落地**（2026-10-26，见下方明细）；**H2 已落地**（2026-10-26，见下方明细）；**H5 已落地**（2026-10-26，见下方明细）；**H6 已落地**（2026-10-26，见下方明细）；**H4 已落地**（2026-10-26，见下方明细）；**H3 已落地**（2026-10-26，见下方明细）；**批次 3 全部收口**。

| # | 问题 | 证据 | 性质 |
|---|---|---|---|
| ~~**H1**~~ | ~~优化器**无真样本外验证**：GA 在同一批 walk-forward 窗口上既评估又取最大，"样本外"窗口实为样本内~~ → **✅ 已修（真样本外隔离）** | 复验确认属实（审计 E-optimization-portfolio §3.1 第 1/2 条）：`walk_forward` 的 `train_days` 只用于"跳过前 N 行"，训练段从未用于拟合；fitness = 各测试窗口指标聚合，而 GA 又在**同一批窗口**上取最大 → 全流程无未被触碰的留出集 | 已修 + `tests/test_h1_oos_isolation.py` 21 用例；明细见下方说明 |
| ~~**H3**~~ | ~~`historical_backtest_validator` 的回测引擎是**死属性**（全文仅 `:86` 一处）；验证参数来自"全历史优化出的"产物 → IS/OOS 隔离仍破；样本按评估结果过滤（`:449-453` `forward_returns[hd] != 0`）；报告区间硬编码（`:504`）~~ → **✅ 已修（验证链重做）** | 复验属实且更具体：① `self.backtester` 全文仅实例化、**从未使用** → 挂着"回测引擎"却从不回测；② manifest **已落盘** `data_start`/`data_end`（优化器 E-P0-3 落的），而验证器**从不读** → pick 日期可能落在参数拟合区间内（参数已见过这些日期的数据）；③ `!= 0` 过滤把"无数据哨兵"与"真实 0 收益"混为一谈 → 真实 0 样本被静默丢弃、覆盖率不可见；④ 报告写死 `"评估范围: 1996-01 ~ 2026-06"` 与 180 天 | 已修 + `tests/test_h3_validation_chain.py` 32 用例；明细见下方说明 |
| ~~**H4**~~ | ~~幸存者偏差：`get_universe()` **无 `as_of` 参数**，用 `datetime.now()` 回溯到 1996；`stock_selector.get_hot_stocks` 硬编码热门股字典~~ → **✅ 已修（point-in-time 股票池）** | 复验属实：`get_universe(min_history_days=5000, min_rows=2000)` 确无 as_of，`cutoff_date = datetime.now() - timedelta(days=min_history_days)` → ① 用"今天"描述"历史"（前视）② 同一份代码不同时间跑出**不同股票池**（不可复现）；`get_hot_stocks` 的 35 只名单是人工挑的板块股（ai/chip/new_energy/military/consumer/finance/tmt），与任何日期无关 | 已修 + `tests/test_h4_point_in_time_universe.py` 23 用例；明细见下方说明 |
| ~~**H6**~~ | ~~多因子权重拟合仍**样本内 + 前瞻收益**（`shift(-1)`），且与 `shift(1)` 的打分口径**互相矛盾**~~ → **✅ 已修（同期配对 + 样本外显式化）** | 复验属实且比审计更严重：`factors_df` 的 index 是**股票代码**（横截面）→ 那些 `shift` 是沿**股票轴**的错行配对（配的是"第 i 只股票的因子 × **第 i+1 只股票**的收益"），既非"下一期收益"也非前瞻，且**权重随行序变化**（实测同一输入换行序 → factor_returns 均值 −0.0151 → −0.0071）；三条路径对同一份 `returns` 用了三种配对 | 已修 + `tests/test_h6_factor_point_in_time.py` 23 用例；明细见下方说明 |
| ~~**H2**~~ | ~~`confidence` 是**硬编码常数**（`0.7`/`min(0.9, fitness*1.2)`/`0.6`/`0.75`），却被 `daily_signal_generator` 当作**生产参数体系的唯一挑选依据**~~ → **✅ 已修（证据派生）** | 复验确认属实：4 个构造点的 confidence 与任何证据无关（全局/稳健/迭代是纯常数，体制路径是无出处的 `×1.2` 放大），`daily_signal_generator.load_systems:363` 用它裁决同体制多系统的取舍 | 已修 + `tests/test_h2_confidence.py` 16 用例；明细见下方说明 |
| ~~**H10**~~ | ~~优化结果无**多重检验校正 / 稳健性证据**：`save_results` 落盘无试验次数、最优 fitness 在随机基线上的分位数、Top-10 参数离散度、bootstrap 置信区间。而 `optimize_global` 3200 次 / `iterative` ~7000 次回测量级~~ → **✅ 已修（稳健性证据落盘）** | 复验确认属实：落盘仅 `seed`/`n_stocks`/`fitness_weights`/`param_space`/`ga_runs` —— 无试验次数/分位数/bootstrap | 已修 + `tests/test_h10_robustness.py` 32 用例；明细见下方说明 |
| ~~**H5**~~ | ~~停牌建模**只落在信号层**（`trade_constraints` + `core/trading_calendar.py`），4 套回测引擎侧**完全没接** —— "停牌期间持仓无法平仓"未建模~~ → **✅ 已修（引擎侧停牌建模）** | 复验确认属实：`rg 停牌\|suspend` 在 `backtest_framework`/`vectorized_backtest`/`reversal_backtest`/`historical_backtest_validator` → **0 命中**；`execution_model.py` docstring 自述"停牌: 数据侧无停牌标记 …… 不虚构交易日历" | 已修 + `tests/test_h5_suspension.py` 29 用例；明细见下方说明 |

**建议决策点**：~~H1（接线成本最低、收益最高）~~ **✅ 已做（2026-10-26，见下方明细）**；~~H10（只改落盘）~~ **✅ 已做（2026-10-26，见下方明细）**；~~H2（编造常数参与生产裁决）~~ **✅ 已做（2026-10-26，见下方明细）**；~~H3（验证链重做）~~ **✅ 已做（2026-10-26，见下方明细）**；~~H4（point-in-time 股票池）~~ **✅ 已做（2026-10-26，见下方明细）**；~~H6（因子层前瞻/样本内口径）~~ **✅ 已做（2026-10-26，见下方明细）**；~~H5（引擎侧停牌建模）~~ **✅ 已做（2026-10-26，见下方明细）**。

**H1 修复明细（2026-10-26，真样本外隔离）**：

| 环节 | 做法 |
|---|---|
| ① 窗口切分 | 新增 `optimization_engine.split_is_oos(windows, oos_ratio)` —— 按时间顺序把回测窗口切成 **IS（选择用）/ OOS（仅报告）**，末尾 `oos_ratio` 比例的窗口留作样本外；窗口数 < 2 或 ratio ≤ 0 → 无 OOS（调用方如实标记） |
| ② 选择隔离 | `FitnessEvaluator.evaluate` 的**适应度只由 IS 窗口计算**（旧 `_compute_fitness(all_metrics)` → `_compute_fitness(is_metrics)`）；OOS 指标只进 `details['oos']`，**从不参与参数选择** —— GA 的选择偏差来源被切断（体制路径同样按时间顺序切分） |
| ③ 指标分列 | `IndicatorSystem` 增 `oos_*` 字段（IS 选择口径 / OOS 验证口径）；`save_results` 落盘 `systems[].oos` + 顶层 `oos_policy`（隔离口径可审计）；`load_results` 读回；控制台摘要打印 `[样本外 OOS]` 行 |
| ④ 稳健模式 | `_aggregate_oos` 跨体制汇总样本外证据 + `details['regime_oos']` 保留各体制块（不丢证据） |
| ⑤ 配置与诚实性 | `WalkForwardConfig.oos_ratio`（默认 **0.3**，走配置层三级优先级；0 = 关闭隔离仅供对照）；窗口数不足时**如实标记** `available=False` + 原因，不静默假装有样本外证据 |

端到端实测：3 股 × 4 窗 → 9 IS + 3 OOS，控制台摘要与落盘 manifest 均分列。

> **为什么不接 `walk_forward(param_space=...)` 分支**（与台账原"能力已备、链路未接"表述的偏离说明）：该分支的语义是"每窗在训练段重新网格拟合指定维度，**拟合值覆盖 GA 候选值**"。若把它接到 GA 生产路径，被评估的参数（每窗拟合值）与最终**部署**的参数（GA 的 `best.params`）**不是同一套** → 报告出来的 OOS 指标无法代表部署参数的表现 = 制造新的口径冒充。本框架部署的是**固定参数**（`optimized_params` → `signal_generator`），没有逐窗重估的等价实现，因此正确做法是把 **GA 定位为 IS 拟合器**、给它一份**从未参与拟合的留出窗口**（即本次修复），`param_space` 分支保留为"自适应策略"研究工具，不接生产选择路径。另：`train_days` 段在修复后仍只是"窗口前置丢弃期（指标预热）"，不再是拟合段 —— `walk_forward` docstring 已按此口径改写。

**H10 修复明细（2026-10-26，稳健性证据落盘）**：

| 环节 | 做法 |
|---|---|
| ① 试验次数 | `IndicatorSystem.robustness['n_selection_evaluations']` = 参与"取最大"的评估数（基线/bootstrap 以 `track=False` 调用 → **不计入**）；manifest 顶层 `n_evaluations_total` = 各轮 `ga_runs[].n_evals` 之和 |
| ② 随机基线 | `_random_baseline(stage, evaluate_fn, n_samples, best_fitness)` —— 随机参数经**同一评估闭包**（同一 IS 口径，不触碰 OOS）产出适应度分布 → 落盘 `fitness_mean/std/p50/p90/best_fitness/best_percentile`（最优值在基线分布中的分位数）；独立 RNG 子流 `f'{stage}:baseline'` → **不扰动 GA 搜索**（同 seed 基线开关 on/off 参数逐位一致，已测） |
| ③ Top-k 离散度 | `_top_k_dispersion(entries, k)`（staticmethod）—— 全程被评估参数按适应度取前 k，逐维 `min/max/range/mean/std(ddof=1)` + `fitness_values`/`fitness_spread`；空集 → `available=False` + 原因 |
| ④ bootstrap CI | `_bootstrap_fitness_ci(stage, evaluate_fn, best_params, n_boot)` —— 最优参数的 **IS 窗口重采样** 95% percentile CI；稳健模式按体制分层，组合口径走 **`FitnessEvaluator._robust_combine`（0.7×min+0.3×avg，从闭包提炼 → 与搜索同源，防口径冒充）**；窗口 < 2 或 `n_bootstrap=0` → 诚实标 `available=False` + 原因 |
| ⑤ 落盘与读回 | `save_results`：`systems[].robustness` + 顶层 `robustness_policy`（`n_baseline_samples`/`top_k`/`n_bootstrap` + "不参与选择"注记）+ `n_evaluations_total`；`load_results` 读回（旧 JSON 无键 → 空 dict，不编造）；`_print_result_summary` 打印 `[稳健性证据]` 块（不可用时打印 reason） |
| ⑥ 配置接线 | `optimization_config.RobustnessConfig`（出厂 100/10/500，0 = 关闭→如实标 unavailable）三级优先级：显式 kwargs > config > 引擎默认；`_from_dict` 走 `_filter_known` 存量 JSON 兼容（M2 同款） |
| ⑦ 顺带修复 H1 遗留 | `optimize_robust` 的 `evaluate_robust` 原写 `self._aggregate_oos(...)` —— 该方法在 `FitnessEvaluator` 上 → **有体制标签的稳健模式必 `AttributeError`**（H1 测试仅源码级断言，未跑行为路径 → 潜伏）；改 `self.evaluator._aggregate_oos(...)`，并加行为回归用例（spy 证明 OOS 汇总路径真的被执行） |

关键设计约束：**证据只在选择之后组装**（`_finalize_robustness` 在 `ga.run` 返回后调用，恰好 1 次/阶段，有源码级门禁）——基线/bootstrap 的评估**不进选择计数、不进 top-k、不参与取最大**，因此不改变搜索结果（核心门禁：同 seed 基线 on/off `best.params` 逐位一致）。不落任何"校正后 p 值"（无多次检验原始统计量，编一个比不给更糟）——只落**可解释的证据**。

端到端实测：global 阶段 `n_selection_evaluations=4`（= GA pop×gen）+ 基线 3 次 = 评估器总调用 7 次（分账正确）；manifest `n_evaluations_total` = `sum(ga_runs n_evals)`；稳健模式 1000 行 × 双体制全链路跑通（GA + 基线 + 分层 bootstrap + 落盘/读回）。

**H2 修复明细（2026-10-26，confidence 证据派生）**：

| 环节 | 做法 |
|---|---|
| ① 单一真相源 | 新增 `optimization_engine.confidence_from_fitness(fitness)` —— `confidence = clamp01(适应度)`：GA **实际最大化的目标值本身**（`FitnessConfig` 加权和，权重和为 1，来自真实回测窗口指标：达标率/中位收益分/中位夏普分/回撤分）。刻度：<0 → 0，[0,1] → 原值，>1 → 1（防御性夹取） |
| ② 四个构造点 | global / by_regime / robust / iterative 全部改调该函数（`optimization_engine.py` 4 处 `confidence=`）；旧值 `0.7` / `min(0.9, f*1.2)` / `0.6` / `0.75` 全部废止 —— 其中 3 个是纯常数（与任何证据无关），体制路径的 `×1.2` 是无出处放大 |
| ③ 语义声明 | `IndicatorSystem.confidence` 字段注释 + 函数 docstring 均如实写明：**不是统计校准的置信概率**，而是适应度的 [0,1] 夹取值（避免换个名字继续骗人）；manifest 顶层加 `confidence_policy`（`formula: clamp01(fitness)` + 说明），与 `oos_policy` / `robustness_policy` 同款自证 |
| ④ 消费端 | `daily_signal_generator.load_systems` 的同体制裁决改由证据驱动（新 manifest：confidence 随适应度；旧 manifest：原值读入不改写）。局限已在代码注释写明：**不同系统的适应度来自各自选择窗口**（全局系 = 全窗口，体制系 = 该体制窗口），横向比较是近似裁决而非严格排序 |
| ⑤ 历史兼容 | `load_results` 对旧 manifest 的硬编码 confidence **原样读取**（历史数据不改写、不"纠正"成 clamp01(fitness)）—— 否则等于篡改历史实验记录 |
| ⑥ 门禁 | `tests/test_h2_confidence.py` 16 用例：夹取语义 / 四阶段构造值 == clamp01(适应度)（桩评估器定值断言）/ 高适应度饱和到 1 / DSG 裁决三态（高者胜、平局先到先得、**低适应度专用系统不再凭"专用型"身份压过高适应度全局系统**）/ 旧 manifest 原样读回 / save→load 往返 / 源码级 AST 门禁（`confidence=` 只允许 `confidence_from_fitness(...)` 或 `sys_data['confidence']` 两种形态 + 4 个旧硬编码字面量不得复现） |

效果：生产裁决依据从"编造的常数"变为"GA 实际最大化的适应度"——同一份 manifest 下，旧实现里**专用型系统几乎恒胜**（`min(0.9, f*1.2)` 常 ≥ 全局常数 0.7），现按证据裁决（适应度低的专用系统不再顶掉适应度高的全局系统）。

**H5 修复明细（2026-10-26，引擎侧停牌建模）**：

| 环节 | 做法 |
|---|---|
| ① 单一真相源 | 新建 `core/suspension.py`：`SuspensionModel` 由**真实交易日历** + 个股行情行推导真停牌日（个股在日历中有、自身无行）→ 复用 `TradingCalendar.missing_trading_days`（日历经已排除节假日，不误伤）；`trading_day_index()` 给出交易日→bar 的**前向填充**映射（停牌日沿用上一根 bar，无价格即无 P&L，精确口径） |
| ② 引擎 A | `BacktestEngine.run(..., trading_calendar=)`：停牌日不撮合（挂单顺延、止损止盈跳过）+ **净值曲线按交易日对齐**（停牌日市值持平）→ 年化分母用交易日数、夏普按每交易日口径 → 修正停牌导致的**年化/夏普虚高**；逐笔记录 `suspended_days`；结果增 `suspension_modeled`/`suspension_days`/`suspension_blocked_bars`/`equity_aligned_to_trading_days` |
| ③ 引擎 B | `VectorizedBacktester.backtest(..., trading_calendar=)`：`metrics_from_trades` 增 `trading_day_index` 参数（可选）→ 年化分母用交易日数、日频收益按交易日对齐（停牌日 0 收益）；`TradeDetail.suspended_days` + `BacktestMetrics.suspension_days`/`suspension_trading_days` |
| ④ 引擎 D | `ReversalBacktester.backtest_single(..., trading_calendar=)`：停牌日不撮合；**期末停牌 → 不可平仓 → 按盯市计入收益**（不虚构成交、不计卖出费用）；结果增 `suspension_modeled`/`suspension_days`/`suspension_blocked_bars`/`suspension_holding_days` |
| ⑤ 引擎 E | `HistoricalBacktestValidator.calculate_forward_return(..., trading_calendar=)`：持有期由**个股 bar 数**改为**交易日**（旧实现 `actual_days = min(holding_days, len(stock_data)-1)` → 停牌把窗口静默拉长，60 根 bar 可能横跨 75 个交易日 → 不同个股实际持有期不可比、"持有 N 天"名不副实）；到期日停牌 → 顺延到下一个可交易日（现实：卖不掉只能继续持有），顺延交易日数如实记录进 `ValidationReport.suspension`；无指数数据 → 无日历 → **如实回退旧口径**（不臆造日历） |
| ⑥ 诚实边界 | **无日历 = 不建模**（`suspension_modeled=False`），默认路径与旧版**逐位一致**（黄金快照未变）；日历**显式传入**（不隐式取全局日历 —— 否则回测结果依赖环境文件，破坏 E-P0-3 可复现性）；停牌日**不补成平盘行再算指标**（那会让 MA/RSI 窗口被假 bar 污染，指标仍在真实 bar 上算，只把**时间轴**换成交易日轴） |
| ⑦ 门禁 | `tests/test_h5_suspension.py` 29 用例：core 语义（真停牌日推导/节假日不误伤/前向填充映射）+ 引擎 A/B/D/E 行为（建模开关、总收益与回撤不变、年化按交易日修正、逐笔敞口、期末不可平仓、顺延记录）+ 源码级门禁（4 引擎签名均含 `trading_calendar`、默认 None 不隐式取日历、`execution_model` docstring 的旧自述必须更新、4 引擎统一走 `core/suspension.py`） |

关键修复（此前被静默压扁的口径）：**年化收益/夏普的分母**。旧实现按 **bar 数**计（`252/days`、`years = n/252`）→ 停牌 10 天真实时间流逝了，引擎却当没发生 → 年化与夏普**虚高**。现按**交易日**计（停牌日市值持平、收益率 0），实测同一份数据：引擎 A 年化 −10.08% → **−8.66%**，引擎 B 年化 −4.86% → **−4.59%**（总收益与最大回撤逐位不变 —— 停牌不产生价格）。

**H6 修复明细（2026-10-26，因子层点时口径）**：

| 环节 | 做法 |
|---|---|
| ① 复验（比审计更严重） | `factors_df` 的 index = **股票代码**（横截面）→ `factor_data[col].shift(-1) * aligned_returns` 实际配的是"第 i 只股票的因子 × **第 i+1 只股票**的收益"：既不是"下一期收益"（审计原话）也不是前瞻，而是**沿股票轴的错行配对** → 权重结果**依赖输入行序**（实测换行序：factor_returns 均值 −0.0151 → −0.0071）。`test_all_factors` 的 `.shift(1)` 同病（且注释写的是时序语义"t-1 期因子"，与横截面数据不符） |
| ② 配对单一真相源 | 新增 `FactorWeightingMethod._align(factors_df, returns)` —— **同期配对**（同一行 = 同一只股票/同一期），全仓唯一入口；`ic_weights` / `max_sharpe_weights` / `risk_parity_weights` 三处全部改调（旧的 `.shift(-1)` 废止） |
| ③ 标签口径唯一真相源 | 新增模块级 `forward_returns(close)` —— 构造 **t → t+1 前瞻收益**标签（末行 NaN）。避免误用 `pct_change()`（后向收益）当标签：后向收益会让 IC 变成"因子解释已发生的收益"，看起来很好但没有预测力 |
| ④ 检验口径显式化 | `test_all_factors(factors_df, returns, window=None)`：`window=None` → **横截面口径**（同期配对，单截面 → 时序统计量 ic_std/ir/t 检验**不可得**，如实记 NaN + `is_significant=False`）；`window=N` → **时序口径**（滚动 IC，且**要求 index 为时间索引**，股票代码轴直接 `ValueError` —— 绝不用代码轴做滚动窗口）。新增 `FactorTestResult.mode` 自证口径 |
| ⑤ 样本内/样本外显式化 | `get_composite_score(factors_df, returns, fitted_weights=None, fit_returns=None)`：① 传 `fitted_weights`（历史样本拟合好的权重）→ 直接套用，样本外；② 传 `fit_returns`（历史期标签）→ 样本外拟合；③ 只传 `returns` → **样本内** → 打印 `[WARN] 因子权重为**样本内拟合**…` 并记 `last_weight_fit={'in_sample': True, 'n_fit_rows': N}`；④ 无标签 → 回退配置权重（不静默用等权冒充"拟合结果"）。选股结果经 `attrs['weight_fit']` 携带口径 |
| ⑥ 门禁 | `tests/test_h6_factor_point_in_time.py` 23 用例：**行序不变性**（max_sharpe / risk_parity / ic 权重与检验 IC 在输入行序置换后**逐位不变** —— 旧实现不满足，是最硬的行为门禁）+ 同期配对语义（有预测力的因子拿到更高权重）+ 横截面统计量如实 NaN + 时序口径强制时间索引 + 样本内标记/告警/`fit_returns`/`fitted_weights` 三态 + 源码级 AST 门禁（配对与检验函数内不得出现 `.shift(`，错行配对无法复现） |

效果：因子权重从"依赖行序的错行乘积"变为"与标签同期配对的真实因子收益"；样本内拟合不再沉默 —— 调用方要么显式声明样本外，要么被 `[WARN]` 标出。

**H4 修复明细（2026-10-26，point-in-time 股票池）**：

| 环节 | 做法 |
|---|---|
| ① 单一真相源（参考日） | 新增 `HistoricalDataManager._reference_date(as_of)`：显式 `as_of` 优先，否则取**缓存最新日**（本地数据实际覆盖到的最新日期）—— **不再用 `datetime.now()`**（既是前视，又让同一份代码在不同时间跑出不同股票池 → 不可复现） |
| ② point-in-time 判定 | `get_universe(min_history_days, min_rows, as_of=None)`：as_of 口径下该股须 ① 当时**已上市**（`first_date ≤ as_of − min_history_days`，历史长度判据相对 **as_of** 而非 now）② **数据覆盖到 as_of**（`last_date ≥ as_of` → 排除"当时还没上市/已退市"的股票 = 消除前视与截断偏差） |
| ③ 拒绝静默有偏 | 缓存不覆盖 `as_of` → **ValueError**（部分覆盖的股票池 = 静默有偏的股票池）；缺 `as_of` → 保持旧调用兼容（当前视角） |
| ④ 幸存者偏差如实标记 | 新增 `get_universe_meta(...)` → 输出口径元数据（参考日 / 缓存覆盖区间 / 池子规模）并**标记 `survivorship_bias=True`**：本地缓存只含**当前在市**的股票 → 当时已退市的股票根本不在池内 → 任何 as_of 口径都**仍带幸存者偏差**（需退市股历史行情才能消除，本地数据做不到 → 只能标记，不能假装没有） |
| ⑤ 手写热门股名单 → 数据驱动 | `stock_selector.get_hot_stocks` 删掉 35 只人工板块名单（ai/chip/new_energy/military/consumer/finance/tmt）→ 改为从**本地缓存股票池**按最近 period 个交易日涨幅排序（无网络、可复现、支持 `as_of` 截断）；缓存不可用 → **如实返回空列表 + `[WARN]`**，不再用手写名单顶替；`market` 过滤语义保留 |
| ⑥ 验证器接线 | `HistoricalBacktestValidator.validate(..., universe_as_of=)` → 股票池走 PIT 口径；`ValidationReport.universe_meta` + JSON 输出携带股票池口径与幸存者偏差标记（报告里看得见，而不是只打印）；**调用方自带股票池** → 如实标 `source=caller_supplied` + `survivorship_bias=None`（不假装核查过） |
| ⑦ 门禁 | `tests/test_h4_point_in_time_universe.py` 23 用例：参考日=数据驱动（停更股票不进池；旧实现会进）/ as_of 三个排除规则（上市晚、无数据、历史不足）/ 超出覆盖报错 / meta 字段与偏差标记 / 手写名单**代码对**不得复现 + 主题键不得复现 / 热门榜按涨幅排序 + 空缓存如实空列表 + market 过滤 + as_of 截断 / 源码级 AST 门禁（`get_universe`/`_reference_date`/`get_universe_meta` 内不得出现 `.now()` 调用 → wall clock 无法回潮） |

**根本限制（如实保留）**：本地缓存只含当前在市的股票，**退市股的历史行情本地没有** → 幸存者偏差**无法用本地数据消除**，本批做的是"消除前视 + 消除不可复现 + 把残余偏差显式标记出来"。要把偏差真正压到 0，需要补齐退市股历史行情（外部数据源），属批次 4 的数据基建范畴。

**H3 修复明细（2026-10-26，验证链重做）**（用户 2026-10-26 拍板：① 段1 默认严格"无样本外日期 → 不出验证结论"；② 段2 每-pick 点时池默认开；③ 产出出口 CLI + web 都要）：

| 环节 | 做法 |
|---|---|
| ① 死属性清零（段 0） | 删 `self.backtester = VectorizedBacktester()` 与相应 import；类 docstring 自证"本引擎**不做回测**"（评估口径是买入持有前瞻收益，与 4 套回测引擎不是一回事）→ 不再借一个死属性暗示两者等价 |
| ② 样本外隔离（段 1，核心） | `_load_systems` 增读 manifest 的 `data_start`/`data_end`（优化器 E-P0-3 已落盘）→ `self._param_fit_range`；`select_pick_dates(oos_only=)` **只在拟合区间终点之后**的交易日里均匀取日期；**默认严格**：拟合区间未知 或 之后无可用日期 → **不出验证结论**（返回结构完整的空报告 + 明确原因，不返回 None 让调用方自己猜）；`allow_in_sample=True` 才允许退化为样本内（报告标 ⚠️ + 原因含拟合区间）；CLI 新增 `--allow-in-sample` |
| ③ 股票池点时（段 2） | `universe_mode='per_pick'`（默认）→ **每个 pick 日期用该日期的 PIT 池**（旧实现一个池覆盖所有日期 → 对最早的日期是未来视角）；`'single'` 保留统一池（快但有偏，如实标记 mode）；点时池门槛改为 `UNIVERSE_MIN_HISTORY_DAYS=504` / `UNIVERSE_MIN_ROWS=252`（**相对 as_of**，旧值 5000/2000 是墙钟锚定口径，套到历史日期上既过严又错位）；池覆盖不足（H4 严格口径抛错）→ 跳过该日期并记录 `universe_meta['skipped_dates']`，**不用部分覆盖的池顶替** |
| ④ 覆盖度记账（段 3） | `HistoricalPick` 增 `n_picks` / `n_evaluated`（逐股计数）/ `n_missing` / `valid`；报告与 JSON 带 `coverage`（每持有期的有效 pick 数 / 总 pick 数 / 覆盖率）→ 结论"基于几个样本"看得见 |
| ⑤ 聚合去哨兵过滤（段 4） | 聚合层不再用 `forward_returns[hd] != 0` 判有效性 → 改用显式 `valid[hd]` 标记；**真实中位收益恰为 0 的 pick 现在被正确计入**（旧口径静默丢弃）；聚合项增 `n_valid_picks`/`n_picks_total`；覆盖度不足（无有效 pick）→ 该持有期不出聚合数字 |
| ⑥ 报告自证（段 5） | "评估范围"由**实际数据**推导（pick 日期 min/max + 参数拟合区间），删除写死的 `"1996-01 ~ 2026-06 (30年A股数据)"`；"关键结论"与明细表改用**主口径持有期** `primary_holding_days`（可传参，默认取 holding 列表中位项；旧实现写死 180 天）；报告头新增**【口径自证】块**（样本外与否+原因 / 股票池口径+幸存者偏差 / 停牌建模+顺延次数 / 有效样本覆盖）；无聚合 → 报告直接写"【无验证结论】"并给出原因 |
| ⑦ web 出口（段 6） | web_app 新增 **🧪 历史验证** 页（导航 + 路由 + 渲染）：读 `stock_data/historical_validation.json`，展示同一套口径自证 + 按持有期统计 + 跑赢基准 + 关键结论（含有效样本数）+ 推荐明细（逐 pick 收益与有效样本）；无结论时如实提示；表格统一走 `st_fill_width(st.dataframe)` 兼容层（streamlit 1.37 已移除 `use_container_width`）；CLI JSON 落盘增 `oos`/`coverage`/`primary_holding_days` 与逐 pick 覆盖度字段；CLI 异常不再裸崩（打印错误 + 完整 traceback 后退出 1） |
| ⑧ 门禁 | `tests/test_h3_validation_chain.py` 32 用例：死属性 AST 清零（无 `self.backtester` 赋值 / 无 `VectorizedBacktester` import / docstring 自证）/ 拟合区间读自 manifest + 旧 manifest 标未知 / pick 日期必须晚于 data_end + 之后无日期即空 / **未知拟合区间默认不出结论**（显式 allow_in_sample 才退化为样本内）/ 真实 0 收益样本计入 + 数据不足标 invalid + 覆盖度记账 / per_pick 与 single 两种池口径 / 报告不含写死区间串 + 含真实区间 + 口径自证块 + 主口径持有期可传 + 无结论时写明 / 点时池覆盖不足跳过该日期 / web 页导航+路由+口径自证项+st_fill_width+JSON 读取容错 / 端到端字段齐备 |

**口径修正的诚实说明（不是"更好/更差"的方向性结论）**：段 4/5 会让历史报告数字**变化**（原先被 `!= 0` 过滤掉的真实 0 收益样本现在计入；覆盖度不足的持有期不再输出基于少数样本的数字）；段 3 会让**可用 pick 日期大幅减少**（参数拟合通常覆盖整段历史 → 之后可能没日期）→ 报告常显"无法构造样本外验证"，这是**诚实结果而非缺陷**（要真正验证需重新做一次只用历史前半段的参数拟合）。

---

## 5. 批次 4 —— 工程基座与副本治理（需先定方向）

### 5.1 `optimization_package/` 副本治理 —— ✅ 已决策并落地（2026-10-26，选③「依赖主链」）

**决策**：**③ 改为依赖主链** —— 主链 `.claude/skills/` 是唯一真相源；本目录的 `skills/` 降级为**构建产物**（由 `pack.py` 自动生成，**请勿手改**）。不选①废弃（README 承诺的"整目录复制到其他电脑离线跑"是真实交付形态，且成本已被压到一次 `pack.py`），不选②维护（不变量级复制 + gitignored = 每次改动必然隐形漂移，已实证 7 个批次）。

**决策依据（实测，非推测）**：

| 事实 | 证据 |
|---|---|
| 副本已漂移 **5000+ 行**，且**不含任何已审计修复** | `optimization_engine` 1106 行 / `vectorized_backtest` 690 / `historical_data_manager` 577 / `signal_generator` 466 / `backtest_framework` 411 …（台账旧记录 546/336/… 已严重低估）；`split_is_oos`/`confidence_from_fitness`/`core.suspension`/`trading_day_index`/`get_universe_meta` 在副本中**命中 0 文件** |
| 副本可 import → **陈旧产物冒充最新** | 现存副本自包含可运行，但它跑的是**未审计语义**（无 H1 样本外隔离 / 无 H2 证据 / 无 H5 停牌 / 无 H6 点时 / 无 H4 PIT 池），产出的 `optimization_result.json` 可被主链 `optimized_params`/`daily_signal_generator` 直接加载 → **未审计逻辑污染已审计主链** |
| 旧 `pack.py` **已断链**，打包产物连 import 都过不去 | 手写清单漏 `execution_model`/`factor_library`/`sina_daily`/`stock_list_manager`/`trade_constraints` + 整个 `core/` → 实测 `ModuleNotFoundError: No module named 'execution_model'` |
| `indicator_system_report.py` **只在副本存在**、主链无源 | `pack.py` 对它 `[SKIP]` → 产物缺报告生成器（副本 `run_optimize.py` 依赖它出报告） |
| 副本从未跑出过结果 | `optimization_package/stock_data` = **0B**，无 `optimization_result.json`/reports → 部署链路长期处于"能打包但没人验证过"状态 |

**落地动作**：

| 动作 | 做法 |
|---|---|
| ① 打包工具**移入主链** + 改依赖闭包自动打包 | 旧 `pack.py` 在 gitignored 目录里 → **构建工具本身不受版本控制**（治理不可复现/评审）→ 移入 `.claude/skills/tools/pack.py`（**受跟踪**）+ AST 递归闭包 → 结构上不可能再漏依赖；整包复制 `core/` 子包；带戳头注入（"由 pack.py 生成, 请勿手改"，幂等） |
| ② 版本戳 `PROVENANCE.json` | 写源 commit + 生成时间 + 每文件 sha256 → 部署包**自带"来自哪个版本"的证据**，陈旧产物无法冒充最新（可核对 `source_commit`） |
| ③ 孤儿模块并入主链 | `indicator_system_report.py`（518 行，自包含、主链无源）→ 并入 `.claude/skills/` 成为唯一真相源 → 打包自动收录，产物不再缺报告器（需给 `.gitignore` 的 `*_report.py` 加**单文件**豁免 —— 该规则本为拦一次性生成脚本；注意 gitignore **不支持行尾注释**，豁免与注释须分行） |
| ④ 副本重打一次 | 用新 `pack.py` 重打 → 副本**一次性对齐主链**（含 H1/H2/H4/H5/H6 修复 + `core/`）→ 副本从此不再是"另一个真相源" |
| ⑤ README 改写定位 | 头部加"构建产物, 请勿手改"告示 + provenance 核对方法 + "旧版副本不含这些修复, 别用旧包产出的参数"警告 |
| ⑥ 门禁 | 新建 `tests/test_package_parity.py`（16 用例）：打包产物**可 import** + 内容与主链**逐字节一致**（除戳头）+ PROVENANCE 完整（源 commit + 每文件 sha256）+ 入口模块主链必须存在（孤儿清零）+ 闭包解析回归（双扩展名 bug）+ **打包脚本必须被 git 跟踪**（构建工具不可游离于版本控制外）+ 副本里不得残留 pack.py；工作区副本若陈旧 → **可检出**（sha256 不符）但**不阻塞**（该目录 gitignored，不是仓库内容，不该让每次提交都红） |

**残余风险（如实记录）**：副本仍 gitignored → 克隆仓库后需重跑 `pack.py` 才有包（README 已写明）；副本内的 `run_optimize.py`/`fetch_data.py` 等**入口脚本不在闭包内**（它们是包自己的胶水层，非主链模块），其与主链新 API 的兼容性需在真跑一次完整优化流程时验证（目前无数据可跑，0B）。

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

### 5.3 数据基建 —— 退市股历史行情（消除幸存者偏差的前提）⚠️

| # | 问题 | 证据 | 备注 |
|---|---|---|---|
| **D1** | 本地缓存只含**当前在市**股票 → 任何 `as_of` 口径的股票池**都仍带幸存者偏差**（当时已退市的股票根本不在池内） | §4 H4 修复明细的"根本限制"段 + `get_universe_meta()` 的 `survivorship_bias=True` 标记 | **无法用本地数据消除**，只能标记。消除需补齐退市股历史行情（外部数据源：交易所历史文件 / 第三方归档）。**动手前先确认数据源可得性与复权口径** —— 否则做出来是"看起来无偏"的新坑 |

> 现状：H4 已把偏差**显式化**（`survivorship_bias=True` + `universe_meta` 落盘），D1 是把标记变成事实的前置条件。

---

## 6. 与 `AGENTS.md` "仍开" 清单的对应

> 2026-10-29 起 `AGENTS.md` 的 "Still open" 已压缩为 6 条摘要（本文不重复其叙事），对应关系：

| AGENTS.md 摘要条目 | 本文档对应 | 状态 |
|---|---|---|
| 批次 2 余量 (M5 / M4 / M19 / M20) | §3 | **仍开**；M5/M4 标 ⚠️（动手前先复验，审计基线距今 30+ 提交） |
| 批次 4.2 工程基座 (L1/L2/L3/L4/L5/L9/L10/L11) | §5.2 | **仍开** |
| 停牌建模根本限制（无指数数据即无日历） | §4 H5 | **部分收口**（引擎侧已落地：`core/suspension.py` + 4 引擎接线），但**无日历 = 不建模**（`suspension_modeled=False`）—— 日历来源仍依赖指数数据/本地缓存 |
| 幸存者偏差无法本地消除 | §4 H4 根本限制 + §5.3 D1 | **仍开**（H4 已把偏差显式标记；消除需外部数据源） |
| 线上历史数据批量重取（除权跳空只标记不改写） | — | **仍开**。依赖网络与磁盘；`data_cleaner.py` 已就位 |
| `technical_analyzer` signals 缺 `shift(1)` | ⚠️ B L3/L4（`position_analyzer` 连声明都没有） | **仍开**（advisory-only，已文档化） |

> 批次 1 之前的已修项（原 `AGENTS.md` 的 "Fixed" 长清单）已搬入 §9 附录。

---

## 7. 建议执行顺序

1. **批 1**（~14 条小 bug）→ 低风险，逐条配回归测试，沿用 `tests/test_optional_deps.py` 的门禁模式
2. ~~**H1 接线** + **H10 落盘字段** → 批次 3 里成本最低、收益最高的两条~~ **✅ 两条均已落地（2026-10-26）**
3. **批 4.1 决策**（副本：废弃 / 维护 / 依赖主链）→ 阻塞后续所有改动
4. **批 2**（回测数值）→ 一次性做完 + 重新评估黄金快照
5. ~~**H3**（验证链重做）~~ **✅ 已做（2026-10-26，见下方明细）** —— 批次 3 至此全部收口

---

## 8. 维护约定

- 本文档是**活台账**：修完一条就划掉（改状态列 / 移到已修区）
- **与 `AGENTS.md` 的分工**（2026-10-29 确立，避免两处重复维护）：台账 = 逐条证据 / 复验置信度 / 归因 / 修复明细（唯一真相源）；`AGENTS.md` = 契约清单（"勿回退"约束 + 对应门禁文件）+ 指针，**不重复台账的逐条叙事**
- 标 ⚠️ 的条目**动手前必须先复验**（审计基线 `14b2f59` 距今已 30+ 提交，可能已过时或误报）
- 每条修复应配**回归测试**，否则下一个 30 提交后又会退回原样 —— 参见 `tests/test_optional_deps.py` 的门禁思路
- 相关入口：`AGENTS.md`（分层/依赖/测试约定）、`docs/skills_layers.md`（三层边界）

---

## 9. 附录 —— 批次 1 之前的已修审计项 (基线 `14b2f59`→`e9ea505`)

> 本节原为 `AGENTS.md` 的 "Audit fix status / Fixed" 清单 (2026-10-29 压缩 AGENTS.md 时搬入台账, **逐字保留**)。这些条目**早于**本台账的 4 个批次 → 当初无逐条复验记录, 已被后续批次的门禁间接回归覆盖 (相关门禁见 `tests/`)。

pattern-recognition layer, Flask duplicate route, optional-dep guards, `strategy_optimizer` executability, `signal_generator` pandas≥3 + tier signals, 4-engine t+1 fills + costs + limit-up/down (`execution_model.py`), ml_predictor time-series split, `database_manager:667` precedence, RSI/profit-factor/MDD unification (`core/`), walk-forward IS/OOS (`param_space` arg), Chikou lookahead, MACD true-cross, cache key `days` dimension, `batch_save_stock_quotes` symbol param, `FetchResult` type + `get_quote_result` (项 11), `concurrent_fetcher` empty-data counts as failed, `historical_data_manager` API failure warns (no silent stale-as-fresh), `optimization_engine.load_data` raises on 0 loaded (no more false "[OK] 成功加载 0 只"), `market_regime_classifier` trend thresholds live + min_segment hysteresis + adaptive first-year NaN fix, ATR 4-way divergence → core Wilder (incl. `pattern_recognition` single-bar-TR bug + `keltner_channel` ATR overwrite guard), remaining 8 RSI sites → core, realtime quote 成交额 万元→元 + 日期/时间字段语义, fallback `adjust`/volume-unit alignment, `FitnessConfig.w_*` wired into `FitnessEvaluator` (项 19), `SKILL.md` rewritten against real API (P0-7), FetchResult caller migration (technical_analyzer/position_analyzer/quant_workflow/web_app/real_time_monitor/multi_stock_backtester/cache_manager warm_up surface failure reasons + skip counts), risk wiring into order path (项 20: `PortfolioManager` 集中度/现金闸门阻断下单 + rebalance 超限阻断 + `StopLossManager`/`PortfolioRiskMonitor` 接线 + HHI 双刻度统一; `vectorized_backtest` `max_position_pct` clamp (默认1.0不改黄金快照); `PositionConfig` 无上限警告 + 工厂配置显式约束), `reversal_rules.py` 单一真相源统一实盘/回测反转规则 (C-P1-13: 阈值/背离窗口/判定闸门互斥一致, 回测补齐 RSI24/Vol_MA20/ROC/ATR/趋势衰竭, 删自比较死代码块), 可复现性种子+manifest 落盘 (C-P1-15), 死代码删除 (C-P1-17: MFS `technical_factor`、SS `min_market_cap` 空分支、DSG `top_n` 参数、SG `middle` 变量; `--top` CLI 接通 `format_report`), 7 模块端到端回归 (C-P2-19: 输出结构契约 + 点时截断无未来函数 + 训练/测试无重叠, `tests/test_e2e_regression.py`), 优化器可复现 (E-P0-3/4: `OptimizationEngine(seed=)` 按阶段派生独立子流、CLI `--seed` 默认42、`save_results` 落盘 seed/适应度权重/参数空间指纹/数据起止/GA 运行元数据; GA 初始种群/交叉变异子代/最优解全部 `ParameterSpace.repair` + validate 断言), 财务 point-in-time 止血契约 (C-P0-7: MFS `select_stocks`/`multi_factor_select` 强制『公告日』列 + `as_of` 参数, 缺列即 `ValueError`, 按公告日≤as_of 过滤且 NaT 剔除, `filter_point_in_time` 单一入口), MFS 因子修复 (C-P0-4/5, 落于 `34e6a41`; 合成数据实测验证 2026-10-22: momentum/volatility 经 `_price_cross_section` 横截面非 NaN, `weighting_method` 默认 `'custom'` 真读 `factor_weights` 且全 NaN 列跳过+缺因子重归一化, `optimize_weights` 真返回), 杂项清扫批次 (F-P1/F-P2/A-P1-4/A-P2-6: 删零引用死模板 `templates/backtest_ui.html`; `web_app.py` sys.path 改 `__file__` 基准 + 导入失败显式错误页含完整 traceback (st.stop), 不再静默降级; 根目录 29 篇遗留报告/手册 `git mv` 进 `docs/` 只留 8 篇入口文档并修链接; `stock_data_fetcher` 历史行情文档"腾讯接口"订正为新浪源 `stock_zh_a_daily` (腾讯仅实时行情), CLAUDE/README 移除无支撑的"10倍性能"宣称并标注 database_manager/concurrent_fetcher/realtime_quote 无生产调用方; `realtime_quote.get_quotes` 行号下标 → 按内容 `v_(\w{6})=` 正则匹配, 修缺行全体错位), B-report P2 批次 (审计 #9-14: `position_analyzer.analyze_position` `days` 参数透传修复 (便捷函数+类方法双层, 原静默失效恒 120); `pattern_recognition.analyze_patterns` `price_position` 改取价格下方最近支撑/上方最近压力 (修 vs_resistance=-30.9% 荒谬负值, 新增 nearest_support/nearest_resistance 字段); 列名契约统一 (technical_analyzer 补 `MACD_Hist` 产出 + `EMA20` 别名, position_analyzer 补 `MACD_Hist`, chart_visualizer 两处读取兜底缺列); `advanced_indicators.obv` O(n) 循环 → numpy cumsum 向量化 (首元素语义保留); `pattern_recognition.scan_all_patterns` 逐行 .loc O(n²) → 单次 numpy 向量化 (与逐条形态函数逐行等价断言), 5 个形态函数 (is_doji/is_morning_star/is_evening_star/is_piercing/is_dark_cloud) 返回类型统一 dict; trend_indicators 删 5 个 0 调用方孤儿 (adaptive_ma/KAMA, mcginley_dynamic, triple_screen, abands, all_trend_indicators, 连带清理 _core_* import); advanced_indicators.calculate_all 默认列表补 mass_index; `docs/skills_layers.md` 分层架构文档 (C-P2-16: L1 选股/L2 择时/信号层边界 + 列名契约 + 变更守则, README 文档导航接入), 孤岛模块清理 (项 15, 用户决策: 删 `web_backtest.py`/`database_manager.py`/`concurrent_fetcher.py`/`cache_manager.py`/`batch_query_sectors.py` 连同测试与文档入口, redis/psycopg2/SQLAlchemy 依赖移出 web_requirements; 保留 `realtime_quote.py` 待接入 web_app 实时监控页), web presentation P2 批次 (审计 #18-20: Streamlit 假数据/桩清除 — 仪表盘 3 个硬编码假指标改真实信号聚合+组合 manager 聚合, 监控页整页桩 (假指标 3/12/5/2 + 3 条假列表) 改接 `realtime_quote.RealTimeQuoteAPI.get_quotes(watchlist)` 真实行情+涨跌幅告警阈值, 组合页 3 个"开发中"按钮接 `rebalance`/`get_performance`/`generate_report` 真实 API, `get_stock_name` 硬编码 10 只改 stock_list.csv 懒加载全量 5523 只; `chart_visualizer` 上岗 — 分析页 95 行内联 matplotlib 4 图 + 回测页净值曲线内联图全部委托 `session_state.visualizer` (K线/MACD/RSI/布林带/综合分析/信号图 6 类, 综合分析占位符补实, matplotlib 缺失降级 None+提示), 实例化加 ImportError 守卫; 买卖点语义 — `plot_signals` `== True` 改 `fillna(0).astype(bool)` (int 0/1 信号列安全, 与回测引擎同源), web 信号图直接用 `generator.generate_signals` 同一真相源, 原 web_backtest 加权阈值错配随项15 删除消亡; `tests/test_web_presentation_p2.py` 14 用例), 因子库统一 (C-P1-11, 用户决策: 打分引擎分立不合并 — 新建 `factor_library.py` 叶子库收敛 MFS/SS 原始因子计算 (momentum/volatility/downside_vol/max_drawdown/volume + `FACTOR_REGISTRY` 方向元数据, z-score 留 MFS、0-100 绝对分留 SS), SS `min_score` 语义与单票场景保留; 权重/阈值外置 `config/stock_selector.json` + `config/multi_factor.json` (出厂值=内置默认, 显式传参最高优先), `LTS` 原样保留; `tests/test_factor_library.py` 24 用例含新旧内联逐位等价断言)), 速赢批 (C-P1-14: MFS `growth_factor` 删 ROE/毛利率双计 — 两指标原在 growth+quality 重复合计有效权重 18.3%, 归一 quality, 成长块留营收/利润增长率+净利率; E-P1: `strategy_optimizer.bayesian_optimize` → `random_sampling` 诚实更名 (旧实现为 random.uniform 均匀采样非贝叶斯), 保留兼容别名 + `optimize()` 分派 "bayesian" 历史名, 删 `OptimizationConfig` 零引用 `cv`/`n_jobs` 死字段, 模块 docstring/进度文案改随机采样; B-P2: `.claude/skills/requirements.txt` 分析层依赖清单 (scipy/akshare 顶层 import 核心 + pyarrow 运行时 + matplotlib/sklearn 守卫可选), web_requirements 陈旧依赖标注同步; `tests/test_factor_library.py` 增 3 用例 + `tests/test_stage2_fix_regressions.py::TestStrategyOptimizerHonesty` 增 5 用例), 交易约束过滤器 (C-P1-12: 新建 `trade_constraints.py` 7 模块共用前置检查 — 一字板复用 execution_model 限板真相源 (高==低近似一字板, 买仅阻涨停/卖仅阻跌停, 30/68→20%、ST 5% 可传), 零成交末 bar 停牌嫌疑常开, as_of+max_stale_days 默认关 (无交易日历防节假日误伤), min_price 默认 1.0 开, ADV 下限默认关 (历史成交额单位未清洗防误杀), 目标金额 ADV 占比上限, 市值无数据诚实记 skipped; 接线: S1 `get_latest_signal` 加 executable/blocked_reasons/skipped_checks + `format_signal_report` 阻断行 (历史信号列不动, 黄金快照不受影响), S2 `StockSignal` 标注 + `generate_daily_report` 过滤 (total_analyzed 记过滤前分析数, 调用签名不动), S3 `select_stocks` 排序前收盘面板过滤 (min_price + 末列 NaN 停牌嫌疑; price_df=None 路径不变), S4 `screen_stocks`/`filter_by_criteria` 丢弃阻断标的 (文件内无 min_market_cap 字样, 不破 C-P1-17 合同), S5 `StockAnalysis` 标注 + `select_stocks` SKIP, S6 `ReversalAlert` 标注 + `analyze_stocks` SKIP, S7 `PredictionResult` 标注 (预测不丢弃); `config/trade_constraints.json` 出厂值=内置默认; `tests/test_trade_constraints.py` 38 用例), 优化器指标口径统一 (E-P1 #15/#20: `vectorized_backtest.metrics_from_trades` 提炼为模块级共享真相源 (B `_simulate_trades` 指标块改调用, 黄金快照逐位不变), `FitnessEvaluator._compute_metrics_from_trades` 48 行复制块删除改调用 — 年化分母从整只股票全历史改为过滤后交易暴露跨度 [首笔入场,末笔出场], MDD/Sharpe 从逐笔复利序列改为日频盯市净值 (与 B 同构造, core 函数), 仓位系数补 `max_position_pct` clamp, 逐笔冒充日频夏普的 `252/mean_hold` 公式与 placeholder 死代码删除; `tests/test_backtest_honesty.py` 增 8 用例含共享函数↔B 逐位等价 + 源码诚实性), 优化器配置接线 (E-P1 #16: `optimization_config.py` 影子配置复活 — `OptimizationEngine(config=)` 真读 mode/ga/fitness/walk_forward/iterative_rounds, 三级优先级 显式CLI/kwargs > config.* > 阶段分档默认 (不传 config 行为逐位不变), 新 `run --config` config-first 子命令 (mode 分派, n_stocks=stock_sample_size, labels=regime_labels_file, 轮数=len(iterative_rounds)), `--pop/--gen/--regime-labels` argparse 默认改 None 防遮蔽 config, FitnessEvaluator 增 `walk_forward_config` (evaluate 旧硬编码 504/180/63 入配置), save_results manifest 记 `config{name,mode,version}`; `tests/test_optimizer_config_wiring.py` 19 用例), 优化器评分制死维度接线 (E-P1 #19 P1-1: `vectorized_backtest.weighted_factor_scores` 移植已删 web_backtest 评分制 (4 因子 0-100 加权, 卖方=100-买方镜像, 无未来函数), `_generate_signals` 双模式开关 `use_weighted_scoring` 默认 False 保 B 引擎/黄金快照逐位不变; 优化器路径 `OptimizationEngine._eval_params` 在 4 阶段 evaluate 闭包注入默认 True — parameter_space 6 个评分维 (w_*/score_*) 从噪声维度变活, `OptimizationConfig.use_weighted_scoring` 可关回旧投票基线; 镜像分默认 60/35 档存在 [60,65] 卖出优先冲突带 (参数空间默认值未动, GA 可自调; 语义测试用非重叠阈值); web_app/signal_generator 生产侧仍投票制 — 评分消费端接入为后续批次; `tests/test_weighted_scoring.py` 14 用例), 参数下发契约 + signal_generator 评分双模式 (E-P1 #19 闭环 P1+P2: 新建 `optimized_params.py` — `load_optimized_params` 从 save_results JSON 提取 systems[].params (优先全局/唯一系统, 多体制系统强制显式 regime=, 未知键软校验, use_weighted_scoring 显式参数 > JSON 顶层键 (save_results 新增落盘) > 缺键默认 True), `list_systems` 选择摘要; `SignalGenerator(use_weighted_scoring=False 出厂, scoring_params=)` 双模式 — 分项 7 信号列照常产出仅作报告明细, 综合信号走 `weighted_factor_scores` 列名适配 (MA5/MA10/MACD/RSI/K/BB_* → ma_*/…, MA10 缺失就地 rolling 补算, 缺关键列 ValueError 不软降级), warmup 与引擎同口径, strength 改评分差/10 保持 -10..10 报告尺度; 便捷函数 `generate_signals/get_latest_signal(data, params=None)` 直通下发字典, 默认 None 生产调用方零变化; `tests/test_params_delivery.py` 17 用例), web_app 优化参数加载入口 (E-P1 #19 收尾: 侧边栏 `🎯 优化参数` 区 — `list_systems` 探测结果文件 + 体制系统选择 (自动=全局优先) + 加载/清除按钮; 加载成功 `st.session_state.generator` 换 `generator_from_params(params)` 实例, 首页/分析页交易信号/信号图/回测多因子 4 个调用面零改动跟随, 清除回出厂 `SignalGenerator()`; `generator_from_params` 由私有转公开契约入口; `tests/test_params_delivery.py` 20 用例含 web 源码级接线断言)), 可选依赖降级路径契约 (系统性盲区收口: `tests/test_optional_deps.py` 16 用例 + AST 门禁 — 新增模块级 `except ImportError` 守卫未登记契约即失败; 配套修 web_app 顶层 streamlit 无守卫 / historical_data_manager CSV 降级丢复权维度 / data_cleaner 只扫 parquet / run_web_app.py 依赖清单脱节 4 个真 bug), L6/L7/L8 诚实性批 (web_app 5 死 import 删除 / run_web_app `--run` 删除 + reversal_detector `--top` 接线 / parameter_space docstring 计数修正 26/13/4/4/5; 3 源码级门禁见 `tests/test_source_hygiene.py`), M2/M3/M9 优化器诚实性批 (`target_probability` 死配置删除 + 存量 JSON 兼容过滤 / `generations_run` 改记实际代数 (GA run 4 元组 + 落盘增键 + 迭代聚合修正) / `risk_parity_position` 死参删除; `tests/test_optimizer_honesty.py`), M22/M15/M18/M16 诚实性批 (multi_stock_backtester 聚合口径 worst_drawdown 改名+seed+体制窗口对齐 / get_stock_name 走 stock_list_manager / 新建 sina_daily bj 前缀与新浪 klc 直连 + 5 调用方接线 / 报价缓存按口径去重; `tests/test_batch1_m22_m15_m18_m16.py`), L12 全仓死 import 批 (84 个删除, 逐名核实无重导出/无字符串注解; 2 个 noqa 豁免; 门禁 `TestUnusedImportsRepoWide` 放宽到 skills 全树+tests+run_web_app; `tests/test_source_hygiene.py`). H8 引擎 B 结构性偏差批 (持仓状态机消除 0 持仓日伪交易 / `min_holding_days` 默认 20→0 不再隐式锁退出 / warmup 跨窗口继承 `backtest(history=)` 使 OOS 窗口不再被吃前 1/3; 黄金快照已重评并留归因证明; `tests/test_backtest_honesty.py::TestH8StructuralBiases` 9 用例). H9 引擎 A walk-forward 批 (测试窗口预热 `run(warmup_data=)` / OOS 净值曲线拼接 `_stitch_oos_equity` 使 OOS 总收益=各窗复利; `walk_forward` 返回 `{windows,oos,oos_equity_curve}`; A 引擎黄金快照逐位不变; `tests/test_backtest_honesty.py::TestH9WalkForwardOS` 7 用例). H7 成交容量约束批 (execution_model 新增 bar_turnover_amount/capacity_limit_notional; A 引擎 PositionConfig.max_volume_participation + B 引擎 max_volume_participation/capital 逐笔部分成交 + metrics_from_trades 支持逐笔仓位比例; 引擎 A 黄金快照已重评并留归因证明, 引擎 B 不变; `tests/test_backtest_honesty.py::TestH7CapacityConstraint` 11 用例). M1 残余指标口径批 (core/metrics 增 win_rate/consecutive_streaks/max_consecutive_true; 引擎 A/B/D 胜率与连段统计全部改调 core; A 的连胜/连亏改交易序列口径 + 日频口径另存诚实字段; B 补 max_consecutive_wins 字段并修掉连亏 gap bug; 引擎 A/B 黄金主断言逐位不变; `tests/test_backtest_honesty.py::TestM1MetricConventions` 12 用例).
