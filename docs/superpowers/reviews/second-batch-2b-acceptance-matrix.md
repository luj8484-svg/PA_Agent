# 2B 需求追踪与验收矩阵

状态：规格冻结候审；所有测试和实现路径均为计划，不代表已编码。
Requirement 总数：`66`。每个 Requirement 至少对应一个唯一 Unit Test ID；Property 和 Golden 列给出独立覆盖或明确共享覆盖。测试命名冻结，编码时不得出现没有 Requirement ID 的测试。

缩写：`EI` EntryIntent，`EP` EntryExecutionPlan，`XI` ExitIntent，`XP` ExitExecutionPlan，`ER` ExecutionRejection，`CR` ContractRuleCoverage，`AS` AccountPlanningSnapshot。

## A. 生命周期与 Schema（14）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-LIFE-001 | LONG/SHORT Candidate 生成 EI | side 仅由 Candidate | 2A Candidate | LONG/SHORT | NO_SETUP | EI | CANDIDATE_NOT_ACTIONABLE | LONG、SHORT 各一 | UT-LIFE-001 | PT-LIFE-SIDE | GF-BTC-LONG/GF-ETH-SHORT | `domain/intents.py` | PLANNED |
| 2B-LIFE-002 | Candidate→EI 不读未来数据 | EI 无价格/contract/account | Candidate+time config | decision 已到 | 未来 1m 注入 | 同 Canonical EI | DATA_INVALID | 修改 future bars | UT-LIFE-002 | PT-FUTURE-INTENT | GF-FUTURE-INTENT | `planning/factory.py` | PLANNED |
| 2B-LIFE-003 | EI→EP 只在 target 到达 | plan_created=target | target 1m event | watermark 已到且有 open | target 未到 | EP/等待 | TARGET_MINUTE_UNAVAILABLE 仅 watermark 越过 | 到达前 1ms/正好 | UT-LIFE-003 | PT-TIME-WATERMARK | GF-TARGET-ARRIVAL | `planning/factory.py` | PLANNED |
| 2B-LIFE-004 | ExitCondition→XI 不判断 trigger | condition 是上游事实 | ExitCondition+position | 合法 condition | 2B 自算 stop 命中 | XI | DATA_INVALID | 各 ExitReason | UT-LIFE-004 | PT-XI-NO-TRIGGER | GF-XI-FUTURE | `domain/intents.py` | PLANNED |
| 2B-LIFE-005 | XI→XP 只在未来 target 到达 | target>condition | XI+target 1m | position 未变 | position hash 变化 | XP | POSITION_SNAPSHOT_CHANGED/PLAN_CANCELLED | 下一分钟 open | UT-LIFE-005 | PT-XP-FUTURE | GF-XP-NORMAL | `planning/factory.py` | PLANNED |
| 2B-LIFE-006 | Plan 不产生 Fill/账户 mutation | 输入快照逐字节不变 | immutable inputs | 任意合法 plan | mutation attempt | final Plan | DATA_INVALID | 重复调用 | UT-LIFE-006 | PT-PURITY | GF-PURITY | `planning/factory.py` | PLANNED |
| 2B-SCHEMA-001 | EI 完整且无 EP 字段 | 无 nullable 联合 | Candidate | 完整 EI payload | entry_price/quantity | EI | DATA_INVALID | unknown field | UT-SCHEMA-001 | PT-SCHEMA-CLOSED | GF-BTC-LONG | `domain/intents.py` | PLANNED |
| 2B-SCHEMA-002 | EP 完整且只有 Entry 字段 | Entry/Exit 分离 | final planning payload | 全字段 | ExitReason/position_id | EP | DATA_INVALID | missing reserve | UT-SCHEMA-002 | PT-SCHEMA-CLOSED | GF-BTC-LONG | `domain/plans.py` | PLANNED |
| 2B-SCHEMA-003 | XI 不含未来 price | future open 未知 | condition+position | 无 price | reference_price | XI | DATA_INVALID | target 配置变化 | UT-SCHEMA-003 | PT-XI-NO-PRICE | GF-XI-FUTURE | `domain/intents.py` | PLANNED |
| 2B-SCHEMA-004 | XP 不含 Entry 风险字段 | XP 只描述全退计划 | XI+target+cost | exit fields | stop/TP/margin/reserve | XP | DATA_INVALID | all forbidden fields | UT-SCHEMA-004 | PT-SCHEMA-CLOSED | GF-XP-NORMAL | `domain/plans.py` | PLANNED |
| 2B-SCHEMA-005 | ER subject 使用 tagged reference | 一个 subject_type/id | failure facts | matching pair | 多个 nullable IDs | ER | DATA_INVALID | 各 subject type | UT-SCHEMA-005 | PT-REJECTION-SUBJECT | GF-MULTI-REJECT | `domain/rejections.py` | PLANNED |
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
| 2B-GAP-001 | LONG adverse gap 方向 | gap=P0-close | Candidate+1m | gap≤0.5ATR | gap>0.5ATR | continue/ER | GAP_TOO_LARGE | 前/等/后 | UT-GAP-001 | PT-GAP-LONG-MONOTONIC | GF-GAP-LONG-3 | `planning/prices.py` | PLANNED |
| 2B-GAP-002 | SHORT adverse gap 方向 | gap=close-P0 | Candidate+1m | gap≤0.5ATR | gap>0.5ATR | continue/ER | GAP_TOO_LARGE | 前/等/后 | UT-GAP-002 | PT-GAP-SHORT-MONOTONIC | GF-GAP-SHORT-3 | `planning/prices.py` | PLANNED |
| 2B-GAP-003 | gap 等于阈值接受 | 比较严格 `>` | Decimal | exact equality | `>=` 实现 | continue | 无 | 0.5ATR exact | UT-GAP-003 | PT-GAP-EQUALITY | GF-GAP-EQUAL | `planning/prices.py` | PLANNED |
| 2B-GAP-004 | gap 在滑点前计算 | P0 不含 s | target 1m+Candidate | raw P0 | fill 作为 P0 | deterministic gap | DATA_INVALID | s 压力变化 | UT-GAP-004 | PT-GAP-COST-INDEPENDENT | GF-GAP-PRE-SLIP | `planning/prices.py` | PLANNED |

## D. 成本与价格几何（5）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-COST-001 | LONG/SHORT entry 滑点一次 | fill 只含一次 s | P0+cost+tick | s≥0 | 二次乘 s | entry fill | DATA_INVALID | s=0 | UT-COST-001 | PT-SLIP-DIRECTION | GF-BTC-LONG/GF-ETH-SHORT | `planning/prices.py` | PLANNED |
| 2B-COST-002 | stop/TP 定向 tick | 几何公式固定 | entry+ATR+tick | 正 ATR | 反向 round | prices | PRICE_GEOMETRY_INVALID | 一 tick ATR | UT-COST-002 | PT-TICK-DIRECTION | GF-TICK-STEP | `planning/prices.py` | PLANNED |
| 2B-COST-003 | stop/TP expected fill 只含退出滑点一次 | trigger→fill 一次 | trigger+cost | valid | 重复扣滑点 | estimates | DATA_INVALID | s=0/pressure | UT-COST-003 | PT-NO-DOUBLE-SLIP | GF-COST-ONCE | `planning/prices.py` | PLANNED |
| 2B-COST-004 | fee 精确且不量化到分 | q×fill×f | cost snapshot | ≥0 | negative/nonfinite | fee/reserve | DATA_INVALID | f=0、stress | UT-COST-004 | PT-FEE-LINEAR | GF-FEE | `domain/costs.py` | PLANNED |
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
| 2B-RULE-002 | APPROX 强制水印 | Plan/manifest 均带 watermark | approx archive | research/paper | missing watermark | Plan/ER | DATA_INVALID | backtest/paper | UT-RULE-002 | PT-APPROX-WATERMARK | GF-RULE-APPROX | `domain/contracts.py` | PLANNED |
| 2B-RULE-003 | APPROX 禁止 Live Eligibility | mode gate 唯一 | stage+coverage | paper | live eligibility | ER | DATA_INVALID | gate exact | UT-RULE-003 | PT-APPROX-NO-LIVE | GF-RULE-GATES | `domain/contracts.py` | PLANNED |
| 2B-RULE-004 | UNAVAILABLE 不生成 Plan | Candidate 保留 | unavailable payload | missing archive | synthetic defaults | ER | CONTRACT_RULE_UNAVAILABLE | BTC/ETH | UT-RULE-004 | PT-NO-DEFAULT-RULE | GF-RULE-UNAVAILABLE | `planning/factory.py` | PLANNED |
| 2B-RULE-005 | tick/step/minimum 正值与身份 | rule content 进入 ID | coverage | valid decimals | zero/negative/hash错 | coverage/ER | DATA_INVALID | tiny values | UT-RULE-005 | PT-RULE-NUMERIC | GF-TICK-STEP | `domain/contracts.py` | PLANNED |
| 2B-RULE-006 | rule 版本变更改变 Plan ID | hash/version 均在 payload | two coverages | same values/version diff | rule 在 ID 外 | different Plan IDs | DATA_INVALID | expiry rollover | UT-RULE-006 | PT-RULE-ID-SENSITIVITY | GF-RULE-ID | `domain/plans.py` | PLANNED |

## G. 风险、现金与 quantity（10）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-RISK-001 | unit risk 四项且无双重滑点 | price loss+2 fees+fund buffer | prices/cost/schedule | finite positive | duplicate/missing component | unit risk | DATA_INVALID | fee=0/fund=0 | UT-RISK-001 | PT-UNIT-RISK-LINEAR | GF-RISK-05 | `planning/sizing.py` | PLANNED |
| 2B-RISK-002 | 单笔预算0.5% | equity×0.005 | AS | equity>0 | ≤0 | budget/ER | RISK_BUDGET_EXCEEDED/DATA_INVALID | exact 0.5% | UT-RISK-002 | PT-RISK-BUDGET | GF-RISK-05 | `planning/sizing.py` | PLANNED |
| 2B-RISK-003 | raw qty=budget/unit risk | 无预舍入 | budget+unit | >0 | zero unit | raw qty/ER | DATA_INVALID | repeating decimal | UT-RISK-003 | PT-QTY-INVERSE-RISK | GF-QTY | `planning/sizing.py` | PLANNED |
| 2B-RISK-004 | planned risk 用 final qty 重算 | ≤0.5% | final qty+unit | equal boundary | exceeded | result/ER | RISK_BUDGET_EXCEEDED | exact equal | UT-RISK-004 | PT-RISK-NOT-EXCEED | GF-RISK-05 | `planning/sizing.py` | PLANNED |
| 2B-RISK-005 | 总风险≤1% | open+pending+batch | AS+batch | exact 1% | >1% | scale/result | TOTAL_RISK_EXCEEDED | equal/1 ulp above | UT-RISK-005 | PT-TOTAL-RISK | GF-RISK-10 | `planning/portfolio.py` | PLANNED |
| 2B-RISK-006 | AS 派生字段一致 | available 公式唯一 | ledger snapshot | exact equality | duplicate/double reserve | AS accepted/ER | DATA_INVALID | zero reserves | UT-RISK-006 | PT-ACCOUNT-IDENTITY | GF-ACCOUNT | `domain/accounts.py` | PLANNED |
| 2B-QTY-001 | step 向下量化 | floor(raw/step)*step | raw+rule | positive | ceil/nearest | qty | DATA_INVALID | exact step/just below | UT-QTY-001 | PT-FLOOR-STEP | GF-TICK-STEP | `planning/sizing.py` | PLANNED |
| 2B-QTY-002 | 量化为0独立拒绝 | zero reason 优先 minimum | scaled raw | result 0 | generic min reason | ER | QUANTITY_ROUNDED_TO_ZERO | raw<step | UT-QTY-002 | PT-QTY-ZERO | GF-QTY-ZERO | `planning/sizing.py` | PLANNED |
| 2B-QTY-003 | minQty equality 接受 | qty>=min | rule+qty | equal | below | plan/ER | BELOW_MIN_QTY | ±step | UT-QTY-003 | PT-MIN-QTY | GF-MINIMUM | `planning/sizing.py` | PLANNED |
| 2B-QTY-004 | minNotional 用 final entry fill | qty×entry>=min | rule+plan | equal | below | plan/ER | BELOW_MIN_NOTIONAL | ±1 tick/step | UT-QTY-004 | PT-MIN-NOTIONAL | GF-MINIMUM | `planning/sizing.py` | PLANNED |

## H. 组合缩量（4）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-PORT-001 | 同刻 plans 一起 scale | 先全算后缩量 | same target set | BTC+ETH | sequential allocation | result | DATA_INVALID | one/two items | UT-PORT-001 | PT-BATCH-SIMULTANEOUS | GF-SCALE-BTC-ETH | `planning/portfolio.py` | PLANNED |
| 2B-PORT-002 | 输入顺序无关 | sorted by symbol/result_id | set | permutations | BTC_FIRST bias | same bytes | DATA_INVALID | all permutations | UT-PORT-002 | PT-ORDER-INVARIANT | GF-SCALE-ORDER | `planning/portfolio.py` | PLANNED |
| 2B-PORT-003 | risk/cash 取最小 scale | min(1,risk,cash) | AS+sizing | each limiter | max/first limiter | scale | DATA_INVALID | ties | UT-PORT-003 | PT-SCALE-BOUNDS | GF-SCALE-BTC-ETH | `planning/portfolio.py` | PLANNED |
| 2B-PORT-004 | item 拒绝后不再分配 | scale 一次冻结 | scaled items | ETH below min | BTC re-expanded | result+ER | BELOW_MIN_QTY | one rejects | UT-PORT-004 | PT-NO-REDISTRIBUTION | GF-SCALE-NO-REDIST | `planning/portfolio.py` | PLANNED |

## I. Canonical、ID 与优先级（5）

| Requirement ID | 需求描述 | 唯一不变量 | 数据来源 | 合法输入 | 非法输入 | 预期输出 | Failure/Rejection | 边界案例 | Unit Test | Property Test | Golden Fixture | 实现文件 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2B-ID-001 | 正式对象禁止空/错 ID | __post_init__ 重算 | payload | correct ID | empty/wrong | object/ValueError | DATA_INVALID at factory boundary | all 9 objects | UT-ID-001 | PT-ID-CONTENT | GF-CANONICAL | `domain/*` | PLANNED |
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

## 测试到需求反向约束

编码时每个测试函数 docstring/marker 必须包含其 `Requirement ID`。CI 生成两张集合：矩阵中的 Unit/Property/Golden Test ID 与测试目录实际声明的 Test ID；两集合必须完全相等。新增测试前先新增 Requirement，删除 Requirement 时同步删除测试和 fixture 引用。当前阶段测试代码数量为 `0`，这里只冻结未来 Test ID。
