# 第二批 2C 最小事件引擎冻结规范

状态：`FROZEN_FOR_TDD_IMPLEMENTATION`

确定性运行时冻结为 `DETERMINISTIC_RESEARCH_RUNTIME_V1 = CPython 3.12.13`。2A、2B、
2C 的 Candidate、Plan 与 Simulation 在其他解释器或补丁版本上必须 fail closed；通用旧
GUI 包的 `Python >=3.11` 声明不构成研究运行时授权。

最终验收严格区分 24 条 `TIMELINE_REGISTRY_V1` 追踪记录和 6 个
`TIMELINE_FULL_GOLDENS_V1` 完整 Canonical Golden。后者冻结 input、event sequence、
ledger、fill/trade、equity、PathResult 哈希；前者不得称为 Golden fixture。

最终源码语义同时冻结如下：`ExecutionRejection.disposition` 是唯一拒绝控制源；
`CANDIDATE_REJECTED` 保留证据并继续，`EXECUTION_PATH_INVALID` 与
`EXPERIMENT_INVALID` 在任何 Fill 前终止整批。Ledger reducer 只处理 wallet、locks、
reserve 与 consumed identity；equity/peak 仅在带当前 mark 的估值步骤更新，部分平仓后按
全部剩余仓位重估。Entry batch 先在临时不可变状态完整预演，再全有或全无提交。
`SimulationResult`、`OutputManifest` 和逐分钟 `state_snapshots.jsonl` 必须绑定实际输入身份、
配置及输出哈希。生产 planner 默认从当前 `EngineState`、本分钟数据及版本化 evidence catalog
构造 2B 输入，不接受未来状态或预制 Sizing/Scaling/Plan。

父基线：`b07cd9e7dd56cfb628400ef0878c6610d4d6b894`

目标：以确定性的 UTC 1 分钟事件闭环，把 2A `StrategyCandidate` 在目标分钟调用 2B 纯规划器生成的 Plan，转化为可审计的历史模拟成交、逐仓仓位、账本、交易、权益和路径结果。

## 1. 权威边界与版本

- Python 确定性规则是唯一交易决策源；无 GUI、LLM、API Key、鉴权、HTTP、交易所写接口、`create_order` 或真实下单能力。
- 市场仅限 Binance USDⓈ-M `BTCUSDT`、`ETHUSDT` 永续；逐仓、单向持仓、固定 1 倍杠杆。
- 2C 可调用已冻结的 2A/2B 纯函数，但不得复制 2B 公式、重算 quantity/risk、修改 Candidate/Intent/Plan，或自行改变 stop、TP、风险预算。
- 爆仓始终是版本化估算，不声称精确复刻 Binance。
- 不包含 GUI/LLM、paper/live 自动化、绩效晋级、年化、Sharpe、walk-forward、OOS、参数网格或 2D。
- 冻结版本：`SIMULATION_CONFIG_V1`、`MINUTE_EVENT_ORDER_V2`、`INTRAMINUTE_HALT_POLICY_V1`、`ESTIMATED_FIXED_ISOLATED_MARGIN_V1`、`CANONICAL_2C_V1`。

## 2. 集成生命周期：禁止未来状态预生成 Plan

完整 `run_simulation` 不接受“预先知道未来账户状态后生成的最终 Plan 集合”作为权威输入。Golden 单元测试可直接注入 Plan，但必须显式标记 `LOCAL_PLAN_FIXTURE_ONLY`，不得进入完整 run identity。

### 2.1 Entry 生命周期

1. 接收 2A `StrategyCandidate`，调用现有 2B `make_entry_intent` 生成 `EntryIntent`。
2. Intent 等待自己的 `target_execution_time_utc_ms`；未来 Intent 不影响此前状态。
3. 2C 回放到目标分钟，先完成 funding、open 保护性退出和到期退出。
4. 2C 从该分钟 trade open 构造 BTC/ETH `TargetMinuteOpenSnapshot` 集合，从当前 `EngineState` 一次性构造唯一 `AccountPlanningEvidenceBundle`、`AccountPlanningSnapshot` 与 `PortfolioBatchCompletenessSnapshot`。
5. `plan_due_entry_batch` 一次接收同一 target minute 的全部 Intent：逐项调用现有 2B `position_sizing`，构造唯一 `PortfolioPlanningBatch`，只调用一次现有 `scale_portfolio`，得到唯一 `PortfolioScalingResult`；不得按 symbol 独立计算最终仓位，也不得在 item 被量化拒绝后重新放大其他 item。
6. 仅为 `AcceptedScalingItem` 调用现有 `build_entry_execution_plan`；原样保存全部 `PositionSizingResult`、`ExecutionRejection`、`RejectedScalingItem`、Batch、ScalingResult、Plan 及其 Canonical ID/hash。Plan 的 quantity、risk、required cash 必须来自同一证据链。
7. 批后若 `sum(plan.required_cash)>available_balance`、总计划风险超过当前组合1%上限，或 Plan 引用的 batch/scaling/account evidence 不一致，产生 `ENTRY_BATCH_POST_PLAN_INVARIANT_VIOLATION` 与 `PathInvalidEvent`，整批不生成任何 Entry Fill，路径立即 `INVALID`；这是实现不变量破坏，不得静默降级成“无交易”。正常现金/最小量拒绝只能由2B Sizing/Scaling产生正式 Rejection。

执行延迟（0/1/2 分钟）由 2B execution config 决定，不属于 Candidate，也不得改变 Candidate ID。

### 2.2 Scheduled Exit 生命周期

2C 按冻结条件创建 `ExitConditionSnapshot`，调用 2B `make_exit_intent`；到 Intent 的目标分钟 open 时构造 `TargetMinuteOpenSnapshot` 和当前 `PositionSnapshot`，再调用 `build_exit_execution_plan`。仅成功的 `ExitExecutionPlan` 可生成 Scheduled Exit Fill。失败必须保存 `ExecutionRejection`；影响既有仓位安全退出且不可恢复的缺失/拒绝使路径 `INVALID`。

四类条件：

- `TIME_EXIT`：来源唯一为 origin EntryPlan 的 `maximum_exit_time_utc_ms`；到达该事件时间创建 Intent。
- `TREND_EXIT`：只在已收盘 4H 决策边界评估；LONG 在 `trend_state != BULL`、SHORT 在 `trend_state != BEAR` 时触发。`NO_SETUP` 本身不是退出条件；应有而缺失的趋势证据使受影响路径 `INVALID`。
- `HALT_EXIT`：HALT 触发后为所有未平仓仓位创建，目标为下一可用 1m open；`HALTED` 不得阻止该 Intent/Plan。若仓位先被保护性退出，Intent/Plan 取消。
- `EXPERIMENT_END`：到 `simulation_end_exit_open_utc_ms` 以该分钟 open 退出全部剩余仓位；数据必须覆盖此 open，实验结束后禁止新 Entry，禁止使用“最后已知 close”临时成交。

同一 open 多个 Scheduled 原因的选择优先级为 `HALT_EXIT > TREND_EXIT > TIME_EXIT > EXPERIMENT_END`。相同成交只产生一个 Fill，输出保存全部命中原因、最终选择原因和取消原因。

## 3. SimulationConfig、初始状态与身份

`SimulationConfig` 至少包含：

```text
schema_version=SIMULATION_CONFIG_V1
symbols=(BTCUSDT, ETHUSDT)
simulation_start_utc_ms
simulation_end_exit_open_utc_ms
initial_wallet_balance
leverage=1
position_mode=ONE_WAY
margin_mode=ISOLATED
active_path_kinds=(BASELINE, CONSERVATIVE)
minute_event_order_version=MINUTE_EVENT_ORDER_V2
intraminute_halt_policy_version=INTRAMINUTE_HALT_POLICY_V1
liquidation_model_version=ESTIMATED_FIXED_ISOLATED_MARGIN_V1
cost_model_version
funding_model_version
two_a_version
two_b_planner_version
two_b_planner_config_hash
code_commit
dependency_lock_hash
config_content_hash
config_id
```

开始/结束时间必须对齐 UTC 1m open，且结束不早于开始，否则 fail closed。初始状态固定：`wallet_balance=equity=peak_equity=initial_wallet_balance`，全部 locks 为 0，无仓位、无已消费 Intent/Plan/funding/close ID，`path_state=VALID`。

`simulation_run_id` 只依赖 SimulationConfig 内容、规范 trade/mark/funding 内容 hash、Candidate stream/manifest hash、2A 版本、2B planner 版本/config hash、contract/cost/funding-risk/maintenance 证据 hash、代码与依赖版本。采集时间和 acquisition manifest 不得进入。完整 run 不以预生成 Plan 集合为输入身份；运行中实际生成的 Intent/Plan/Rejection 是输出身份的一部分。

## 4. 输入、可见性与缺口

- 仅使用已收盘、UTC 对齐的 1m trade/mark；trade 驱动 open/fill/stop/TP，mark 驱动估算爆仓、未实现 PnL、equity/HALT。
- funding 使用真实 timestamp/rate/结算 mark 证据；index 仅审计告警。
- Candidate stream 只允许在其 decision watermark 后可见；2C 读取完整分钟 OHLC 仅用于历史执行/风险，不得反向修改 Candidate/Plan。
- trade 缺口影响行情、入场、退出或持仓时 `INVALID`；持仓期间 mark 缺口 `INVALID`；有仓位跨越但缺 funding 结算 `INVALID`；空仓且无相关事件的 trade/mark 缺口只记录；index 缺口不改变路径。
- INVALID 分钟写 `PathInvalidEvent`、terminal `StateSnapshot` 和 `PathResult`，此后不得生成 Ledger/Trade/Equity。关键 mark 缺失时不得伪造该分钟 `EquityPoint`。

## 5. 唯一逐分钟事件顺序

版本 `MINUTE_EVENT_ORDER_V2`：

1. `LOAD_CLOSED_INPUTS`
2. `FAIL_CLOSED_DATA_GATE`
3. `OPENING_POSITION_RECONCILIATION`
4. `FUNDING_SETTLEMENT`
5. `OPEN_GAP_PROTECTIVE_GATE`
6. `SCHEDULED_OPEN_EXITS`
7. `OPEN_EQUITY_AND_HALT_GATE`
8. `ENTRY_PLANNING_AND_BATCH_GATE`
9. `ENTRY_FILLS`
10. `INTRAMINUTE_TRIGGER_DISCOVERY`
11. `AMBIGUITY_POLICY_SELECTION`
12. `PROTECTIVE_OR_LIQUIDATION_EXITS`
13. `MARK_TO_MARKET_CLOSE`
14. `HALT_AND_CANONICAL_COMMIT`

`OPEN_GAP_PROTECTIVE_GATE` 只检查进入本分钟前已存在的仓位：mark open 越过估算爆仓线、trade open 越过 stop、trade open 越过 TP。优先级固定为 `ESTIMATED_LIQUIDATION > STOP > TAKE_PROFIT > SCHEDULED_EXIT`。open 保护性退出后，对应 Scheduled Intent/Plan 记录取消，禁止重复平仓。

funding 对进入该分钟前已持有且命中结算点的仓位结算；同刻退出仍结算，新 Entry 不结算。Scheduled Exit 在 Entry planning 前释放资金。Entry planner 必须看到 funding、保护性退出、Scheduled Exit 之后的真实当前账户状态。

## 6. 成交、费用、资金费与逐仓保证金

- Entry/Scheduled Exit actual fill 必须分别等于 2B Plan 的 expected fill；Plan 已含滑点，禁止第二次加滑点。
- `fee = abs(quantity * fill_price) * effective_fee_rate`；入场和每次退出各记一次。Plan fee 只用于一致性校验，唯一经济扣款来自 Ledger。
- 非 gap stop/TP 使用 trigger reference 加一次退出方向不利滑点；gap 使用 trade open reference 加一次不利滑点，再按 tick 不利量化。
- `funding_wallet_delta = -(side_sign * quantity * funding_mark_price * historical_rate)`，LONG `side_sign=+1`，SHORT `-1`；每个 position/timestamp 恰好一次。

V1 唯一逐仓定义：

```text
isolated_margin_balance = origin EntryPlan.initial_margin
M = isolated_margin_balance
```

entry/exit fee 与 funding 只改变 wallet；margin lock/release 只改变 `locked_initial_margin`；fee/funding 不得再从 isolated margin 扣除。`isolated_margin_balance` 持仓期间不因 fee/funding 自动变化。这是 `ESTIMATED_FIXED_ISOLATED_MARGIN_V1 / ESTIMATED_NOT_EXCHANGE_EXACT` 近似。

Funding reserve 生命周期：Entry 锁定 Plan 全部 reserve；按 `funding_event_count` 计算 planned slice；每个实际 funding 事件释放一个 slice；实际 funding wallet delta 只记一次；Exit 释放剩余 reserve；funding 收入不增加 reserve；reserve 释放不是收入。若 `actual_adverse_payment > remaining_reserve`，必须在提交前生成含 `position_id`、funding timestamp/record ID、actual payment、remaining reserve 的 `FundingReserveExceeded`，再生成 `PathInvalidEvent` 并立即 `INVALID`；不得提交该次 funding wallet Ledger、reserve release Ledger，不得修改 position remaining reserve/events，terminal 必须保留失败证据且该路径不得进入绩效晋级。禁止部分修改账户后再 INVALID。任一事件后 `available_balance < 0`、wallet 无法覆盖 locks、或 `isolated_margin_balance <= 0` 均 INVALID，禁止 `max(0)` 修补。

## 7. 估算爆仓与触发

`q=quantity`、`P=entry_price`、`r=maintenance_margin_rate`：

- LONG：`liq = max(0, (q*P - M) / (q*(1-r)))`
- SHORT：`liq = (M + q*P) / (q*(1+r))`

LONG 用 mark low、SHORT 用 mark high 检查。open 已越过时 reference=mark open，否则 reference=liq。maintenance 证据必须含 tier/notional range、有效期、来源 hash 和 `VERIFIED|APPROXIMATED`；持仓时缺失/过期即 INVALID。任何输出必须带 `ESTIMATED_NOT_EXCHANGE_EXACT`。

## 8. 有界双路径歧义

`BASELINE` 和 `CONSERVATIVE` 在 simulation start 即创建，active path 数始终恰为2；不得等到第一次歧义才创建，也不得新增第三条路径。第一次歧义前，除 path identity 外，两条路径的 Event 经济事实、Ledger、Fill、Trade、Equity 必须完全一致；从第一次歧义所在分钟起才允许各自 policy 产生不同后继。状态重新相同仍保留两个 identity。

- BASELINE：选择相对各自 minute open 绝对百分比距离最小的触发；相等时 `LIQUIDATION > STOP > TAKE_PROFIT`。
- CONSERVATIVE：在 1m OHLC 可支持的候选中选择 minute-end equity 最低的结果；相等用同一优先级。
- 每个歧义分钟保存候选集、选择理由、parent snapshot hash 和 `PATH_AMBIGUOUS`；不得使用未来 close 之后的数据、后续分钟或后续 funding 选择当前结果。
- 未来2D必须分别报告两条路径；禁止将两条路径的交易、收益或样本数量相加。

## 9. Account、HALT、INVALID 与 Equity

所有经济量仅由 Ledger reducer 产生：

```text
equity = wallet_balance + unrealized_pnl
available_balance = wallet_balance
  - locked_initial_margin
  - locked_fee_reserve
  - locked_funding_reserve
  - pending_plan_reserve
```

禁止同一资金重复占用；同一 Plan、funding timestamp、fee obligation 和 position close 只能入账一次。

HALT 为吸收状态但不是立即终止模拟。PathResult 保存 `halt_trigger_time_utc_ms`、`halt_reason`、`entry_disabled=true`、可空 `flat_after_halt_time_utc_ms`、`final_processed_time_utc_ms`。HALT 后永久禁止 Entry，但已有仓位继续 funding、保护性退出和 Scheduled Exit，继续产生 Ledger/Trade/Equity，直到全部关闭或 experiment end。2C 不计算年化或晋级指标；未来 2D 只能用 halt 前区间做晋级。

`INTRAMINUTE_HALT_POLICY_V1=CONSERVATIVE_FULL_MINUTE_WHILE_INTRAMINUTE_POSITION_ACTIVE`：

- open gap 或 Scheduled Exit 已关闭的仓位不使用该分钟后续 mark extreme。
- 本分钟 open 新建且持有到 close 的仓位使用完整分钟不利 mark extreme。
- 本分钟 intraminute 保护性退出的仓位，保守地允许使用完整分钟不利 mark extreme，并明确标记估算。
- 组合最低权益只使用当时仍可能暴露的仓位集合；阈值统一为相对 peak `>=10%`。

每个“成功完成 `MARK_TO_MARKET_CLOSE` 的有效分钟”每路径至少一个 EquityPoint；INVALID 分钟若无法完成 mark，不适用该要求。

## 10. 输出闭集

每次完整运行输出：实际 Intent、2B Plan/ExecutionRejection、Fill、Event、Ledger、Position、Trade、Equity、StateSnapshot、PathResult 和 Canonical manifest。`TradeRecord.net_pnl = gross_pnl - entry_fee - exit_fee + funding_wallet_delta_sum`。Event 只保存事实；before/after 由 Ledger reducer 和 StateSnapshot 推导，不允许 Fill 或 TradeRecord 成为独立状态真相源。

## 11. 冻结 Requirements（60，语义修订后数量不变）

| 范畴 | Requirement IDs | 数量 |
|---|---|---:|
| 生命周期与规划 | `2C-LIFE-001..012` | 12 |
| 成交与触发 | `2C-FILL-001..010` | 10 |
| 费用与资金费 | `2C-COST-001..009` | 9 |
| 仓位与爆仓 | `2C-POS-001..007` | 7 |
| 账户与风险 | `2C-ACCT-001..010` | 10 |
| 数据与路径 | `2C-DATA-001..006` | 6 |
| 身份与回放 | `2C-ID-001..003` | 3 |
| 范围与安全 | `2C-SCOPE-001..003` | 3 |
| **总计** |  | **60** |

每项必须在验收矩阵绑定显式 Unit Test、Property Test 或 Golden Fixture、实现文件，以及适用的红队场景。

## 12. 编码授权与停止线

本规范完成交叉审计后授权按 TDD 实施 2C，无需再次纯文档审批。编码必须从批准基线创建独立 feature 分支；每个 Task 先写独立参考/Golden 再写生产代码。完成后创建 Draft PR 并停止等待源码审查。不得开始 2D，亦不得增加 GUI、LLM、API Key、HTTP、交易接口或自动下单能力。
