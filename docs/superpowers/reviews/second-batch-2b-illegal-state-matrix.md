# 2B 非法状态矩阵

状态：preflight闭环后获准TDD实施。非法状态总数：`53`。所有条目都必须在对象边界或纯工厂 fail closed；不得靠 2C 修补。

| Illegal ID | 非法状态/构造方式 | 被破坏的不变量 | 唯一预期结果 | Disposition | Requirement ID | Test ID |
|---|---|---|---|---|---|---|
| IS-001 | LONG Candidate 构造 SHORT EI/EP | side 只来自 Candidate | DATA_INVALID | EXPERIMENT_INVALID | 2B-LIFE-001 | UT-ILLEGAL-001 |
| IS-002 | EI 无 candidate_id 或引用不存在 Candidate | Intent 必须有合法上游 | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-001 | UT-ILLEGAL-002 |
| IS-003 | EP 同时包含 ExitReason/position_id | Entry/Exit Schema 分离 | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-002 | UT-ILLEGAL-003 |
| IS-004 | XP 包含 stop/TP/unit_risk/margin/reserve | Exit Schema 不复制 Entry 字段 | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-004 | UT-ILLEGAL-004 |
| IS-005 | target minute 早于/等于 Candidate decision | Entry target 必须在下一4H open或之后 | DATA_INVALID | EXPERIMENT_INVALID | 2B-TIME-001 | UT-ILLEGAL-005 |
| IS-006 | XI target 不严格晚于 condition time | Exit future-open 语义 | DATA_INVALID | EXPERIMENT_INVALID | 2B-TIME-003 | UT-ILLEGAL-006 |
| IS-007 | 使用 `datetime.now()` 填 created time | event clock 唯一 | DATA_INVALID/Scope guard fail | EXPERIMENT_INVALID | 2B-TIME-007 | UT-ILLEGAL-007 |
| IS-008 | 两个不同 payload 人工写同 plan_id | ID 必须内容匹配 | 构造 ValueError；工厂映射 DATA_INVALID | EXPERIMENT_INVALID | 2B-ID-001 | UT-ILLEGAL-008 |
| IS-009 | 修改未来 1m 数据导致历史 EI 改变 | Intent 只含 decision-visible 输入 | DATA_INVALID | EXPERIMENT_INVALID | 2B-LIFE-002 | UT-ILLEGAL-009 |
| IS-010 | 修改 plan target 之后数据导致历史 EP 改变 | Plan 只含 target 可见输入 | DATA_INVALID | EXPERIMENT_INVALID | 2B-ID-003 | UT-ILLEGAL-010 |
| IS-011 | contract rule `target==effective_to` 仍接受 | `[from,to)` | CONTRACT_RULE_EXPIRED | PLAN_CANCELLED | 2B-TIME-005 | UT-ILLEGAL-011 |
| IS-012 | contract rule tick/step≤0 或 hash 错 | coverage 自验证 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RULE-005 | UT-ILLEGAL-012 |
| IS-013 | 负/零价格、负费率、负数量 | 所有 Decimal 有限且领域合法 | DATA_INVALID | EXPERIMENT_INVALID | 2B-COST-004 | UT-ILLEGAL-013 |
| IS-014 | Decimal NaN/Infinity/sNaN | Canonical/经济值有限 | DATA_INVALID | EXPERIMENT_INVALID | 2B-ID-002 | UT-ILLEGAL-014 |
| IS-015 | LONG stop≥entry 或 TP≤entry | LONG strict geometry | PRICE_GEOMETRY_INVALID | CANDIDATE_REJECTED | 2B-COST-005 | UT-ILLEGAL-015 |
| IS-016 | SHORT TP≥entry 或 stop≤entry | SHORT strict geometry | PRICE_GEOMETRY_INVALID | CANDIDATE_REJECTED | 2B-COST-005 | UT-ILLEGAL-016 |
| IS-017 | tick 量化后 stop==entry 或 TP==entry | 量化后仍 strict geometry | PRICE_GEOMETRY_INVALID | CANDIDATE_REJECTED | 2B-COST-005 | UT-ILLEGAL-017 |
| IS-018 | final quantity×unit_risk 超0.5% | floor后不应超限 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RISK-004 | UT-ILLEGAL-018 |
| IS-019 | final batch risk 加既有风险超1% | scale后不应超限 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RISK-005 | UT-ILLEGAL-019 |
| IS-020 | quantity=0 却返回 BELOW_MIN_QTY | zero reason 优先 | QUANTITY_ROUNDED_TO_ZERO | CANDIDATE_REJECTED | 2B-QTY-002 | UT-ILLEGAL-020 |
| IS-021 | quantity>0 但低于 minQty 被接受 | minimum equality规则 | BELOW_MIN_QTY | CANDIDATE_REJECTED | 2B-QTY-003 | UT-ILLEGAL-021 |
| IS-022 | notional 低于 minNotional 被接受 | final fill minimum | BELOW_MIN_NOTIONAL | CANDIDATE_REJECTED | 2B-QTY-004 | UT-ILLEGAL-022 |
| IS-023 | BTC/ETH 各用全部 available balance | 同刻共享 snapshot+scale | INSUFFICIENT_AVAILABLE_BALANCE 或 deterministic scale | CANDIDATE_REJECTED | 2B-PORT-001 | UT-ILLEGAL-023 |
| IS-024 | wallet 与 isolated view 各扣一次 funding | 单一 wallet 经济账 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RISK-006 | UT-ILLEGAL-024 |
| IS-025 | required_cash 中 fee/funding reserve 重复加 | 每项一次 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RISK-001 | UT-ILLEGAL-025 |
| IS-026 | funding buffer 固定×6 或覆盖不足仍计算 | schedule window枚举 | FUNDING_SCHEDULE_UNVERIFIED | EXECUTION_PATH_INVALID | 2B-FUND-005 | UT-ILLEGAL-026 |
| IS-027 | APPROXIMATED Plan 进入 Live Eligibility | APPROX 永不 live eligible | DATA_INVALID | EXPERIMENT_INVALID | 2B-RULE-003 | UT-ILLEGAL-027 |
| IS-028 | 正式 EI/EP/ER 允许空 ID | final object ID 强校验 | 构造 ValueError；工厂 DATA_INVALID | EXPERIMENT_INVALID | 2B-ID-001 | UT-ILLEGAL-028 |
| IS-029 | Plan 字段变化但 Canonical ID 不变 | 所有字段进入 ID | 构造 ValueError | EXPERIMENT_INVALID | 2B-ID-001 | UT-ILLEGAL-029 |
| IS-030 | ETH 缩量后拒绝，BTC 被二次放大 | 不再分配 | 保持原 BTC quantity；若放大则 DATA_INVALID | EXPERIMENT_INVALID | 2B-PORT-004 | UT-ILLEGAL-030 |
| IS-031 | 在EntryIntent前读HALTED/AS导致同Candidate不同ID | Intent输入边界 | DATA_INVALID | EXPERIMENT_INVALID | 2B-LIFE-007 | UT-ILLEGAL-031 |
| IS-032 | STOP/TP/liquidation被转成下一分钟ExitPlan | protective path必须在2C | DATA_INVALID/Scope failure | EXPERIMENT_INVALID | 2B-LIFE-009 | UT-ILLEGAL-032 |
| IS-033 | HALTED阻止HALT_EXIT | HALTED仅禁新Entry | DATA_INVALID | EXPERIMENT_INVALID | 2B-LIFE-008 | UT-ILLEGAL-033 |
| IS-034 | TargetMinuteOpenSnapshot含HLCV/close metadata | open-visible closed Schema | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-009 | UT-ILLEGAL-034 |
| IS-035 | batch rejection被强制为单symbol/hash | subject cardinality | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-011 | UT-ILLEGAL-035 |
| IS-036 | 历史contract/cost/funding/account缺失被当普通拒绝 | selection bias禁止 | EXECUTION_PATH_INVALID | EXECUTION_PATH_INVALID | 2B-RISK-010 | UT-ILLEGAL-036 |
| IS-037 | exit fee reserve只用LONG stop低价 | envelope现金需求 | DATA_INVALID | EXPERIMENT_INVALID | 2B-COST-006 | UT-ILLEGAL-037 |
| IS-038 | funding reserve固定entry notional | funding basis必须用envelope | DATA_INVALID | EXPERIMENT_INVALID | 2B-COST-007 | UT-ILLEGAL-038 |
| IS-039 | 使用未来contract evidence作primary APPROX | no lookahead | DATA_INVALID | EXPERIMENT_INVALID | 2B-RULE-008 | UT-ILLEGAL-039 |
| IS-040 | pending reserve>available被max(0)吞掉 | 非法AS不得降级 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RISK-007 | UT-ILLEGAL-040 |
| IS-041 | base risk≥1%最终返回quantity zero | 明确risk cap reason | TOTAL_RISK_ALREADY_AT_LIMIT | CANDIDATE_REJECTED | 2B-RISK-008 | UT-ILLEGAL-041 |
| IS-042 | 无正式CompletenessSnapshot时只scale BTC | 同target batch完整 | BATCH_INCOMPLETE | EXECUTION_PATH_INVALID | 2B-PORT-007 | UT-ILLEGAL-042 |
| IS-043 | ExitIntent提前用target step量化position | target rule尚未知 | DATA_INVALID | EXPERIMENT_INVALID | 2B-LIFE-011 | UT-ILLEGAL-043 |
| IS-044 | Contract/Cost字段变但content hash不变 | hash内容闭包 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RULE-007 | UT-ILLEGAL-044 |
| IS-045 | 同reason在Entry/Exit subject上强制相同Disposition | 联合映射 | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-011 | UT-ILLEGAL-045 |
| IS-046 | 非法Candidate Schema/ID/hash/MarketView被返CANDIDATE_NOT_ACTIONABLE | 该reason仅合法NO_SETUP | DATA_INVALID | EXPERIMENT_INVALID | 2B-LIFE-001 | UT-ILLEGAL-046 |
| IS-047 | 同open event因合法watermark/消费时间不同产生不同Snapshot或Plan ID | Snapshot身份只含open事实 | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-016 | UT-ILLEGAL-047 |
| IS-048 | Completeness只列BTC并遗漏同target ETH Intent | expected与resolution必须双射 | DATA_INVALID | EXPERIMENT_INVALID | 2B-PORT-008 | UT-ILLEGAL-048 |
| IS-049 | ScalingResult引用另一个Batch或input IDs不等于batch成功投影 | Scaling唯一绑定Batch | DATA_INVALID | EXPERIMENT_INVALID | 2B-PORT-009 | UT-ILLEGAL-049 |
| IS-050 | AcceptedScalingItem包含不可由closed字段重算的item_input_hash | 禁止opaque第二真相源 | DATA_INVALID | EXPERIMENT_INVALID | 2B-SCHEMA-019 | UT-ILLEGAL-050 |
| IS-051 | current_equity改变但wallet/UPnL/valuation evidence不变 | equity必须可重放 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RISK-011 | UT-ILLEGAL-051 |
| IS-052 | open-risk或pending aggregate改变但记录集合/hash不变 | 聚合必须逐记录重算 | DATA_INVALID | EXPERIMENT_INVALID | 2B-RISK-012 | UT-ILLEGAL-052 |
| IS-053 | Registry只读取acceptance导致Supplemental被判孤儿或文档ID遗漏 | master set必须取五文档并集 | DATA_INVALID | EXPERIMENT_INVALID | 2B-ID-008,2B-SCOPE-006 | UT-ILLEGAL-053 |

## 组合非法状态的优先级

若一个 payload 同时命中多个非法状态，必须先收集全部 evidence，再按 `2B_REJECTION_PRIORITY_V2` 选择唯一 reason，并按subject×reason×stage映射 disposition/retry。例如：

- 非有限价格 + contract unavailable + gap：`DATA_INVALID`；
- HALTED + existing position + gap：`EXPERIMENT_HALTED`；
- contract expired + cost missing：`CONTRACT_RULE_EXPIRED`；
- quantity=0 + below minQty + below minNotional：`QUANTITY_ROUNDED_TO_ZERO`；
- base risk已达上限 + cash不足：`TOTAL_RISK_ALREADY_AT_LIMIT`；final公式后超限则`DATA_INVALID`；
- APPROX live gate + otherwise valid plan：`DATA_INVALID`。

校验器输入顺序、dict 顺序、BTC_FIRST/ETH_FIRST 和异常抛出先后不得改变 reason、evidence Canonical bytes 或 rejection_id。
