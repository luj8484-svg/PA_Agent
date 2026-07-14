# 2B 时间边界矩阵

状态：规格冻结候审。时间边界案例数：`30`。所有时间均为 UTC 整数毫秒，来源只能是市场/实验事件或冻结公式。

| Case ID | 场景 | 输入边界 | 预期 Intent/Plan 时间 | 预期失败 | Requirement | Test ID |
|---|---|---|---|---|---|---|
| TB-001 | Candidate decision close | `03:59:59.999` | anchor=`04:00:00.000` | 无 | 2B-TIME-001 | UT-TB-001 |
| TB-002 | decision 非 4H close | `03:59:59.998` | 无 | DATA_INVALID | 2B-TIME-001 | UT-TB-002 |
| TB-003 | Entry delay 0 | anchor `04:00` | target `04:00` | 无 | 2B-TIME-002 | UT-TB-003 |
| TB-004 | Entry delay 1 | anchor `04:00` | target `04:01` | 无 | 2B-TIME-002 | UT-TB-004 |
| TB-005 | Entry delay 2 | anchor `04:00` | target `04:02` | 无 | 2B-TIME-002 | UT-TB-005 |
| TB-006 | delay 非法 | -1 或 3 | 无 | DATA_INVALID | 2B-TIME-002 | UT-TB-006 |
| TB-007 | target open 未到却调factory | event `<target` | 无领域对象 | precondition error | 2B-TIME-008 | UT-TB-007 |
| TB-008 | target 正好到达 | event=`target` 且 1m open 可见 | plan_created=`target` | 无 | 2B-LIFE-003 | UT-TB-008 |
| TB-009 | watermark 越过但 target open Snapshot 缺失 | watermark≥target证明时刻 | 无 EP | TARGET_MINUTE_UNAVAILABLE/EXECUTION_PATH_INVALID | 2B-TIME-009 | UT-TB-009 |
| TB-010 | Exit condition 在 minute 内 | `04:00:30.000` | anchor `04:01:00.000` | 无 | 2B-TIME-003 | UT-TB-010 |
| TB-011 | Exit condition 正好 minute open | `04:00:00.000` | anchor `04:01:00.000` | 无 | 2B-TIME-003 | UT-TB-011 |
| TB-012 | XI 创建时未来 open 被注入 | condition 时传 `04:01` price | XI 不得构造 | DATA_INVALID | 2B-SCHEMA-003 | UT-TB-012 |
| TB-013 | XP 提前构造 | event `<target` | 无领域对象 | precondition error | 2B-TIME-008 | UT-TB-013 |
| TB-014 | 48h 精确终点 | entry target +172800000 | maximum exit 精确该值 | 无 | 2B-TIME-004 | UT-TB-014 |
| TB-015 | funding 与 maximum exit 同刻 | window含 endpoint | count 包含该次；未来先 funding 后 exit | 无 | 2B-FUND-003 | UT-TB-015 |
| TB-016 | contract rule 起点 | target=`effective_from` | coverage 接受 | 无 | 2B-TIME-005 | UT-TB-016 |
| TB-017 | contract rule 终点 | target=`effective_to` | 无 Plan | CONTRACT_RULE_EXPIRED | 2B-TIME-005 | UT-TB-017 |
| TB-018 | BTC/ETH 同刻 Candidate | 相同 target、不同输入顺序 | 一个 batch、同一 AS | 无 | 2B-PORT-001 | UT-TB-018 |
| TB-019 | 跨日/月/年 | anchor/target 越 UTC 边界 | 纯整数正确 rollover | 无 | 2B-TIME-001 | UT-TB-019 |
| TB-020 | 跨 split | decision 在 train、target 在 validation/越 execution range | 标签不改 ID；越 manifest range 则 DATA_INVALID | DATA_INVALID only if range violated | 2B-TIME-006 | UT-TB-020 |
| TB-021 | open相同但后续HLCV不同 | target open事件相同 | 同Snapshot/Plan ID | 无 | 2B-SCHEMA-009 | UT-TB-021 |
| TB-022 | open price改变 | 同target/source，open+1tick | Plan ID必须改变 | 无 | 2B-SCHEMA-009 | UT-TB-022 |
| TB-023 | AS时间早于batch | `AS.event=batch-1ms` | 无batch/Plan | DATA_INVALID | 2B-TIME-010 | UT-TB-023 |
| TB-024 | AS正好同target phase | event=eligible，phase正确 | 可规划 | 无 | 2B-TIME-010 | UT-TB-024 |
| TB-025 | 同刻funding/exit未反映 | phase为pre-settlement | 无batch/Plan | DATA_INVALID | 2B-TIME-010 | UT-TB-025 |
| TB-026 | completeness watermark前另有ETH Intent未收集 | 只batch BTC | 无Scaling | BATCH_INCOMPLETE | 2B-TIME-011 | UT-TB-026 |
| TB-027 | completeness watermark到达 | BTC+ETH全收集 | 单一batch/scaling | 无 | 2B-TIME-011 | UT-TB-027 |
| TB-028 | APPROX evidence正好等于query | evidence=query | PRIOR_ONLY接受 | 无 | 2B-TIME-012 | UT-TB-028 |
| TB-029 | APPROX evidence晚1ms | evidence=query+1 | 仅HINDSIGHT diagnostic | primary DATA_INVALID | 2B-TIME-012 | UT-TB-029 |
| TB-030 | Exit rule rollover target | XI创建后rule step改变 | target时验证，不改qty | POSITION_QUANTITY_RULE_MISMATCH | 2B-LIFE-011 | UT-TB-030 |

## 事件时钟来源表

| 字段 | 唯一允许来源 | 禁止来源 |
|---|---|---|
| candidate_decision_time | 2A Candidate 已收盘 4H close | system time |
| intent_created_time | 等于 Candidate decision 或 ExitCondition event | constructor call time |
| execution_anchor | TIME-F01/TIME-F02 | 搜索“下一个可用 bar” |
| target_execution_time | anchor + versioned delay | sleep/loop time |
| plan_created_time | target 1m market event，必须等于 target | process timestamp |
| maximum_exit_time | target + exact 48h | 第 12 根 4H close |
| contract effective bounds | versioned archive | current exchangeInfo download time |
| funding windows | schedule snapshot | 当前 wall clock 或硬编码次数 |
| target open snapshot time/watermark | target open market event/event-engine watermark | Kline close/system time |
| batch completeness watermark | event engine证明同target Intent集合完整 | 首次factory调用时间 |
| account snapshot time | 上游 Ledger/实验事件，等于batch eligible time | snapshot 下载/序列化时间 |

未来 forward orchestration 可在factory之外等待target event；factory本身不提供`None`或持久化等待结果。只有数据 watermark已证明target Snapshot应存在但缺失时才生成 `TARGET_MINUTE_UNAVAILABLE`。
