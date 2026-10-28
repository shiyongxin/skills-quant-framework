# 后续待办计划（审计项复核）

> **生成日期**: 2026-10-25（星期日）
> **代码基线**: `e9ea505` — 死代码清理 + 依赖契约修正 (ml_predictor.FeatureEngineer) + 源码卫生门禁
> **测试基线**: 531 passed / 0 skipped（装齐 `pyarrow` + `matplotlib`）
> **最近更新**: 2026-10-26 — 批次 3 首条 **H1 已修（优化器真样本外验证）**：新增 `optimization_engine.split_is_oos()`，walk-forward 窗口按时间顺序切成 IS（选择用）/ OOS（仅报告）；**适应度只由 IS 窗口计算**，末尾 30% 窗口（`WalkForwardConfig.oos_ratio`）留作样本外，其指标只进 `details['oos']` 与 `systems[].oos` 落盘，**从不参与参数选择** —— 切断"样本外窗口实为样本内"的选择偏差；IS/OOS 两套指标在 IndicatorSystem 字段、控制台摘要、落盘 manifest 三处分列；窗口数不足时如实标记 `available=False`；测试基线 641 → **662**；同日早些 **M1 已修（残余指标口径分歧）**：新增 `core/metrics.win_rate` / `consecutive_streaks` / `max_consecutive_true` 三个单一真相源，引擎 A/B/D 全部改调；A 的连胜/连亏由**日频净值**口径改为**交易序列**口径（与 B 一致，旧日频口径另存为 `max_consecutive_up_days`/`max_consecutive_down_days` 诚实字段），B 补 `max_consecutive_wins` 字段并修掉"连亏统计其实是亏损起始点间隔"的 bug；**引擎 A/B 收益/夏普/回撤/盈亏比等黄金主断言逐位不变**（只改报告字段口径）；测试基线 629 → **641**；同日早些 **H7 已修（回测引擎无流动性/容量约束）**：新增 `execution_model.bar_turnover_amount()` + `capacity_limit_notional()` 共享助手，A 引擎 `PositionConfig.max_volume_participation`（默认 5%）按 当日成交额×占比 截断买入股数，B 引擎 `params['max_volume_participation']` + `params['capital']` 支持逐笔部分成交（`metrics_from_trades` 支持逐笔仓位比例数组，全部相等时走标量路径 → 逐位兼容旧版）；**引擎 A 黄金快照已重评**（ret 20.03%→20.62%、Sharpe 0.810→0.838、MDD 14.19%→14.00%，归因：10 笔买入中 3 笔落在低量日被截断；关闭约束时逐位复现旧值），引擎 B 黄金不变；测试基线 618 → **629**；同日早些 **H9 已修（引擎 A walk-forward）**：测试窗口带预热（`run(warmup_data=)`，策略可见窗口前历史但账户空仓起步）+ 各窗口 OOS 净值曲线拼接（`_stitch_oos_equity`，OOS 总收益 = 各窗逐段复利），实测裸切片 OOS 仅 6 笔 → 带预热 12 笔；测试基线 611 → **618**；同日早些 **H8 已修（引擎 B 三处结构性偏差）**：持仓状态机（重叠买讯不再切出 0 持仓日伪交易）/ `min_holding_days` 默认 20→0（锁定期不再屏蔽退出）/ warmup 跨窗口继承（`backtest(history=)`，OOS 窗口不再被吃前 1/3）；**黄金快照已重评**（引擎 B ret 8.24→12.99、Sharpe 0.707→1.431、MDD 6.52→2.76，归因证明见下表），测试基线 602 → **611**；此前同日批次 1 全部清账（L12 收口 602、M22+M15+M18+M16 599、M2+M3+M9 560、L6+L7+L8 553、M12+M13+M17+M14 2026-10-25 531）
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
| **M5** | 优化器逐股回测失败**静默 `except Exception: continue`**，无失败计数、无惩罚 → 参数组可能在更少样本上被评估而不受罚 | `optimization_engine.py:161-162,219-220,236-237` | ⚠️ 需再核 |
| **M4** | 短体制窗口冷启动（`ma_slow` 可达 120 > warmup 60）；`min_hold_end` 使止盈/移动止损在体制窗内永不触发 | `vectorized_backtest.py:448-450`、`optimization_engine.py:194-195` | ⚠️ 需再核 |
| **M19** | 日线列名标准化 + `pct_change` 块从 2 处扩散到 **4 处**（从未抽公共函数） | `stock_data_fetcher.py:160-180`、`historical_data_manager.py:265-272`、`long_term_selector.py:194-201`、`reversal_detector.py:179-185` | 低风险，可抽 `core/` 公共函数 |
| **M20** | `long_term_selector` / `reversal_detector` **绕过共享数据层**自行调 `ak.stock_zh_a_daily`：无 adjust 维度、无 as_of、无 FetchResult、无交易日历接入 | `long_term_selector.py:180-207`、`reversal_detector.py:167-189` | 中。与 P0-4 口径矛盾 |

**注意**：这一批会**改变回测数值** → `tests/test_backtest_honesty.py::TestGoldenMetrics` 黄金快照必须重新评估，不能默默更新。

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
> 进度：**H1 已拍板并落地**（2026-10-26，见下方明细）；**H10 已落地**（2026-10-26，见下方明细）；其余条目仍待定方案。

| # | 问题 | 证据 | 性质 |
|---|---|---|---|
| ~~**H1**~~ | ~~优化器**无真样本外验证**：GA 在同一批 walk-forward 窗口上既评估又取最大，"样本外"窗口实为样本内~~ → **✅ 已修（真样本外隔离）** | 复验确认属实（审计 E-optimization-portfolio §3.1 第 1/2 条）：`walk_forward` 的 `train_days` 只用于"跳过前 N 行"，训练段从未用于拟合；fitness = 各测试窗口指标聚合，而 GA 又在**同一批窗口**上取最大 → 全流程无未被触碰的留出集 | 已修 + `tests/test_h1_oos_isolation.py` 21 用例；明细见下方说明 |
| **H3** ✅ | `historical_backtest_validator` 的回测引擎是**死属性**（全文仅 `:86` 一处）；验证参数来自"全历史优化出的"产物 → IS/OOS 隔离仍破；样本按评估结果过滤（`:449-453` `forward_returns[hd] != 0`）；报告区间硬编码（`:504`） | `historical_backtest_validator.py` | 需重做验证链 |
| **H4** ✅ | 幸存者偏差：`get_universe()` **无 `as_of` 参数**，用 `datetime.now()` 回溯到 1996；`stock_selector.get_hot_stocks` 硬编码热门股字典 | `historical_data_manager.py:433-434` `get_universe(min_history_days=5000, min_rows=2000)` —— **无 as_of 参数** | 与 C-P0-7 的 point-in-time 止血契约同源，但因子层没跟上 |
| **H6** ✅ | 多因子权重拟合仍**样本内 + 前瞻收益**（`shift(-1)`），且与 `shift(1)` 的打分口径**互相矛盾** | `multi_factor_selection.py:176`/`:239` `shift(-1)` vs `:411` `shift(1)` —— 口径自相矛盾 | 因子层是选股入口，影响面大 |
| **H2** ✅ | `confidence` 是**硬编码常数**（`0.7`/`min(0.9, fitness*1.2)`/`0.6`/`0.75`），却被 `daily_signal_generator` 当作**生产参数体系的唯一挑选依据** | `optimization_engine.py:810` `confidence=0.7` / `:919` `min(0.9, best.fitness*1.2)` / `:1045` `0.6` / `:1156` `0.75` | 编造的数参与决策 |
| ~~**H10**~~ | ~~优化结果无**多重检验校正 / 稳健性证据**：`save_results` 落盘无试验次数、最优 fitness 在随机基线上的分位数、Top-10 参数离散度、bootstrap 置信区间。而 `optimize_global` 3200 次 / `iterative` ~7000 次回测量级~~ → **✅ 已修（稳健性证据落盘）** | 复验确认属实：落盘仅 `seed`/`n_stocks`/`fitness_weights`/`param_space`/`ga_runs` —— 无试验次数/分位数/bootstrap | 已修 + `tests/test_h10_robustness.py` 32 用例；明细见下方说明 |
| **H5** | 停牌建模**只落在信号层**（`trade_constraints` + `core/trading_calendar.py`），4 套回测引擎侧**完全没接** —— "停牌期间持仓无法平仓"未建模 | `rg 停牌\|suspend` 在 `backtest_framework`/`vectorized_backtest`/`reversal_backtest`/`historical_backtest_validator` → **0 命中**；`execution_model.py:13-14` docstring 自述"停牌: 数据侧无停牌标记" | ✅ 已复验 |

**建议决策点**：~~H1（接线成本最低、收益最高）~~ **✅ 已做（2026-10-26，见下方明细）**；~~H10（只改落盘）~~ **✅ 已做（2026-10-26，见下方明细）**；H4/H6 涉及因子层改造，工作量大；H3 需要重做验证链设计。

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
2. ~~**H1 接线** + **H10 落盘字段** → 批次 3 里成本最低、收益最高的两条~~ **✅ 两条均已落地（2026-10-26）**
3. **批 4.1 决策**（副本：废弃 / 维护 / 依赖主链）→ 阻塞后续所有改动
4. **批 2**（回测数值）→ 一次性做完 + 重新评估黄金快照
5. **H4 / H6 / H3**（研究有效性核心）→ 需先定方案再动

---

## 8. 维护约定

- 本文档是**活台账**：修完一条就划掉（改状态列 / 移到已修区），并同步更新 `AGENTS.md` 的 "Audit fix status"
- 标 ⚠️ 的条目**动手前必须先复验**（审计基线 `14b2f59` 距今已 30+ 提交，可能已过时或误报）
- 每条修复应配**回归测试**，否则下一个 30 提交后又会退回原样 —— 参见 `tests/test_optional_deps.py` 的门禁思路
- 相关入口：`AGENTS.md`（分层/依赖/测试约定）、`docs/skills_layers.md`（三层边界）
