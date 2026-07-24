# V2-A Breakout Quality Walk-forward 实施计划

**状态：** PLAN_ONLY / NOT_IMPLEMENTED / NOT_AUTHORIZED_TO_RUN

**日期：** 2026-07-23

**唯一研究方向：** `BREAKOUT_QUALITY_FILTER`
**前置冻结结论：** V1=`STRATEGY_FAILED_BASELINE_VALIDATION`；H1=`SUPPORTED_FOR_LIMITED_V2_TEST`；H2=`INSUFFICIENT_EVIDENCE`；H3不单独进入V2。

## 1. 目标、唯一改变量与停止边界

本计划验证一个严格受限的事前假设：弱 Donchian 突破缺少后续动量；在 Candidate 进入现有 2B 之前，以 decision 时可见的 `breakout_strength` 拒绝弱突破，可能降低低质量交易与成本侵蚀。

唯一允许改变的行为是：一个已经由 V1 生成的 `LONG` 或 `SHORT` Candidate 是否获准进入 2B。过滤器只能输出：

- `ACCEPT`
- `REJECT_WEAK_BREAKOUT`

执行链固定为：

`V1 Candidate -> breakout quality gate -> existing 2B -> existing 2C -> existing metrics`

以下全部冻结，不允许 V2-A 改动：V1 趋势判定、Donchian 周期、EMA、ATR、Candidate 方向、入场价格、止损、止盈、`TIME_EXIT`、仓位与风险计算、组合风险、手续费、滑点、资金费、2C 事件顺序，以及 BTC/ETH 或 LONG/SHORT 的差异化规则。V2-A 不生成新方向、价格、数量、退出或账户状态。

本轮只交付本计划。不得编写生产代码、测试、Fixture、Runner、Harness，不运行回测、分钟事件引擎、原 OOS 或自动调参，不创建 PR。未来实施若 Walk-forward 无候选通过，结论固定为 `V2A_WALK_FORWARD_FAILED` 并停止，不自动产生下一轮策略。

## 2. 唯一 Canonical `breakout_strength`

### 2.1 当前已验证实现与输入来源

当前 V1 失败归因使用：

- 文件：`pa_agent/research_2d/attribution.py`
- 函数：`_candidate_features`
- 输入字段：`StrategyCandidate.market_view`、`decision_close`、`donchian_high_previous_20`、`donchian_low_previous_20`、`atr14_4h`
- Candidate 构造入口：`pa_agent/research_backtest/strategy/candidate_factory.py::build_candidate` 与正式数据适配器 `pa_agent/research_2d/data.py::build_actionable_candidate_stream`
- Donchian 实现：`pa_agent/research_backtest/indicators/donchian.py::previous_donchian`，使用 Python 切片 `highs[index - 20:index]` / `lows[index - 20:index]`，明确排除当前 decision bar
- ATR 边界：Wilder ATR 使用 float64 指标路径，进入交易/Canonical 边界时经 `pa_agent/research_backtest/indicators/numeric.py::float64_to_decimal_15sig` 转为 15 位有效数字的 `Decimal`，舍入为 `ROUND_HALF_EVEN`
- 收盘约束：Candidate factory 和 Canonical Kline loader 均拒绝未收盘 4H/1D bar；decision bar 是完全收盘的 native 4H bar
- Canonical 序列化：`pa_agent/research_backtest/domain/canonical.py::canonical_dumps`；有限 `Decimal` 经 `canonical_decimal` 输出无指数、去除无意义尾零、零统一为字符串 `"0"`，对象 key 排序，UTF-8 JSON 使用紧凑分隔符，禁止 binary float

### 2.2 冻结公式

对 `decision_atr_4h > 0`：

```text
LONG:
breakout_strength =
    max(Decimal("0"), decision_close - prior_20_bar_donchian_upper)
    / decision_atr_4h

SHORT:
breakout_strength =
    max(Decimal("0"), prior_20_bar_donchian_lower - decision_close)
    / decision_atr_4h
```

变量映射固定为：

- `decision_close` = `candidate.decision_close`
- `prior_20_bar_donchian_upper` = `candidate.donchian_high_previous_20`
- `prior_20_bar_donchian_lower` = `candidate.donchian_low_previous_20`
- `decision_atr_4h` = `candidate.atr14_4h`

所有算术直接使用这些 `Decimal` 输入和 `Decimal("0")`；不得转回 float、不得 `isclose`、不得另行量化或按 symbol/side 舍入。结果只通过现有 `canonical_decimal`/`canonical_dumps` 序列化。非有限值、ATR 非正、非 LONG/SHORT 输入均 fail closed。

### 2.3 现有实现差异及唯一公式迁移

现有 `_candidate_features` 计算的是 `breakout_distance / atr14_4h`，没有显式写 `max(0, ...)`。它依赖已验证的 V1 可交易 Candidate 不变量：LONG 必须已突破 prior upper，SHORT 必须已跌破 prior lower，因此归因样本中的 distance 为正。冻结公式在该合法输入域与现有结果逐位相同，但对非法/边界输入的显式下限语义更完整。

未来实现不得保留两套公式。第一项实现任务应把上述算术提取为中立共享 helper `pa_agent/research_backtest/strategy/breakout_strength.py::calculate_breakout_strength`；`pa_agent/research_2d/attribution.py::_candidate_features` 与 `pa_agent/research_v2a/breakout_quality.py` 都只能调用该共享 helper。依赖方向固定为 `research_2d -> research_backtest.strategy.breakout_strength <- research_v2a`，严禁 `research_2d -> research_v2a`。先用当前 V1 归因 Golden 证明输出逐位不变；不得在 attribution、过滤器或 Runner 中再次书写公式。

共享 helper 只承载已冻结、事前可见的纯算术，不承载 V2-A threshold 或 gate 语义。删除整个 `pa_agent/research_v2a/` 后，V1 Candidate、V1 attribution、2B 与 2C 必须仍可导入并独立运行。

禁止输入未来 K 线、最终 PnL、MFE、MAE、退出后价格、`TIME_EXIT` 后验结果、V1 attribution 的收益字段、REUSED OOS 绩效产物或未来 Holdout。Walk-forward 模型选择阈值只来自当前 Fold 的 Training Candidate strength；入选后的滚动阈值只按第4.1节读取当时已成为过去的 Candidate strength。两者均不读取 PnL。

## 3. 唯一三个策略身份

完整 Walk-forward 只允许：

1. `V1_BASELINE`：不应用过滤器；所有合法 V1 Candidate 进入既有 2B。
2. `V2A_Q50`：接受 `breakout_strength >=` 当前 Fold Training 全局 Q50。
3. `V2A_Q67`：接受 `breakout_strength >=` 当前 Fold Training 全局 Q67（q=`2/3`，不是近似插值分位数）。

每个 Fold 将 BTCUSDT/ETHUSDT 与 LONG/SHORT 的 Training Candidate 合并成一个序列；不允许 symbol 或 side 专属阈值。排序 key 固定为 `(breakout_strength, candidate_id)`，数值阈值按升序 strength 的 nearest-rank 元素取得：

```text
index = ceil(q * N) - 1
threshold = sorted_strengths[index]
```

其中 N 是该 Fold Training 合法 LONG/SHORT Candidate 数，Q50 的 q=`1/2`，Q67 的 q=`2/3`；不得调用带默认插值的统计库分位数。相同 strength 的接受规则是 `>=`，因此 ties 全部接受。空集合 fail closed。

禁止新增 Q25/Q40/Q60/Q75、绝对阈值、网格搜索、贝叶斯优化、AI 阈值或人工挑选。

## 4. 冻结 Walk-forward 边界

V2 开发数据的最大可见范围固定为 `2020-10-01T00:00:00.000Z` 至 `2024-09-30T23:59:59.999Z`。全部边界为 UTC，Training 24 个月、Validation 6 个月、滚动步长 6 个月，Validation 互不重叠。

| Fold | Training（首尾包含） | Validation（首尾包含） |
|---|---|---|
| F1 | `2020-10-01T00:00:00.000Z` – `2022-09-30T23:59:59.999Z` | `2022-10-01T00:00:00.000Z` – `2023-03-31T23:59:59.999Z` |
| F2 | `2021-04-01T00:00:00.000Z` – `2023-03-31T23:59:59.999Z` | `2023-04-01T00:00:00.000Z` – `2023-09-30T23:59:59.999Z` |
| F3 | `2021-10-01T00:00:00.000Z` – `2023-09-30T23:59:59.999Z` | `2023-10-01T00:00:00.000Z` – `2024-03-31T23:59:59.999Z` |
| F4 | `2022-04-01T00:00:00.000Z` – `2024-03-31T23:59:59.999Z` | `2024-04-01T00:00:00.000Z` – `2024-09-30T23:59:59.999Z` |

每个 Fold 的顺序固定为：读取该 Fold Training Candidate -> 计算并冻结 Q50/Q67 manifest -> 验证 manifest -> 过滤对应 Validation Candidate -> 运行该 Validation。Validation 数据或结果不得反向改变阈值。

### 4.1 入选分位数的滚动部署阈值

Walk-forward 只选择分位数身份（Q50 或 Q67），不永久复用 F4 的数值阈值。入选后每个6个月应用区间开始前，用此前完整24个月的 Candidate 重新计算同一个入选分位数；阈值在该应用区间内冻结，每6个月只更新一次：

| 应用区间（UTC，首尾包含） | threshold Training（UTC，首尾包含） |
|---|---|
| `2024-10-01T00:00:00.000Z` – `2025-03-31T23:59:59.999Z` | `2022-10-01T00:00:00.000Z` – `2024-09-30T23:59:59.999Z` |
| `2025-04-01T00:00:00.000Z` – `2025-09-30T23:59:59.999Z` | `2023-04-01T00:00:00.000Z` – `2025-03-31T23:59:59.999Z` |
| `2025-10-01T00:00:00.000Z` – `2026-03-31T23:59:59.999Z` | `2023-10-01T00:00:00.000Z` – `2025-09-30T23:59:59.999Z` |
| 从 `2026-04-01T00:00:00.000Z` 开始的短 Holdout，终点由 Gate C 冻结 | `2024-04-01T00:00:00.000Z` – `2026-03-31T23:59:59.999Z` |

每次重算仍使用第3节同一 global nearest-rank 规则，合并 BTC/ETH 与 LONG/SHORT，只读取阈值 Training 结束时已经存在的 Candidate `breakout_strength`。禁止读取 PnL、MFE、MAE、退出、交易归因或任何后验结果。应用区间数据不得反向影响其阈值；manifest 身份规则与第10节相同。

## 5. 数据、执行与实验范围

Walk-forward 正式路径只使用已经批准的数据和模型：Binance native 4H、native 1D、trade 1m、mark 1m、真实 funding、当前冻结的 APPROXIMATED contract rule 与 maintenance evidence。Authority 只允许 `NATIVE_PRIMARY`，成本场景只允许 `BASE_1X`。

每个 Validation task 通过现有 2B 和 2C 同时产出既有 BASELINE/CONSERVATIVE path；路径歧义语义不变。不得运行 Aggregated sensitivity、2倍/3倍成本、Training 收益优化、REUSED OOS 或 2026 短 Holdout。

`V1_BASELINE` 必须在同一 Fold、同一数据身份、同一成本和执行版本下重新运行，作为配对基准；不能引用旧的跨区间汇总替代。

## 6. Candidate 级低成本 Preflight Gate

分钟回放前，一次性生成四个 Fold 的 Training/Validation Candidate 流；只计算 strength、threshold、接受集合和身份，不加载 minute replay，不计算任何收益。

每个 Fold、每个策略身份至少输出：

- `training_candidate_count`
- `training_candidate_content_hash`
- `threshold`（V1 为 `null`）
- `validation_candidate_count`
- `accepted_candidate_count`
- `rejected_candidate_count`
- `retention_rate`
- `accepted_by_symbol`：BTCUSDT、ETHUSDT
- `accepted_by_side`：LONG、SHORT
- `accepted_candidate_content_hash`

Q50/Q67 候选在以下任一条件成立时，在分钟回放前淘汰；V1 只在至少一个 V2-A 候选通过 Preflight 时作为 Fold 基准运行：

- 任一 Fold `accepted_candidate_count < 15`
- 四个 Validation 合计 `accepted_candidate_count < 80`
- 四个 Validation 合计或任一 Fold中任一 symbol/side 接受数为零（采用更严格的逐 Fold 保护，避免局部结构被完全删除）
- Training threshold 输入为空
- dataset、Candidate、fold、threshold 或 filter identity hash 不匹配

预检失败状态必须说明具体 Fold/identity/reason；身份不一致统一为 `EXPERIMENT_IDENTITY_INVALID`。不得用 PnL 放宽门槛或重选阈值。

Preflight 后的分钟任务注册表按结果冻结：

- Q50、Q67 均失败：**0个分钟任务**，返回 `V2A_PREFLIGHT_FAILED`，不得为了基线报告单独运行 V1。
- 仅一个候选通过：**8个分钟任务**，即4个 `V1_BASELINE` + 4个通过候选。
- 两个候选均通过：**12个分钟任务**，即4个 `V1_BASELINE` + 4个 `V2A_Q50` + 4个 `V2A_Q67`。

任何已被 Preflight 淘汰的候选不得进入 `_run_scenario`、task registry 或正式 Artifact。

## 7. Walk-forward 指标聚合与晋级标准

每个 Validation Fold 使用独立的新账户，从 `10,000 USDT` 开始。Fold 之间禁止钱包、可用资金、保证金、持仓或未实现盈亏继承，禁止跨 Fold 复利。聚合只允许：

```text
total_net_pnl = sum(fold_net_pnl)
aggregate_return = sum(fold_net_pnl) / Decimal("40000")
aggregate_profit_factor =
    sum(fold_gross_profit) / abs(sum(fold_gross_loss))
```

`sum(fold_gross_loss) == 0` 时 PF 使用现有指标域的明确无亏损表示，晋级比较前必须由测试冻结，禁止用任意大数代替。每个 Fold 独立计算 drawdown，再按第7条第8项定义取四 Fold 中位数；不得把四条独立 equity 曲线拼接后重算 drawdown。

对每个 V2 候选独立汇总四个 Validation Fold，且必须同时满足以下 13 条：

1. 至少 3 个 Fold 净收益为正。
2. 至少 3 个 Fold 的净收益高于同 Fold `V1_BASELINE`。
3. 四 Fold 合计净收益为正。
4. 合计 Profit Factor `>= 1.10`；合计 PF 必须由所有 Fold 的 gross profit / gross loss 重新计算，不得平均 Fold PF。
5. 合计正式交易数 `>= 60`。
6. 每个 Fold 正式交易数 `>= 10`。
7. 四 Fold 净收益的中位数 `> 0`；偶数样本中位数按排序后中间两值算术平均，Decimal 运算。
8. 四 Fold最大回撤的中位数不高于 `V1_BASELINE` 四 Fold最大回撤的中位数；同一冻结 drawdown 定义配对比较。
9. 最大单个盈利 Fold 的净收益不超过全部正收益之和的 60%。
10. 不能由单一 symbol 贡献全部正利润：BTCUSDT 与 ETHUSDT 均须有至少一笔正式交易，且候选的合计正净利润不能只来自一个 symbol；若一个 symbol 净利润 `<= 0` 且另一个 `> 0`，本条失败。
11. 不能由单一 side 贡献全部正利润：LONG 与 SHORT 均须有至少一笔正式交易，且候选的合计正净利润不能只来自一个 side；若一 side 净利润 `<= 0` 且另一 side `> 0`，本条失败。
12. 所有必需 path 无 `DATA_INVALID` 且完整到达 Fold 终点。因组合风险、回撤上限或其他原因提前 `HALTED` 的 Fold 不得满足晋级条件，也不得进入晋级聚合；HALTED 仍如实报告，但不能伪造完整区间年化。
13. 无资金、账本、实验身份或未来数据不变量失败。

不得以总收益最高、胜率最高、单一 Fold、单一 symbol 或单一 side 的表现替代上述 conjunction。

## 8. 固定候选选择规则

- 只有 Q50 或 Q67 一者通过全部 13 条：选择该候选。
- 两者均通过：默认选择交易保留更多且规则较宽的 `V2A_Q50`。只有 `V2A_Q67` 同时满足以下全部条件才改选 Q67：合计 PF 至少高 Q50 `0.10`；合计净收益 `>= 1.25 * Q50` 合计净收益；正式交易数 `>= 60`；正收益 Fold 数不少于 Q50；最大回撤不高于 Q50。这里的最大回撤使用与晋级第 8 条相同的汇总定义。
- 两者均未通过：结论 `V2A_WALK_FORWARD_FAILED`，停止，不运行 REUSED OOS，也不自动生成新阈值或 V2-B。

选择过程是纯确定性规则；不得人工覆写。

## 9. 通过后的后续闸门（仅描述，不在本轮或 Walk-forward 中执行）

### Gate A：唯一入选候选的成本压力

只运行 `BASE_1X` 与 `COMBINED_2X`。2倍综合成本下合计净收益不得明显为负（实施前必须把“明显”为一个经人工冻结的数值边界；在未冻结前 fail closed）、PF `>= 1.00`、无执行失效。Gate A 不可反向改变阈值。

### Gate B：REUSED OOS 诊断

区间固定为 `2024-10-01T00:00:00.000Z` 至 `2026-03-31T23:59:59.999Z`，永久标记 `REUSED_OOS`、`POST_HOC_DIAGNOSTIC_ONLY`、`NOT_CLEAN_HOLDOUT`。只诊断弱突破损失、成本、交易数、symbol/side 结构；不得用于阈值选择或单独批准 V2。

### Gate C：短期未见 Holdout veto

区间为 `2026-04-01T00:00:00.000Z` 至届时人工冻结的数据终点。交易数足够且明显亏损则 veto；样本过少为 `HOLDOUT_INCONCLUSIVE`；盈利也不能直接批准实盘。运行前须先冻结“足够”和“明显亏损”的数值定义，禁止看结果后定义。

### Gate D：前向模拟

仅当前面未被拒绝时，冻结唯一策略，每4小时使用完全收盘数据产生模拟信号；参数不再修改，不配置交易所私钥，不连接账户，不自动下单。

## 10. 实验身份、Manifest 与防泄漏

### 10.1 Canonical 身份对象

- `fold_manifest`：schema version、Fold ID、UTC Training/Validation 边界、authority、cost scenario、dataset hash、V1 Candidate/indicator/strategy version。
- `threshold_manifest`：schema version、Fold ID、Training 起止、Training Candidate canonical hash、Candidate 数、排序与 nearest-rank 规则、q 的有理数表示、Q50/Q67 Canonical Decimal、candidate filter version、threshold calculation hash。
- `candidate_filter_version`：独立固定版本，例如未来实施时冻结为 `BREAKOUT_QUALITY_FILTER_V2A_V1`。
- `strategy_version`：三者分别独立，如 `V1_BASELINE` 保留原 V1 identity，Q50/Q67 绑定 V1 identity + filter identity + quantile identity。
- `dataset_content_hash`：只绑定实际策略/执行所需 Canonical 内容，不绑定采集时间。
- `code_commit`：执行时 clean tree 的完整 Git SHA。
- `dependency_lock_hash`：依赖锁定文件的 Canonical hash。
- `threshold_calculation_hash`：唯一公式版本、输入 Candidate hash、排序规则、nearest-rank 规则、Q50/Q67 输出构成的 Canonical SHA-256。
- `computational_experiment_id`：上述经济决定性身份、四个 fold/threshold manifest hash、2B/2C/成本/证据版本的 Canonical SHA-256；不得包含 PID、worker 数、路径、duration 或 `generated_at`。

`generated_at` 可作为非权威诊断元数据保存，但必须从 threshold manifest canonical hash 和 experiment ID 中排除。

Validation 前重新计算并核对所有 manifest/hash；任何 mismatch 返回 `EXPERIMENT_IDENTITY_INVALID`，不得启动分钟回放或发布绩效。

### 10.2 防泄漏守卫

未来静态 scope guard 与行为测试共同禁止 `pa_agent/research_v2a/` 导入或读取：REUSED OOS 绩效产物、V1 attribution PnL、`trade_attribution` 净收益、MFE/MAE、退出后价格、`TIME_EXIT` 后验分类、尚未发生的 Holdout 数据。阈值 API 只接受按 manifest 边界裁剪的历史 `StrategyCandidate` tuple，不接受 Trade、Fill、Ledger、Metrics 或绩效路径字符串。第4.1节部署重算可以使用已经结束区间的 Candidate strength，但不能使用该区间绩效，且不能反向改变 Walk-forward 选择。

改变某一已经冻结 manifest 的 Training 终点之后的数据，必须既不改变该 manifest canonical bytes，也不改变其 threshold；否则 fail closed。下一个6个月部署窗口按第4.1节创建新的24个月 Training manifest，不覆盖旧 manifest。

## 11. 未来实施文件地图

### 11.1 新建 V2-A 模块

```text
pa_agent/research_v2a/
  __init__.py
  breakout_quality.py      # 调用共享 strength helper；nearest-rank、ACCEPT/REJECT
  domain.py                # immutable Fold/Threshold/Filter result schema
  identity.py              # manifests、canonical hashes、experiment identity
  preflight.py             # Candidate-only counts/retention/fail-closed gate
  walk_forward.py          # 0/8/12-task registry、晋级与固定选择规则
  reporting.py             # 父进程原子发布，不含运行诊断字段的经济产物
```

中立共享模块仅新建 `pa_agent/research_backtest/strategy/breakout_strength.py`，其中只放置唯一纯函数 `calculate_breakout_strength`。它不导入 `research_2d` 或 `research_v2a`。

### 11.2 最小 Runner/CLI 接线

- 新建 `scripts/run_v2a_walk_forward.py`：仅解析冻结输入并调用 V2-A orchestration；必须有 `if __name__ == "__main__"`。
- 修改 `pa_agent/research_cli.py`：未来仅增加显式子命令 `v2a-preflight` 和 `v2a-walk-forward`；默认 CLI 仍不联网、不启动 GUI、不要求 API Key。
- 修改 `pa_agent/research_2d/attribution.py`：仅让 `_candidate_features` 委托中立共享 strength helper，并用 Golden 证明现有 V1 attribution 内容不变；不得改动归因经济结果，且不得导入 `research_v2a`。
- 复用而不重写 `pa_agent/research_2d/runner.py::_run_scenario`、`parallel.py` 和原子发布能力。若需传入已过滤 Candidate，应通过新的 V2-A adapter/registry 包装，不在 2D Runner 内加入策略公式。

计划中的 CLI 形式：

```text
python -m pa_agent.research_cli v2a-preflight --data-root <approved-root> --output-root artifacts/research_v2a/<experiment-id>/preflight
python -m pa_agent.research_cli v2a-walk-forward --data-root <approved-root> --output-root artifacts/research_v2a/<experiment-id> --max-workers 6 --hard-timeout-seconds 21600
```

CLI 不提供任意 quantile、任意 Fold、symbol/side threshold 或 reused-OOS 参数。

### 11.3 只读与禁止修改边界

V1 只读：

- `pa_agent/research_backtest/strategy/btc_eth_pa_v1.py`
- `pa_agent/research_backtest/strategy/candidate_factory.py`
- `pa_agent/research_backtest/indicators/{ema,atr,donchian,numeric}.py`
- V1 Golden 与现有 Candidate schema

2B/2C 禁止修改：

- `pa_agent/research_backtest/planning/**`
- `pa_agent/research_backtest/simulation/**`
- 2B/2C Golden、费用、仓位、资金费、爆仓、Ledger、Fill 和事件顺序

测试位置：`tests/research_v2a/`；既有 V1/2B/2C 测试只运行，不改写期待值。Artifacts 独立写入 `artifacts/research_v2a/<computational_experiment_id>/`，运行诊断写入相邻但不参与 canonical hash 的 `artifacts/research_v2a_diagnostics/<run-id>/`。V1 与 V2-A 结果目录永不覆盖。

V1 必须保持可独立运行；V2-A 有独立版本号；删除 `pa_agent/research_v2a/`、V2-A CLI/脚本接线和 V2-A Artifact 后，仍保留中立共享公式供 attribution 使用，且不改变 V1/2B/2C。

## 12. 实施任务、基线接口与 TDD 顺序

### 12.1 冻结实施基线与引用验证

未来实施必须从完整基线 commit `3a5583598122236904c5a0919f8eb5740b6d6c54` 开始，或从只包含本计划后续 docs-only commit 的直接后代开始；经济源码基线必须与该 SHA 相同。每项任务固定遵循：**测试先行 -> 最小实现 -> 聚焦测试 -> 全部 V1/2B/2C 回归 -> 小提交**。

已在该基线 commit 验证存在的既有引用：

| 路径 | 已验证函数/入口 |
|---|---|
| `pa_agent/research_2d/attribution.py` | `_candidate_features(*, data_root, candidates, oos_end)` |
| `pa_agent/research_backtest/strategy/candidate_factory.py` | `build_candidate(...)` |
| `pa_agent/research_backtest/indicators/donchian.py` | `previous_donchian(highs, lows, *, index, lookback)` |
| `pa_agent/research_backtest/indicators/numeric.py` | `float64_to_decimal_15sig(value)` |
| `pa_agent/research_backtest/domain/canonical.py` | `canonical_decimal(value)`、`canonical_dumps(value)` |
| `pa_agent/research_2d/runner.py` | `_run_scenario(...)`、`run_baseline_evaluation(...)` |
| `pa_agent/research_2d/parallel.py` | `run_tasks(...)` |
| `pa_agent/research_2d/streaming.py` | `run_streaming_paths(...)` |
| `pa_agent/research_cli.py` | `_parser()`、`main(argv=None)` |
| `scripts/run_2d_baseline_evaluation.py` | `main()` |

下文 `pa_agent/research_v2a/**`、`tests/research_v2a/**`、`scripts/run_v2a_walk_forward.py` 与共享 `breakout_strength.py` 均明确为**计划新增**，基线不存在是预期状态。除此之外，任何被实施任务引用为“既有”的路径、函数、参数或测试若不能在上述基线 SHA 中以 `git cat-file`/`git grep` 验证，整个实施返回 `IMPLEMENTATION_BASELINE_INVALID` 并停止；不得猜测替代路径、静默改名或扩大修改范围。

### Task 1：中立共享公式与 V1 attribution 等价

本 Task 基线：`3a5583598122236904c5a0919f8eb5740b6d6c54`；基线身份不符即 `IMPLEMENTATION_BASELINE_INVALID`。

计划新增精确签名：

```python
def calculate_breakout_strength(
    *,
    market_view: MarketView,
    decision_close: Decimal,
    prior_20_bar_donchian_upper: Decimal,
    prior_20_bar_donchian_lower: Decimal,
    decision_atr_4h: Decimal,
) -> Decimal:
```

先写 LONG/SHORT、零下限、ATR/market-view fail-closed、Decimal canonical、归因 Golden 等价测试；再在 `pa_agent/research_backtest/strategy/breakout_strength.py` 实现唯一 helper，使 attribution 委托它。不得改变 V1 Golden或形成 `research_2d -> research_v2a` 依赖。

```text
pytest tests/research_v2a/test_breakout_strength.py tests/research_2d/test_v1_failure_attribution.py -q
pytest tests/research_backtest tests/research_2d -q
```

通过条件：聚焦测试全部通过、V1 attribution canonical bytes/hash逐位不变、研究回归无新增失败。独立 commit message：`feat(research-v2a): centralize canonical breakout strength`。

### Task 2：Fold、nearest-rank 与 immutable manifests

本 Task 基线：`3a5583598122236904c5a0919f8eb5740b6d6c54`；基线身份不符即 `IMPLEMENTATION_BASELINE_INVALID`。

计划新增精确签名：

```python
def nearest_rank_threshold(
    strengths: tuple[Decimal, ...], *, quantile_numerator: int, quantile_denominator: int
) -> Decimal:

def build_threshold_manifest(
    *,
    fold: WalkForwardFold,
    training_candidates: tuple[StrategyCandidate, ...],
    dataset_content_hash: str,
    candidate_filter_version: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> ThresholdManifest:
```

先写4个边界、Q50/Q67、ties、空集合、滚动部署阈值与 canonical identity 测试；再实现 `domain.py`/`identity.py`。所有时间只允许整数 UTC ms，所有对象 immutable、可 pickle。

```text
pytest tests/research_v2a/test_folds.py tests/research_v2a/test_thresholds.py tests/research_v2a/test_identity.py -q
pytest tests/research_backtest tests/research_2d -q
```

通过条件：聚焦测试全部通过；nearest-rank、四个 Walk-forward Fold、四个部署阈值窗口、manifest hash 稳定且无未来输入；研究回归无新增失败。独立 commit message：`feat(research-v2a): freeze folds thresholds and identities`。

### Task 3：Candidate filter 与低成本 Preflight

本 Task 基线：`3a5583598122236904c5a0919f8eb5740b6d6c54`；基线身份不符即 `IMPLEMENTATION_BASELINE_INVALID`。

计划新增精确签名：

```python
def filter_candidate(
    candidate: StrategyCandidate, *, threshold: Decimal, candidate_filter_version: str
) -> CandidateFilterDecision:

def run_candidate_preflight(
    *,
    folds: tuple[WalkForwardFold, ...],
    strategy_candidates: tuple[StrategyCandidate, ...],
    dataset_content_hash: str,
    code_commit: str,
    dependency_lock_hash: str,
) -> CandidatePreflightReport:
```

先写集合包含、经济字段不变、计数、symbol/side删除、样本门槛、hash fail-closed，以及0/8/12 task eligibility测试；再实现只接受 Candidate 的纯函数和预检报告，不加载分钟行情或绩效。

```text
pytest tests/research_v2a/test_filter.py tests/research_v2a/test_preflight.py -q
pytest tests/research_backtest tests/research_2d -q
```

通过条件：聚焦测试全部通过；淘汰候选不进入 eligibility；双失败明确为 `V2A_PREFLIGHT_FAILED`；研究回归无新增失败。独立 commit message：`feat(research-v2a): add candidate-only preflight gate`。

### Task 4：Walk-forward registry、账户隔离与泄漏守卫

本 Task 基线：`3a5583598122236904c5a0919f8eb5740b6d6c54`；基线身份不符即 `IMPLEMENTATION_BASELINE_INVALID`。

计划新增精确签名：

```python
def build_walk_forward_tasks(
    *,
    preflight: CandidatePreflightReport,
    folds: tuple[WalkForwardFold, ...],
    baseline_scenario: Scenario,
) -> tuple[WalkForwardTask, ...]:

def run_walk_forward_task(
    task: WalkForwardTask, *, root: Path, experiment_identity: ExperimentIdentity
) -> WalkForwardTaskResult:
```

先写0/8/12 task registry、只含 Native/Base1X、每 Fold 独立10,000 USDT且无资金/持仓/复利继承、Training只算阈值、Validation不反哺、禁止敏感 imports/paths测试；再实现薄 adapter，内部只调用基线已存在的 `_run_scenario`。不得创建通用 Harness。

```text
pytest tests/research_v2a/test_registry.py tests/research_v2a/test_fold_isolation.py tests/research_v2a/test_scope_guard.py -q
pytest tests/research_backtest tests/research_2d -q
```

通过条件：聚焦测试全部通过；任务数量严格为0/8/12；Fold初始账户、终点和输入完全隔离；scope guard零违规；研究回归无新增失败。独立 commit message：`feat(research-v2a): orchestrate isolated walk-forward folds`。

### Task 5：绩效聚合、晋级、选择与报告

本 Task 基线：`3a5583598122236904c5a0919f8eb5740b6d6c54`；基线身份不符即 `IMPLEMENTATION_BASELINE_INVALID`。

计划新增精确签名：

```python
def aggregate_fold_performance(
    fold_results: tuple[FoldPerformance, ...], *, initial_capital_per_fold: Decimal
) -> AggregatePerformance:

def evaluate_promotion(
    *, candidate: StrategyIdentity, aggregate: AggregatePerformance,
    baseline: AggregatePerformance
) -> PromotionDecision:

def select_walk_forward_candidate(
    *, q50: PromotionDecision, q67: PromotionDecision
) -> SelectionDecision:
```

先覆盖冻结聚合公式、独立 drawdown 中位数、提前HALT否决、13个门槛、Q50/Q67选择、失败终止、canonical/diagnostic分离；再实现纯聚合和父进程原子发布。

```text
pytest tests/research_v2a/test_aggregation.py tests/research_v2a/test_promotion.py tests/research_v2a/test_selection.py tests/research_v2a/test_reporting.py -q
pytest tests/research_backtest tests/research_2d -q
```

通过条件：聚焦测试全部通过；聚合公式逐位相等；任何HALTED Fold不能晋级；13项为严格 conjunction；无候选通过时停止；研究回归无新增失败。独立 commit message：`feat(research-v2a): evaluate and select walk-forward candidate`。

### Task 6：容量探针、CLI、回归与受控执行准备

本 Task 基线：`3a5583598122236904c5a0919f8eb5740b6d6c54`；基线身份不符即 `IMPLEMENTATION_BASELINE_INVALID`。

计划新增精确签名：

```python
def run_capacity_probe(
    *,
    task: WalkForwardTask,
    root: Path,
    diagnostics_output: Path,
    hard_timeout_seconds: float = 21_600,
    no_progress_timeout_seconds: None = None,
) -> CapacityProbeReport:

def run_v2a_walk_forward(
    *,
    root: Path,
    output_root: Path,
    code_commit: str,
    max_workers: int,
    hard_timeout_seconds: float = 21_600,
    no_progress_timeout_seconds: None = None,
) -> Path:
```

先写 CLI scope/no-network/no-key/no-GUI、固定 F4/V1 capacity probe、资源选择2或6 workers、no-progress永久禁用、hard-timeout和父进程原子发布测试；再最小接线。正式顺序固定为 Candidate Preflight -> F4 `V1_BASELINE`容量探针 -> 资源选择 -> 0/8/12正式任务。探针结果不进入晋级或候选选择。

```text
pytest tests/research_v2a/test_capacity_probe.py tests/research_v2a/test_cli.py tests/research_v2a/test_publication.py -q
pytest tests/research_cli tests/research_backtest tests/research_2d tests/research_v2a -q
```

通过条件：聚焦测试全部通过；探针只运行冻结任务且只发布诊断；最终配置 `no_progress_timeout_seconds is None`、`hard_timeout_seconds == 21600`；研究全量回归无新增失败。独立 commit message：`feat(research-v2a): add bounded walk-forward execution entrypoint`。

## 13. 最低测试矩阵

未来测试至少包括以下 25 项；本轮不创建或运行这些测试：

1. LONG 冻结 `breakout_strength` 公式。
2. SHORT 冻结 `breakout_strength` 公式。
3. 负 distance 被 `max(0, ...)` 截为零。
4. 当前 decision bar 不进入 previous-20 Donchian。
5. 未收盘 decision/visible bar 被拒绝。
6. ATR 非正或非有限输入 fail closed。
7. Decimal 15 位转换与 Canonical string/hash 确定性。
8. 当前 V1 attribution Golden 在委托唯一 helper 后逐位不变。
9. nearest-rank Q50 的奇数、偶数、ties 测试。
10. nearest-rank Q67 使用精确 `2/3` 和 `ceil(q*N)-1`。
11. Threshold 只读取当前 Fold Training Candidate。
12. Validation 内容变化不改变该 Fold Threshold 或 manifest bytes。
13. REUSED OOS/Holdout绩效不可进入阈值或模型选择；部署重算只能读取第4.1节已经过去的Candidate strength。
14. Q50 接受集是 V1 接受集的子集或等集。
15. Q67 接受集是 Q50 接受集的子集或等集。
16. Filter 不改变 Candidate 的任何经济或身份字段。
17. Filtered Candidate 进入既有 2B/2C 后，2B/2C 版本与语义不变。
18. 同一输入产生相同 Threshold、接受集、manifest 和 experiment ID。
19. 任一 manifest/hash 改变返回 `EXPERIMENT_IDENTITY_INVALID`。
20. 四个 Fold 的首尾、24m/6m/6m roll 与 Validation 不重叠测试。
21. Preflight 的 `<15/fold`、`<80 total`、symbol/side deletion、empty threshold、hash mismatch 分别停止。
22. 13 条 Walk-forward 晋级条件逐条 fail/pass，且是 conjunction。
23. Q50/Q67 固定选择规则的边界值与 ties。
24. V1 Candidate、2B、2C、Golden 全量回归不变。
25. Scope guard 禁止 PnL、MFE/MAE、post-exit、REUSED OOS/Holdout绩效、尚未发生的数据、GUI、LLM、API Key 和交易接口；仅允许第4.1节已结束窗口的Candidate strength。

## 14. 任务数、耗时与资源预算

### 14.1 实测基线

当前已完成 V1 核心 OOS `OOS:NATIVE_PRIMARY:BASE_1X` 覆盖 787,681 分钟（约18个月），本机产物时间跨度约 218 秒，单 worker 峰值 RSS 100,454,400 bytes（约95.8 MiB），结果目录 9,214,549 bytes（约8.79 MiB）。既有真实规模容量矩阵记录父进程峰值约66.5 MiB；6 worker fixture 聚合 worker 峰值约194.6 MiB。正式 V1 单 worker RSS 高于短 fixture，故预算采用正式值而非仅采用 fixture。

### 14.2 V2-A 估算

- Candidate preflight：四 Fold 的 Training/Validation 4H Candidate 扫描和两个 threshold，预计 10–60 秒；预算 2 分钟。
- Capacity probe：Preflight 至少一个候选通过后、正式任务前，单独运行且只运行 `F4:V1_BASELINE`，区间 `2024-04-01T00:00:00.000Z` – `2024-09-30T23:59:59.999Z`。只记录 elapsed time、CPU time、peak RSS、output size；输出进入非权威 diagnostics，不参与候选选择、阈值、晋级或正式经济 hash。
- 正式分钟回放任务：Preflight 双失败为 **0 tasks**；单候选通过为 **8 tasks**；双候选通过为 **12 tasks**。Training 不回放 PnL；每 task 内保留既有 BASELINE/CONSERVATIVE 两 path，不把它们重复计为独立调度 task。Capacity probe 不计入正式任务数。
- 每 task：6个月约 259k–264k 分钟。按 18个月实测线性约 73 秒；考虑重叠数据读取、过滤后不同事件量和冷缓存，执行预算 **2–4 分钟/task**，hard timeout 保守设为 **21,600秒/task**，仅代表异常上限而非预期耗时。
- 串行：8 tasks 计划预算 **16–32分钟**；12 tasks 计划预算 **24–48分钟**；另加预检、一次probe和发布约4–10分钟。
- 安全并行：不预先固定6 workers。probe完成后按其实测单任务 peak RSS、CPU time、elapsed time与output size计算：若 `6 * probe_peak_rss * 1.5 + parent_peak_rss` 不超过当时可用物理内存的50%，且磁盘临时空间足够，则选择6；否则选择2。禁止选择其他数量。8/12 tasks在6 workers下计划约6–15分钟，在2 workers下计划约12–30分钟（均含spawn和I/O）。结果按预声明task key重建。
- 峰值 RAM：按正式单 worker 100,454,400 bytes × 6 + 父进程约69,730,304 bytes，再加50%数据/序列化安全余量，预算 **约1.0 GiB**；启动门槛建议至少2 GiB可用内存。worker 只读输入，不共享可变缓存/文件句柄，不写正式输出。
- 磁盘：18个月核心结果约8.79 MiB，线性6个月约2.93 MiB；8 tasks约23 MiB，12 tasks约35 MiB。考虑三身份 manifests、失败证据、probe diagnostics、临时原子发布副本与日志，预算 **100 MiB最终产物 + 100 MiB临时空间**，并预留至少500 MiB可用空间。
- 并行控制：Windows `spawn`；OMP/MKL/OpenBLAS/NumExpr 各1线程；`no_progress_timeout_seconds=None` 必须经过CLI、配置序列化和worker传递后仍为None；只保留每task `hard_timeout_seconds=21600`；外部监控CPU/RSS；任一必需task失败时取消未开始任务，不发布不完整绩效；全部成功后父进程 `fsync` + atomic replace。

这些是基于当前硬件与已存 V1 产物的容量计划，不是性能保证。正式运行前先以 Candidate preflight 的实际 count 和可用资源复核，但不得据此改变策略身份或阈值。

## 15. 计划自我审查

- [x] 策略身份恰好三个：`V1_BASELINE`、`V2A_Q50`、`V2A_Q67`。
- [x] 未加入趋势强度过滤。
- [x] 未加入成本比例过滤。
- [x] 未加入 SHORT、LONG、BTC 或 ETH 专属规则/阈值。
- [x] 未使用 REUSED OOS、Holdout 或交易 PnL 调参。
- [x] 未改变 V1 交易语义；未来唯一 attribution 改动只是委托同一公式并要求 Golden 不变。
- [x] 共享公式位于中立 `research_backtest.strategy`，不存在 `research_2d -> research_v2a` 依赖；删除 V2-A 不破坏 V1/归因/2B/2C。
- [x] 未增加通用 Harness；只规划独立、可移除的 V2-A orchestration。
- [x] strength、nearest-rank、中位数、PF、贡献集中度与选择规则均有明确公式/比较语义。
- [x] Q50/Q67 阈值来源、ties 与接受运算符无歧义。
- [x] 入选分位数部署时按24个月历史Candidate每6个月重算一次，且不读后验结果。
- [x] Preflight 后正式任务数只可能是0、8或12，淘汰候选不回放。
- [x] 每个Fold独立10,000 USDT；无跨Fold资金、持仓或复利；HALTED Fold不能晋级。
- [x] 正式任务前只有一个固定 F4/V1容量探针，且探针不参与选择或晋级。
- [x] Task 1–6均冻结基线SHA、精确新增签名、pytest命令、通过条件与独立commit message；既有引用不存在时fail closed。
- [x] 没有无限优化循环或自动继续；两者失败即 `V2A_WALK_FORWARD_FAILED` 并停止。

## 16. 人工审批点

本计划提交后停止。后续只有人工明确批准实施，才按 Task 1–6 编码；编码完成、Preflight通过并再次获得运行授权后，才执行一次固定 F4/V1容量探针，并据此选择2或6 workers，再执行0、8或12个 Walk-forward tasks。Gate A–D 均不属于本计划的执行授权。
