# 2B 需求追踪与验收矩阵

状态：规格冻结候审；所有测试和实现路径均为计划，不代表已编码。
Requirement 总数：`100`。每个 Requirement 至少对应一个唯一 Unit Test ID；Property 和 Golden 列给出独立覆盖或明确共享覆盖。测试命名冻结，编码时不得出现没有 Requirement ID 的测试。

缩写：`EI` EntryIntent，`EP` EntryExecutionPlan，`XI` ExitIntent，`XP` ExitExecutionPlan，`ER` ExecutionRejection，`CR` ContractRuleCoverage，`AS` AccountPlanningSnapshot。

## A. 生命周期与 Schema（14）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-LIFE-001 | Candidate产生EI或合法NO_SETUP rejection | CANDIDATE_NOT_ACTIONABLE仅表示NO_SETUP | 2A Candidate | 合法LONG/SHORT/NO_SETUP | Schema/ID/hash/方向/MarketView非法 | EI/ER | NO_SETUP→CANDIDATE_NOT_ACTIONABLE；其他→DATA_INVALID | 三种market view | UT-LIFE-001 | PT-LIFE-SIDE | GF-CANDIDATE-NOSETUP | `domain/intents.py` | PLANNED |
| 2B-LIFE-002 | Candidate→EI 不读未来数据 | EI 无价格/contract/account | Candidate+time config | decision 已到 | 未来 1m 注入 | 同 Canonical EI | DATA_INVALID | 修改 future bars | UT-LIFE-002 | PT-FUTURE-INTENT | GF-FUTURE-INTENT | `planning/factory.py` | PLANNED |
| 2B-LIFE-003 | EI→Sizing→Batch→Scaling→EP | EP quantity仅来自AcceptedScalingItem | open Snapshot+planning evidence | 全链已完成 | 先EP后scale | final EP | DATA_INVALID | 一/两symbol | UT-LIFE-003 | PT-LIFE-ORDER | GF-LIFECYCLE-FINAL-PLAN | `planning/factory.py` | PLANNED |
| 2B-LIFE-004 | Scheduled ExitCondition→XI | 仅四种scheduled reason | condition+position | TIME/TREND/HALT/END | STOP/TP/LIQ | XI | DATA_INVALID/Scope | HALTED+HALT_EXIT | UT-LIFE-004 | PT-XI-SCHEDULED-ONLY | GF-HALTED-EXIT | `domain/intents.py` | PLANNED |
| 2B-LIFE-005 | XI→XP 只在future target Snapshot到达 | target>condition，HALTED不阻止 | XI+open Snapshot | position未变 | position hash变 | XP | POSITION_SNAPSHOT_CHANGED/PLAN_CANCELLED | HALT_EXIT | UT-LIFE-005 | PT-XP-HALTED-ALLOWED | GF-HALTED-EXIT | `planning/factory.py` | PLANNED |
| 2B-LIFE-006 | Plan 不产生 Fill/账户 mutation | 输入快照逐字节不变 | immutable inputs | 任意合法 plan | mutation attempt | final Plan | DATA_INVALID | 重复调用 | UT-LIFE-006 | PT-PURITY | GF-PURITY | `planning/factory.py` | PLANNED |
| 2B-SCHEMA-001 | EI 完整且无 EP 字段 | 无 nullable 联合 | Candidate | 完整 EI payload | entry_price/quantity | EI | DATA_INVALID | unknown field | UT-SCHEMA-001 | PT-SCHEMA-CLOSED | GF-BTC-LONG | `domain/intents.py` | PLANNED |
| 2B-SCHEMA-002 | EP 完整且只有 Entry 字段 | Entry/Exit 分离 | final planning payload | 全字段 | scheduled_exit_reason/position_id | EP | DATA_INVALID | missing reserve | UT-SCHEMA-002 | PT-SCHEMA-CLOSED | GF-BTC-LONG | `domain/plans.py` | PLANNED |
| 2B-SCHEMA-003 | XI 不含未来 price | future open 未知 | condition+position | 无 price | reference_price | XI | DATA_INVALID | target 配置变化 | UT-SCHEMA-003 | PT-XI-NO-PRICE | GF-XI-FUTURE | `domain/intents.py` | PLANNED |
| 2B-SCHEMA-004 | XP 不含 Entry 风险字段 | XP 只描述全退计划 | XI+target+cost | exit fields | stop/TP/margin/reserve | XP | DATA_INVALID | all forbidden fields | UT-SCHEMA-004 | PT-SCHEMA-CLOSED | GF-XP-NORMAL | `domain/plans.py` | PLANNED |
| 2B-SCHEMA-005 | ER subject 使用tagged union | 每种subject自有symbols/origins/hashes | failure facts | matching payload | 强制单symbol/hash | ER | DATA_INVALID | BTC+ETH batch | UT-SCHEMA-005 | PT-REJECTION-SUBJECT-CARDINALITY | GF-BATCH-SUBJECT | `domain/rejections.py` | PLANNED |
| 2B-SCHEMA-006 | CR 三模式为 tagged union | UNAVAILABLE 无 rule values | rule archive | mode 对应 payload | mode/字段错配 | CR/ER | DATA_INVALID | 三模式 | UT-SCHEMA-006 | PT-CONTRACT-UNION | GF-RULE-MODES | `domain/contracts.py` | PLANNED |
| 2B-SCHEMA-007 | Sizing success 与 rejection 分离 | 无 nullable quantity | pure sizing | valid result | quantity=None | result/ER | 对应 risk/qty reason | raw qty 0 | UT-SCHEMA-007 | PT-NO-NULL-RESULT | GF-QTY-ZERO | `planning/sizing.py` | PLANNED |
| 2B-SCHEMA-008 | Scaling item 为 accepted/rejected union | 每 item 仅一分支 | sizing set | accepted 或 rejected | 两者同时/均无 | scaling result | DATA_INVALID | ETH rejected | UT-SCHEMA-008 | PT-SCALING-UNION | GF-SCALE-NO-REDIST | `planning/portfolio.py` | PLANNED |

## B. 时间与未来数据（7）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-TIME-001 | 下一 4H anchor | anchor=decision+1 且 4H 对齐 | Candidate time | 对齐 close | 非对齐 | anchor | DATA_INVALID | 日/月边界 | UT-TIME-001 | PT-TIME-ALIGN | GF-TIME-ANCHOR | `planning/time.py` | PLANNED |
| 2B-TIME-002 | Entry delay 0/1/2 | target=anchor+d×1m | config | d∈{0,1,2} | -1/3 | EI | DATA_INVALID | 三个 exact target | UT-TIME-002 | PT-DELAY-DOMAIN | GF-DELAY-012 | `planning/time.py` | PLANNED |
| 2B-TIME-003 | Exit target 严格未来 | next minute open+delay | condition time | 任意 ms | target≤condition | XI | DATA_INVALID | condition 正好 minute open | UT-TIME-003 | PT-XTARGET-FUTURE | GF-XI-FUTURE | `planning/time.py` | PLANNED |
| 2B-TIME-004 | 最大持有 48h | target+172800000 | EI target | 非负 target | 12 bars 语义 | max exit | DATA_INVALID | month/year rollover | UT-TIME-004 | PT-EXACT-48H | GF-FUND-7 | `planning/time.py` | PLANNED |
| 2B-TIME-005 | contract `[from,to)` | target>=from且<to | CR | from、to-1ms | to | coverage/ER | CONTRACT_RULE_EXPIRED | 两端点 | UT-TIME-005 | PT-HALF-OPEN | GF-RULE-EXPIRY | `domain/contracts.py` | PLANNED |
| 2B-TIME-006 | split 不改变对象身份 | split label 排除 ID | experiment manifest | 同数据不同 label | target 越执行区间 | 同 ID/ER | DATA_INVALID | train→validation | UT-TIME-006 | PT-SPLIT-INVARIANT | GF-SPLIT | `planning/factory.py` | PLANNED |
| 2B-TIME-007 | wall clock 永不进入领域 | event time 唯一 | market/experiment events | wall clock 改变 | datetime.now 输入 | 同 bytes/拒绝 | DATA_INVALID | 两台机器时间 | UT-TIME-007 | PT-WALL-CLOCK | GF-WALL-CLOCK | `domain/*` | PLANNED |

## C. Gap 与价格（4）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-GAP-001 | LONG adverse gap 方向 | gap=P0-close | Candidate+TargetMinuteOpenSnapshot | gap≤0.5ATR | gap>0.5ATR | continue/ER | GAP_TOO_LARGE | 前/等/后 | UT-GAP-001 | PT-GAP-LONG-MONOTONIC | GF-GAP-LONG-3 | `planning/prices.py` | PLANNED |
| 2B-GAP-002 | SHORT adverse gap 方向 | gap=close-P0 | Candidate+TargetMinuteOpenSnapshot | gap≤0.5ATR | gap>0.5ATR | continue/ER | GAP_TOO_LARGE | 前/等/后 | UT-GAP-002 | PT-GAP-SHORT-MONOTONIC | GF-GAP-SHORT-3 | `planning/prices.py` | PLANNED |
| 2B-GAP-003 | gap 等于阈值接受 | 比较严格 `>` | Decimal | exact equality | `>=` 实现 | continue | 无 | 0.5ATR exact | UT-GAP-003 | PT-GAP-EQUALITY | GF-GAP-EQUAL | `planning/prices.py` | PLANNED |
| 2B-GAP-004 | gap 在滑点前计算 | P0 不含 s | open Snapshot+Candidate | raw P0 | fill 作为 P0 | deterministic gap | DATA_INVALID | s 压力变化 | UT-GAP-004 | PT-GAP-COST-INDEPENDENT | GF-GAP-PRE-SLIP | `planning/prices.py` | PLANNED |

## D. 成本与价格几何（5）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-COST-001 | LONG/SHORT entry 滑点一次 | fill 只含一次 s | P0+cost+tick | s≥0 | 二次乘 s | entry fill | DATA_INVALID | s=0 | UT-COST-001 | PT-SLIP-DIRECTION | GF-BTC-LONG/GF-ETH-SHORT | `planning/prices.py` | PLANNED |
| 2B-COST-002 | stop/TP 定向 tick | 几何公式固定 | entry+ATR+tick | 正 ATR | 反向 round | prices | PRICE_GEOMETRY_INVALID | 一 tick ATR | UT-COST-002 | PT-TICK-DIRECTION | GF-TICK-STEP | `planning/prices.py` | PLANNED |
| 2B-COST-003 | stop/TP expected fill 只含退出滑点一次 | trigger→fill 一次 | trigger+cost | valid | 重复扣滑点 | estimates | DATA_INVALID | s=0/pressure | UT-COST-003 | PT-NO-DOUBLE-SLIP | GF-COST-ONCE | `planning/prices.py` | PLANNED |
| 2B-COST-004 | fee精确，exit reserve用价格包络max | q×basis×effective f | cost+prices | ≥0 | stop-only reserve | fee/reserve | DATA_INVALID | LONG TP最高 | UT-COST-004 | PT-RESERVE-ENVELOPE | GF-RESERVE-BASIS | `domain/costs.py` | PLANNED |
| 2B-COST-005 | 合法价格几何 | LONG stop<entry<TP；SHORT 反向 | all prices | strict order | equality/reverse | plan/ER | PRICE_GEOMETRY_INVALID | tick 后重合 | UT-COST-005 | PT-GEOMETRY | GF-GEOMETRY-INVALID | `planning/prices.py` | PLANNED |

## E. 资金费缓冲（6）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-FUND-001 | 计数使用 `(entry,maxExit]` | 开入闭出 | schedule windows | full coverage | endpoint 写反 | count | DATA_INVALID | 两端点 | UT-FUND-001 | PT-FUND-INTERVAL | GF-FUND-ENDPOINTS | `planning/funding.py` | PLANNED |
| 2B-FUND-002 | entry 刚前/后结算 | window_end>entry 才计 | schedule | ±1ms | nominal 硬比较 | count | DATA_INVALID | 前后 | UT-FUND-002 | PT-FUND-ENTRY-MONOTONIC | GF-FUND-BEFORE-AFTER | `planning/funding.py` | PLANNED |
| 2B-FUND-003 | exit 同刻先 funding | endpoint event 计入 | schedule+maxExit | event==exit | 排除终点 | count | DATA_INVALID | 48h endpoint | UT-FUND-003 | PT-FUND-END-INCLUSIVE | GF-FUND-ENDPOINTS | `planning/funding.py` | PLANNED |
| 2B-FUND-004 | 非 8h schedule 显式枚举 | 不假设固定间隔 | snapshot events | 6h/12h | ×6/×7 常量 | count | DATA_INVALID | irregular | UT-FUND-004 | PT-FUND-ENUMERATION | GF-FUND-IRREGULAR | `planning/funding.py` | PLANNED |
| 2B-FUND-005 | coverage 不完整拒绝 | 整个区间覆盖 | schedule validity | full `[entry,max]` | 少1ms | ER | FUNDING_SCHEDULE_UNVERIFIED | 两端少1ms | UT-FUND-005 | PT-FUND-COVERAGE | GF-FUND-UNCOVERED | `planning/funding.py` | PLANNED |
| 2B-FUND-006 | 48h 保守边界可为7 | window overlap 枚举 | ±1000ms schedule | edge alignment | 固定6 | count=7 | DATA_INVALID | 两端 window | UT-FUND-006 | PT-FUND-UPPER-BOUND | GF-FUND-7 | `planning/funding.py` | PLANNED |

## F. Contract rule（6）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-RULE-001 | VERIFIED 覆盖 target | 审核证据+有效期 | archive | covered | expired | coverage/ER | CONTRACT_RULE_EXPIRED | from/to | UT-RULE-001 | PT-RULE-COVERAGE | GF-RULE-MODES | `domain/contracts.py` | PLANNED |
| 2B-RULE-002 | APPROX方向/水印冻结 | PRIOR_ONLY不读未来 | evidence/query | evidence≤query | future as primary | coverage/ER | DATA_INVALID | prior/hindsight | UT-RULE-002 | PT-APPROX-NO-FUTURE | GF-APPROX-DIRECTIONS | `domain/contracts.py` | PLANNED |
| 2B-RULE-003 | HINDSIGHT禁Paper/Live/primary OOS | diagnostic单独 | stage+coverage | diagnostic dir | paper/live/merge | ER | DATA_INVALID | gate exact | UT-RULE-003 | PT-HINDSIGHT-GATES | GF-APPROX-DIRECTIONS | `domain/contracts.py` | PLANNED |
| 2B-RULE-004 | UNAVAILABLE不生成Plan且path invalid | 不得伪装未交易 | unavailable payload | missing archive | synthetic default | ER | EXECUTION_PATH_INVALID | BTC/ETH | UT-RULE-004 | PT-MISSING-NOT-ECONOMIC | GF-PATH-INVALID | `planning/factory.py` | PLANNED |
| 2B-RULE-005 | tick/step/minimum 正值与身份 | rule content 进入 ID | coverage | valid decimals | zero/negative/hash错 | coverage/ER | DATA_INVALID | tiny values | UT-RULE-005 | PT-RULE-NUMERIC | GF-TICK-STEP | `domain/contracts.py` | PLANNED |
| 2B-RULE-006 | rule 版本变更改变 Plan ID | hash/version 均在 payload | two coverages | same values/version diff | rule 在 ID 外 | different Plan IDs | DATA_INVALID | expiry rollover | UT-RULE-006 | PT-RULE-ID-SENSITIVITY | GF-RULE-ID | `domain/plans.py` | PLANNED |

## G. 风险、现金与 quantity（10）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-RISK-001 | unit risk使用stop fee与funding envelope basis | loss+2fees+fund buffer | prices/cost/schedule/risk config | finite positive | entry-only funding | unit risk | DATA_INVALID | LONG/SHORT | UT-RISK-001 | PT-UNIT-RISK-BASIS | GF-RESERVE-BASIS | `planning/sizing.py` | PLANNED |
| 2B-RISK-002 | 单笔预算0.5% | equity×0.005 | AS | equity>0 | ≤0 | budget/ER | DATA_INVALID | exact 0.5% | UT-RISK-002 | PT-RISK-BUDGET | GF-RISK-05 | `planning/sizing.py` | PLANNED |
| 2B-RISK-003 | raw qty=budget/unit risk | 无预舍入 | budget+unit | >0 | zero unit | raw qty/ER | DATA_INVALID | repeating decimal | UT-RISK-003 | PT-QTY-INVERSE-RISK | GF-QTY | `planning/sizing.py` | PLANNED |
| 2B-RISK-004 | planned risk用final qty重算 | ≤0.5%；超限是不变量破坏 | final qty+unit | equal | exceeded | result/ER | DATA_INVALID | exact equal | UT-RISK-004 | PT-RISK-NOT-EXCEED | GF-RISK-05 | `planning/sizing.py` | PLANNED |
| 2B-RISK-005 | base risk先判断，final总风险≤1% | at-limit不变qty zero | AS+batch | base<1% | base≥1% | scale/ER | TOTAL_RISK_ALREADY_AT_LIMIT | equal/above | UT-RISK-005 | PT-BASE-RISK-GATE | GF-ACCOUNT-RISK-EVIDENCE | `planning/portfolio.py` | PLANNED |
| 2B-RISK-006 | AS派生值、集合证据、phase/time一致 | 聚合可追溯 | ledger/risk evidence | exact | hash/phase/pending错 | AS/ER | DATA_INVALID | pending>available | UT-RISK-006 | PT-ACCOUNT-EVIDENCE | GF-ACCOUNT-RISK-EVIDENCE | `domain/accounts.py` | PLANNED |
| 2B-QTY-001 | step 向下量化 | floor(raw/step)*step | raw+rule | positive | ceil/nearest | qty | DATA_INVALID | exact step/just below | UT-QTY-001 | PT-FLOOR-STEP | GF-TICK-STEP | `planning/sizing.py` | PLANNED |
| 2B-QTY-002 | 量化为0独立拒绝 | zero reason 优先 minimum | scaled raw | result 0 | generic min reason | ER | QUANTITY_ROUNDED_TO_ZERO | raw<step | UT-QTY-002 | PT-QTY-ZERO | GF-QTY-ZERO | `planning/sizing.py` | PLANNED |
| 2B-QTY-003 | minQty equality 接受 | qty>=min | rule+qty | equal | below | plan/ER | BELOW_MIN_QTY | ±step | UT-QTY-003 | PT-MIN-QTY | GF-MINIMUM | `planning/sizing.py` | PLANNED |
| 2B-QTY-004 | minNotional 用 final entry fill | qty×entry>=min | rule+plan | equal | below | plan/ER | BELOW_MIN_NOTIONAL | ±1 tick/step | UT-QTY-004 | PT-MIN-NOTIONAL | GF-MINIMUM | `planning/sizing.py` | PLANNED |

## H. 组合缩量（4）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-PORT-001 | 同target intents在完整batch中scale | completeness watermark先于scale | batch | BTC+ETH完整 | sequential BTC | result | BATCH_INCOMPLETE | one/two items | UT-PORT-001 | PT-BATCH-COMPLETE | GF-BATCH-COMPLETE | `planning/portfolio.py` | PLANNED |
| 2B-PORT-002 | 输入顺序无关 | sorted by symbol/result_id | set | permutations | BTC_FIRST bias | same bytes | DATA_INVALID | all permutations | UT-PORT-002 | PT-ORDER-INVARIANT | GF-SCALE-ORDER | `planning/portfolio.py` | PLANNED |
| 2B-PORT-003 | risk/cash 取最小 scale | min(1,risk,cash) | AS+sizing | each limiter | max/first limiter | scale | DATA_INVALID | ties | UT-PORT-003 | PT-SCALE-BOUNDS | GF-SCALE-BTC-ETH | `planning/portfolio.py` | PLANNED |
| 2B-PORT-004 | item 拒绝后不再分配 | scale 一次冻结 | scaled items | ETH below min | BTC re-expanded | result+ER | BELOW_MIN_QTY | one rejects | UT-PORT-004 | PT-NO-REDISTRIBUTION | GF-SCALE-NO-REDIST | `planning/portfolio.py` | PLANNED |

## I. Canonical、ID 与优先级（5）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-ID-001 | 所有正式对象/Snapshot/Batch/SubjectRef禁止空/错ID/hash | 边界重算 | payload | correct | empty/wrong | object/ValueError | DATA_INVALID | 全对象表 | UT-ID-001 | PT-ID-CONTENT | GF-CONTENT-HASH-CLOSURE | `domain/*` | PLANNED |
| 2B-ID-002 | 同输入同 Canonical bytes | deterministic serializer | pure inputs | repeats | map/set order | same bytes | DATA_INVALID | 100 runs | UT-ID-002 | PT-CANONICAL-DETERMINISM | GF-CANONICAL | `domain/canonical.py` | PLANNED |
| 2B-ID-003 | future data不改历史对象 | visible hashes only | history+future | future mutation | full dataset hash | same ID | DATA_INVALID | Intent/Plan | UT-ID-003 | PT-FUTURE-INVARIANT | GF-FUTURE-PLAN | `planning/factory.py` | PLANNED |
| 2B-ID-004 | delay只改变 Intent/Plan | Candidate ID稳定 | candidate+configs | d 0/1/2 | Candidate mutation | three Intent IDs | DATA_INVALID | all delays | UT-ID-004 | PT-DELAY-IDENTITY | GF-DELAY-012 | `domain/intents.py` | PLANNED |
| 2B-ID-005 | 多失败唯一优先级 | 收集事实后按 rank | validators | multiple failures | first-return order | one ER+all evidence | rank reason | shuffled validators | UT-ID-005 | PT-PRIORITY-ORDER | GF-MULTI-REJECT | `domain/rejections.py` | PLANNED |

## J. 范围与安全（5）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-SCOPE-001 | 无网络/HTTP及间接网络 | 所有数据参数注入 | AST/dependency graph | pure imports | socket/subprocess/curl | guard pass/fail | build failure | dynamic import | UT-SCOPE-001 | PT-SCOPE-IMPORT-CLOSURE | GF-SCOPE-MANIFEST | `acceptance/test_scope_guard.py` | PLANNED |
| 2B-SCOPE-002 | 无 API Key/private/create_order | 无鉴权词/调用 | AST/text | pure domain | secret loader/order | guard | build failure | alias/reflection | UT-SCOPE-002 | PT-SCOPE-CALL-GRAPH | GF-SCOPE-MANIFEST | `acceptance/test_scope_guard.py` | PLANNED |
| 2B-SCOPE-003 | 无 GUI/LLM/Shadow | 依赖闭包禁止 | AST | domain only | Qt/openai/worker | guard | build failure | transitive import | UT-SCOPE-003 | PT-SCOPE-IMPORT-CLOSURE | GF-SCOPE-MANIFEST | `acceptance/test_scope_guard.py` | PLANNED |
| 2B-SCOPE-004 | 无 2C 对象/状态 mutation | 不出现 Fill/Position/Ledger/event loop | AST/schema | Plans only | FillEvent/ledger/liquidation | guard | build failure | hidden reducer | UT-SCOPE-004 | PT-SCOPE-SYMBOLS | GF-SCOPE-MANIFEST | `acceptance/test_scope_guard.py` | PLANNED |
| 2B-SCOPE-005 | 2B 无文件/env I/O | 纯函数输入决定输出 | AST | parameters | open/os.environ | guard | build failure | pathlib indirect | UT-SCOPE-005 | PT-SCOPE-IO | GF-SCOPE-MANIFEST | `acceptance/test_scope_guard.py` | PLANNED |

## K. 最终语义关闭增量（34）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-LIFE-007 | Intent不读账户/HALTED/position | 同Candidate+config+manifest同ID | Candidate/config/manifest | 不同AS | AS进Intent hash | 同Intent | DATA_INVALID | RUNNING/HALTED | UT-LIFE-007 | PT-INTENT-ACCOUNT-INVARIANT | GF-INTENT-ACCOUNT-INVARIANT | `domain/intents.py` | PLANNED |
| 2B-LIFE-008 | HALTED仅拒绝新Entry planning | Exit永不被HALTED阻止 | AS+Intent | HALTED Entry | HALTED Exit reject | Entry ER/Exit continue | EXPERIMENT_HALTED only Entry | HALT_EXIT | UT-LIFE-008 | PT-HALTED-ASYMMETRY | GF-HALTED-EXIT | `planning/factory.py` | PLANNED |
| 2B-LIFE-009 | protective exit绕过2B | STOP/TP/LIQ不产XI/XP | 2C condition | scheduled reason | protective reason | Scope/DATA_INVALID | DATA_INVALID | stop same minute | UT-LIFE-009 | PT-PROTECTIVE-NO-PLAN | GF-PROTECTIVE-EXIT-SCOPE | `domain/intents.py` | PLANNED |
| 2B-LIFE-010 | Plan仅由accepted scaling item生成 | final quantity source唯一 | ScalingResult | accepted item | pre-scale Plan | EP | DATA_INVALID | one reject | UT-LIFE-010 | PT-PLAN-AFTER-SCALE | GF-LIFECYCLE-FINAL-PLAN | `planning/factory.py` | PLANNED |
| 2B-LIFE-011 | Exit rule rollover不量化position | mismatch不改quantity | XI+target coverage | step aligned | misaligned | XP/ER | POSITION_QUANTITY_RULE_MISMATCH | rule rollover | UT-LIFE-011 | PT-EXIT-NO-REQUANTIZE | GF-EXIT-RULE-ROLLOVER | `planning/factory.py` | PLANNED |
| 2B-SCHEMA-009 | TargetMinuteOpenSnapshot closed-world | 只includes open-visible fields | target event | open only | HLCV/close metadata | Snapshot | DATA_INVALID | open unchanged | UT-SCHEMA-009 | PT-OPEN-SNAPSHOT-CLOSED | GF-OPEN-ONLY-ID | `domain/market_inputs.py` | PLANNED |
| 2B-SCHEMA-010 | PortfolioPlanningBatch正式Schema | 同target完整集合 | intents/AS/snapshots | complete | partial | batch | BATCH_INCOMPLETE | BTC+ETH | UT-SCHEMA-010 | PT-BATCH-SCHEMA | GF-BATCH-COMPLETE | `domain/batches.py` | PLANNED |
| 2B-SCHEMA-011 | RejectionSubjectRef union | symbols/hash cardinality按kind | failure inputs | batch 2 symbols | single-symbol coercion | ER | DATA_INVALID | BTC+ETH | UT-SCHEMA-011 | PT-SUBJECT-UNION | GF-BATCH-SUBJECT | `domain/rejections.py` | PLANNED |
| 2B-SCHEMA-012 | AcceptedScalingItem完整Schema | final qty/risk/cash可反算 | sizing+scale | all fields | nullable values | accepted item | DATA_INVALID | minimum equal | UT-SCHEMA-012 | PT-ACCEPTED-ITEM-CLOSED | GF-NESTED-SCALING-ITEMS | `domain/scaling.py` | PLANNED |
| 2B-SCHEMA-013 | RejectedScalingItem完整Schema | rejection引用唯一 | sizing+ER | all fields | accepted fields | rejected item | DATA_INVALID | min reject | UT-SCHEMA-013 | PT-REJECTED-ITEM-CLOSED | GF-NESTED-SCALING-ITEMS | `domain/scaling.py` | PLANNED |
| 2B-SCHEMA-014 | FundingRiskConfig与schedule分离 | rate/time不双重存储 | config+schedule | matching symbol | cap in schedule | inputs | DATA_INVALID | baseline | UT-SCHEMA-014 | PT-FUND-CONCERNS-SEPARATE | GF-FUND-RISK-CONFIG | `domain/funding.py` | PLANNED |
| 2B-SCHEMA-015 | Account risk聚合有集合证据 | Decimal可追溯 | ledger/risk records | hashes match | naked aggregate | AS/ER | REQUIRED_ACCOUNT_EVIDENCE_UNAVAILABLE | empty sets | UT-SCHEMA-015 | PT-ACCOUNT-TRACEABLE | GF-ACCOUNT-RISK-EVIDENCE | `domain/accounts.py` | PLANNED |
| 2B-TIME-008 | target前factory调用为precondition error | 无None/等待对象 | event clock | target reached | before target | exception/no domain object | precondition | -1ms/exact | UT-TIME-008 | PT-NO-EARLY-FACTORY | GF-TARGET-PRECONDITION | `planning/factory.py` | PLANNED |
| 2B-TIME-009 | watermark越过且Snapshot缺失才拒绝 | missing语义唯一 | explicit watermark | passed+missing | not-yet | ER | TARGET_MINUTE_UNAVAILABLE | exact watermark | UT-TIME-009 | PT-WATERMARK-MISSING | GF-TARGET-PRECONDITION | `planning/factory.py` | PLANNED |
| 2B-TIME-010 | AS phase/time与batch一致 | post exits/pre entries | account event | exact target/phase | stale phase | batch/ER | DATA_INVALID | funding same time | UT-TIME-010 | PT-PLANNING-PHASE | GF-PLANNING-PHASE | `domain/accounts.py` | PLANNED |
| 2B-TIME-011 | batch completeness watermark证明全量 | 顺序不能决定集合 | event engine | complete | first-call BTC | batch/ER | BATCH_INCOMPLETE | simultaneous | UT-TIME-011 | PT-BATCH-WATERMARK | GF-BATCH-COMPLETE | `domain/batches.py` | PLANNED |
| 2B-TIME-012 | APPROX证据时间不泄漏 | primary evidence≤query | archive | prior | future primary | coverage/ER | DATA_INVALID | equal timestamp | UT-TIME-012 | PT-APPROX-TIME | GF-APPROX-DIRECTIONS | `domain/contracts.py` | PLANNED |
| 2B-COST-006 | exit fee reserve用max envelope | LONG TP高时reserve增 | price estimates | max basis | stop-only | reserve | DATA_INVALID | LONG/SHORT | UT-COST-006 | PT-EXIT-FEE-MAX | GF-RESERVE-BASIS | `planning/costs.py` | PLANNED |
| 2B-COST-007 | funding reserve用同envelope | 不固定entry | prices+fund config | basis max | entry-only | reserve | DATA_INVALID | SHORT stop max | UT-COST-007 | PT-FUNDING-BASIS | GF-RESERVE-BASIS | `planning/funding.py` | PLANNED |
| 2B-FUND-007 | FundingRiskConfig有证据/版本 | target-time-known only | risk config | covered | future/no cover | input/ER | FUNDING_RISK_CONFIG_UNAVAILABLE | from/to | UT-FUND-007 | PT-FUND-RISK-COVERAGE | GF-FUND-RISK-CONFIG | `domain/funding.py` | PLANNED |
| 2B-FUND-008 | 0.0001仅baseline assumption | 强制水印/版本 | risk config | approx baseline | call verified cap | input/ER | DATA_INVALID | multiplier1 | UT-FUND-008 | PT-BASELINE-WATERMARK | GF-FUND-RISK-CONFIG | `domain/funding.py` | PLANNED |
| 2B-FUND-009 | funding stress独立可提高 | effective cap=cap×multiplier | 2D config | >=1 | future-derived | reserve | DATA_INVALID | 1/1.5/2 | UT-FUND-009 | PT-FUND-STRESS-MONOTONIC | GF-FUND-RISK-CONFIG | `planning/funding.py` | PLANNED |
| 2B-RULE-007 | Contract/Cost content hash自证 | 字段变则hash/ID变 | canonical payload | recomputed | stale hash | object/ER | DATA_INVALID | one-field mutation | UT-RULE-007 | PT-CONTENT-HASH-SENSITIVITY | GF-CONTENT-HASH-CLOSURE | `domain/contracts.py` | PLANNED |
| 2B-RULE-008 | PRIOR_ONLY是primary唯一APPROX | future evidence仅diagnostic | evidence time | prior | hindsight primary | coverage/ER | DATA_INVALID | equality | UT-RULE-008 | PT-PRIOR-ONLY | GF-APPROX-DIRECTIONS | `domain/contracts.py` | PLANNED |
| 2B-RULE-009 | review_status为冻结枚举 | 无任意str | review config | two enums | arbitrary | coverage/ER | DATA_INVALID | both directions | UT-RULE-009 | PT-REVIEW-ENUM | GF-APPROX-DIRECTIONS | `domain/contracts.py` | PLANNED |
| 2B-RISK-007 | pending reserve不超available | 超限是非法AS | AS | <= | > | AS/ER | DATA_INVALID | equal/+ulp | UT-RISK-007 | PT-PENDING-BOUND | GF-ACCOUNT-RISK-EVIDENCE | `domain/accounts.py` | PLANNED |
| 2B-RISK-008 | base risk达1%不新Entry | 明reason非qty zero | AS | below | equal/above | ER | TOTAL_RISK_ALREADY_AT_LIMIT | equal | UT-RISK-008 | PT-BASE-RISK-LIMIT | GF-ACCOUNT-RISK-EVIDENCE | `planning/portfolio.py` | PLANNED |
| 2B-RISK-009 | floor/scale后超限是实现错 | 不作经济拒绝 | recomputation | within | above | ER | DATA_INVALID | 1 ulp | UT-RISK-009 | PT-FINAL-RISK-INVARIANT | GF-RISK-INVARIANT | `planning/portfolio.py` | PLANNED |
| 2B-RISK-010 | open-risk evidence缺失不晋级 | path invalid静默删除禁止 | AS evidence | complete | missing | ER | EXECUTION_PATH_INVALID | one symbol | UT-RISK-010 | PT-INVALID-NOT-PERFORMANCE | GF-PATH-INVALID | `planning/factory.py` | PLANNED |
| 2B-PORT-005 | batch是portfolio rejection subject | 稳定batch ID | batch | two symbols | temp ID | ER | DATA_INVALID | order permutations | UT-PORT-005 | PT-BATCH-SUBJECT-STABLE | GF-BATCH-SUBJECT | `domain/rejections.py` | PLANNED |
| 2B-PORT-006 | nested item有独立ID/hash | 完整payload进result ID | scaling | accepted/rejected | ambiguous union | result | DATA_INVALID | one reject | UT-PORT-006 | PT-NESTED-ITEM-ID | GF-NESTED-SCALING-ITEMS | `domain/scaling.py` | PLANNED |
| 2B-PORT-007 | 不完batch不得scale | 不单独处理BTC | completeness | complete | partial | result/ER | BATCH_INCOMPLETE | BTC then ETH | UT-PORT-007 | PT-NO-PARTIAL-SCALE | GF-BATCH-COMPLETE | `planning/portfolio.py` | PLANNED |
| 2B-ID-006 | config hashes精确列字段 | 无“全部纯输入” | config payload | exact | omitted version | hash/ER | DATA_INVALID | each version mutation | UT-ID-006 | PT-CONFIG-HASH-CLOSURE | GF-CONTENT-HASH-CLOSURE | `domain/config.py` | PLANNED |
| 2B-ID-007 | 所有upstream interface有正式ID/hash | 生产/消费字段一致 | all snapshots | matching | stale/missing | object/ER | DATA_INVALID | field mutation | UT-ID-007 | PT-UPSTREAM-HASH-CLOSURE | GF-CONTENT-HASH-CLOSURE | `domain/*` | PLANNED |

## 测试到需求反向约束

编码时每个测试函数 docstring/marker 必须包含其 `Requirement ID`。CI 生成两张集合：矩阵中的 Unit/Property/Golden Test ID 与测试目录实际声明的 Test ID；两集合必须完全相等。新增测试前先新增 Requirement，删除 Requirement 时同步删除测试和 fixture 引用。当前阶段测试代码数量为 `0`，这里只冻结未来 Test ID。
