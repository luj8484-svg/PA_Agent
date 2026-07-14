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
| EntryIntent | `eint_ + first_24_hex(SHA256(Canonical(全部字段排除 intent_id)))` |
| ExitIntent | `xint_ + first_24_hex(SHA256(Canonical(全部字段排除 intent_id)))` |
| EntryExecutionPlan | `eplan_ + first_24_hex(SHA256(Canonical(全部字段排除 plan_id)))` |
| ExitExecutionPlan | `xplan_ + first_24_hex(SHA256(Canonical(全部字段排除 plan_id)))` |
| ExecutionRejection | `rej_ + first_24_hex(SHA256(Canonical(全部字段排除 rejection_id)))` |
| ContractRuleCoverage | `cr_ + first_24_hex(SHA256(Canonical(全部字段排除 coverage_id)))` |
| CostModelSnapshot | `cost_ + first_24_hex(SHA256(Canonical(全部字段排除 snapshot_id)))` |
| PositionSizingResult | `size_ + first_24_hex(SHA256(Canonical(全部字段排除 result_id)))` |
| PortfolioScalingResult | `scale_ + first_24_hex(SHA256(Canonical(全部字段排除 result_id)))` |

## 4. 公共枚举和 tagged union

```text
Side = LONG | SHORT
MarginMode = ISOLATED
PositionMode = ONE_WAY
OrderType = MARKET_AT_1M_OPEN
TriggerBasis = TRADE_1M_OPEN
ContractRuleMode = VERIFIED | APPROXIMATED | UNAVAILABLE
ResearchStage = BACKTEST | PAPER_SIMULATION | LIVE_ELIGIBILITY_RESEARCH
RejectionDisposition = EXPERIMENT_INVALID | CANDIDATE_REJECTED | PLAN_CANCELLED | RETRYABLE
SubjectType = CANDIDATE | ENTRY_INTENT | EXIT_INTENT | ENTRY_PLAN | EXIT_PLAN | PORTFOLIO_BATCH
ExitReason = TIME_EXIT | TREND_EXIT | HALT_EXIT | EXPERIMENT_END | UPSTREAM_STOP_TRIGGER | UPSTREAM_TP_TRIGGER | UPSTREAM_ESTIMATED_LIQUIDATION
```

Entry 与 Exit 是不同 Schema。Contract coverage 是三种 payload 的 tagged union；portfolio item 是 accepted/rejected tagged union。禁止以一个大 Schema 加互斥 nullable 字段模拟联合类型。

## 5. 领域对象 Schema

下表中的“必填”均为正式对象必填；`None` 不允许，除非字段类型明确写为 optional。正式对象均 frozen。

### 5.1 EntryIntent

EntryIntent 只能由 `LONG` 或 `SHORT` Candidate 创建，表达未来计划请求，不读取目标分钟价格、contract rule、账户或成本。

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `ENTRY_INTENT_SCHEMA_V1` |
| intent_id | str | 是 | Canonical payload | `eint_[0-9a-f]{24}` 且内容匹配 |
| candidate_id | str | 是 | StrategyCandidate | 非空、已通过 2A 校验 |
| candidate_schema_version | str | 是 | Candidate | `STRATEGY_CANDIDATE_SCHEMA_V1` |
| symbol | str | 是 | Candidate | `BTCUSDT` 或 `ETHUSDT` |
| side | Side | 是 | Candidate.market_view | LONG→LONG、SHORT→SHORT；NO_SETUP 禁止 |
| candidate_decision_time_utc_ms | int | 是 | Candidate | 事件时钟 |
| intent_created_time_utc_ms | int | 是 | Candidate | 必须等于 decision time |
| execution_anchor_utc_ms | int | 是 | TIME-F01 | 下一 4H UTC open |
| target_execution_time_utc_ms | int | 是 | TIME-F01 | anchor + delay |
| execution_delay_minutes | int | 是 | ExecutionTimeConfig | 仅 `0/1/2` |
| execution_time_config_version | str | 是 | config | `EXECUTION_TIME_CONFIG_V1` |
| decision_visible_input_hash | sha256 | 是 | Candidate | 原样复制 |
| strategy_version | str | 是 | Candidate | 原样复制 |
| intent_config_hash | sha256 | 是 | 冻结 2B intent config | 不含 wall clock |
| code_commit | hex str | 是 | 实验 manifest | 7–64 小写 hex |
| dependency_lock_hash | sha256 | 是 | 实验 manifest | 64 小写 hex |

### 5.2 EntryExecutionPlan

EntryExecutionPlan 只能在目标 1m open 已可见后生成，并且是 portfolio scaling 后的 final plan。内部 draft 不是领域对象、不可持久化、无 ID。

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `ENTRY_EXECUTION_PLAN_SCHEMA_V1` |
| plan_id | str | 是 | Canonical payload | `eplan_[0-9a-f]{24}` 且内容匹配 |
| intent_id | str | 是 | EntryIntent | 内容已校验 |
| candidate_id | str | 是 | EntryIntent | 不重新派生 |
| computational_experiment_id | sha256 | 是 | 实验 manifest | acquisition hash 排除 |
| symbol | str | 是 | Intent | BTCUSDT/ETHUSDT |
| side | Side | 是 | Intent | 必须与 Candidate 一致 |
| decision_time_utc_ms | int | 是 | Intent | 事件时钟 |
| target_execution_time_utc_ms | int | 是 | Intent | 1m UTC open |
| plan_created_time_utc_ms | int | 是 | 目标分钟市场事件 | 必须等于 target time；非 wall clock |
| maximum_exit_time_utc_ms | int | 是 | TIME-F03 | target + 48h |
| order_type | OrderType | 是 | 常量 | `MARKET_AT_1M_OPEN` |
| trigger_basis | TriggerBasis | 是 | 常量 | `TRADE_1M_OPEN` |
| reference_price | Decimal | 是 | 目标 trade 1m open | 有限且 >0，未加滑点 |
| expected_entry_fill_price | Decimal | 是 | PRICE-F04 | tick 对齐、>0 |
| stop_trigger_price | Decimal | 是 | PRICE-F05 | tick 对齐、>0 |
| take_profit_trigger_price | Decimal | 是 | PRICE-F06 | tick 对齐、>0 |
| expected_stop_fill_price | Decimal | 是 | PRICE-F07 | tick 对齐、>0 |
| expected_take_profit_fill_price | Decimal | 是 | PRICE-F08 | tick 对齐、>0 |
| quantity | Decimal | 是 | PortfolioScalingResult | step 对齐、>0 |
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
| funding_reserve | Decimal | 是 | FUND-F12 | ≥0 |
| required_cash | Decimal | 是 | CASH-F20 | 四项和，仅锁定不扣款 |
| leverage | int | 是 | 常量 | 精确等于 1 |
| margin_mode | MarginMode | 是 | 常量 | ISOLATED |
| position_mode | PositionMode | 是 | 常量 | ONE_WAY |
| execution_delay_minutes | int | 是 | Intent | 0/1/2 |
| execution_time_config_version | str | 是 | Intent | 固定版本 |
| contract_rule_mode | ContractRuleMode | 是 | coverage | VERIFIED/APPROXIMATED；UNAVAILABLE 无 Plan |
| contract_rule_coverage_id | str | 是 | coverage | 内容已校验 |
| contract_rule_content_hash | sha256 | 是 | coverage | 进入 plan ID |
| contract_rule_version | str | 是 | coverage | 有效期覆盖 target |
| cost_model_snapshot_id | str | 是 | CostModelSnapshot | 内容已校验 |
| cost_model_content_hash | sha256 | 是 | snapshot | 进入 plan ID |
| funding_schedule_version | str | 是 | schedule | 覆盖 `(target,max_exit]` |
| funding_schedule_content_hash | sha256 | 是 | schedule | 进入 plan ID |
| account_snapshot_id | str | 是 | Account snapshot | 同一规划批次冻结 |
| account_snapshot_hash | sha256 | 是 | Account snapshot | 进入 plan ID |
| position_sizing_result_id | str | 是 | PositionSizingResult | 未缩量结果 |
| portfolio_scaling_result_id | str | 是 | PortfolioScalingResult | final quantity 来源 |
| target_minute_input_hash | sha256 | 是 | target 1m record | 只覆盖当时可见记录 |
| decision_visible_input_hash | sha256 | 是 | Candidate | 原样复制 |
| plan_config_hash | sha256 | 是 | 2B config | 公式/枚举/优先级版本集合 |
| code_commit | hex str | 是 | manifest | 7–64 小写 hex |
| dependency_lock_hash | sha256 | 是 | manifest | 64 小写 hex |
| approximation_watermark | str | 是 | mode 规则 | VERIFIED=`VERIFIED`; APPROX=`APPROXIMATED_NOT_LIVE_ELIGIBLE` |

### 5.3 ExitIntent

ExitIntent 只接受上游已判断的退出条件；2B 不判断条件是否命中。Intent 创建时未来目标 open 必须未知且不得写入价格。

上游 `EXIT_CONDITION_SNAPSHOT_V1` 接口固定包含：`condition_event_id`、`origin_candidate_id`、`position_id`、`position_snapshot_hash`、`symbol`、`position_side`、`full_exit_quantity`、`exit_reason`、`condition_time_utc_ms`、`condition_visible_input_hash`、`code_commit`、`dependency_lock_hash`。所有字段必填；时间来自触发该条件的市场/实验事件，数量>0，hash/ID内容匹配。2B只验证和复制，不重新判断 `exit_reason`。

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `EXIT_INTENT_SCHEMA_V1` |
| intent_id | str | 是 | Canonical payload | `xint_[0-9a-f]{24}` 且匹配 |
| condition_event_id | str | 是 | ExitConditionSnapshot | 非空 |
| origin_candidate_id | str | 是 | position snapshot | 非空 |
| position_id | str | 是 | position snapshot | 非空；2B 不创建 position |
| position_snapshot_hash | sha256 | 是 | position snapshot | 冻结数量/side |
| symbol | str | 是 | position | BTCUSDT/ETHUSDT |
| position_side | Side | 是 | position | LONG/SHORT |
| full_exit_quantity | Decimal | 是 | position | step 对齐、>0；只允许全退 |
| exit_reason | ExitReason | 是 | condition | 上游枚举 |
| condition_time_utc_ms | int | 是 | condition market event | 非 wall clock |
| intent_created_time_utc_ms | int | 是 | condition | 等于 condition time |
| execution_anchor_utc_ms | int | 是 | TIME-F02 | 严格晚于 condition 的下一分钟 open |
| target_execution_time_utc_ms | int | 是 | TIME-F02 | anchor + exit delay |
| execution_delay_minutes | int | 是 | exit config | 0/1/2 |
| execution_time_config_version | str | 是 | config | 固定版本 |
| intent_config_hash | sha256 | 是 | config | 不含 wall clock |
| code_commit | hex str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 格式合法 |

### 5.4 ExitExecutionPlan

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `EXIT_EXECUTION_PLAN_SCHEMA_V1` |
| plan_id | str | 是 | Canonical payload | `xplan_[0-9a-f]{24}` 且匹配 |
| intent_id | str | 是 | ExitIntent | 已校验 |
| condition_event_id | str | 是 | ExitIntent | 原样复制 |
| origin_candidate_id | str | 是 | ExitIntent | 原样复制 |
| position_id | str | 是 | ExitIntent | 原样复制 |
| computational_experiment_id | sha256 | 是 | manifest | 固定实验 |
| symbol | str | 是 | Intent | 一致 |
| position_side | Side | 是 | Intent | 一致 |
| exit_reason | ExitReason | 是 | Intent | 不重新判断 |
| quantity | Decimal | 是 | Intent + target position check | 必须等于 full_exit_quantity |
| condition_time_utc_ms | int | 是 | Intent | 事件时钟 |
| target_execution_time_utc_ms | int | 是 | Intent | 未来 1m open |
| plan_created_time_utc_ms | int | 是 | 目标市场事件 | 等于 target time |
| order_type | OrderType | 是 | 常量 | MARKET_AT_1M_OPEN |
| trigger_basis | TriggerBasis | 是 | 常量 | TRADE_1M_OPEN |
| reference_price | Decimal | 是 | target trade 1m open | >0 |
| expected_exit_fill_price | Decimal | 是 | PRICE-F09 | tick 对齐、>0 |
| expected_exit_fee | Decimal | 是 | COST-F11 | ≥0；不是 reserve |
| contract_rule_mode | ContractRuleMode | 是 | coverage | UNAVAILABLE 无 Plan |
| contract_rule_coverage_id | str | 是 | coverage | target 有效 |
| contract_rule_content_hash | sha256 | 是 | coverage | 进入 ID |
| cost_model_snapshot_id | str | 是 | cost | 进入 ID |
| cost_model_content_hash | sha256 | 是 | cost | 进入 ID |
| target_minute_input_hash | sha256 | 是 | 1m record | 可见数据 |
| position_snapshot_hash | sha256 | 是 | Intent/target recheck | 必须未变化；否则取消 |
| plan_config_hash | sha256 | 是 | config | 版本集合 |
| code_commit | hex str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 格式合法 |
| approximation_watermark | str | 是 | coverage | 同 EntryPlan |

ExitPlan 禁止包含 entry fee、exit fee reserve、funding reserve、initial margin、unit risk、risk budget、stop、TP 或 portfolio scaling 字段。

### 5.5 ExecutionRejection

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `EXECUTION_REJECTION_SCHEMA_V1` |
| rejection_id | str | 是 | Canonical payload | `rej_[0-9a-f]{24}` 且匹配 |
| subject_type | SubjectType | 是 | 调用阶段 | 不使用 nullable 多 ID |
| subject_id | str | 是 | 对应对象 | 非空 |
| symbol | str | 是 | subject | BTC/ETH |
| event_time_utc_ms | int | 是 | 市场/实验事件 | 禁止 wall clock |
| reason | ExecutionRejectionReason | 是 | 优先级选择 | 见第 11 节 |
| disposition | RejectionDisposition | 是 | reason matrix | 唯一映射 |
| retry_allowed | bool | 是 | reason matrix | 不由调用顺序决定 |
| required_values | tuple[pair[str,str]] | 是 | 校验器 | Canonical 排序 |
| observed_values | tuple[pair[str,str]] | 是 | 校验器 | Canonical 排序 |
| relevant_version_hashes | tuple[pair[str,sha256]] | 是 | inputs | Canonical 排序 |
| gap_intervals | tuple[pair[int,int]] | 是 | data | 有序、闭区间；无 gap 为 `[]` |
| decision_visible_input_hash | sha256 | 是 | Candidate | Candidate subject 必填 |
| rejection_config_hash | sha256 | 是 | config | 含优先级版本 |
| code_commit | hex str | 是 | manifest | 格式合法 |
| dependency_lock_hash | sha256 | 是 | manifest | 格式合法 |

### 5.6 ContractRuleCoverage tagged union

| 字段 | 类型 | 必填模式 | 唯一来源 | 约束 |
|---|---|---|---|---|
| schema_version | str | 全部 | 常量 | `CONTRACT_RULE_COVERAGE_V1` |
| coverage_id | str | 全部 | Canonical payload | `cr_[0-9a-f]{24}` 且内容匹配 |
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
| review_status | str | VERIFIED/APPROXIMATED | archive review | VERIFIED固定`APPROVED_VERIFIED` |
| tick_size | Decimal | VERIFIED/APPROXIMATED | rule archive | >0 |
| step_size | Decimal | VERIFIED/APPROXIMATED | rule archive | >0 |
| min_qty | Decimal | VERIFIED/APPROXIMATED | rule archive | ≥0 |
| min_notional | Decimal | VERIFIED/APPROXIMATED | rule archive | ≥0 |
| quantity_precision_audit | int | VERIFIED/APPROXIMATED | source audit | ≥0，仅审计，不替代 step |
| price_precision_audit | int | VERIFIED/APPROXIMATED | source audit | ≥0，仅审计，不替代 tick |
| evidence_manifest_hash | sha256 | VERIFIED/APPROXIMATED | covered archive | 64小写hex |
| approximation_method | str | APPROXIMATED | approved reconstruction | 非空；其他模式字段不存在 |
| approximation_distance_ms | int | APPROXIMATED | query与证据时间差 | ≥0 |
| approximation_watermark | str | APPROXIMATED | 常量 | `APPROXIMATED_NOT_LIVE_ELIGIBLE` |
| unavailable_reason | str | UNAVAILABLE | resolver search | 非空；covered模式字段不存在 |
| searched_archive_hashes | tuple[sha256] | UNAVAILABLE | resolver search | 去重升序，可为空但必须显式 `[]` |
| requested_time_utc_ms | int | UNAVAILABLE | resolver query | 必须等于 query_time |

UNAVAILABLE 必须产生 `CONTRACT_RULE_UNAVAILABLE`，不能创建 Plan。

有效期统一为半开区间 `[effective_from,effective_to)`；`from < to`，同一 symbol/mode 的 VERIFIED 区间不得重叠。

### 5.7 CostModelSnapshot

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `COST_MODEL_SNAPSHOT_SCHEMA_V1` |
| snapshot_id | str | 是 | Canonical | `cost_[0-9a-f]{24}`且内容匹配 |
| symbol | str | 是 | config | BTCUSDT/ETHUSDT |
| fee_rate | Decimal | 是 | `FEE_MODEL_V1` | baseline `0.0005`，≥0 |
| slippage_rate | Decimal | 是 | `SLIPPAGE_MODEL_V1` | BTC `0.0001`、ETH `0.0002`，≥0 |
| funding_adverse_rate_cap | Decimal | 是 | funding config | `0.0001`，≥0 |
| stress_multiplier | Decimal | 是 | experiment config | `1`、`1.5` 或 `2` |
| effective_fee_rate | Decimal | 是 | COST-F01 | 精确乘法且自校验 |
| effective_slippage_rate | Decimal | 是 | COST-F02 | 精确乘法且自校验 |
| fee_model_version | str | 是 | config | `FEE_MODEL_V1` |
| slippage_model_version | str | 是 | config | `SLIPPAGE_MODEL_V1` |
| funding_buffer_model_version | str | 是 | config | `FUNDING_BUFFER_MODEL_V1` |
| config_hash | sha256 | 是 | config | 全部配置字段 Canonical hash |

资金费 cap 不乘 cost stress multiplier；若未来改变必须提升 funding buffer 版本。

### 5.8 PositionSizingResult

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `POSITION_SIZING_RESULT_SCHEMA_V1` |
| result_id | str | 是 | Canonical | `size_[0-9a-f]{24}`且内容匹配 |
| intent_id | str | 是 | EntryIntent | 非空、内容已验证 |
| symbol | str | 是 | Intent | BTCUSDT/ETHUSDT |
| side | Side | 是 | Intent | 一致 |
| reference_price | Decimal | 是 | target trade 1m open | >0 |
| expected_entry_fill_price | Decimal | 是 | PRICE-F04 | tick对齐、>0 |
| stop_trigger_price | Decimal | 是 | PRICE-F05 | tick对齐、>0 |
| take_profit_trigger_price | Decimal | 是 | PRICE-F06 | tick对齐、>0 |
| expected_stop_fill_price | Decimal | 是 | PRICE-F07 | tick对齐、>0 |
| expected_take_profit_fill_price | Decimal | 是 | PRICE-F08 | tick对齐、>0 |
| unit_risk | Decimal | 是 | RISK-F13 | >0 |
| single_risk_budget | Decimal | 是 | RISK-F14 | >0 |
| raw_quantity | Decimal | 是 | RISK-F15 | >0 |
| step_quantized_quantity | Decimal | 是 | QTY-F16 | ≥0 |
| unscaled_planned_risk | Decimal | 是 | RISK-F19 | 用于共同scale分母，>0 |
| unscaled_required_cash | Decimal | 是 | CASH-F23 | 保守用于scale分母，>0 |
| contract_rule_coverage_id | str | 是 | covered CR | 非空且target有效 |
| cost_model_snapshot_id | str | 是 | CostModelSnapshot | 非空且symbol一致 |
| funding_event_upper_bound | int | 是 | FUND-F11 | ≥0 |
| account_snapshot_id | str | 是 | AS | 同一batch |
| account_snapshot_hash | sha256 | 是 | AS | 同一batch完整内容hash |
| sizing_model_version | str | 是 | 常量 | `POSITION_SIZING_MODEL_V1` |
| input_hash | sha256 | 是 | 全部纯输入 | 不含acquisition/wall clock |

这是成功值对象；任一失败返回 ExecutionRejection，禁止用 nullable quantity 表示失败。

### 5.9 PortfolioScalingResult

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 常量 | `PORTFOLIO_SCALING_RESULT_SCHEMA_V1` |
| result_id | str | 是 | Canonical | `scale_[0-9a-f]{24}`且内容匹配 |
| eligible_time_utc_ms | int | 是 | batch key | 全部item相同target |
| account_snapshot_id | str | 是 | AS | batch冻结 |
| account_snapshot_hash | sha256 | 是 | AS | batch冻结完整内容hash |
| ordered_input_result_ids | tuple[str] | 是 | sizing set | 按`(symbol,result_id)`排序且去重 |
| remaining_risk | Decimal | 是 | RISK-F21 | ≥0 |
| deployable_cash | Decimal | 是 | CASH-F22 | ≥0 |
| risk_scale | Decimal | 是 | SCALE-F23 | ≥0 |
| cash_scale | Decimal | 是 | SCALE-F23 | ≥0 |
| final_scale | Decimal | 是 | SCALE-F23 | `min(1,risk,cash)`，范围`[0,1]` |
| item_results | tuple[tagged item] | 是 | SCALE-F24+minimum | 按symbol排序；Accepted含result_id/final_qty/final risk/cash，Rejected含rejection_id |
| scaling_model_version | str | 是 | 常量 | `PORTFOLIO_SCALING_MODEL_V1` |
| input_hash | sha256 | 是 | sorted sizing inputs+AS | 与输入容器顺序无关 |

一个 item 因 minimum/zero 被拒绝后，其他 item 不重新放大，原 `final_scale` 不变。

### 5.10 AccountPlanningSnapshot 接口

2B 不实现 Ledger，但必须读取以下一次性冻结快照：

| 字段 | 类型 | 必填 | 唯一来源 | 约束 |
|---|---|---:|---|---|
| schema_version | str | 是 | 上游快照版本 | `ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1` |
| snapshot_id | str | 是 | Canonical | `acct_[0-9a-f]{24}`且内容匹配 |
| snapshot_hash | sha256 | 是 | Canonical | 全字段排除snapshot_id/hash后的SHA-256 |
| event_time_utc_ms | int | 是 | 账户/市场事件 | 非负、非wall clock |
| wallet_balance | Decimal | 是 | 上游Ledger snapshot | 单一经济钱包；有限且≥0 |
| current_equity | Decimal | 是 | wallet+mark未实现PnL | 有限且>0才能新计划 |
| locked_initial_margin | Decimal | 是 | 已成交持仓分类 | ≥0 |
| locked_fee_reserve | Decimal | 是 | 已成交持仓分类 | ≥0 |
| locked_funding_reserve | Decimal | 是 | 已成交持仓分类 | ≥0 |
| available_balance | Decimal | 是 | CASH-F01 | `wallet-三项locks`；≥0；不含pending |
| existing_open_risk | Decimal | 是 | 已成交仓位risk | ≥0 |
| pending_plan_reserve | Decimal | 是 | 先前批准未成交plans | ≥0，只计现金一次 |
| pending_plan_risk | Decimal | 是 | 先前批准未成交plans | ≥0，只计risk一次 |
| existing_position_symbols | tuple[str] | 是 | position snapshot | 去重升序 |
| experiment_state | str | 是 | experiment state | RUNNING或HALTED |

2B 校验 `available_balance` 必须与其派生公式一致，防止第二真相源。`deployable_cash=available_balance-pending_plan_reserve`。所有 reserve 是 wallet 内锁定分类，不是经济扣款。资金费只允许 Ledger 在 2C 对 wallet 产生一次经济变化；isolated margin view 是派生视图，不是第二账户。

## 6. 生命周期与状态转换

| 转换 | 触发 | 输入 | 输出 | 不变量 | 失败 | 重试 | ID 规则 |
|---|---|---|---|---|---|---|---|
| Candidate→EntryIntent | 2A 输出 LONG/SHORT | Candidate、delay config | EntryIntent | 不读未来价格；side 一致 | CANDIDATE_NOT_ACTIONABLE、HALTED、EXISTING_POSITION | config/账户状态变化可新请求；同输入不可重试出不同结果 | 同输入同 ID；delay 变化 Intent ID 变化，Candidate ID 不变 |
| EntryIntent→EntryPlan | target 1m open 到达且 data watermark 完成 | Intent、1m、coverage、cost、schedule、account | EntryPlan 或 Rejection | plan time=target；先 gap 后价格/风险 | priority matrix | 只有标记 retryable 才允许；历史缺口不可重试 | target 数据/版本变化 Plan ID 变化 |
| Candidates batch→Scaling | 同一 target 的全部 sizing success 同时就绪 | sorted sizing results、同一 account snapshot | PortfolioScalingResult | 同算后缩量；不按输入顺序分配 | TOTAL_RISK、cash、minimum 等 item rejection | 冻结 batch 不重试 | 输入集合相同 ID 相同 |
| Open Position Exit Condition (`ExitConditionSnapshot`)→ExitIntent | 上游条件事件发生 | condition、position、delay config | ExitIntent | 不判断 trigger；不读未来 open | DATA_INVALID、HALTED policy、position mismatch | position/condition 新版本才产生新 Intent | condition/config 变化 ID 变化 |
| ExitIntent→ExitPlan | 严格未来 target minute 到达 | Intent、target 1m、position recheck、coverage、cost | ExitPlan 或 Rejection | 全退；不含 Entry 字段 | target/data/contract/POSITION_SNAPSHOT_CHANGED | 仅 retryable 状态 | target 数据/版本变化 ID 变化 |
| Intent→Rejection | 任一冻结校验失败 | 全部当时可见 facts | ExecutionRejection | 不修改 Candidate/position/account | 唯一最高优先级 reason | 由 matrix 决定 | 证据或 subject 变化 ID 变化 |

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
| COST-F09 | `entry_fee=quantity*expected_entry_fill*effective_fee_rate` | 不按 tick/step/USDT 分位量化 | FEE_MODEL_V1 |
| COST-F10 | `exit_fee_reserve=quantity*expected_stop_fill*effective_fee_rate` | 只预留一次；以 stop adverse exit | FEE_MODEL_V1 |
| COST-F11 | `expected_exit_fee=quantity*expected_exit_fill*effective_fee_rate` | ExitPlan estimate；不修改 wallet | FEE_MODEL_V1 |
| FUND-F11 | `count=sum(window_end>entry and window_start<=maximum_exit for each schedule window)` | 区间 `(entry,maximum_exit]`；相同终点先 funding 后 exit | FUNDING_BUFFER_MODEL_V1 |
| FUND-F12 | `funding_reserve=quantity*entry_fill*adverse_rate_cap*count` | cap 不乘 cost stress | FUNDING_BUFFER_MODEL_V1 |
| RISK-F13 | `price_loss=abs(entry-stop_fill)`；`unit_risk=price_loss+entry*effective_fee_rate+stop_fill*effective_fee_rate+entry*adverse_rate_cap*count` | 逐项精确相加；滑点已在 fill 内，不另扣 | POSITION_SIZING_MODEL_V1 |
| RISK-F14 | `single_risk_budget=current_equity*Decimal("0.005")` | 负/零 equity 拒绝 | POSITION_SIZING_MODEL_V1 |
| RISK-F15 | `raw_quantity=single_risk_budget/unit_risk` | unit_risk>0；不先量化 budget | POSITION_SIZING_MODEL_V1 |
| QTY-F16 | `step_qty=floor(raw_quantity/step_size)*step_size` | 只向下；禁止向上满足 minimum | POSITION_SIZING_MODEL_V1 |
| RISK-F17 | `planned_risk=final_quantity*unit_risk` | final quantity 后重算；必须 ≤ budget | POSITION_SIZING_MODEL_V1 |
| RISK-F18 | `notional=final_quantity*expected_entry_fill` | 正值；用于 minNotional 和 margin | POSITION_SIZING_MODEL_V1 |
| RISK-F19 | `unscaled_planned_risk=raw_quantity*unit_risk` | 用于共同scale分母；不使用step preview | POSITION_SIZING_MODEL_V1 |
| CASH-F01 | `available_balance=wallet_balance-locked_initial_margin-locked_fee_reserve-locked_funding_reserve` | 与AS字段精确一致；pending不在此式 | ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1 |
| CASH-F19 | `initial_margin=notional/Decimal("1")` | leverage 精确等于 1 | POSITION_SIZING_MODEL_V1 |
| CASH-F20 | `required_cash=initial_margin+entry_fee+exit_fee_reserve+funding_reserve` | 四项各算一次；只是 reserve | POSITION_SIZING_MODEL_V1 |
| RISK-F21 | `remaining=max(0,current_equity*0.01-existing_open_risk-pending_plan_risk)` | 本批计划尚未计入 | PORTFOLIO_SCALING_MODEL_V1 |
| RISK-F22 | `total_risk_after_plan=existing_open_risk+pending_plan_risk+sum(final_planned_risk_i)` | 必须≤`current_equity*0.01`；等于接受 | PORTFOLIO_SCALING_MODEL_V1 |
| CASH-F22 | `deployable=max(0,available_balance-pending_plan_reserve)` | available 先经快照一致性校验 | PORTFOLIO_SCALING_MODEL_V1 |
| CASH-F23 | 以 `q=raw_quantity` 依次计算 `raw_notional=q*entry`、`raw_entry_fee=q*entry*effective_fee_rate`、`raw_exit_fee=q*stop_fill*effective_fee_rate`、`raw_funding=q*entry*adverse_rate_cap*count`，再精确求和 | 用于 cash scale 分母；不得先 step 量化 | PORTFOLIO_SCALING_MODEL_V1 |
| SCALE-F23 | `risk_scale=1 if sumRisk=0 else remaining/sumRisk`; `cash_scale=1 if sumCash=0 else deployable/sumCash`; `scale=min(1,risk_scale,cash_scale)` | scale clamp 仅上限 1；负输入拒绝 | PORTFOLIO_SCALING_MODEL_V1 |
| SCALE-F24 | `scaled_qty_i=floor(raw_qty_i*scale/step_i)*step_i` | 不从 step_qty 再乘，避免双量化；拒绝后不再分配 | PORTFOLIO_SCALING_MODEL_V1 |
| MIN-F25 | accept iff `qty>=min_qty AND qty*entry_fill>=min_notional`; zero 先判 QUANTITY_ROUNDED_TO_ZERO | 等于 minimum 接受 | CONTRACT_MINIMUM_V1 |
| LEV-F26 | accept iff `leverage==1 AND initial_margin==notional` | `2` 即拒绝 DATA_INVALID；2B 不测试 2x | LEVERAGE_POLICY_V1_FIXED_1X |

价格几何：LONG 必须 `expected_stop_fill <= stop_trigger < entry < take_profit_trigger` 且 `expected_take_profit_fill > entry`；SHORT 必须 `expected_take_profit_fill < entry < stop_trigger <= expected_stop_fill`。任一 tick 量化导致相等或反序，拒绝 `PRICE_GEOMETRY_INVALID`。

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

`FundingScheduleSnapshot` 全字段必填：`schema_version=FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_V1`、`schedule_id`、`schedule_content_hash`、`symbol`、`schedule_version`、`effective_from_utc_ms`、`effective_to_utc_ms`、`timezone=UTC`、`nominal_timestamps_utc_ms`、`settlement_windows`、`settlement_boundary_semantics=CONSERVATIVE_WINDOW_V1`、`window_tolerance_ms`、`source_manifest_hash`、`created_by=PYTHON_DETERMINISTIC`。timestamps 严格升序；windows 与其一一对应、各自 `start<=nominal<=end`、彼此不重叠；有效期覆盖全部 windows。

计数区间固定 `(entry_time,maximum_exit_time]`。window 与该区间相交的判定是 `window_end > entry_time AND window_start <= maximum_exit_time`。当 funding window/事件与 maximum exit 同刻时，该次 funding 计入，未来 2C 必须先结算再退出。schedule 未覆盖整个区间、版本错误、窗口重叠/倒置或 symbol 不符，返回 `FUNDING_SCHEDULE_UNVERIFIED`，不得按零或固定 ×6/×7。

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
| APPROXIMATED | 当前/邻近快照或审核重建 | 自身声明且 target 落入 | 是，必须水印 | 独立分层 | 是，需成本/规则压力测试 | 否 |
| UNAVAILABLE | 搜索事实和缺失证据 | 无可用覆盖 | 否 | Candidate 保留、执行拒绝 | 否 | 否 |

APPROXIMATED 结果的 Plan、实验 manifest、输出目录和报告标题必须包含 `APPROXIMATED_NOT_LIVE_ELIGIBLE`。任何 attempt 把该 mode 输入 Live Eligibility 都拒绝 `DATA_INVALID`，并标记实验级 INVALID。2B 永不接真钱或自动交易。

## 10. Gap、minimum、风险和资金边界

- gap 使用未加滑点 `P0`、Candidate 冻结 `decision_close` 和 ATR；严格 `>` 拒绝，等于接受。
- 先验证数据/版本，再 gap；通过后才计算 fill、geometry、sizing。
- 单笔 planned risk 必须 `<= current_equity*0.005`，等于接受。
- batch 后 `existing_open_risk+pending_plan_risk+sum(final planned risk) <= current_equity*0.01`，等于接受。
- 同刻 BTC/ETH 必须全部 sizing 完成后共同 scale；排序只用于 Canonical，不用于分配。
- 一个 item 缩量后拒绝，不把释放量重新给其他 item。
- quantity=0、低于 minQty、低于 minNotional 使用不同 reason，按第 11 节优先级只返回一个。
- required cash 与 planned risk 是两个独立约束；不得以风险余额替代现金余额。
- 若 `deployable_cash<=0` 且本批存在正 required cash，返回 `INSUFFICIENT_AVAILABLE_BALANCE`；若 deployable>0，则先共同 scale，scale 后再判 zero/minimum，不用现金不足覆盖更具体的量化拒绝。

## 11. ExecutionRejection 枚举和唯一优先级

冻结优先级从高到低：

| Rank | Reason | Disposition | Retry | 说明 |
|---:|---|---|---:|---|
| 1 | DATA_INVALID | EXPERIMENT_INVALID | 否 | Schema、非有限数、hash/ID、双重真相、leverage 等系统非法 |
| 2 | EXPERIMENT_HALTED | CANDIDATE_REJECTED | 否 | HALTED 后禁止新计划 |
| 3 | CANDIDATE_NOT_ACTIONABLE | CANDIDATE_REJECTED | 否 | NO_SETUP、方向不支持或 Candidate 不完整 |
| 4 | EXISTING_POSITION | CANDIDATE_REJECTED | 是 | 状态改变后新 Candidate 可再试；同 Candidate 不原地改写 |
| 5 | POSITION_SNAPSHOT_CHANGED | PLAN_CANCELLED | 是 | ExitIntent 的 position hash/quantity 在 target 前变化；旧 Intent 不改写 |
| 6 | CONTRACT_RULE_EXPIRED | PLAN_CANCELLED | 是 | Intent 保留；新 coverage 产生新尝试 |
| 7 | CONTRACT_RULE_UNAVAILABLE | CANDIDATE_REJECTED | 是 | Candidate 保留 |
| 8 | COST_MODEL_UNAVAILABLE | CANDIDATE_REJECTED | 是 | 缺失冻结成本版本 |
| 9 | FUNDING_SCHEDULE_UNVERIFIED | CANDIDATE_REJECTED | 是 | 区间覆盖不足 |
| 10 | TARGET_MINUTE_UNAVAILABLE | EXPERIMENT_INVALID | 否 | watermark 已越过仍缺 1m；watermark 未到只等待，不产 Rejection |
| 11 | GAP_TOO_LARGE | CANDIDATE_REJECTED | 否 | 方向性 gap 严格超过阈值 |
| 12 | PRICE_GEOMETRY_INVALID | CANDIDATE_REJECTED | 否 | 只拒绝单计划，不使全实验 INVALID |
| 13 | RISK_BUDGET_EXCEEDED | CANDIDATE_REJECTED | 否 | 单笔 >0.5% |
| 14 | TOTAL_RISK_EXCEEDED | CANDIDATE_REJECTED | 否 | scale 后仍 >1% 即实现/数据错误 |
| 15 | INSUFFICIENT_AVAILABLE_BALANCE | CANDIDATE_REJECTED | 是 | 新账户 snapshot 可重试 |
| 16 | QUANTITY_ROUNDED_TO_ZERO | CANDIDATE_REJECTED | 否 | final floor 后为 0 |
| 17 | BELOW_MIN_QTY | CANDIDATE_REJECTED | 否 | qty>0 但小于 minQty |
| 18 | BELOW_MIN_NOTIONAL | CANDIDATE_REJECTED | 否 | qty 合格但 notional 不足 |

多个事实同时存在时，先收集全部 evidence，再按 rank 选择唯一 reason；禁止校验代码先后决定结果。Rejection 保存全部可构造 required/observed facts。`PLAN_CANCELLED` 只适用于已经存在 Intent 或 Plan、但目标时刻版本/position 发生有效变化；Candidate 本身永远不被删除或改写。

## 12. 时间边界冻结

1. Candidate decision time 是已收盘 4H 的市场 close time。
2. 下一 4H open 精确为 `decision_time+1ms` 且必须 UTC 4H 对齐。
3. Entry delay 0/1/2 分别是 anchor、anchor+1m、anchor+2m。
4. 目标 1m open 在到达前不可进入 EntryPlan；只能存在 EntryIntent。
5. ExitIntent condition time 来自上游市场/实验事件，target 是严格未来分钟 open。
6. ExitPlan 只能在 target open 到达后构造。
7. funding 采用 `(entry,maxExit]`；同刻先 funding 后 exit。
8. contract rule target 必须位于 `[from,to)`；`target==to` 过期。
9. 同刻 BTC/ETH 以相同 eligible time 和 account snapshot 组成一个 batch。
10. 跨日/月仅按 UTC 整数运算，不调用 timezone locale。
11. split 标签不影响 Intent/Plan；但 target 不得越过实验 manifest 允许的 execution range。
12. 未来数据变化不得改变已经生成的历史 Intent/Plan；修改 target time 之后的数据不在其 input hash 中。

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
ENTRY_EXECUTION_PLAN_SCHEMA_V1
EXIT_INTENT_SCHEMA_V1
EXIT_EXECUTION_PLAN_SCHEMA_V1
EXECUTION_REJECTION_SCHEMA_V1
CONTRACT_RULE_COVERAGE_V1
COST_MODEL_SNAPSHOT_SCHEMA_V1
POSITION_SIZING_RESULT_SCHEMA_V1
PORTFOLIO_SCALING_RESULT_SCHEMA_V1
ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1
FUNDING_SCHEDULE_SNAPSHOT_SCHEMA_V1
EXIT_CONDITION_SNAPSHOT_V1
EXECUTION_TIME_CONFIG_V1
MAX_HOLD_V1_EXACT_48H
GAP_POLICY_V1
PRICE_GEOMETRY_V1
FEE_MODEL_V1
SLIPPAGE_MODEL_V1
FUNDING_BUFFER_MODEL_V1
POSITION_SIZING_MODEL_V1
PORTFOLIO_SCALING_MODEL_V1
CONTRACT_MINIMUM_V1
LEVERAGE_POLICY_V1_FIXED_1X
2B_REJECTION_PRIORITY_V1
2B_CANONICAL_VERSION_V1
```

任何字段、枚举、公式、先后顺序、区间开闭、Decimal 量化或 ID 输入变化必须提升相应版本。仅文案拼写且不改变语义可不提升，但必须记录 docs commit。

## 16. 一次性设计决策与未决项

本冻结包不给编码阶段留自由裁量。以下问题在本文中已选择推荐答案：

| 问题 | 冻结答案 |
|---|---|
| Exit trigger 谁判断 | 2C；2B 只消费 ExitConditionSnapshot |
| Intent 是否含未来价格 | 否 |
| Plan 何时产生 | target 1m open 已到达且 watermark 可验证后 |
| 48h 从何时算 | EntryPlan target execution time；2C 实际 Fill 必须同一事件时刻，否则路径 INVALID/版本升级 |
| funding ×6/×7 | 均禁止写死；窗口枚举，Golden 可得到 7 |
| available balance 是否含 pending | 不含；pending_plan_reserve 单独减，避免重复扣 |
| open risk 是否含 pending | 分为 existing_open_risk 与 pending_plan_risk，公式显式相加 |
| 一个计划失败是否重新放大另一个 | 否 |
| APPROX 是否可生成 Plan | 仅独立 backtest/paper 且强制水印；Live Eligibility 禁止 |
| minNotional 参考价 | final expected entry fill |
| fee/reserve 是否量化到分 | V1 不量化，保留完整 Decimal |
| target minute 未到 | 等待，不生成 Rejection |
| watermark 已过但缺 target | EXPERIMENT_INVALID/TARGET_MINUTE_UNAVAILABLE |
| 多错误如何选 | 收集全部事实后用 2B_REJECTION_PRIORITY_V1 |
| Plan 是否修改账户 | 永不；只输出 required cash/risk |

当前未决设计问题数量：`0`。如人工审核不同意任何答案，必须在编码前一次性修改本文、矩阵、版本和追踪；不得在编码中临时决定。

## 17. 追踪与验收入口

- 需求/测试：`../reviews/second-batch-2b-acceptance-matrix.md`
- 非法状态：`../reviews/second-batch-2b-illegal-state-matrix.md`
- 时间边界：`../reviews/second-batch-2b-time-boundary-matrix.md`
- Golden Fixtures：`../reviews/second-batch-2b-golden-fixture-plan.md`
- 自我红队：`../reviews/second-batch-2b-red-team.md`
- 完整性审计：`../reviews/second-batch-2b-traceability-audit.md`

未经人工书面批准，不得创建上述未来生产文件或任何 2B 测试文件。
