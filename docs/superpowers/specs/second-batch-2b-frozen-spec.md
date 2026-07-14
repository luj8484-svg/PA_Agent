# 第二批 2B 规格冻结规范

日期：2026-07-14

状态：`FROZEN_FOR_ONE_TIME_HUMAN_REVIEW`

上游基线：`fork/main@07004498a7091519a4fb08c323a1dde5b97ced6d`
实现授权：未授权。本文只冻结设计；人工书面批准前不得编码。

## 1. 权威性、目标与范围

本文是 2B 的唯一规范入口。与旧文档冲突时，2B 以本文为准；2A 的 Candidate 规范和第一批数据规范不被本文改写。任何字段、公式、舍入、枚举、优先级或 ID 输入变更都必须提升相应版本并重新走完整审核。

2B 的目标是把已经冻结的 `StrategyCandidate` 转换为不改变账户的纯领域意图、计划或拒绝，并为未来 2C 提供可重放、可验证、无 wall clock 的输入。2B 只允许：

1. `EntryIntent`、`EntryExecutionPlan`；
2. `ExitIntent`、`ExitExecutionPlan`；
3. `ExecutionRejection`；
4. contract rule 覆盖解析；
5. gap、费用、滑点、资金费缓冲、风险预算、仓位、量化、minimum 和组合缩量纯函数；
6. Canonical、确定性 ID、版本、Golden Fixture 与 property-test 设计。

2B 明确不实现：分钟事件回放、真实/模拟成交、账户修改、仓位创建或关闭、资金费结算、止损/止盈/爆仓触发判断、Ledger、PnL、收益、回撤、报告、GUI、LLM、HTTP、API Key、交易所客户端、`create_order` 或任何实盘接口。这些职责属于 2C、2D 或永久禁止范围。

## 2. 纯模块边界和唯一数据来源

计划实现时只能创建无 I/O 的纯模块；本轮不创建这些文件。冻结的未来文件边界如下：

| 未来模块 | 唯一职责 | 允许依赖 | 禁止职责 |
|---|---|---|---|
| `domain/intents.py` | Entry/Exit Intent Schema、Canonical、ID | 2A domain、canonical、versions | 价格、仓位、网络 |
| `domain/plans.py` | Entry/Exit Plan Schema、Canonical、ID | intents、纯值对象 | Fill、账户 mutation |
| `domain/rejections.py` | Rejection Schema、优先级、ID | enums、canonical | 市场结论改写 |
| `domain/contracts.py` | ContractRuleCoverage tagged union | canonical、versions | 下载 exchangeInfo |
| `domain/costs.py` | CostModelSnapshot | Decimal、versions | 真实扣款 |
| `planning/time.py` | target time 纯函数 | 整数 UTC 时间 | wall clock |
| `planning/prices.py` | gap、滑点、tick、价格几何 | Decimal | 撮合 |
| `planning/funding.py` | schedule 覆盖和缓冲次数 | 冻结 schedule snapshot | 资金费结算 |
| `planning/sizing.py` | 单计划 sizing、minimum | 纯快照 | 仓位创建 |
| `planning/portfolio.py` | 同刻等比例缩量 | sizing results、账户快照 | 二次再分配 |
| `planning/factory.py` | 编排纯函数并只生成 final object | 上述模块 | I/O、状态修改 |

唯一数据来源：

- 市场结论：2A `StrategyCandidate`；禁止重新计算方向。
- 目标分钟参考价：已验证、已收盘或已到达事件水位的 trade 1m open；禁止提前读取未来 open。
- 合约规则：按执行时刻解析的版本化 `ContractRuleCoverage`。
- 成本：版本化 `CostModelSnapshot`，不是交易所账户查询。
- 资金费排程：版本化、带覆盖区间的 schedule snapshot；不是固定乘数。
- 账户：不可变 `AccountPlanningSnapshot`；2B 只读。
- 退出条件：未来 2C 提供的不可变 `ExitConditionSnapshot`；2B 不判断 stop/TP/liquidation 是否命中。
- 时间：市场/实验事件时钟及其确定性推导；本地 wall clock 永远禁止。

## 3. 全局确定性与数值规则

### 3.1 类型

- 价格、数量、费率、费用、保证金、风险、余额全部使用有限 `Decimal`。
- UTC 时间使用非负整数毫秒 `int`，禁止 `bool` 冒充 `int`。
- ID、版本、hash、枚举使用非空字符串；SHA-256 为 64 个小写 hex。
- 2B 禁止任何 `float` 进入领域对象或公式。
- 所有金额和风险 V1 保留完整 Decimal，不进行 USDT 分位舍入；交易边界只按 tick/step 定向量化。

### 3.2 Canonical 序列化

版本：`2B_CANONICAL_VERSION_V1`。

1. JSON UTF-8、键 Unicode 码点升序、无空白、不得输出 NaN/Infinity。
2. Decimal 输出规范十进制字符串：无指数、去除无意义尾零，零统一为 `"0"`。
3. Enum 输出其字符串值；tuple 输出 JSON array；对象字段完整输出，禁止依赖默认值省略字段。
4. Map 仅允许字符串键；set、bytes、datetime、float 和 wall-clock metadata 禁止进入 Canonical。
5. 数组顺序必须有领域语义；无领域顺序的输入先按冻结 key 排序。
6. acquisition manifest、下载时间、重试信息、Index audit hash 不进入 Intent/Plan/Rejection ID。

### 3.3 ID 规则

所有正式对象禁止空 ID、格式正确但内容错误 ID，以及先用空 ID 构造再 `replace` 的两阶段公开对象。工厂先构造私有 payload，再计算 ID，最后一次性构造 frozen object。`__post_init__` 必须重新计算并验证。

| 对象 | ID 公式 |
|---|---|
| EntryIntent | `eint_ + first_24_hex(intent_content_hash)` |
| ExitIntent | `xint_ + first_24_hex(intent_content_hash)` |
| EntryExecutionPlan | `eplan_ + first_24_hex(plan_content_hash)` |
| ExitExecutionPlan | `xplan_ + first_24_hex(plan_content_hash)` |
| ExecutionRejection | `rej_ + first_24_hex(rejection_content_hash)` |
| RejectionSubjectRef | `sref_ + first_24_hex(subject_content_hash)` |
| TargetMinuteOpenSnapshot | `tmopen_ + first_24_hex(snapshot_content_hash)` |
| TargetEventWatermark | `tmark_ + first_24_hex(watermark_content_hash)` |
| PortfolioPlanningBatch | `pbatch_ + first_24_hex(batch_content_hash)` |
| ContractRuleCoverage | `cr_ + first_24_hex(coverage_content_hash)` |
| CostModelSnapshot | `cost_ + first_24_hex(snapshot_content_hash)` |
| FundingScheduleSnapshot | `fsched_ + first_24_hex(schedule_content_hash)` |
| FundingRiskConfigSnapshot | `frisk_ + first_24_hex(content_hash)` |
| AccountPlanningSnapshot | `acct_ + first_24_hex(snapshot_hash)` |
| ExitConditionSnapshot | `xcond_ + first_24_hex(condition_content_hash)` |
| ExecutionTimeConfig | `etime_ + first_24_hex(config_content_hash)` |
| PositionSizingResult | `size_ + first_24_hex(result_content_hash)` |
| PortfolioScalingResult | `scale_ + first_24_hex(result_content_hash)` |
| AcceptedScalingItem | `asitem_ + first_24_hex(item_content_hash)` |
| RejectedScalingItem | `rsitem_ + first_24_hex(item_content_hash)` |

### 3.4 content/config hash 精确输入

| Hash | 精确 Canonical payload（排除该 hash 和对应 ID） |
|---|---|
| `EntryIntent/ExitIntent.intent_content_hash` | 对应closed Schema全字段，排除 `intent_id,intent_content_hash` |
| `EntryExecutionPlan/ExitExecutionPlan.plan_content_hash` | 对应closed Schema全字段，排除 `plan_id,plan_content_hash` |
| `ExecutionRejection.rejection_content_hash` | 全字段，排除 `rejection_id,rejection_content_hash` |
| `RejectionSubjectRef.subject_content_hash` | 对应union payload全字段，排除 `subject_id,subject_content_hash` |
| `PositionSizingResult/PortfolioScalingResult.result_content_hash` | 对应closed Schema全字段，排除 `result_id,result_content_hash` |
| `intent_config_hash` | `{execution_time_config_id, execution_time_config_content_hash, entry_intent_schema_version, canonical_version}` |
| `plan_config_hash` | `{execution_time_version,gap_version,price_geometry_version,fee_model_version,slippage_model_version,funding_schedule_version,funding_risk_version,sizing_version,scaling_version,contract_minimum_version,leverage_policy_version,rejection_priority_version,canonical_version,entry_or_exit_plan_schema_version,planning_phase_version}` |
| `rejection_config_hash` | `{rejection_schema_version,subject_union_schema_version,ordered_reason_priority_rows,ordered_subject_reason_stage_disposition_retry_rows,canonical_version}` |
| `TargetMinuteOpenSnapshot.snapshot_content_hash` | `{schema_version,symbol,stream,open_time_utc_ms,open_price,source_event_id,source_stream_version,event_watermark_time_utc_ms,created_by,code_commit,dependency_lock_hash}` |
| `TargetEventWatermark.watermark_content_hash` | `{schema_version,symbol,target_open_time_utc_ms,event_watermark_time_utc_ms,source_event_id,source_stream_version,created_by,code_commit,dependency_lock_hash}` |
| `PortfolioPlanningBatch.batch_content_hash` | `{schema_version,eligible_time_utc_ms,ordered_entry_intent_ids,ordered_symbols,account_snapshot_id,account_snapshot_hash,target_open_snapshot_ids,batch_completeness_watermark,batch_config_hash,code_commit,dependency_lock_hash}` |
| `ContractRuleCoverage.coverage_content_hash` | 全部 union payload 字段，排除 `coverage_id,coverage_content_hash` |
| `CostModelSnapshot.snapshot_content_hash` | 全部字段，排除 `snapshot_id,snapshot_content_hash` |
| `FundingScheduleSnapshot.schedule_content_hash` | 第 8 节冻结的全部 schedule 字段，排除 `schedule_id,schedule_content_hash` |
| `FundingRiskConfigSnapshot.content_hash` | 第 8 节冻结的全部 risk config 字段，排除 `config_id,content_hash` |
| `AccountPlanningSnapshot.snapshot_hash` | 第 5.14 节全部字段，排除 `snapshot_id,snapshot_hash` |
| `ExitConditionSnapshot.condition_content_hash` | `{schema_version,origin_candidate_id,position_id,position_snapshot_hash,symbol,position_side,exit_quantity,scheduled_exit_reason,condition_time_utc_ms,condition_visible_input_hash,code_commit,dependency_lock_hash}` |
| `ExecutionTimeConfig.config_content_hash` | `{schema_version,entry_delay_minutes,exit_delay_minutes,anchor_policy_version,version,canonical_version}` |
| `PortfolioPlanningBatch.batch_config_hash` | `{batch_schema_version,completeness_policy_version,sorting_policy_version,planning_phase_version,canonical_version}` |
| `AcceptedScalingItem.item_content_hash` | 第 5.12 节全部字段，排除 `item_id,item_content_hash` |
| `RejectedScalingItem.item_content_hash` | 第 5.12 节全部字段，排除 `item_id,item_content_hash` |

`PositionSizingResult.input_hash` 和 `PortfolioScalingResult.input_hash` 从 Schema 删除；正式字段和 result ID 已完整表达输入，禁止保存不能从对象自证的泛化 hash。

## 4. 公共枚举和 tagged union

```text
Side = LONG | SHORT
MarginMode = ISOLATED
PositionMode = ONE_WAY
OrderType = MARKET_AT_1M_OPEN
TriggerBasis = TRADE_1M_OPEN
ContractRuleMode = VERIFIED | APPROXIMATED | UNAVAILABLE
FundingRiskVerificationMode = VERIFIED | APPROXIMATED | UNAVAILABLE
ResearchStage = BACKTEST | PAPER_SIMULATION | LIVE_ELIGIBILITY_RESEARCH
RejectionDisposition = EXPERIMENT_INVALID | EXECUTION_PATH_INVALID | CANDIDATE_REJECTED | PLAN_CANCELLED
RejectionSubjectKind = CANDIDATE | ENTRY_INTENT | EXIT_INTENT | ENTRY_PLAN | EXIT_PLAN | PORTFOLIO_BATCH
ScheduledExitReason = TIME_EXIT | TREND_EXIT | HALT_EXIT | EXPERIMENT_END
ProtectiveExitReason2C = STOP_TRIGGER | TP_TRIGGER | ESTIMATED_LIQUIDATION
ApproximationDirection = PRIOR_ONLY_APPROXIMATION | HINDSIGHT_DIAGNOSTIC_APPROXIMATION
ContractRuleReviewStatus = APPROVED_VERIFIED | APPROVED_PRIOR_ONLY | APPROVED_HINDSIGHT_DIAGNOSTIC
PlanningPhase = POST_SAME_TIME_FUNDING_AND_SCHEDULED_EXITS_PRE_ENTRY_BATCH_V1
```

Entry 与 Exit 是不同 Schema。Contract coverage、RejectionSubjectRef 和 portfolio item 都是 tagged union。禁止以一个大 Schema 加互斥 nullable 字段模拟联合类型。`RETRYABLE` 不是 disposition；可重试性只存在 `retry_allowed: bool`。

## 5. 领域对象 Schema

下表中的“必填”均为正式对象必填；`None` 不允许，除非字段类型明确写为 optional。正式对象均 frozen。

### 5.1 EntryIntent

EntryIntent 只能由 `LONG` 或 `SHORT` Candidate 创建，表达未来计划请求，不读取目标分钟价格、contract rule、账户或成本。

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `ENTRY_INTENT_SCHEMA_V1` |
| intent_id | str | 是 | Canonical payload | `eint_[0-9a-f]{24}` 且内容匹配 |
| intent_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| candidate_id | str | 是 | StrategyCandidate | 非空、已通过 2A 校验 |
| candidate_schema_version | str | 是 | Candidate | `STRATEGY_CANDIDATE_SCHEMA_V1` |
| computational_experiment_id | sha256 | 是 | experiment manifest | 不含 acquisition identity |
| symbol | str | 是 | Candidate | `BTCUSDT` 或 `ETHUSDT` |
| side | Side | 是 | Candidate.market_view | LONG→LONG、SHORT→SHORT；NO_SETUP 禁止 |
| candidate_decision_time_utc_ms | int | 是 | Candidate | 事件时钟 |
| intent_created_time_utc_ms | int | 是 | Candidate | 必须等于 decision time |
| execution_anchor_utc_ms | int | 是 | TIME-F01 | 下一 4H UTC open |
| target_execution_time_utc_ms | int | 是 | TIME-F01 | anchor + delay |
| execution_delay_minutes | int | 是 | ExecutionTimeConfig | 仅 `0/1/2` |
| execution_time_config_id | str | 是 | ExecutionTimeConfig | 内容已校验 |
| execution_time_config_content_hash | sha256 | 是 | ExecutionTimeConfig | 进入 Intent ID |
| execution_time_config_version | str | 是 | config | `EXECUTION_TIME_CONFIG_V1` |
| decision_visible_input_hash | sha256 | 是 | Candidate | 原样复制 |
| strategy_version | str | 是 | Candidate | 原样复制 |
| intent_config_hash | sha256 | 是 | 冻结 2B intent config | 不含 wall clock |
| code_commit | hex str | 是 | 实验 manifest | 7–64 小写 hex |
| dependency_lock_hash | sha256 | 是 | 实验 manifest | 64 小写 hex |

Candidate→EntryIntent 只能读上表来源中的 StrategyCandidate、ExecutionTimeConfig 和 experiment manifest identity。该转换不得读 AccountPlanningSnapshot、existing position、HALTED state、contract rule、cost、funding schedule/risk、TargetMinuteOpenSnapshot。因此同一 Candidate、delay 和 manifest 在不同账户状态下必须生成完全相同的 EntryIntent 和 `intent_id`。仅合法 `NO_SETUP` 返回 `CANDIDATE_NOT_ACTIONABLE`；Candidate Schema、ID/hash、方向或 MarketView 非法一律 `DATA_INVALID`。

### 5.2 TargetMinuteOpenSnapshot

Plan factory 禁止接收完整 1m Kline，只接收下列已封闭 Snapshot：

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `TARGET_MINUTE_OPEN_SNAPSHOT_SCHEMA_V1` |
| snapshot_id | str | 是 | snapshot_content_hash | `tmopen_[0-9a-f]{24}` |
| snapshot_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| symbol | str | 是 | target event | BTCUSDT/ETHUSDT |
| stream | str | 是 | 常量 | `trade` |
| open_time_utc_ms | int | 是 | target event | 必须等于 Intent target |
| open_price | Decimal | 是 | target minute open event | 有限且>0 |
| source_event_id | str | 是 | event engine | 必须是 open-event identity；其 payload 只含 `symbol,stream,open_time_utc_ms,open_price,source_stream_version`，禁止依赖该 bar 的未来 HLCV/成交统计 |
| source_stream_version | str | 是 | data stream manifest | 非空；只标识 open-event Schema/来源，不包含 bar content hash |
| event_watermark_time_utc_ms | int | 是 | event engine | `>=open_time_utc_ms`；非 wall clock；同一 open event 下不因未来 HLCV 改变 |
| created_by | str | 是 | 常量 | `PYTHON_DETERMINISTIC` |
| code_commit | str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 64小写hex |

Schema 是 closed-world；`high,low,close,volume,quote_volume,trade_count,taker_volume,close_time,is_closed` 以及任何 bar-close metadata 都是禁止字段。`source_event_id=tmopen_source_+first_24_hex(SHA256(Canonical({symbol,stream,open_time_utc_ms,open_price,source_stream_version})))`，其中 `source_stream_version` 由数据流 manifest 冻结但不得编码未来 bar 内容。Plan 的 `reference_price`和 `target_minute_input_hash` 只能分别复制 `open_price`和 `snapshot_content_hash`。

Snapshot 缺失时仍需要独立显式 watermark，因此 `TARGET_EVENT_WATERMARK_SCHEMA_V1` 字段全部必填：`schema_version,watermark_id,watermark_content_hash,symbol,target_open_time_utc_ms,event_watermark_time_utc_ms,source_event_id,source_stream_version,created_by=PYTHON_DETERMINISTIC,code_commit,dependency_lock_hash`。`watermark_id=tmark_+first24(watermark_content_hash)`，hash按第3.4节重算。Snapshot存在时，其watermark字段必须与独立Watermark一致；Snapshot缺失时，只能由该对象证明target已越过。

### 5.3 EntryExecutionPlan

EntryExecutionPlan 只能在目标 1m open 已可见后生成，并且是 portfolio scaling 后的 final plan。内部 draft 不是领域对象、不可持久化、无 ID。

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `ENTRY_EXECUTION_PLAN_SCHEMA_V1` |
| plan_id | str | 是 | Canonical payload | `eplan_[0-9a-f]{24}` 且内容匹配 |
| plan_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| intent_id | str | 是 | EntryIntent | 内容已校验 |
| candidate_id | str | 是 | EntryIntent | 不重新派生 |
| computational_experiment_id | sha256 | 是 | 实验 manifest | acquisition hash 排除 |
| portfolio_planning_batch_id | str | 是 | PortfolioPlanningBatch | 同 target batch |
| portfolio_scaling_result_id | str | 是 | PortfolioScalingResult | accepted item 唯一来源 |
| accepted_scaling_item_id | str | 是 | AcceptedScalingItem | symbol/quantity一致 |
| symbol | str | 是 | Intent | BTCUSDT/ETHUSDT |
| side | Side | 是 | Intent | 必须与 Candidate 一致 |
| decision_time_utc_ms | int | 是 | Intent | 事件时钟 |
| target_execution_time_utc_ms | int | 是 | Intent | 1m UTC open |
| plan_created_time_utc_ms | int | 是 | 目标分钟市场事件 | 必须等于 target time；非 wall clock |
| maximum_exit_time_utc_ms | int | 是 | TIME-F03 | target + 48h |
| order_type | OrderType | 是 | 常量 | `MARKET_AT_1M_OPEN` |
| trigger_basis | TriggerBasis | 是 | 常量 | `TRADE_1M_OPEN` |
| target_open_snapshot_id | str | 是 | TargetMinuteOpenSnapshot | 内容已校验 |
| reference_price | Decimal | 是 | TargetMinuteOpenSnapshot.open_price | 有限且 >0，未加滑点 |
| expected_entry_fill_price | Decimal | 是 | PRICE-F04 | tick 对齐、>0 |
| stop_trigger_price | Decimal | 是 | PRICE-F05 | tick 对齐、>0 |
| take_profit_trigger_price | Decimal | 是 | PRICE-F06 | tick 对齐、>0 |
| expected_stop_fill_price | Decimal | 是 | PRICE-F07 | tick 对齐、>0 |
| expected_take_profit_fill_price | Decimal | 是 | PRICE-F08 | tick 对齐、>0 |
| planned_exit_notional_price_basis | Decimal | 是 | PRICE-F10 | 价格包络最大值 |
| funding_notional_price_basis | Decimal | 是 | FUND-F13 | 等于 planned exit basis |
| quantity | Decimal | 是 | AcceptedScalingItem.final_quantity | step 对齐、>0；Plan不得自行缩量 |
| notional | Decimal | 是 | RISK-F18 | `quantity*entry_fill` |
| unit_risk | Decimal | 是 | RISK-F13 | >0 |
| single_risk_budget | Decimal | 是 | RISK-F14 | current_equity×0.005 |
| planned_risk | Decimal | 是 | RISK-F17 | quantity×unit_risk，≤ budget |
| existing_open_risk | Decimal | 是 | Account snapshot | ≥0 |
| pending_plan_risk | Decimal | 是 | Account snapshot | ≥0；不含本批 |
| total_risk_after_plan | Decimal | 是 | RISK-F22 | ≤ equity×0.01 |
| initial_margin | Decimal | 是 | CASH-F19 | 等于 notional；leverage=1 |
| entry_fee | Decimal | 是 | COST-F09 | ≥0 |
| exit_fee_reserve | Decimal | 是 | COST-F10 | ≥0，只预留一次 |
| funding_event_upper_bound | int | 是 | FUND-F11 | ≥0 |
| effective_adverse_rate_cap | Decimal | 是 | FUND-F14 | 有限且≥0 |
| funding_reserve | Decimal | 是 | FUND-F12 | ≥0 |
| required_cash | Decimal | 是 | CASH-F20 | 四项和，仅锁定不扣款 |
| leverage | int | 是 | 常量 | 精确等于 1 |
| margin_mode | MarginMode | 是 | 常量 | ISOLATED |
| position_mode | PositionMode | 是 | 常量 | ONE_WAY |
| execution_delay_minutes | int | 是 | Intent | 0/1/2 |
| execution_time_config_version | str | 是 | Intent | 固定版本 |
| contract_rule_mode | ContractRuleMode | 是 | coverage | VERIFIED/APPROXIMATED；UNAVAILABLE 无 Plan |
| contract_rule_coverage_id | str | 是 | coverage | 内容已校验 |
| contract_rule_coverage_content_hash | sha256 | 是 | ContractRuleCoverage.coverage_content_hash | 进入 plan ID |
| contract_rule_version | str | 是 | coverage | 有效期覆盖 target |
| cost_model_snapshot_id | str | 是 | CostModelSnapshot | 内容已校验 |
| cost_model_snapshot_content_hash | sha256 | 是 | CostModelSnapshot.snapshot_content_hash | 进入 plan ID |
| funding_schedule_version | str | 是 | schedule | 覆盖 `(target,max_exit]` |
| funding_schedule_content_hash | sha256 | 是 | schedule | 进入 plan ID |
| funding_risk_config_id | str | 是 | FundingRiskConfigSnapshot | target 有效 |
| funding_risk_config_content_hash | sha256 | 是 | FundingRiskConfigSnapshot | 进入 plan ID |
| funding_risk_config_version | str | 是 | FundingRiskConfigSnapshot.version | 进入 plan ID |
| account_snapshot_id | str | 是 | Account snapshot | 同一规划批次冻结 |
| account_snapshot_hash | sha256 | 是 | Account snapshot | 进入 plan ID |
| position_sizing_result_id | str | 是 | PositionSizingResult | 未缩量结果 |
| target_minute_input_hash | sha256 | 是 | TargetMinuteOpenSnapshot.snapshot_content_hash | 不含未来 HLCV |
| decision_visible_input_hash | sha256 | 是 | Candidate | 原样复制 |
| plan_config_hash | sha256 | 是 | 2B config | 公式/枚举/优先级版本集合 |
| code_commit | hex str | 是 | manifest | 7–64 小写 hex |
| dependency_lock_hash | sha256 | 是 | manifest | 64 小写 hex |
| approximation_watermark | str | 是 | mode 规则 | VERIFIED=`VERIFIED`; APPROX=`APPROXIMATED_NOT_LIVE_ELIGIBLE` |

### 5.4 ExitIntent

ExitIntent 只接受需要“下一分钟或其 delay 后 open”的计划性退出：`TIME_EXIT,TREND_EXIT,HALT_EXIT,EXPERIMENT_END`。Intent 创建时未来目标 open 必须未知且不得写入价格。`STOP_TRIGGER,TP_TRIGGER,ESTIMATED_LIQUIDATION` 属于 2C 分钟内保护性路径，直接产生保护性 Fill/路径结果，不得进入 2B ExitIntent 或生成 `MARKET_AT_1M_OPEN` Plan。

上游 `EXIT_CONDITION_SNAPSHOT_V1` 接口固定包含：`schema_version,condition_event_id,condition_content_hash,origin_candidate_id,position_id,position_snapshot_hash,symbol,position_side,exit_quantity,scheduled_exit_reason,condition_time_utc_ms,condition_visible_input_hash,code_commit,dependency_lock_hash`。`condition_event_id=xcond_+first24(condition_content_hash)`，hash排除ID/hash后按第3.4节重算。所有字段必填；时间来自计划性条件的市场/实验事件，quantity 只要求有限、>0 且与 position snapshot 一致，创建 Intent 时不检查 target contract step。2B 只验证和复制 scheduled reason，不重新判断 trigger。

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `EXIT_INTENT_SCHEMA_V1` |
| intent_id | str | 是 | Canonical payload | `xint_[0-9a-f]{24}` 且匹配 |
| intent_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| condition_event_id | str | 是 | ExitConditionSnapshot | 非空 |
| origin_candidate_id | str | 是 | position snapshot | 非空 |
| position_id | str | 是 | position snapshot | 非空；2B 不创建 position |
| position_snapshot_hash | sha256 | 是 | position snapshot | 冻结数量/side |
| symbol | str | 是 | position | BTCUSDT/ETHUSDT |
| position_side | Side | 是 | position | LONG/SHORT |
| full_exit_quantity | Decimal | 是 | position | 有限、>0、与 position snapshot 一致；不提前要求 target step 对齐 |
| scheduled_exit_reason | ScheduledExitReason | 是 | condition | 仅计划性四枚举 |
| condition_visible_input_hash | sha256 | 是 | ExitConditionSnapshot | 原样复制并进入 Intent ID |
| computational_experiment_id | sha256 | 是 | experiment manifest | acquisition identity 排除 |
| condition_time_utc_ms | int | 是 | condition market event | 非 wall clock |
| intent_created_time_utc_ms | int | 是 | condition | 等于 condition time |
| execution_anchor_utc_ms | int | 是 | TIME-F02 | 严格晚于 condition 的下一分钟 open |
| target_execution_time_utc_ms | int | 是 | TIME-F02 | anchor + exit delay |
| execution_delay_minutes | int | 是 | exit config | 0/1/2 |
| execution_time_config_id | str | 是 | ExecutionTimeConfig | 内容已校验 |
| execution_time_config_content_hash | sha256 | 是 | ExecutionTimeConfig | 进入 Intent ID |
| execution_time_config_version | str | 是 | config | 固定版本 |
| intent_config_hash | sha256 | 是 | config | 不含 wall clock |
| code_commit | hex str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 格式合法 |

HALTED 只禁止新 Entry planning，永不阻止 ExitIntent/ExitExecutionPlan。`HALT_EXIT` 在 HALTED 状态下必须可接受，`EXPERIMENT_HALTED` 不允许是 Exit subject 的 reason。

### 5.5 ExitExecutionPlan

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `EXIT_EXECUTION_PLAN_SCHEMA_V1` |
| plan_id | str | 是 | Canonical payload | `xplan_[0-9a-f]{24}` 且匹配 |
| plan_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| intent_id | str | 是 | ExitIntent | 已校验 |
| condition_event_id | str | 是 | ExitIntent | 原样复制 |
| origin_candidate_id | str | 是 | ExitIntent | 原样复制 |
| position_id | str | 是 | ExitIntent | 原样复制 |
| computational_experiment_id | sha256 | 是 | manifest | 固定实验 |
| symbol | str | 是 | Intent | 一致 |
| position_side | Side | 是 | Intent | 一致 |
| scheduled_exit_reason | ScheduledExitReason | 是 | Intent | 不重新判断 |
| quantity | Decimal | 是 | Intent + target position check | 必须等于 full_exit_quantity |
| condition_time_utc_ms | int | 是 | Intent | 事件时钟 |
| target_execution_time_utc_ms | int | 是 | Intent | 未来 1m open |
| plan_created_time_utc_ms | int | 是 | 目标市场事件 | 等于 target time |
| order_type | OrderType | 是 | 常量 | MARKET_AT_1M_OPEN |
| trigger_basis | TriggerBasis | 是 | 常量 | TRADE_1M_OPEN |
| target_open_snapshot_id | str | 是 | TargetMinuteOpenSnapshot | target/symbol 一致 |
| reference_price | Decimal | 是 | TargetMinuteOpenSnapshot.open_price | >0 |
| expected_exit_fill_price | Decimal | 是 | PRICE-F09 | tick 对齐、>0 |
| expected_exit_fee | Decimal | 是 | COST-F11 | ≥0；不是 reserve |
| contract_rule_mode | ContractRuleMode | 是 | coverage | UNAVAILABLE 无 Plan |
| contract_rule_coverage_id | str | 是 | coverage | target 有效 |
| contract_rule_coverage_content_hash | sha256 | 是 | ContractRuleCoverage.coverage_content_hash | 进入 ID |
| cost_model_snapshot_id | str | 是 | cost | 进入 ID |
| cost_model_snapshot_content_hash | sha256 | 是 | CostModelSnapshot.snapshot_content_hash | 进入 ID |
| target_minute_input_hash | sha256 | 是 | TargetMinuteOpenSnapshot.snapshot_content_hash | 不含未来 HLCV |
| position_snapshot_hash | sha256 | 是 | Intent/target recheck | 必须未变化；否则取消 |
| plan_config_hash | sha256 | 是 | config | 版本集合 |
| code_commit | hex str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 格式合法 |
| approximation_watermark | str | 是 | coverage | 同 EntryPlan |

ExitPlan 禁止包含 entry fee、exit fee reserve、funding reserve、initial margin、unit risk、risk budget、stop、TP 或 portfolio scaling 字段。

ExitPlan target 时才用当前 ContractRuleCoverage 验证 quantity。已有 position quantity 若满足当前 step 则正常生成 Plan；若 rule rollover 导致不对齐，返回 `POSITION_QUANTITY_RULE_MISMATCH/EXECUTION_PATH_INVALID`，禁止向上或向下偷偷量化。保护性退出不经 2B，不受此规则阻断。

### 5.6 ExecutionRejection

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `EXECUTION_REJECTION_SCHEMA_V1` |
| rejection_id | str | 是 | Canonical payload | `rej_[0-9a-f]{24}` 且匹配 |
| rejection_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| subject | RejectionSubjectRef | 是 | 调用阶段 | 第5.7节 tagged union；无顶层单symbol/hash |
| event_time_utc_ms | int | 是 | 市场/实验事件 | 禁止 wall clock |
| reason | ExecutionRejectionReason | 是 | 优先级选择 | 见第 11 节 |
| disposition | RejectionDisposition | 是 | reason matrix | 唯一映射 |
| retry_allowed | bool | 是 | reason matrix | 不由调用顺序决定 |
| required_values | tuple[pair[str,str]] | 是 | 校验器 | Canonical 排序 |
| observed_values | tuple[pair[str,str]] | 是 | 校验器 | Canonical 排序 |
| relevant_version_hashes | tuple[pair[str,sha256]] | 是 | inputs | Canonical 排序 |
| gap_intervals | tuple[pair[int,int]] | 是 | data | 有序、闭区间；无 gap 为 `[]` |
| rejection_config_hash | sha256 | 是 | config | 含优先级版本 |
| code_commit | hex str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 格式合法 |

### 5.7 RejectionSubjectRef tagged union

| Payload | 必填字段 |
|---|---|
| CandidateSubjectRef | `schema_version,subject_id,subject_content_hash,candidate_id,symbols=(symbol,),origin_ids=(candidate_id,),decision_visible_input_hash` |
| EntryIntentSubjectRef | `schema_version,subject_id,subject_content_hash,entry_intent_id,candidate_id,symbols=(symbol,),origin_ids=(candidate_id,),intent_content_hash` |
| ExitIntentSubjectRef | `schema_version,subject_id,subject_content_hash,exit_intent_id,condition_event_id,position_id,symbols=(symbol,),origin_ids=(condition_event_id,position_id),condition_visible_input_hash,position_snapshot_hash` |
| EntryPlanSubjectRef | `schema_version,subject_id,subject_content_hash,entry_plan_id,entry_intent_id,symbols=(symbol,),origin_ids=(candidate_id,intent_id),plan_content_hash` |
| ExitPlanSubjectRef | `schema_version,subject_id,subject_content_hash,exit_plan_id,exit_intent_id,symbols=(symbol,),origin_ids=(condition_event_id,position_id,intent_id),plan_content_hash` |
| PortfolioBatchSubjectRef | `schema_version,subject_id,subject_content_hash,portfolio_planning_batch_id,symbols,origin_ids=ordered_entry_intent_ids,batch_content_hash,account_snapshot_hash,target_open_snapshot_hashes` |

`symbols` 为去重升序 tuple；Portfolio batch 可且必须支持 `("BTCUSDT","ETHUSDT")`。每个 payload 有自己的 closed-world Schema，禁止强制单一 symbol 或单一 `decision_visible_input_hash`。

### 5.8 ContractRuleCoverage tagged union

| 字段 | 类型 | 必填模式 | 唯一来源 | 约束 |
|---|---|---|---|---|
| schema_version | str | 全部 | 常量 | `CONTRACT_RULE_COVERAGE_V1` |
| coverage_id | str | 全部 | Canonical payload | `cr_[0-9a-f]{24}` 且内容匹配 |
| coverage_content_hash | sha256 | 全部 | 第3.4节 | 排除 ID/hash 后重算 |
| mode | ContractRuleMode | 全部 | resolver result | VERIFIED/APPROXIMATED/UNAVAILABLE |
| symbol | str | 全部 | resolver query | BTCUSDT/ETHUSDT |
| query_time_utc_ms | int | 全部 | target market event | 非负、1m UTC open |
| created_by | str | 全部 | 常量 | `PYTHON_DETERMINISTIC` |
| source_kind | str | VERIFIED/APPROXIMATED | archive manifest | 非空；UNAVAILABLE 不存在 |
| source_uri_or_archive_id | str | VERIFIED/APPROXIMATED | archive manifest | 非空；不是网络调用 |
| source_content_hash | sha256 | VERIFIED/APPROXIMATED | archive bytes | 64小写hex |
| effective_from_utc_ms | int | VERIFIED/APPROXIMATED | archive | 非负且 `< effective_to` |
| effective_to_utc_ms | int | VERIFIED/APPROXIMATED | archive | 半开区间终点 |
| rule_version | str | VERIFIED/APPROXIMATED | archive | 非空，字段/数值变化提升版本 |
| review_status | ContractRuleReviewStatus | VERIFIED/APPROXIMATED | archive review | VERIFIED=`APPROVED_VERIFIED`；APPROX仅允许对应的 PRIOR/HINDSIGHT 枚举 |
| tick_size | Decimal | VERIFIED/APPROXIMATED | rule archive | >0 |
| step_size | Decimal | VERIFIED/APPROXIMATED | rule archive | >0 |
| min_qty | Decimal | VERIFIED/APPROXIMATED | rule archive | ≥0 |
| min_notional | Decimal | VERIFIED/APPROXIMATED | rule archive | ≥0 |
| quantity_precision_audit | int | VERIFIED/APPROXIMATED | source audit | ≥0，仅审计，不替代 step |
| price_precision_audit | int | VERIFIED/APPROXIMATED | source audit | ≥0，仅审计，不替代 tick |
| evidence_manifest_hash | sha256 | VERIFIED/APPROXIMATED | covered archive | 64小写hex |
| approximation_method | str | APPROXIMATED | approved reconstruction | 非空；其他模式字段不存在 |
| approximation_distance_ms | int | APPROXIMATED | query与证据时间差 | ≥0 |
| evidence_time_utc_ms | int | APPROXIMATED | archive evidence | 非负 |
| approximation_direction | ApproximationDirection | APPROXIMATED | policy | PRIOR_ONLY 或 HINDSIGHT_DIAGNOSTIC |
| approximation_policy_version | str | APPROXIMATED | policy | `CONTRACT_APPROXIMATION_POLICY_V1` |
| approximation_watermark | str | APPROXIMATED | 常量 | `APPROXIMATED_NOT_LIVE_ELIGIBLE` |
| unavailable_reason | str | UNAVAILABLE | resolver search | 非空；covered模式字段不存在 |
| searched_archive_hashes | tuple[sha256] | UNAVAILABLE | resolver search | 去重升序，可为空但必须显式 `[]` |
| requested_time_utc_ms | int | UNAVAILABLE | resolver query | 必须等于 query_time |

UNAVAILABLE 必须产生 `CONTRACT_RULE_UNAVAILABLE`，不能创建 Plan。

有效期统一为半开区间 `[effective_from,effective_to)`；`from < to`，同一 symbol/mode 的 VERIFIED 区间不得重叠。

主 Backtest/Paper 的 APPROX 只允许 `PRIOR_ONLY_APPROXIMATION`，且 `evidence_time_utc_ms<=query_time_utc_ms`。未来证据只能用于 `HINDSIGHT_DIAGNOSTIC_APPROXIMATION`：单独目录和水印，不进 Paper Simulation Gate/Live Eligibility Gate，不与 primary OOS 合并。

### 5.9 CostModelSnapshot

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `COST_MODEL_SNAPSHOT_SCHEMA_V1` |
| snapshot_id | str | 是 | Canonical | `cost_[0-9a-f]{24}`且内容匹配 |
| snapshot_content_hash | sha256 | 是 | 第3.4节 | 排除 ID/hash 后重算 |
| symbol | str | 是 | config | BTCUSDT/ETHUSDT |
| fee_rate | Decimal | 是 | `FEE_MODEL_V1` | baseline `0.0005`，≥0 |
| slippage_rate | Decimal | 是 | `SLIPPAGE_MODEL_V1` | BTC `0.0001`、ETH `0.0002`，≥0 |
| stress_multiplier | Decimal | 是 | experiment config | `1`、`1.5` 或 `2` |
| effective_fee_rate | Decimal | 是 | COST-F01 | 精确乘法且自校验 |
| effective_slippage_rate | Decimal | 是 | COST-F02 | 精确乘法且自校验 |
| fee_model_version | str | 是 | config | `FEE_MODEL_V1` |
| slippage_model_version | str | 是 | config | `SLIPPAGE_MODEL_V1` |
| funding_buffer_model_version | str | 是 | config | `FUNDING_BUFFER_MODEL_V2` |

本对象只负责手续费和滑点，不保存 funding cap。

### 5.10 PositionSizingResult

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `POSITION_SIZING_RESULT_SCHEMA_V1` |
| result_id | str | 是 | Canonical | `size_[0-9a-f]{24}`且内容匹配 |
| result_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| intent_id | str | 是 | EntryIntent | 非空、内容已验证 |
| symbol | str | 是 | Intent | BTCUSDT/ETHUSDT |
| side | Side | 是 | Intent | 一致 |
| reference_price | Decimal | 是 | TargetMinuteOpenSnapshot.open_price | >0 |
| expected_entry_fill_price | Decimal | 是 | PRICE-F04 | tick对齐、>0 |
| stop_trigger_price | Decimal | 是 | PRICE-F05 | tick对齐、>0 |
| take_profit_trigger_price | Decimal | 是 | PRICE-F06 | tick对齐、>0 |
| expected_stop_fill_price | Decimal | 是 | PRICE-F07 | tick对齐、>0 |
| expected_take_profit_fill_price | Decimal | 是 | PRICE-F08 | tick对齐、>0 |
| planned_exit_notional_price_basis | Decimal | 是 | PRICE-F10 | 价格包络最大值 |
| funding_notional_price_basis | Decimal | 是 | FUND-F13 | 等于 planned exit basis |
| unit_risk | Decimal | 是 | RISK-F13 | >0 |
| single_risk_budget | Decimal | 是 | RISK-F14 | >0 |
| raw_quantity | Decimal | 是 | RISK-F15 | >0 |
| step_quantized_quantity | Decimal | 是 | QTY-F16 | ≥0 |
| unscaled_planned_risk | Decimal | 是 | RISK-F19 | 用于共同scale分母，>0 |
| unscaled_required_cash | Decimal | 是 | CASH-F23 | 保守用于scale分母，>0 |
| contract_rule_coverage_id | str | 是 | covered CR | 非空且target有效 |
| cost_model_snapshot_id | str | 是 | CostModelSnapshot | 非空且symbol一致 |
| funding_risk_config_id | str | 是 | FundingRiskConfigSnapshot | target 有效且symbol一致 |
| funding_event_upper_bound | int | 是 | FUND-F11 | ≥0 |
| effective_adverse_rate_cap | Decimal | 是 | FUND-F14 | 有限且≥0 |
| account_snapshot_id | str | 是 | AS | 同一batch |
| account_snapshot_hash | sha256 | 是 | AS | 同一batch完整内容hash |
| sizing_model_version | str | 是 | 常量 | `POSITION_SIZING_MODEL_V2` |

这是成功值对象；任一失败返回 ExecutionRejection，禁止用 nullable quantity 表示失败。

### 5.11 PortfolioScalingResult

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `PORTFOLIO_SCALING_RESULT_SCHEMA_V1` |
| result_id | str | 是 | Canonical | `scale_[0-9a-f]{24}`且内容匹配 |
| result_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| eligible_time_utc_ms | int | 是 | batch key | 全部item相同target |
| account_snapshot_id | str | 是 | AS | batch冻结 |
| account_snapshot_hash | sha256 | 是 | AS | batch冻结完整内容hash |
| ordered_input_result_ids | tuple[str] | 是 | sizing set | 按`(symbol,result_id)`排序且去重 |
| remaining_risk | Decimal | 是 | RISK-F21 | ≥0 |
| deployable_cash | Decimal | 是 | CASH-F22 | ≥0 |
| risk_scale | Decimal | 是 | SCALE-F23 | ≥0 |
| cash_scale | Decimal | 是 | SCALE-F23 | ≥0 |
| final_scale | Decimal | 是 | SCALE-F23 | `min(1,risk,cash)`，范围`[0,1]` |
| item_results | tuple[tagged scaling item] | 是 | SCALE-F24+minimum | AcceptedScalingItem/RejectedScalingItem；按 `(symbol,sizing_result_id,item_id)` 排序 |
| scaling_model_version | str | 是 | 常量 | `PORTFOLIO_SCALING_MODEL_V2` |

一个 item 因 minimum/zero 被拒绝后，其他 item 不重新放大，原 `final_scale` 不变。

### 5.12 PortfolioPlanningBatch 与 nested scaling item

| PortfolioPlanningBatch 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `PORTFOLIO_PLANNING_BATCH_SCHEMA_V1` |
| batch_id | str | 是 | batch_content_hash | `pbatch_[0-9a-f]{24}` |
| batch_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| eligible_time_utc_ms | int | 是 | 同target intents | 同target事件时刻 |
| ordered_entry_intent_ids | tuple[str] | 是 | complete intent set | 按 `(symbol,intent_id)` 排序，非空 |
| ordered_symbols | tuple[str] | 是 | intents | 一一对应，去重 |
| account_snapshot_id | str | 是 | AccountPlanningSnapshot | 所有item共享 |
| account_snapshot_hash | sha256 | 是 | AccountPlanningSnapshot.snapshot_hash | 完整复制 |
| target_open_snapshot_ids | tuple[str] | 是 | open snapshots | 与symbols一一对应 |
| batch_completeness_watermark | str | 是 | event engine | 证明该target所有可执行BTC/ETH Intent已收集 |
| batch_config_hash | sha256 | 是 | 第3.4节 | 对应config payload重算 |
| code_commit | str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 64小写hex |

| AcceptedScalingItem 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `ACCEPTED_SCALING_ITEM_SCHEMA_V1` |
| item_id | str | 是 | item_content_hash | `asitem_[0-9a-f]{24}` |
| item_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| symbol | str | 是 | sizing result | 与sizing result一致 |
| sizing_result_id | str | 是 | sizing result | 内容已校验 |
| final_quantity | Decimal | 是 | SCALE-F24 | step对齐且>0 |
| final_notional | Decimal | 是 | final quantity×entry fill | 精确 |
| final_planned_risk | Decimal | 是 | final quantity×unit risk | ≤single budget |
| final_required_cash | Decimal | 是 | final quantity与保守reserve basis | 精确 |
| step_size | Decimal | 是 | coverage | >0 |
| minimum_status | str | 是 | minimum validator | `PASSED_MIN_QTY_AND_NOTIONAL` |
| item_input_hash | sha256 | 是 | 精确payload | SHA256(Canonical(`{sizing_result_id,final_scale,step_size,min_qty,min_notional,entry_fill,unit_risk,planned_exit_notional_price_basis,funding_count,effective_adverse_rate_cap}`)) |

| RejectedScalingItem 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `REJECTED_SCALING_ITEM_SCHEMA_V1` |
| item_id | str | 是 | item_content_hash | `rsitem_[0-9a-f]{24}` |
| item_content_hash | sha256 | 是 | 第3.4节 | 对象边界重算 |
| symbol | str | 是 | sizing result | BTCUSDT/ETHUSDT |
| sizing_result_id | str | 是 | sizing result | 内容已校验 |
| rejection_id | str | 是 | ExecutionRejection | 内容已校验 |

nested item 有独立 ID，其完整 Canonical payload 作为 PortfolioScalingResult `item_results` 元素进入 result ID。一个 item 拒绝后另一个不得重新放大。PortfolioPlanningBatch 是 portfolio rejection 的稳定 subject，禁止临时拼接 subject ID。

### 5.13 ExecutionTimeConfig

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `EXECUTION_TIME_CONFIG_V1` |
| config_id / config_content_hash | str/sha256 | 是 | 第3节 | 边界重算 |
| entry_delay_minutes / exit_delay_minutes | int/int | 是 | experiment config | 各自仅0/1/2 |
| anchor_policy_version | str | 是 | config | 非空 |
| version / canonical_version | str/str | 是 | 常量/config | 与冻结版本一致 |

### 5.14 AccountPlanningSnapshot 接口

2B 不实现 Ledger，但必须读取以下一次性冻结快照：

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 上游快照版本 | `ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1` |
| snapshot_id | str | 是 | Canonical | `acct_[0-9a-f]{24}`且内容匹配 |
| snapshot_hash | sha256 | 是 | Canonical | 全字段排除snapshot_id/hash后的SHA-256 |
| event_time_utc_ms | int | 是 | 账户/市场事件 | 非负、非wall clock |
| planning_phase | PlanningPhase | 是 | event engine | `POST_SAME_TIME_FUNDING_AND_SCHEDULED_EXITS_PRE_ENTRY_BATCH_V1` |
| planning_phase_version | str | 是 | event-order config | `PLANNING_PHASE_V1` |
| wallet_balance | Decimal | 是 | 上游Ledger snapshot | 单一经济钱包；有限且≥0 |
| current_equity | Decimal | 是 | wallet+mark未实现PnL | 有限且>0才能新计划 |
| locked_initial_margin | Decimal | 是 | 已成交持仓分类 | ≥0 |
| locked_fee_reserve | Decimal | 是 | 已成交持仓分类 | ≥0 |
| locked_funding_reserve | Decimal | 是 | 已成交持仓分类 | ≥0 |
| available_balance | Decimal | 是 | CASH-F01 | `wallet-三项locks`；≥0；不含pending |
| existing_open_risk | Decimal | 是 | 已成交仓位risk | ≥0 |
| open_risk_model_version | str | 是 | risk evidence | 非空 |
| open_risk_source_hash | sha256 | 是 | position risk records | 与聚合值一致 |
| pending_plan_reserve | Decimal | 是 | 先前批准未成交plans | ≥0，只计现金一次 |
| pending_plan_risk | Decimal | 是 | 先前批准未成交plans | ≥0，只计risk一次 |
| pending_plan_set_hash | sha256 | 是 | pending plan records | 与 reserve/risk 聚合一致 |
| existing_position_set_hash | sha256 | 是 | position records | 与 open risk/symbols 聚合一致 |
| existing_position_symbols | tuple[str] | 是 | position snapshot | 去重升序 |
| experiment_state | str | 是 | experiment state | RUNNING或HALTED |
| experiment_state_id | str | 是 | experiment state object | 非空 |
| experiment_state_hash | sha256 | 是 | experiment state object | 内容已校验 |

2B 校验 `available_balance` 必须与其派生公式一致，防止第二真相源。入口必须满足 `pending_plan_reserve<=available_balance`、risk非负、集合 hash/模型版本与聚合值证据一致。snapshot `event_time_utc_ms==PortfolioPlanningBatch.eligible_time_utc_ms`，phase 证明同刻 funding 和计划性 open exits 已反映，本 Entry batch 尚未反映；同 batch 所有 item 必须用完全同一 snapshot。若 2C 事件顺序改变，必须提升 planning phase 版本。

`deployable_cash=available_balance-pending_plan_reserve`在证据校验通过后精确计算，禁止 `max(0,...)`。所有 reserve 是 wallet 内锁定分类，不是经济扣款。资金费只允许 Ledger 在 2C 对 wallet 产生一次经济变化；isolated margin view 是派生视图，不是第二账户。

## 6. 生命周期与状态转换

| 转换 | 触发 | 输入 | 输出 | 不变量 | 失败 | 重试 | ID 规则 |
|---|---|---|---|---|---|---|---|
| Candidate→EntryIntent | 2A 输出 LONG/SHORT/NO_SETUP | 仅 Candidate、ExecutionTimeConfig、manifest identity | EntryIntent 或 Rejection | 不读 target/规则/成本/funding/账户/仓位/HALTED | 合法NO_SETUP→CANDIDATE_NOT_ACTIONABLE；其他非法Candidate→DATA_INVALID | 同输入不可得不同结果 | 账户状态改变不改 Intent ID |
| EntryIntent→target event | target open 事件到达 | Intent、TargetMinuteOpenSnapshot、显式 watermark | 进入 planning 前置条件 | factory 不接收 Kline/HLCV | target 前调用是 API precondition error，不产生领域对象 | 到达后可调用 | Snapshot ID 只受 open-visible fields 影响 |
| target→PositionSizingResult | target已到达且证据完整 | Intent、open snapshot、contract/cost/funding、AS | SizingResult 或 Rejection | 此时才检查 HALTED/existing position/风险证据 | 按第11节 | 由联合映射决定 | sizing result 尚不是 Plan |
| SizingResults→PortfolioPlanningBatch | completeness watermark 证明同target集合完整 | 全部可执行 EntryIntents、open snapshots、同一 AS | PortfolioPlanningBatch | 不得BTC_FIRST/ETH_FIRST/分次调用 | BATCH_INCOMPLETE/DATA_INVALID | 缺证据不构造batch | batch ID 依赖完整有序集合 |
| PortfolioPlanningBatch→PortfolioScalingResult | batch 完整且 AS phase/time 一致 | batch、全部 SizingResults | ScalingResult | 先同算后缩量；item拒绝后不再分配 | risk/cash/minimum/rejection items | 冻结batch不原地重试 | 输入集合与顺序规则进入ID |
| AcceptedScalingItem→EntryPlan | ScalingResult 已完成 | batch、accepted item、全部已验证输入 | final EntryExecutionPlan | `quantity`唯一来自 accepted item | 任何反算不一致→DATA_INVALID | 否 | Plan ID 包含batch/scaling/item IDs |
| Scheduled ExitCondition→ExitIntent | 上游计划性条件发生 | condition、position、delay config | ExitIntent | 仅四种 scheduled reason；HALTED不阻止 | protective reason→DATA_INVALID/Scope failure | condition/config变化才新Intent | condition/config 变化ID变 |
| ExitIntent→ExitPlan | 严格未来 target open Snapshot 到达 | Intent、Snapshot/watermark、position recheck、coverage、cost | ExitPlan 或 Rejection | HALTED不阻止；quantity不偷偷量化 | target/data/rule/position mismatch | 由联合映射决定 | target/position/rule变化 ID 变化 |
| Intent→Rejection | 任一冻结校验失败 | 全部当时可见 facts | ExecutionRejection | 不修改 Candidate/position/account | 唯一最高优先级 reason | 由 matrix 决定 | 证据或 subject 变化 ID 变化 |

Watermark 选择方案 A：Entry/Exit Plan factory 只允许在 target event 已到达或 watermark 已越过时调用。target 未到达的调用是编程前置条件错误，不返回 `None`、不返回领域对象、不持久化等待状态。仅当 watermark 已证明 target Snapshot 应存在但缺失时，才产生 `TARGET_MINUTE_UNAVAILABLE`。

2B 到此终止。Plan 不是 Fill，不授权成交，也不改变 snapshot。2C 未来只能消费已验证 Plan。

## 7. 公式冻结表

所有 `floor_to_step(x,s)=floor(x/s)*s`；`floor_to_tick` 同理；`ceil_to_tick(x,t)=ceil(x/t)*t`。除明确量化步骤外不得舍入。输入必须先验证有限、正值和版本。公式中 `P0` 是目标成交 1m 的未加滑点 open，`s=effective_slippage_rate`，`fee_rate=effective_fee_rate`，`ATR` 是 Candidate 中已冻结的 2A ATR，`tick=tick_size`，`step=step_size`。这些别名只是公式记法，不构成第二真相源。

| Formula ID | 精确公式与顺序 | 舍入/边界 | 版本 |
|---|---|---|---|
| TIME-F01 | `anchor=decision_time+1`; require `anchor % 14_400_000=0`; `target=anchor+delay*60_000` | int 精确；delay∈{0,1,2} | EXECUTION_TIME_CONFIG_V1 |
| TIME-F02 | `anchor=floor(condition_time/60_000)*60_000+60_000`; `target=anchor+delay*60_000` | 必须严格 `target>condition_time` | EXECUTION_TIME_CONFIG_V1 |
| TIME-F03 | `maximum_exit_time=target_execution_time+172_800_000` | 精确 48h；不是 12 根 4H | MAX_HOLD_V1_EXACT_48H |
| GAP-F01 | LONG `gap=P0-decision_close`; SHORT `gap=decision_close-P0`; reject iff `gap > 0.5*ATR` | 等于接受；负值接受；gap 在 fill 前计算 | GAP_POLICY_V1 |
| COST-F01 | `effective_fee_rate=fee_rate*stress_multiplier` | Decimal精确乘法；multiplier∈{1,1.5,2} | FEE_MODEL_V1 |
| COST-F02 | `effective_slippage_rate=slippage_rate*stress_multiplier` | Decimal精确乘法；funding cap不乘 | SLIPPAGE_MODEL_V1 |
| PRICE-F04 | LONG entry `ceil_to_tick(P0*(1+s),tick)`；SHORT `floor_to_tick(P0*(1-s),tick)` | 先乘后定向 tick；不得二次滑点 | SLIPPAGE_MODEL_V1 |
| PRICE-F05 | LONG stop `ceil_to_tick(entry-2*ATR,tick)`；SHORT `floor_to_tick(entry+2*ATR,tick)` | entry 已含滑点；ATR 不先量化 | PRICE_GEOMETRY_V1 |
| PRICE-F06 | LONG TP `floor_to_tick(entry+3*ATR,tick)`；SHORT `ceil_to_tick(entry-3*ATR,tick)` | 同上 | PRICE_GEOMETRY_V1 |
| PRICE-F07 | LONG stop fill `floor_to_tick(stop*(1-s),tick)`；SHORT `ceil_to_tick(stop*(1+s),tick)` | 卖出向下、买回向上 | SLIPPAGE_MODEL_V1 |
| PRICE-F08 | LONG TP fill `floor_to_tick(TP*(1-s),tick)`；SHORT `ceil_to_tick(TP*(1+s),tick)` | 仅 plan estimate；不是 Fill | SLIPPAGE_MODEL_V1 |
| PRICE-F09 | 退出 LONG（sell）`floor_to_tick(P0*(1-s),tick)`；退出 SHORT（buy）`ceil_to_tick(P0*(1+s),tick)` | 目标 1m open 到达后才计算；不是 Fill | SLIPPAGE_MODEL_V1 |
| PRICE-F10 | `planned_exit_notional_price_basis=max(expected_entry_fill_price,expected_stop_fill_price,expected_take_profit_fill_price)` | Decimal精确max；冻结价格包络 | RESERVE_PRICE_BASIS_V1 |
| COST-F09 | `entry_fee=quantity*expected_entry_fill*effective_fee_rate` | 不按 tick/step/USDT 分位量化 | FEE_MODEL_V1 |
| COST-F10 | `exit_fee_reserve=quantity*planned_exit_notional_price_basis*effective_fee_rate` | 只预留一次；不与unit-risk的stop fee共用basis | FEE_MODEL_V1 |
| COST-F11 | `expected_exit_fee=quantity*expected_exit_fill*effective_fee_rate` | ExitPlan estimate；不修改 wallet | FEE_MODEL_V1 |
| FUND-F11 | `count=sum(window_end>entry and window_start<=maximum_exit for each schedule window)` | 区间 `(entry,maximum_exit]`；相同终点先 funding 后 exit | FUNDING_BUFFER_MODEL_V2 |
| FUND-F12 | `funding_reserve=quantity*funding_notional_price_basis*effective_adverse_rate_cap*count` | 使用当时可见FundingRiskConfig | FUNDING_BUFFER_MODEL_V2 |
| FUND-F13 | `funding_notional_price_basis=planned_exit_notional_price_basis` | 不固定使用entry | RESERVE_PRICE_BASIS_V1 |
| FUND-F14 | `effective_adverse_rate_cap=adverse_rate_cap*funding_stress_multiplier` | 2D可独立提高；不复用cost stress | FUNDING_RISK_CONFIG_V1 |
| RISK-F13 | `price_loss=abs(entry-stop_fill)`；`unit_risk=price_loss+entry*effective_fee_rate+stop_fill*effective_fee_rate+funding_notional_price_basis*effective_adverse_rate_cap*count` | 止损手续费仍用stop fill；funding用保守basis | POSITION_SIZING_MODEL_V2 |
| RISK-F14 | `single_risk_budget=current_equity*Decimal("0.005")` | 负/零 equity 拒绝 | POSITION_SIZING_MODEL_V2 |
| RISK-F15 | `raw_quantity=single_risk_budget/unit_risk` | unit_risk>0；不先量化 budget | POSITION_SIZING_MODEL_V2 |
| QTY-F16 | `step_qty=floor(raw_quantity/step_size)*step_size` | 只向下；禁止向上满足 minimum | POSITION_SIZING_MODEL_V2 |
| RISK-F17 | `planned_risk=final_quantity*unit_risk` | final quantity 后重算；必须 ≤ budget | POSITION_SIZING_MODEL_V2 |
| RISK-F18 | `notional=final_quantity*expected_entry_fill` | 正值；用于 minNotional 和 margin | POSITION_SIZING_MODEL_V2 |
| RISK-F19 | `unscaled_planned_risk=raw_quantity*unit_risk` | 用于共同scale分母；不使用step preview | POSITION_SIZING_MODEL_V2 |
| CASH-F01 | `available_balance=wallet_balance-locked_initial_margin-locked_fee_reserve-locked_funding_reserve` | 与AS字段精确一致；pending不在此式 | ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1 |
| CASH-F19 | `initial_margin=notional/Decimal("1")` | leverage 精确等于 1 | POSITION_SIZING_MODEL_V2 |
| CASH-F20 | `required_cash=initial_margin+entry_fee+exit_fee_reserve+funding_reserve` | 四项各算一次；只是 reserve | POSITION_SIZING_MODEL_V2 |
| RISK-F20 | `base_risk=existing_open_risk+pending_plan_risk`; if `base_risk>=current_equity*0.01` reject `TOTAL_RISK_ALREADY_AT_LIMIT` | 先判断；不能转quantity zero | PORTFOLIO_SCALING_MODEL_V2 |
| RISK-F21 | `remaining=current_equity*0.01-base_risk` | 只在RISK-F20通过后计算；禁止max(0) | PORTFOLIO_SCALING_MODEL_V2 |
| RISK-F22 | `total_risk_after_plan=existing_open_risk+pending_plan_risk+sum(final_planned_risk_i)` | 必须≤`current_equity*0.01`；等于接受 | PORTFOLIO_SCALING_MODEL_V2 |
| CASH-F22 | `deployable=available_balance-pending_plan_reserve` | 先要求pending≤available；否则DATA_INVALID | PORTFOLIO_SCALING_MODEL_V2 |
| CASH-F23 | 以 `q=raw_quantity` 依次计算 `raw_notional=q*entry`、`raw_entry_fee=q*entry*effective_fee_rate`、`raw_exit_fee=q*planned_exit_notional_price_basis*effective_fee_rate`、`raw_funding=q*funding_notional_price_basis*effective_adverse_rate_cap*count`，再精确求和 | 用于cash scale分母；不得先step量化 | PORTFOLIO_SCALING_MODEL_V2 |
| SCALE-F23 | `risk_scale=1 if sumRisk=0 else remaining/sumRisk`; `cash_scale=1 if sumCash=0 else deployable/sumCash`; `scale=min(1,risk_scale,cash_scale)` | scale clamp 仅上限 1；负输入拒绝 | PORTFOLIO_SCALING_MODEL_V2 |
| SCALE-F24 | `scaled_qty_i=floor(raw_qty_i*scale/step_i)*step_i` | 不从 step_qty 再乘，避免双量化；拒绝后不再分配 | PORTFOLIO_SCALING_MODEL_V2 |
| MIN-F25 | accept iff `qty>=min_qty AND qty*entry_fill>=min_notional`; zero 先判 QUANTITY_ROUNDED_TO_ZERO | 等于 minimum 接受 | CONTRACT_MINIMUM_V1 |
| LEV-F26 | accept iff `leverage==1 AND initial_margin==notional` | `2` 即拒绝 DATA_INVALID；2B 不测试 2x | LEVERAGE_POLICY_V1_FIXED_1X |

价格几何：LONG 必须 `expected_stop_fill <= stop_trigger < entry < take_profit_trigger` 且 `expected_take_profit_fill > entry`；SHORT 必须 `expected_take_profit_fill < entry < stop_trigger <= expected_stop_fill`。任一 tick 量化导致相等或反序，拒绝 `PRICE_GEOMETRY_INVALID`。

reserve basis 只是“冻结计划价格包络内的保守 planning buffer”，不是任意跳空价格的绝对数学上界。2C 仍负责真实 funding、跳空和压力路径。`RISK_BUDGET_EXCEEDED` 若在按冻结公式 floor 后的 final quantity 上发生，是实现不变量破坏：`DATA_INVALID/EXPERIMENT_INVALID`，不是普通经济拒绝。

## 8. 资金费次数规则

函数签名冻结为：

```text
count_funding_events(
  entry_time_utc_ms: int,
  maximum_exit_time_utc_ms: int,
  schedule: FundingScheduleSnapshot,
  settlement_boundary_semantics: CONSERVATIVE_WINDOW_V1,
) -> int | ExecutionRejection
```

schedule 必须给出覆盖区间、严格升序 nominal timestamps、每个事件的 `[window_start,window_end]`、时区 UTC、版本和 content hash。V1 Binance assumed schedule 是 nominal `00:00/08:00/16:00 UTC`，容差 `±1000ms`；非 8 小时 schedule 由显式事件序列表示，不允许函数内部假设 8 小时。

`FundingScheduleSnapshot` 全字段必填：`schema_version=FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_V1,schedule_id,schedule_content_hash,symbol,schedule_version,effective_from_utc_ms,effective_to_utc_ms,timezone=UTC,nominal_timestamps_utc_ms,settlement_windows,settlement_boundary_semantics=CONSERVATIVE_WINDOW_V1,window_tolerance_ms,source_manifest_hash,created_by=PYTHON_DETERMINISTIC,code_commit,dependency_lock_hash`。timestamps 严格升序；windows 与其一一对应、各自 `start<=nominal<=end`、彼此不重叠；有效期覆盖全部 windows。ID/hash 按第3节重算。

计数区间固定 `(entry_time,maximum_exit_time]`。window 与该区间相交的判定是 `window_end > entry_time AND window_start <= maximum_exit_time`。当 funding window/事件与 maximum exit 同刻时，该次 funding 计入，未来 2C 必须先结算再退出。schedule 未覆盖整个区间、版本错误、窗口重叠/倒置或 symbol 不符，返回 `FUNDING_SCHEDULE_UNVERIFIED`，不得按零或固定 ×6/×7。

`FundingRiskConfigSnapshot` 只负责“按什么最坏费率规划”，与只负责“何时结算”的 schedule 分离。

| 字段 | 类型 | 必填模式 | 唯一来源 | 约束 |
|---|---|---|---|---|
| schema_version | str | 全部 | 常量 | `FUNDING_RISK_CONFIG_SNAPSHOT_V1` |
| config_id / content_hash | str/sha256 | 全部 | 第3节 | 边界重算 |
| symbol | str | 全部 | config query | BTCUSDT/ETHUSDT |
| adverse_rate_cap | Decimal | covered | 审核证据/假设 | 有限且≥0；UNAVAILABLE不存在 |
| effective_from_utc_ms / effective_to_utc_ms | int/int | covered | config archive | target落在半开区间 |
| source_kind / source_manifest_hash | str/sha256 | covered | archive manifest | 非空/内容匹配 |
| verification_mode | FundingRiskVerificationMode | 全部 | review | VERIFIED/APPROXIMATED/UNAVAILABLE |
| stress_multiplier | Decimal | covered | experiment config | ≥1；2D可独立提高 |
| version | str | 全部 | config | `FUNDING_RISK_CONFIG_V1` |
| watermark | str | 全部 | mode policy | VERIFIED/假设/UNAVAILABLE明确水印 |
| evidence_time_utc_ms | int | covered | source event | `<=target` |
| code_commit / dependency_lock_hash | str/sha256 | 全部 | manifest | 格式合法 |

- `verification_mode=VERIFIED|APPROXIMATED|UNAVAILABLE`；covered mode 要求 target 落在 `[from,to)` 且 `evidence_time<=target`。
- `UNAVAILABLE` 不含 cap，产生 `FUNDING_RISK_CONFIG_UNAVAILABLE/EXECUTION_PATH_INVALID`。
- `Decimal("0.0001")` 只可作为带版本与 `BASELINE_ASSUMPTION_NOT_VERIFIED` 水印的 APPROX baseline，不得称为无条件 cap。
- `stress_multiplier>=1`，2D 可独立提高 funding rate cap；规划时只能读 target 时已知 config，禁止用未来 funding 记录回填历史 cap。

Golden cases：

| Case | 输入关系 | 预期 |
|---|---|---|
| FUND-G01 | entry 在 window_end 前 1ms | 当前窗口计入 |
| FUND-G02 | entry 在 window_end 后 1ms | 当前窗口不计入 |
| FUND-G03 | 48h 终点等于 window_start/nominal | 终点事件计入且先 funding 后 exit |
| FUND-G04 | 显式 6h/12h 混合 schedule | 只按窗口枚举数计数 |
| FUND-G05 | schedule coverage 少 1ms | FUNDING_SCHEDULE_UNVERIFIED |
| FUND-G06 | 48h 跨两个端点容差窗口 | 保守 upper bound=7 |

## 9. 合约规则模式与 Gate

| Mode | 数据来源 | 有效期 | 可生成 Plan | Backtest | Paper Simulation Gate | Live Eligibility Gate |
|---|---|---|---:|---:|---:|---:|
| VERIFIED | 审核过的历史 archive/官方证据 | `[from,to)` 精确覆盖 target | 是 | 是 | 是 | 是，仅作为研究资格；不授权实盘 |
| APPROXIMATED PRIOR_ONLY | target及之前已知证据 | 自身声明且 target 落入 | 是，必须水印 | 独立分层 | 是，需成本/规则压力测试 | 否 |
| APPROXIMATED HINDSIGHT_DIAGNOSTIC | target之后证据 | 仅诊断重建 | 是，必须水印 | 单独目录，不合并primary OOS | 否 | 否 |
| UNAVAILABLE | 搜索事实和缺失证据 | 无可用覆盖 | 否 | Candidate 保留、执行拒绝 | 否 | 否 |

APPROXIMATED 结果的 Plan、实验 manifest、输出目录和报告标题必须包含 `APPROXIMATED_NOT_LIVE_ELIGIBLE`。HINDSIGHT 还必须包含 `HINDSIGHT_DIAGNOSTIC_NOT_PRIMARY_OOS`。任何 attempt 把不合格 mode 输入 gate 都拒绝 `DATA_INVALID`并标记实验级 INVALID。2B 永不接真钱或自动交易。

## 10. Gap、minimum、风险和资金边界

- gap 使用未加滑点 `P0`、Candidate 冻结 `decision_close` 和 ATR；严格 `>` 拒绝，等于接受。
- 先验证数据/版本，再 gap；通过后才计算 fill、geometry、sizing。
- 单笔 planned risk 必须 `<= current_equity*0.005`，等于接受。
- target planning 时 `HALTED` 或 Entry symbol 已有 position 是正常 Entry economic rejection；不影响 EntryIntent ID，也不影响 scheduled Exit。
- `base_risk=existing_open_risk+pending_plan_risk`；若 `base_risk>=current_equity*0.01`，返回 `TOTAL_RISK_ALREADY_AT_LIMIT/CANDIDATE_REJECTED`，禁止转成 QUANTITY_ROUNDED_TO_ZERO。
- batch 后 `existing_open_risk+pending_plan_risk+sum(final planned risk) <= current_equity*0.01`，等于接受。
- 若按冻结 scale/floor 后仍超过 0.5%/1%，属于实现不变量破坏，`DATA_INVALID/EXPERIMENT_INVALID`。
- 同刻 BTC/ETH 必须全部 sizing 完成后共同 scale；排序只用于 Canonical，不用于分配。
- 一个 item 缩量后拒绝，不把释放量重新给其他 item。
- quantity=0、低于 minQty、低于 minNotional 使用不同 reason，按第 11 节优先级只返回一个。
- required cash 与 planned risk 是两个独立约束；不得以风险余额替代现金余额。
- `pending_plan_reserve>available_balance` 是 `DATA_INVALID`；通过后若 `deployable_cash==0` 且本批存在正 required cash，返回 `INSUFFICIENT_AVAILABLE_BALANCE`。若 deployable>0，先共同 scale，scale 后再判 zero/minimum。

## 11. ExecutionRejection 枚举和唯一优先级

reason 优先级从高到低冻结：

| Rank | Reason | 语义 |
|---:|---|---|
| 1 | DATA_INVALID | Schema/ID/hash/数值/不变量/调用范围非法 |
| 2 | TARGET_MINUTE_UNAVAILABLE | watermark证明应存在但open Snapshot缺失 |
| 3 | REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE | AS或其集合证据缺失 |
| 4 | OPEN_RISK_MODEL_UNAVAILABLE | open-risk模型/来源hash缺失 |
| 5 | CONTRACT_RULE_UNAVAILABLE | 无有效coverage |
| 6 | CONTRACT_RULE_EXPIRED | coverage不覆盖target |
| 7 | COST_MODEL_UNAVAILABLE | 无有效cost snapshot |
| 8 | FUNDING_SCHEDULE_UNVERIFIED | schedule时间证据不完整 |
| 9 | FUNDING_RISK_CONFIG_UNAVAILABLE | funding cap证据不完整 |
| 10 | BATCH_INCOMPLETE | completeness watermark/同target集合不完整 |
| 11 | POSITION_SNAPSHOT_CHANGED | Exit position在target前改变 |
| 12 | POSITION_QUANTITY_RULE_MISMATCH | Exit quantity不符当前step |
| 13 | EXPERIMENT_HALTED | 仅禁止新Entry |
| 14 | EXISTING_POSITION | Entry symbol已有position |
| 15 | TOTAL_RISK_ALREADY_AT_LIMIT | base risk已达/超1% |
| 16 | GAP_TOO_LARGE | 方向性gap超阈值 |
| 17 | PRICE_GEOMETRY_INVALID | 价格几何在量化后非法 |
| 18 | INSUFFICIENT_AVAILABLE_BALANCE | 合法AS下无可部署资金 |
| 19 | QUANTITY_ROUNDED_TO_ZERO | scale+floor后为0 |
| 20 | BELOW_MIN_QTY | 低于minQty |
| 21 | BELOW_MIN_NOTIONAL | 低于minNotional |
| 22 | CANDIDATE_NOT_ACTIONABLE | 仅合法NO_SETUP |

Disposition 和 `retry_allowed` 不能只按 reason 全局映射；必须按 `(subject kind,reason,research stage)` 联合决定：

| Subject kind | Reason family | BACKTEST | PAPER_SIMULATION | LIVE_ELIGIBILITY_RESEARCH |
|---|---|---|---|---|
| Candidate | CANDIDATE_NOT_ACTIONABLE | CANDIDATE_REJECTED,false | 同左 | 同左 |
| any | DATA_INVALID | EXPERIMENT_INVALID,false | 同左 | 同左 |
| EntryIntent | EXPERIMENT_HALTED | CANDIDATE_REJECTED,false | CANDIDATE_REJECTED,true | CANDIDATE_REJECTED,false |
| EntryIntent | EXISTING_POSITION | CANDIDATE_REJECTED,true | 同左 | 同左 |
| EntryIntent | TOTAL_RISK_ALREADY_AT_LIMIT | CANDIDATE_REJECTED,true | 同左 | 同左 |
| EntryIntent | GAP_TOO_LARGE/PRICE_GEOMETRY_INVALID/QUANTITY_ROUNDED_TO_ZERO/BELOW_MIN_QTY/BELOW_MIN_NOTIONAL | CANDIDATE_REJECTED,false | 同左 | 同左 |
| EntryIntent | INSUFFICIENT_AVAILABLE_BALANCE | CANDIDATE_REJECTED,true | 同左 | 同左 |
| EntryIntent | CONTRACT_RULE_UNAVAILABLE/CONTRACT_RULE_EXPIRED/COST_MODEL_UNAVAILABLE/FUNDING_SCHEDULE_UNVERIFIED/FUNDING_RISK_CONFIG_UNAVAILABLE/TARGET_MINUTE_UNAVAILABLE/REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE/OPEN_RISK_MODEL_UNAVAILABLE/BATCH_INCOMPLETE | EXECUTION_PATH_INVALID,false | EXECUTION_PATH_INVALID,true | EXPERIMENT_INVALID,false |
| PortfolioBatch | TOTAL_RISK_ALREADY_AT_LIMIT | CANDIDATE_REJECTED,true | 同左 | 同左 |
| PortfolioBatch | INSUFFICIENT_AVAILABLE_BALANCE | CANDIDATE_REJECTED,true | 同左 | 同左 |
| PortfolioBatch | QUANTITY_ROUNDED_TO_ZERO/BELOW_MIN_QTY/BELOW_MIN_NOTIONAL | CANDIDATE_REJECTED,false | 同左 | 同左 |
| ExitIntent | POSITION_SNAPSHOT_CHANGED | PLAN_CANCELLED,true | 同左 | 同左 |
| ExitIntent | CONTRACT_RULE_UNAVAILABLE/CONTRACT_RULE_EXPIRED/COST_MODEL_UNAVAILABLE/TARGET_MINUTE_UNAVAILABLE/POSITION_QUANTITY_RULE_MISMATCH | EXECUTION_PATH_INVALID,false | PLAN_CANCELLED,true | EXPERIMENT_INVALID,false |
| ExitPlan | POSITION_SNAPSHOT_CHANGED | PLAN_CANCELLED,false | PLAN_CANCELLED,true | PLAN_CANCELLED,false |

`BATCH_INCOMPLETE` 在合法 batch 尚无法构造时，以当前已收集尝试中的稳定 `EntryIntentSubjectRef` 表达；合法 `PortfolioPlanningBatch` 一旦存在，后续 portfolio rejection 必须使用其 `PortfolioBatchSubjectRef`，不得临时拼接 batch subject。两种 subject 都必须按上表的 subject kind、reason 和 research stage 联合求值。

上表列出全部合法的非 `DATA_INVALID` 组合；未列出的 `(subject kind,reason)` 是非法构造，唯一结果为 `reason=DATA_INVALID, disposition=EXPERIMENT_INVALID, retry_allowed=false`。因此 EntryPlanSubjectRef 只允许承载 `DATA_INVALID`；ExitPlanSubjectRef 只允许 `DATA_INVALID` 或上表明确的 `POSITION_SNAPSHOT_CHANGED`，不得发明枚举外 reason。

`EXPERIMENT_HALTED` 不允许用于 Exit subject。`CANDIDATE_NOT_ACTIONABLE` 不允许表示非法Candidate。`RISK_BUDGET_EXCEEDED`和`TOTAL_RISK_EXCEEDED`不是正常拒绝；若冻结floor/scale公式后仍出现超限，返回 `DATA_INVALID/EXPERIMENT_INVALID`。

多个事实同时存在时，先收集全部 evidence，再按 rank 选择唯一 reason，随后根据联合映射得到 disposition/retry。禁止校验代码顺序决定结果。

历史缺失不得变成普通未交易：`EXECUTION_PATH_INVALID` 的受影响 symbol/path/segment 不得从分母静默删除、不得计为避免亏损、不得继续计算可晋级绩效。未来报告必须分列 `ECONOMIC_REJECTION`、`EXECUTION_PATH_INVALID`、`EXPERIMENT_INVALID`。APPROXIMATED 只是显式独立路径，绝不是缺失证据的静默默认。

## 12. 时间边界冻结

1. Candidate decision time 是已收盘 4H 的市场 close time。
2. 下一 4H open 精确为 `decision_time+1ms` 且必须 UTC 4H 对齐。
3. Entry delay 0/1/2 分别是 anchor、anchor+1m、anchor+2m。
4. Entry/Exit Plan factory 在 target 前不应被调用；若调用则是前置条件错误，不返回领域对象。
5. ExitIntent condition time 来自上游市场/实验事件，target 是严格未来分钟 open。
6. ExitPlan 只能在 TargetMinuteOpenSnapshot 到达后构造；HALTED不改变此语义。
7. funding 采用 `(entry,maxExit]`；同刻先 funding 后 exit。
8. contract rule target 必须位于 `[from,to)`；`target==to` 过期。
9. 同刻 BTC/ETH 以相同 eligible time、相同planning-phase account snapshot和completeness watermark组成一个 batch。
10. 跨日/月仅按 UTC 整数运算，不调用 timezone locale。
11. split 标签不影响 Intent/Plan；但 target 不得越过实验 manifest 允许的 execution range。
12. TargetMinuteOpenSnapshot和watermark必须是显式输入；仅watermark越过且Snapshot缺失时才产生TARGET_MINUTE_UNAVAILABLE。
13. 修改target 1m bar的high/low/close/volume/trade metadata不得改变Plan bytes/ID；修改open price必须改变它们。
14. Account snapshot time必须等于batch eligible time，phase必须表示同刻funding+计划性exit已完成、Entry batch尚未反映。
15. 修改 target 之后的数据不得改变已生成历史Intent/Plan。

完整案例见 `../reviews/second-batch-2b-time-boundary-matrix.md`。

## 13. Golden Fixture 与 property-test 冻结

编码前先写 fixture manifest，再写生产函数。必须包含 BTC LONG、ETH SHORT、gap 前/等于/超过、tick/step、minimum、7 次 funding、三种 contract mode、同时缩量、拒绝不再分配、0.5%、1%、wall clock、输入顺序、delay 身份和未来数据不变性。完整计划见 `../reviews/second-batch-2b-golden-fixture-plan.md`。

## 14. Scope Guard 冻结

未来 2B 生产目录及其传递依赖禁止：

```text
HTTP client, socket, requests, urllib, curl, websocket
API key, private key, secret loader
create_order, exchange authenticated client
GUI, Qt, LLM, Shadow Worker
minute event loop, FillEvent
Position mutation, funding settlement, liquidation
Ledger, PnL, drawdown, performance report
```

守卫必须同时检查 AST import/call、目录/类/函数名、反射动态 import、`subprocess`/PowerShell/curl 间接网络，以及生产目录依赖闭包。允许读取的所有数据必须以参数传入纯函数；2B 内禁止文件 I/O 和环境变量读取。

## 15. 版本冻结表

```text
ENTRY_INTENT_SCHEMA_V1
TARGET_MINUTE_OPEN_SNAPSHOT_SCHEMA_V1
TARGET_EVENT_WATERMARK_SCHEMA_V1
ENTRY_EXECUTION_PLAN_SCHEMA_V1
EXIT_INTENT_SCHEMA_V1
EXIT_EXECUTION_PLAN_SCHEMA_V1
EXECUTION_REJECTION_SCHEMA_V1
REJECTION_SUBJECT_REF_SCHEMA_V1
CONTRACT_RULE_COVERAGE_V1
CONTRACT_APPROXIMATION_POLICY_V1
COST_MODEL_SNAPSHOT_SCHEMA_V1
POSITION_SIZING_RESULT_SCHEMA_V1
PORTFOLIO_PLANNING_BATCH_SCHEMA_V1
PORTFOLIO_SCALING_RESULT_SCHEMA_V1
ACCEPTED_SCALING_ITEM_SCHEMA_V1
REJECTED_SCALING_ITEM_SCHEMA_V1
ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1
PLANNING_PHASE_V1
FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_V1
FUNDING_RISK_CONFIG_SNAPSHOT_V1
EXIT_CONDITION_SNAPSHOT_V1
EXECUTION_TIME_CONFIG_V1
MAX_HOLD_V1_EXACT_48H
GAP_POLICY_V1
PRICE_GEOMETRY_V1
FEE_MODEL_V1
SLIPPAGE_MODEL_V1
RESERVE_PRICE_BASIS_V1
FUNDING_BUFFER_MODEL_V2
FUNDING_RISK_CONFIG_V1
POSITION_SIZING_MODEL_V2
PORTFOLIO_SCALING_MODEL_V2
CONTRACT_MINIMUM_V1
LEVERAGE_POLICY_V1_FIXED_1X
2B_REJECTION_PRIORITY_V2
2B_REJECTION_SUBJECT_DISPOSITION_V1
2B_CANONICAL_VERSION_V1
```

任何字段、枚举、公式、先后顺序、区间开闭、Decimal 量化或 ID 输入变化必须提升相应版本。仅文案拼写且不改变语义可不提升，但必须记录 docs commit。

## 16. 一次性设计决策与未决项

本冻结包不给编码阶段留自由裁量。以下问题在本文中已选择推荐答案：

| 问题 | 冻结答案 |
|---|---|
| Exit trigger 谁判断 | 2C；2B 只消费 ExitConditionSnapshot |
| 保护性stop/TP/liquidation | 2C分钟内直接路径；禁止经2B下一分钟open Plan |
| Intent 是否含未来价格 | 否 |
| Plan 何时产生 | target open Snapshot到达、sizing+batch completeness+scaling完成后 |
| 48h 从何时算 | EntryPlan target execution time；2C 实际 Fill 必须同一事件时刻，否则路径 INVALID/版本升级 |
| funding ×6/×7 | 均禁止写死；窗口枚举，Golden 可得到 7 |
| available balance 是否含 pending | 不含；pending_plan_reserve 单独减，避免重复扣 |
| open risk 是否含 pending | 分为 existing_open_risk 与 pending_plan_risk，公式显式相加 |
| 一个计划失败是否重新放大另一个 | 否 |
| APPROX 是否可生成 Plan | PRIOR_ONLY可独立backtest/paper；HINDSIGHT仅诊断；均禁止Live |
| minNotional 参考价 | final expected entry fill |
| fee/reserve 是否量化到分 | V1 不量化，保留完整 Decimal |
| target minute 未到 | factory不应被调用；调用是非持久化precondition error |
| watermark 已过但缺 target | TARGET_MINUTE_UNAVAILABLE；历史路径EXECUTION_PATH_INVALID |
| 多错误如何选 | 收集事实后用priority V2，再按subject×reason×stage映射 |
| Plan 是否修改账户 | 永不；只输出 required cash/risk |
| EntryIntent是否读账户/HALTED | 否；两者只在target planning检查 |
| 同target集合如何证明完整 | PortfolioPlanningBatch completeness watermark |
| exit fee/funding reserve basis | 三个冻结价格的max；仅保证价格包络内保守 |

当前未决设计问题数量：`0`。如人工审核不同意任何答案，必须在编码前一次性修改本文、矩阵、版本和追踪；不得在编码中临时决定。

## 17. 追踪与验收入口

- 需求/测试：`../reviews/second-batch-2b-acceptance-matrix.md`
- 非法状态：`../reviews/second-batch-2b-illegal-state-matrix.md`
- 时间边界：`../reviews/second-batch-2b-time-boundary-matrix.md`
- Golden Fixtures：`../reviews/second-batch-2b-golden-fixture-plan.md`
- 自我红队：`../reviews/second-batch-2b-red-team.md`
- 完整性审计：`../reviews/second-batch-2b-traceability-audit.md`

未经人工书面批准，不得创建上述未来生产文件或任何 2B 测试文件。
