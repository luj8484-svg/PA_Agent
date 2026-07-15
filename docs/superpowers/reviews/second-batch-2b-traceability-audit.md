# 2B 规格冻结完整性与追踪审计

日期：2026-07-15

审计基线：`fork/main@07004498a7091519a4fb08c323a1dde5b97ced6d`
结论：上一轮14项BLOCKER与本轮5项preflight均闭环；文档审计通过后获准直接按TDD实施2B。

## 1. 交付计数

| 项目 | 数量 | 权威文件 |
|---|---:|---|
| Requirement/主验收矩阵行 | 114 | `second-batch-2b-acceptance-matrix.md` |
| 主 Unit Test ID | 114 | 同上 |
| Property Test 映射 | 114行、109个唯一family | 同上 |
| Golden Fixture 映射 | 114行均有 | 同上 |
| 非法状态 | 53 | `second-batch-2b-illegal-state-matrix.md` |
| 时间边界案例 | 35 | `second-batch-2b-time-boundary-matrix.md` |
| Golden Fixture 计划 | 71 | `second-batch-2b-golden-fixture-plan.md` |
| 红队攻击场景 | 53 | `second-batch-2b-red-team.md` |
| MASTER_TEST_REGISTRY_V1 | 435个唯一Test ID | 五文档并集；GF Fixture ID排除 |
| 红队 BLOCKER | 累计25个发现、25个关闭、0个未关闭（本轮5/5关闭） | 同上 |
| 未决设计问题 | 0 | frozen spec 第16节 |

## 2. Requirement 分类

| Prefix | 数量 | 设计入口 | 测试入口 |
|---|---:|---|---|
| 2B-LIFE | 11 | Spec 6 | Acceptance A/K |
| 2B-SCHEMA | 20 | Spec 4–5 | Acceptance A/K/L |
| 2B-TIME | 15 | Spec 7/12 | Acceptance B/K/L、Time matrix |
| 2B-GAP | 4 | GAP-F01、Spec 10 | Acceptance C |
| 2B-COST | 7 | PRICE/COST formulas | Acceptance D/K |
| 2B-FUND | 9 | Spec 8 | Acceptance E/K |
| 2B-RULE | 9 | Spec 5.8/9 | Acceptance F/K |
| 2B-RISK | 12 | RISK/CASH formulas、Spec 5.14/5.15 | Acceptance G/K/L |
| 2B-QTY | 4 | QTY/MIN formulas | Acceptance G |
| 2B-PORT | 9 | SCALE formulas、CompletenessSnapshot | Acceptance H/K/L |
| 2B-ID | 8 | Spec 3/13.1 | Acceptance I/K/L |
| 2B-SCOPE | 6 | Spec 13.1/14 | Acceptance J/L |
| 合计 | 114 | 全覆盖 | 全覆盖 |

## 3. 需求→设计→测试链

每条 Requirement 行均包含：描述、不变量、唯一数据来源、合法/非法输入、预期输出、Failure/Rejection、边界、Unit Test、Property Test、Golden Fixture、未来实现文件和状态。追踪规则：

```text
Requirement ID
  -> frozen spec section / Formula ID / Schema field
  -> exactly named Unit Test ID
  -> Property Test family
  -> Golden Fixture ID
  -> planned implementation file
```

每个pytest case必须声明唯一`test_id`与非空`requirement_ids`。CI按`MASTER_TEST_REGISTRY_V1`收集五文档全部Unit/Supplemental/Property Test ID并与实现集合双向比较；Fixture `GF-*`不属于Test ID。非法状态、时间边界、Golden和红队测试作为主Requirement的补充验证，不创造孤儿语义。

### 3.1 MASTER_TEST_REGISTRY_V1 统计

| Registry分类/来源 | 唯一Test ID数 | 是否进入master set |
|---|---:|---:|
| Acceptance Unit `UT-*` | 114 | 是 |
| Acceptance Property `PT-*` | 109 | 是 |
| Illegal supplemental `UT-ILLEGAL-*` | 53 | 是 |
| Time supplemental `UT-TB-*` | 35 | 是 |
| Golden supplemental `UT-GF-*` | 71 | 是 |
| Red-team supplemental `UT-RT-*` | 53 | 是 |
| documented_master_test_id_set | 435 | 是，以上去重并集 |
| Fixture `GF-*` | 71 | 否；仅fixture identity |

实现校验器必须证明 `documented_master_test_id_set == implemented_test_id_set`，并对空测试目录、缺登记ID、孤儿ID、重复实现ID、空Requirement映射逐项fail closed。

## 4. 字段唯一来源审计

| 字段族 | 唯一真相源 | 被拒绝的第二来源 |
|---|---|---|
| Candidate side/time/ATR/close | 2A StrategyCandidate | 2B 重新计算趋势/方向 |
| Intent target | TIME-F01/F02 + delay config | 搜索下一个现存 bar、wall clock |
| Plan reference price/input hash | TargetMinuteOpenSnapshot.open_price/content hash；严格不含watermark/消费时间 | 完整Kline、mark/index/future HLCV、Watermark identity |
| Target arrival/missing evidence | 独立TargetEventWatermark及其watermark source event | open source event假设、Snapshot内嵌watermark |
| Contract tick/step/minimum | ContractRuleCoverage | 当前 exchangeInfo 静默回填 |
| Fee/slippage | CostModelSnapshot | account/API 动态查询 |
| Funding count | FundingScheduleSnapshot windows | 固定×6/×7 |
| Funding rate cap | FundingRiskConfigSnapshot | CostModel、未来funding记录 |
| Quantity | sizing→complete batch→scaling→AcceptedScalingItem | Plan自行缩量、minimum向上取整 |
| Account equity/valuation | AEB wallet+eligible mark-open valuation records；`equity=wallet+UPnL` | last-known/trade/close价、naked aggregate |
| Available balance | AEB ledger/lock records经AS派生公式 | 任意独立外部字段 |
| Pending cash/risk | AEB pending records逐项聚合 | 重复包含在 available/existing open risk、naked aggregate |
| Continuity/data validity | 上游已验证 inputs/watermark | 全局历史 bool |
| Batch completeness | PortfolioBatchCompletenessSnapshot expected全集+逐Intent唯一终态 | 第一次调用/BTC_FIRST/仅成功SizingResults |
| Object identity | 第3节正式ID/content hash payload | 外部 mutable/泛化 input hash |

## 5. 状态唯一来源审计

- Candidate 不因执行拒绝被改写。
- Intent、Plan、Rejection 均 immutable；不存在 `status` mutable 字段。
- Plan 是否接受由 final object 或 Rejection tagged output 表达，不在 Plan 内再保存 accepted bool。
- Contract mode 由 tagged union 表达，不用 nullable rule fields。
- Scaling item 由两个closed payload表达，各有独立ID/hash，完整payload进ScalingResult ID；不存在item_input_hash。
- Account snapshot 与AccountPlanningEvidenceBundle逐项重放一致；2B 不产生Ledger、估值或新账户状态。
- 计划性退出由 ExitConditionSnapshot提供；protective reason仅属于2C。
- HALTED只是Entry planning gate，不是Exit gate。
- 证据缺失是EXECUTION_PATH_INVALID，不是经济CANDIDATE_REJECTED。

## 6. 语义交叉一致性检查

| # | 交叉检查 | 结果 | 证明 |
|---:|---|---|---|
| 1 | Intent输入与生命周期输入一致 | PASS | EntryIntent Schema只引用Candidate/ExecutionTimeConfig/manifest；LIFE-007排除AS/HALTED/position |
| 2 | Plan生成顺序与quantity来源一致 | PASS | Spec 6的Sizing→Batch→Scaling→Accepted item→Plan；EP.quantity只来自item |
| 3 | Exit reason与执行时机一致 | PASS | Scheduled四枚举才使用future open；protective三枚举在2C分钟内处理 |
| 4 | Rejection subject与symbol/hash cardinality一致 | PASS | RejectionSubjectRef union；PortfolioBatchSubjectRef支持BTC+ETH tuple/多hash |
| 5 | content hash生产者/消费者字段一致 | PASS | Spec 3.4精确payload；Plan复制coverage/snapshot正式content hash字段 |
| 6 | normal rejection与invalid path不混淆 | PASS | Spec 11联合映射；证据缺失在Backtest为EXECUTION_PATH_INVALID |
| 7 | Account phase与事件顺序一致 | PASS | AS time=batch eligible；phase=post same-time funding/exits, pre-entry batch |
| 8 | reserve不低估冻结包络内现金需求 | PASS | PRICE-F10取entry/stop/TP max；fee与funding reserve共用该basis |
| 9 | APPROX不使用未来证据 | PASS | primary只PRIOR_ONLY，evidence≤query；HINDSIGHT隔离Paper/Live/OOS |
| 10 | 所有upstream interface有正式ID/hash | PASS | TargetOpen/Watermark/Completeness/Batch/AEB/Funding/Account/ExitCondition/ExecutionTime/Contract/Cost/items均在Spec 3.3/3.4 |
| 11 | OpenSnapshot身份与Watermark身份分离 | PASS | snapshot hash字段集不含watermark；Watermark使用独立source event；晚消费不改Plan ID |
| 12 | Batch expected全集与resolution全集一致 | PASS | CompletenessSnapshot要求逐expected Intent唯一终态；失败终态不得遗漏 |
| 13 | ScalingResult与Batch、AcceptedItem、Plan链一致 | PASS | Scaling保存batch ID/hash且input IDs等于batch成功投影；Plan逐级复制ID/hash |
| 14 | Account equity与风险聚合证据一致 | PASS | AEB携带wallet/valuation/position/open-risk/pending记录；AS全部aggregate可重放 |
| 15 | Master Registry与全部文档测试来源一致 | PASS | 114 Unit+109 Property+212 Supplemental=435唯一Test IDs；GF Fixture排除 |

### 6.1 本轮 14 项 BLOCKER 闭环追踪

| B | Requirement | Schema/Formula | Illegal | Time | Unit/Property | Golden | Red | Future file | Status |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | 2B-LIFE-003, 2B-LIFE-007, 2B-LIFE-010 | EntryIntent/Batch/AcceptedItem | IS-031 | TB-008/026/027 | UT-LIFE-003/007/010; PT-LIFE-ORDER | GF-LIFECYCLE-FINAL-PLAN | RT-33 | `domain/intents.py`,`planning/factory.py` | CLOSED |
| 2 | 2B-LIFE-004, 2B-LIFE-005, 2B-LIFE-008, 2B-LIFE-009 | ScheduledExitReason/ProtectiveExitReason2C | IS-032/033 | TB-010/011/013 | UT-LIFE-004/005/008/009; PT-HALTED-ASYMMETRY | GF-HALTED-EXIT/GF-PROTECTIVE-EXIT-SCOPE | RT-31/32 | `domain/intents.py`,`planning/factory.py` | CLOSED |
| 3 | 2B-SCHEMA-009, 2B-TIME-008, 2B-TIME-009 | TargetMinuteOpenSnapshot | IS-034 | TB-007–009/021/022 | UT-SCHEMA-009,UT-TIME-008/009; PT-OPEN-SNAPSHOT-CLOSED | GF-OPEN-ONLY-ID/GF-TARGET-PRECONDITION | RT-34 | `domain/market_inputs.py`,`planning/factory.py` | CLOSED |
| 4 | 2B-SCHEMA-010, 2B-TIME-010, 2B-TIME-011, 2B-PORT-001, 2B-PORT-007 | PortfolioPlanningBatch/PlanningPhase | IS-042 | TB-023–027 | UT-SCHEMA-010,UT-TIME-010/011; PT-BATCH-COMPLETE | GF-BATCH-COMPLETE/GF-PLANNING-PHASE | RT-42 | `domain/batches.py`,`domain/accounts.py` | CLOSED |
| 5 | 2B-SCHEMA-005, 2B-SCHEMA-011 | RejectionSubjectRef/subject×reason×stage | IS-035/045 | N/A（纯subject映射） | UT-SCHEMA-005/011; PT-SUBJECT-UNION | GF-BATCH-SUBJECT | RT-35/45 | `domain/rejections.py` | CLOSED |
| 6 | 2B-RISK-010,2B-RULE-004 | EXECUTION_PATH_INVALID/report categories | IS-036 | TB-009 | UT-RISK-010; PT-INVALID-NOT-PERFORMANCE | GF-PATH-INVALID | RT-36 | `planning/factory.py` | CLOSED |
| 7 | 2B-ID-001, 2B-ID-006, 2B-ID-007, 2B-RULE-007 | Spec 3.3/3.4 ID/hash payloads | IS-044 | N/A（content mutation） | UT-ID-006/007; PT-UPSTREAM-HASH-CLOSURE | GF-CONTENT-HASH-CLOSURE | RT-44 | `domain/canonical.py`,`domain/*` | CLOSED |
| 8 | 2B-SCHEMA-012, 2B-SCHEMA-013, 2B-PORT-006 | Accepted/RejectedScalingItem | IS-030 | N/A（nested schema） | UT-SCHEMA-012/013,UT-PORT-006; PT-NESTED-ITEM-ID | GF-NESTED-SCALING-ITEMS | RT-17 | `domain/scaling.py` | CLOSED |
| 9 | 2B-COST-004, 2B-COST-006, 2B-COST-007, 2B-RISK-001 | PRICE-F10,COST-F10,FUND-F12/F13,RISK-F13 | IS-037/038 | N/A（Decimal envelope） | UT-COST-006/007; PT-RESERVE-ENVELOPE | GF-RESERVE-BASIS | RT-37/38 | `planning/costs.py`,`planning/funding.py` | CLOSED |
| 10 | 2B-FUND-007, 2B-FUND-008, 2B-FUND-009, 2B-SCHEMA-014 | FundingRiskConfigSnapshot/FUND-F14 | IS-038 | target coverage见TB-028/029 | UT-FUND-007/008/009; PT-FUND-STRESS-MONOTONIC | GF-FUND-RISK-CONFIG | RT-38 | `domain/funding.py` | CLOSED |
| 11 | 2B-RULE-002, 2B-RULE-003, 2B-RULE-008, 2B-RULE-009, 2B-TIME-012 | Contract APPROX evidence/policy enums | IS-039 | TB-028/029 | UT-RULE-008/009,UT-TIME-012; PT-PRIOR-ONLY | GF-APPROX-DIRECTIONS | RT-39 | `domain/contracts.py` | CLOSED |
| 12 | 2B-RISK-005, 2B-RISK-006, 2B-RISK-007, 2B-RISK-008, 2B-RISK-009, 2B-RISK-010, 2B-SCHEMA-015 | Account evidence/RISK-F20/F21/CASH-F22 | IS-040/041 | TB-023–025 | UT-RISK-006–010; PT-ACCOUNT-EVIDENCE | GF-ACCOUNT-RISK-EVIDENCE/GF-RISK-INVARIANT | RT-40/41 | `domain/accounts.py`,`planning/portfolio.py` | CLOSED |
| 13 | 2B-LIFE-011 | ExitIntent quantity/target rule check | IS-043 | TB-030 | UT-LIFE-011; PT-EXIT-NO-REQUANTIZE | GF-EXIT-RULE-ROLLOVER | RT-43 | `planning/factory.py` | CLOSED |
| 14 | 2B-TIME-008, 2B-TIME-009, 2B-TIME-010, 2B-TIME-011, 2B-ID-006 | explicit inputs/config hashes/preconditions | IS-034/042 | TB-007–009/023–027 | UT-TIME-008–011,UT-ID-006; PT-CONFIG-HASH-CLOSURE | GF-TARGET-PRECONDITION/GF-BATCH-COMPLETE | RT-34/42 | `domain/config.py`,`planning/factory.py` | CLOSED |

### 6.2 本轮5项 implementation-preflight闭环追踪

| B | Requirement | Schema/Invariant | Illegal | Time | Unit/Property | Golden | Red | Future file | Status |
|---:|---|---|---|---|---|---|---|---|---|
| 21 | 2B-SCHEMA-016,2B-SCHEMA-017,2B-TIME-013 | OpenSnapshot/TargetEventWatermark身份分离 | IS-047 | TB-031/032/033 | UT-SCHEMA-016/017,UT-TIME-013; PT-SNAPSHOT-CONSUMPTION-INVARIANT | GF-SNAPSHOT-WATERMARK-INDEPENDENT/GF-WATERMARK-WITHOUT-OPEN | RT-47 | `domain/market_inputs.py` | CLOSED |
| 22 | 2B-SCHEMA-018,2B-PORT-008,2B-PORT-009,2B-TIME-014 | CompletenessSnapshot+Batch→Scaling binding | IS-048/049 | TB-034 | UT-SCHEMA-018,UT-PORT-008/009; PT-COMPLETENESS-UNIQUE-RESOLUTION | GF-COMPLETENESS-RESOLUTIONS/GF-BATCH-SCALING-BINDING | RT-48/49 | `domain/batches.py`,`planning/portfolio.py` | CLOSED |
| 23 | 2B-SCHEMA-019 | AcceptedScalingItem closed identity；无opaque hash | IS-050 | N/A | UT-SCHEMA-019; PT-NO-OPAQUE-ITEM-HASH | GF-SCALING-ITEM-SELF-PROVING | RT-50 | `domain/scaling.py` | CLOSED |
| 24 | 2B-SCHEMA-020,2B-RISK-011,2B-RISK-012,2B-TIME-015 | AccountPlanningEvidenceBundle+equity/aggregate replay | IS-051/052 | TB-035 | UT-SCHEMA-020,UT-RISK-011/012; PT-ACCOUNT-AGGREGATE-REPLAY | GF-ACCOUNT-EVIDENCE-REPLAY | RT-51/52 | `domain/accounts.py` | CLOSED |
| 25 | 2B-ID-008,2B-SCOPE-006 | MASTER_TEST_REGISTRY_V1五文档并集/双向集合 | IS-053 | N/A | UT-ID-008,UT-SCOPE-006; PT-MASTER-REGISTRY-BIJECTION | GF-MASTER-TEST-REGISTRY | RT-53 | `testing/registry.py`,`scripts/validate_2b_test_registry.py` | CLOSED |

### 6.3 正式对象 ID/hash 索引

| 正式对象/union payload | 正式身份/内容字段 |
|---|---|
| EntryIntent | `intent_id,intent_content_hash` |
| ExitIntent | `intent_id,intent_content_hash` |
| EntryExecutionPlan | `plan_id,plan_content_hash` |
| ExitExecutionPlan | `plan_id,plan_content_hash` |
| ExecutionRejection | `rejection_id,rejection_content_hash` |
| CandidateSubjectRef | `subject_id,subject_content_hash` |
| EntryIntentSubjectRef | `subject_id,subject_content_hash` |
| ExitIntentSubjectRef | `subject_id,subject_content_hash` |
| EntryPlanSubjectRef | `subject_id,subject_content_hash` |
| ExitPlanSubjectRef | `subject_id,subject_content_hash` |
| PortfolioBatchSubjectRef | `subject_id,subject_content_hash` |
| TargetMinuteOpenSnapshot | `snapshot_id,snapshot_content_hash` |
| TargetEventWatermark | `watermark_id,watermark_content_hash` |
| PortfolioBatchCompletenessSnapshot | `completeness_id,completeness_content_hash` |
| PortfolioPlanningBatch | `batch_id,batch_content_hash` |
| FundingScheduleSnapshot | `schedule_id,schedule_content_hash` |
| FundingRiskConfigSnapshot | `config_id,content_hash` |
| AccountPlanningSnapshot | `snapshot_id,snapshot_hash` |
| AccountPlanningEvidenceBundle | `bundle_id,bundle_content_hash` |
| ExitConditionSnapshot | `condition_event_id,condition_content_hash` |
| ExecutionTimeConfig | `config_id,config_content_hash` |
| ContractRuleCoverage | `coverage_id,coverage_content_hash` |
| CostModelSnapshot | `snapshot_id,snapshot_content_hash` |
| PositionSizingResult | `result_id,result_content_hash`；不保存泛化input_hash |
| PortfolioScalingResult | `result_id,result_content_hash`；不保存泛化input_hash |
| AcceptedScalingItem | `item_id,item_content_hash`；V1无任何item_input_hash |
| RejectedScalingItem | `item_id,item_content_hash` |

精确 hash payload在 frozen spec 3.4；生产者与Plan/Rejection消费者使用同名正式字段，禁止别名或外部泛化hash。

## 7. 提交前 13 项完整性检查

| # | 检查 | 结果 | 证据 |
|---:|---|---|---|
| 1 | 每个 Requirement 至少一个测试 | PASS | 114/114 行有 Unit Test ID |
| 2 | 每个测试至少一个 Requirement | PASS by design | 435个master Test ID均映射已有Requirement；未来pytest metadata强制验证 |
| 3 | 每个领域字段唯一来源 | PASS | Spec 5 + 本文第4节 |
| 4 | 每个状态只有一个真相源 | PASS | 本文第5节 |
| 5 | 每个时间字段来自事件时钟 | PASS | Spec 12 + Time matrix 来源表 |
| 6 | 每个公式有版本和舍入顺序 | PASS | Spec 7 共39个 Formula ID |
| 7 | 每个 ID/hash 列出全部输入字段 | PASS | Spec 3.3/3.4；泛化result input_hash已删除 |
| 8 | 每个失败组合有确定性优先级 | PASS | Spec 11 rank 1–22 + subject×reason×stage映射 |
| 9 | 每个 APPROX 结果有水印与方向 | PASS | Spec 5.8/9，2B-RULE-002/008/009 |
| 10 | 无2C/GUI/LLM/HTTP/交易越界 | PASS | Spec 1/14 + docs-only diff gate |
| 11 | 红队无未关闭 BLOCKER | PASS | 累计25/25 closed，本轮5/5，0 open |
| 12 | 未决问题集中且不留编码决定 | PASS | Spec 16，未决=0 |
| 13 | Master Test Registry完整且分类正确 | PASS | 114 Unit+109 Property+212 Supplemental=435；71个GF Fixture ID排除 |

## 8. 版本与公式关联

| Version | Formula/Schema |
|---|---|
| EXECUTION_TIME_CONFIG_V1 | TIME-F01/F02 |
| MAX_HOLD_V1_EXACT_48H | TIME-F03 |
| GAP_POLICY_V1 | GAP-F01 |
| SLIPPAGE_MODEL_V1 | COST-F02、PRICE-F04/F07/F08/F09 |
| PRICE_GEOMETRY_V1 | PRICE-F05/F06 + strict geometry |
| FEE_MODEL_V1 | COST-F01/F09/F10/F11 |
| RESERVE_PRICE_BASIS_V1 | PRICE-F10/FUND-F13 |
| FUNDING_BUFFER_MODEL_V2 | FUND-F11/F12 |
| FUNDING_RISK_CONFIG_V1 | FUND-F14 |
| POSITION_SIZING_MODEL_V2 | RISK-F13–19、QTY-F16、CASH-F19/F20 |
| ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1 | CASH-F01 |
| ACCOUNT_PLANNING_EVIDENCE_BUNDLE_SCHEMA_V1 | wallet/valuation/position/open-risk/pending逐项证据 |
| ACCOUNT_EQUITY_MODEL_V1 | `current_equity=wallet_balance+unrealized_pnl` |
| MARK_PRICE_OPEN_AT_ELIGIBLE_TIME_V1 | eligible时刻mark-price open估值 |
| PORTFOLIO_BATCH_COMPLETENESS_SNAPSHOT_SCHEMA_V1 | expected intents与resolution双射 |
| PORTFOLIO_BATCH_COMPLETENESS_POLICY_V1 | completion event与排序/终态规则 |
| PORTFOLIO_SCALING_MODEL_V2 | RISK-F20/F21/F22、CASH-F22/F23、SCALE-F23/F24 |
| CONTRACT_MINIMUM_V1 | MIN-F25 |
| LEVERAGE_POLICY_V1_FIXED_1X | LEV-F26 |
| 2B_REJECTION_PRIORITY_V2 | Spec 11 rank matrix |
| 2B_REJECTION_SUBJECT_DISPOSITION_V1 | Spec 11联合映射 |
| 2B_CANONICAL_VERSION_V1 | 所有正式对象 ID/bytes |
| MASTER_TEST_REGISTRY_V1 | 五文档Test ID并集与pytest metadata双向集合 |

## 9. 范围审计规则

本设计分支允许路径只有：

```text
docs/superpowers/specs/second-batch-2b-frozen-spec.md
docs/superpowers/reviews/second-batch-2b-*.md
```

禁止修改 `pa_agent/`、`tests/`、`scripts/`、配置或依赖。提交前运行：

```text
git diff --name-only fork/main...HEAD
git diff --check
```

另行执行中英文占位符与模糊措辞扫描；当前规范公式中不使用近似语言。

## 10. 实施转场

本轮文档审计必须先证明：Snapshot hash不含watermark、Completeness为正式ID/hash对象、expected intents与resolution双射、Scaling绑定Batch、AcceptedItem无opaque hash、AEB可重放全部账户聚合、Master Registry覆盖五文档Test ID、design branch仅修改7份docs。

审计通过后提交design commit，合并并推送`fork/main`，再从更新后的fork main创建`feature/second-batch-2b-execution-planning`。先提交完整实施计划，随后按10个Task逐项RED→GREEN→REFACTOR→commit；不再等待纯文档批准，不得开始2C。
