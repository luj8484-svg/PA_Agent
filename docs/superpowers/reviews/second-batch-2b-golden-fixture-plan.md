# 2B Golden Fixture 冻结计划

状态：编码前 fixture manifest。Golden Fixture 计划数：`64`。本阶段不创建测试或最终数值 JSON；这里冻结输入结构、预期关系和身份要求。

所有 fixture 文件未来使用 `tests/research_backtest/fixtures/2b/`，必须为 `2B_CANONICAL_VERSION_V1` Canonical JSON，并由不调用生产函数的独立 Decimal 参考实现复核。

| Fixture ID | 冻结输入 | 冻结预期 | Requirement/Test |
|---|---|---|---|
| GF-BTC-LONG | BTCUSDT LONG Candidate；delay=1；VERIFIED tick/step/minimum；baseline cost；完整 funding；充足 AS | EI→Sizing→Batch→Scaling→accepted item→EP；final quantity唯一 | 2B-LIFE-001/003 / UT-GF-001 |
| GF-ETH-SHORT | ETHUSDT SHORT；其余同上 | SHORT entry 向下、stop buy 向上、TP buy 向上 exit estimate；合法几何 | 2B-LIFE-001 / UT-GF-002 |
| GF-GAP-LONG-3 | LONG 的 `P0-close` 分别为 threshold-1tick、threshold、threshold+1tick | 前/等接受，超过 GAP_TOO_LARGE | 2B-GAP-001/003 / UT-GF-003 |
| GF-GAP-SHORT-3 | SHORT 的 `close-P0` 前/等/后 | 前/等接受，超过拒绝；证明方向未写反 | 2B-GAP-002/003 / UT-GF-004 |
| GF-GAP-PRE-SLIP | 相同 P0/ATR，slippage stress 1/2 | gap 结果相同，fill/Plan ID 不同 | 2B-GAP-004 / UT-GF-005 |
| GF-TICK-STEP | 价格落在 tick 中间、raw qty 落在 step 中间 | 各方向价格定向 tick；qty floor step；不 nearest/ceil | 2B-COST-002,2B-QTY-001 / UT-GF-006 |
| GF-MINIMUM | qty/minNotional 各在前/等/后 | equal 接受；below 返回精确 reason | 2B-QTY-003/004 / UT-GF-007 |
| GF-QTY-ZERO | raw_qty*scale < step | QUANTITY_ROUNDED_TO_ZERO，非 BELOW_MIN_QTY | 2B-QTY-002 / UT-GF-008 |
| GF-FUND-BEFORE-AFTER | entry 在同一 settlement window end 前后 1ms | 前计当前 window，后不计 | 2B-FUND-002 / UT-GF-009 |
| GF-FUND-ENDPOINTS | maximum exit 等于 settlement window start/nominal；entry endpoint variants | `(entry,maxExit]`；终点计入 | 2B-FUND-001/003 / UT-GF-010 |
| GF-FUND-IRREGULAR | 显式 6h、6h、12h、3h schedule windows | count 等于相交窗口数，不推断8h | 2B-FUND-004 / UT-GF-011 |
| GF-FUND-UNCOVERED | schedule from/to 各少1ms | FUNDING_SCHEDULE_UNVERIFIED，无 qty/Plan | 2B-FUND-005 / UT-GF-012 |
| GF-FUND-7 | ±1000ms windows；48h两端均与window相交；带版本funding risk config | count=7；reserve=qty×envelope basis×effective cap×7 | 2B-FUND-006/007 / UT-GF-013 |
| GF-RULE-MODES | 同一时刻 VERIFIED、APPROXIMATED、UNAVAILABLE | verified Plan；approx 水印 Plan；unavailable rejection | 2B-RULE-001/002/004 / UT-GF-014 |
| GF-RULE-GATES | PRIOR_ONLY/HINDSIGHT分别送Backtest/Paper/Live | PRIOR_ONLY可paper；HINDSIGHT只诊断；Live均禁 | 2B-RULE-003/008 / UT-GF-015 |
| GF-RULE-EXPIRY | target=from、to-1ms、to | 前二接受，to 过期 | 2B-TIME-005 / UT-GF-016 |
| GF-SCALE-BTC-ETH | remaining risk=750/sum risk=1000；cash scale=0.90；BTC/ETH steps | final scale=0.75；BTC 0.750、ETH 7.50（按冻结 synthetic inputs） | 2B-PORT-001/003 / UT-GF-017 |
| GF-SCALE-NO-REDIST | 上例 ETH minQty=8，缩量后 ETH 拒绝 | BTC 保持0.750，不重新放大 | 2B-PORT-004 / UT-GF-018 |
| GF-RISK-05 | final planned risk为budget-ε、budget、budget+ε | 前/等接受；超过是DATA_INVALID不变量破坏 | 2B-RISK-002/004 / UT-GF-019 |
| GF-RISK-10 | base risk为1%-ε、1%、1%+ε | 仅前者可新Entry；后两者TOTAL_RISK_ALREADY_AT_LIMIT | 2B-RISK-005/008 / UT-GF-020 |
| GF-DETERMINISM | 同一输入重复100次、输入 mapping/permutation 变化、wall clock 环境变化 | Canonical bytes/ID 完全一致 | 2B-ID-002,2B-PORT-002,2B-TIME-007 / UT-GF-021 |
| GF-IDENTITY-BOUNDARIES | delay 0/1/2；future minute 改变；contract/cost version 改变 | Candidate ID恒定；Intent随delay变；Plan随target/version变；future-after-target不变 | 2B-ID-003/004,2B-RULE-006 / UT-GF-022 |
| GF-ACCOUNT | wallet/locks/available 一致与差1最小Decimal；pending单列 | 一致接受；矛盾 DATA_INVALID；pending只减一次 | 2B-RISK-006 / UT-GF-023 |
| GF-CANONICAL | 全部正式对象/Snapshot/Batch/SubjectRef固定payload | bytes、content hash和ID逐字节一致 | 2B-ID-001/002/007 / UT-GF-024 |
| GF-COST-ONCE | 相同价格链分别漏算、一次、二次滑点/fee reserve | 只接受一次版本 | 2B-COST-001/003 / UT-GF-025 |
| GF-DELAY-012 | 同一Candidate，delay 0/1/2 | Candidate ID相同；三种 EI target/ID 和 EP ID不同 | 2B-TIME-002,2B-ID-004 / UT-GF-026 |
| GF-FEE | q、fill、fee rate、stress multiplier 的 exact Decimal cases | fee线性、完整Decimal、不分位量化 | 2B-COST-004 / UT-GF-027 |
| GF-FUTURE-INTENT | 同一decision history追加/修改未来1m/4H | EI bytes/ID不变 | 2B-LIFE-002 / UT-GF-028 |
| GF-FUTURE-PLAN | 同一target-visible history修改target之后数据 | EP/XP bytes和ID不变 | 2B-ID-003 / UT-GF-029 |
| GF-GAP-EQUAL | LONG/SHORT directional gap exact 0.5ATR | 均接受 | 2B-GAP-003 / UT-GF-030 |
| GF-GEOMETRY-INVALID | tick后LONG/SHORT stop或TP与entry重合/反序 | PRICE_GEOMETRY_INVALID，不是实验全局INVALID | 2B-COST-005 / UT-GF-031 |
| GF-MULTI-REJECT | 同一输入同时DATA/HALT/contract/gap/risk/minimum失败；validator permutations | 唯一最高rank reason，evidence完整且ID相同 | 2B-ID-005 / UT-GF-032 |
| GF-PURITY | 调用前后 Candidate、AS、coverage、cost、schedule deep snapshot | 输入逐字节不变，无文件/env/网络副作用 | 2B-LIFE-006 / UT-GF-033 |
| GF-QTY | repeating raw qty、exact step、step±最小Decimal | floor结果和planned risk精确 | 2B-RISK-003,2B-QTY-001 / UT-GF-034 |
| GF-RULE-APPROX | APPROX covered payload及水印 | backtest/paper Plan携带水印 | 2B-RULE-002 / UT-GF-035 |
| GF-RULE-ID | 相同rule values，不同version/hash/effective interval | Plan IDs全部不同 | 2B-RULE-006 / UT-GF-036 |
| GF-RULE-UNAVAILABLE | 完整搜索事实但无covered rule | CR unavailable payload+CONTRACT_RULE_UNAVAILABLE，无Plan | 2B-RULE-004 / UT-GF-037 |
| GF-SCALE-ORDER | BTC/ETH list、tuple、mapping、BTC_FIRST、ETH_FIRST permutations | ScalingResult和Plan/Rejection bytes完全相同 | 2B-PORT-002 / UT-GF-038 |
| GF-SCOPE-MANIFEST | 允许/禁止import、动态import、subprocess、env、文件和2C symbol样例 | scope guard 对允许通过、禁止逐项失败 | 2B-SCOPE-001–005 / UT-GF-039 |
| GF-SPLIT | 相同数据/时间，不同train/validation/OOS label；另有越execution range | label不改ID；越range DATA_INVALID | 2B-TIME-006 / UT-GF-040 |
| GF-TARGET-ARRIVAL | target前1ms调factory、正好target、watermark越过且缺Snapshot | precondition error、planning chain、TARGET_MINUTE_UNAVAILABLE | 2B-TIME-008/009 / UT-GF-041 |
| GF-TIME-ANCHOR | 跨日/月/年Candidate close及非对齐close | 对齐anchor精确；非对齐DATA_INVALID | 2B-TIME-001 / UT-GF-042 |
| GF-WALL-CLOCK | 不同TZ、系统时间、文件mtime、进程启动时间 | 所有领域 bytes/ID相同 | 2B-TIME-007 / UT-GF-043 |
| GF-XI-FUTURE | 四种ScheduledExitReason，future open未提供/恶意提供 | 正常XI无price；protective/future字段拒绝 | 2B-LIFE-004,2B-SCHEMA-003 / UT-GF-044 |
| GF-XP-NORMAL | XI target到达、position未变、VERIFIED cost/rule | 全退XP；无Entry risk/reserve字段 | 2B-LIFE-005,2B-SCHEMA-004 / UT-GF-045 |
| GF-INTENT-ACCOUNT-INVARIANT | 同Candidate/delay/manifest，RUNNING/HALTED/不同balance/position | EntryIntent bytes/ID全部相同 | 2B-LIFE-007 / UT-GF-046 |
| GF-HALTED-EXIT | HALTED+LONG EntryIntent；HALTED+HALT_EXIT condition | Entry rejected；ExitIntent/ExitPlan accepted | 2B-LIFE-008 / UT-GF-047 |
| GF-PROTECTIVE-EXIT-SCOPE | STOP/TP/ESTIMATED_LIQUIDATION输入2B | DATA_INVALID/Scope failure，无MARKET_AT_NEXT_1M_OPEN Plan | 2B-LIFE-009 / UT-GF-048 |
| GF-OPEN-ONLY-ID | 同open修改HLCV/trade metadata；再修改open | 前者Entry/Exit Plan bytes/ID不变；后者改变 | 2B-SCHEMA-009 / UT-GF-049 |
| GF-BATCH-SUBJECT | BTC+ETH同target batch rejection | symbols为二元tuple，hashes按subject payload完整表达 | 2B-SCHEMA-011/PORT-005 / UT-GF-050 |
| GF-PATH-INVALID | contract/cost/funding/account/open-risk各缺一项 | 受影响path EXECUTION_PATH_INVALID，不晋级绩效 | 2B-RISK-010 / UT-GF-051 |
| GF-RESERVE-BASIS | LONG TP最高；SHORT stop最高；entry为最高的synthetic case | fee/funding reserve用max envelope；unit risk stop fee仍用stop | 2B-COST-006/007 / UT-GF-052 |
| GF-APPROX-DIRECTIONS | evidence<query、=query、>query | 前两者PRIOR_ONLY；后者仅HINDSIGHT且不进Paper/OOS | 2B-RULE-008/009 / UT-GF-053 |
| GF-ACCOUNT-RISK-EVIDENCE | set hashes/聚合值匹配、pending=available、pending>available、base risk边界 | 精确映射accepted/DATA_INVALID/TOTAL_RISK_ALREADY_AT_LIMIT | 2B-RISK-006/007/008 / UT-GF-054 |
| GF-BATCH-COMPLETE | BTC first、ETH later；watermark前/后；输入permutations | watermark前无batch/scaling；后唯一bytes/ID | 2B-PORT-001/007 / UT-GF-055 |
| GF-EXIT-RULE-ROLLOVER | XI quantity在condition时合法；target step变更后不对齐 | XI不预先拒绝；target返POSITION_QUANTITY_RULE_MISMATCH，不量化 | 2B-LIFE-011 / UT-GF-056 |
| GF-CONTENT-HASH-CLOSURE | 逐对象改一个正式字段；保留旧hash/ID | 旧hash/ID拒绝；重算后两者改变 | 2B-RULE-007,2B-ID-006/007 / UT-GF-057 |
| GF-NESTED-SCALING-ITEMS | 一accepted、一rejected item及permutations | 独立item ID/hash；完整payload进ScalingResult ID；不再分配 | 2B-SCHEMA-012/013,2B-PORT-006 / UT-GF-058 |
| GF-FUND-RISK-CONFIG | VERIFIED/APPROX baseline/UNAVAILABLE；stress 1/1.5/2；future evidence | 覆盖、水印、path invalid和单调reserve精确 | 2B-FUND-007/008/009 / UT-GF-059 |
| GF-PLANNING-PHASE | 同target funding+scheduled exit前/后AS及本Entry batch是否已反映 | 只接受post-funding/exits、pre-entry phase | 2B-TIME-010 / UT-GF-060 |
| GF-LIFECYCLE-FINAL-PLAN | 同一Intent的pre-scale qty、batch scale、accepted item和伪造的pre-scale Plan | 只有accepted item可生成Plan，quantity逐字段一致 | 2B-LIFE-003/010 / UT-GF-061 |
| GF-RISK-INVARIANT | 伪造floor后超0.5%或scale后超1%的result | DATA_INVALID/EXPERIMENT_INVALID，不是economic rejection | 2B-RISK-004/009 / UT-GF-062 |
| GF-TARGET-PRECONDITION | Entry/Exit target前1ms调factory；watermark越过缺Snapshot | 前两者precondition error无领域对象；后者TARGET_MINUTE_UNAVAILABLE | 2B-TIME-008/009 / UT-GF-063 |
| GF-CANDIDATE-NOSETUP | 合法NO_SETUP、非法MarketView、错Candidate ID/hash | 仅NO_SETUP返CANDIDATE_NOT_ACTIONABLE；后两者DATA_INVALID | 2B-LIFE-001 / UT-GF-064 |

## Fixture 通用字段

每个 fixture manifest 至少包含：

```text
fixture_schema_version
fixture_id
requirement_ids
test_ids
candidate_canonical_json 或 candidate_id+冻结快照
execution_time_config
target_minute_open_snapshot（Intent-only fixture 禁止）
contract_rule_coverage
cost_model_snapshot
funding_schedule_snapshot
funding_risk_config_snapshot
account_planning_snapshot
portfolio_planning_batch（Entry Plan fixture）
input_order_variants
expected_object_kind
expected_canonical_json 或 expected rejection
expected_id
expected_content_hash
independent_reference_method
```

Intent fixture 禁止包含 decision time 之后的 price；Plan fixture 只能使用 TargetMinuteOpenSnapshot，不得带完整Kline。Fixture 的生成时间、文件 mtime、下载 manifest 和本地路径排除在 Canonical 之外。
