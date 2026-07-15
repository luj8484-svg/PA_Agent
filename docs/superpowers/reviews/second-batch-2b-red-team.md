# 2B Codex 自我红队

日期：2026-07-15

方法：逐项尝试构造经济非法但 Schema 可接受的对象、身份绕过、资金重复使用、未来数据泄漏、顺序偏置和范围越界。
攻击场景数：`53`。红队后未关闭 BLOCKER：`0`。

| # | Attack scenario | Expected invariant | Current design response | 验收矩阵覆盖 | Requirement ID | Test ID | 未覆盖时修订 |
|---:|---|---|---|---|---|---|---|
| 1 | 构造字段类型合法但 LONG stop≥entry 的 Plan | 经济几何必须 strict | final object 重算几何；PRICE_GEOMETRY_INVALID | 是 | 2B-COST-005 | UT-RT-001 | 已在 PRICE-F05–08 与 schema 后置校验冻结 |
| 2 | 直接调用 dataclass 构造空/错 ID | 正式对象 ID 不可绕过 | `__post_init__` 重算；工厂 payload→ID→final | 是 | 2B-ID-001 | UT-RT-002 | 已关闭 |
| 3 | 两个计划分别读取同一 available balance | 同刻共享一次 AS 并 batch scale | 同target必须一个完整PlanningBatch和ScalingResult | 是 | 2B-PORT-001 | UT-RT-003 | 已关闭 |
| 4 | BTC/ETH 各满足0.5%但加既有风险超1% | 总风险含 open+pending+batch | RISK-F21/SCALE-F23，final 再校验 | 是 | 2B-RISK-005 | UT-RT-004 | 已关闭 |
| 5 | step quantization 用 ceil 令风险超预算 | quantity 只 floor，final risk重算 | QTY-F16 + RISK-F17 | 是 | 2B-QTY-001,2B-RISK-004 | UT-RT-005 | 已关闭 |
| 6 | entry fill 已加滑点，unit risk 再加 slippage amount | 滑点只在 fill 一次 | RISK-F13 不含独立 slippage 项 | 是 | 2B-COST-001,2B-RISK-001 | UT-RT-006 | 已关闭 |
| 7 | exit fee 同时放 unit risk、required cash 两次以上 | 经济 reserve只锁一次，但risk/cash的price basis不同 | unit risk用stop fee；cash reserve用max envelope；required_cash只加一次 | 是 | 2B-COST-004/006,2B-RISK-006 | UT-RT-007 | 已关闭 |
| 8 | wallet 与 isolated margin 各扣一次 funding | wallet 是唯一经济账户 | AS 明确 isolated 为派生视图；2B只 reserve不扣款 | 是 | 2B-RISK-006 | UT-RT-008 | 已关闭 |
| 9 | 48h 资金费固定×6低估 | 逐窗口枚举 `(entry,maxExit]` | FUND-F11，±1s 可得到7 | 是 | 2B-FUND-006 | UT-RT-009 | 已关闭 |
| 10 | APPROX 去掉水印后送 Live | APPROX 永不 live eligible | mode payload强制 watermark；gate DATA_INVALID | 是 | 2B-RULE-002/003 | UT-RT-010 | 已关闭 |
| 11 | 过期 rule 保留正确数值继续 Plan | validity 是 Plan 必要输入 | target∉`[from,to)`→expired | 是 | 2B-TIME-005 | UT-RT-011 | 已关闭 |
| 12 | 在 Candidate 时读取下一1m open预构造 EP | Intent/Plan 分阶段 | EI无price；EP仅在target+batch+scaling后 | 是 | 2B-LIFE-002/003/010 | UT-RT-012 | 已关闭 |
| 13 | 用 `now()` 让 plan_created/ID 每次不同 | event clock唯一 | created必须等于target；scope禁止clock | 是 | 2B-TIME-007 | UT-RT-013 | 已关闭 |
| 14 | full dataset hash含未来数据，未来变化改历史对象 | decision/target visible hashes | Intent/Plan字段排除full interval hash | 是 | 2B-ID-003 | UT-RT-014 | 已关闭 |
| 15 | 输入 list 顺序改变 scale/item输出 | 无领域顺序输入先排序 | `(symbol,result_id)` Canonical排序 | 是 | 2B-PORT-002 | UT-RT-015 | 已关闭 |
| 16 | BTC_FIRST先耗尽现金，系统性拒绝ETH | 所有同刻先独立算再共同scale | 正式CompletenessSnapshot；禁止sequential allocation | 是 | 2B-PORT-001/002/007 | UT-RT-016 | 已关闭 |
| 17 | ETH缩量后below minimum，把释放额度给BTC | scale只计算一次 | rejected item不触发重算 | 是 | 2B-PORT-004 | UT-RT-017 | 已关闭 |
| 18 | LONG/SHORT directional gap 公式互换 | adverse方向按side冻结 | GAP-F01分别定义并有monotonic property | 是 | 2B-GAP-001/002 | UT-RT-018 | 已关闭 |
| 19 | threshold相等因Decimal量化/`>=`随机拒绝 | equality必须接受 | 未量化P0/ATR，严格`>` | 是 | 2B-GAP-003 | UT-RT-019 | 已关闭 |
| 20 | tick量化让 stop/entry/TP重合 | final几何重新校验 | PRICE_GEOMETRY_INVALID | 是 | 2B-COST-005 | UT-RT-020 | 已关闭 |
| 21 | 输入负费用/数量或 Decimal NaN/Inf | 所有经济值有限且合法 | Schema/Cost snapshot fail DATA_INVALID | 是 | 2B-COST-004,2B-ID-002 | UT-RT-021 | 已关闭 |
| 22 | 多拒绝原因返回依赖 validator 调用顺序 | 收集事实后唯一priority | 2B_REJECTION_PRIORITY_V2+联合映射 | 是 | 2B-ID-005 | UT-RT-022 | 已关闭 |
| 23 | contract values入Plan但rule hash/version留在ID外 | 所有语义依赖进入ID | coverage id/hash/version全在Plan | 是 | 2B-RULE-006 | UT-RT-023 | 已关闭 |
| 24 | dict/hash迭代顺序导致Canonical变化 | serializer完全确定 | sort keys/集合领域排序；100次fixture | 是 | 2B-ID-002 | UT-RT-024 | 已关闭 |
| 25 | 在2B添加 Fill/Position/Ledger helper | 2B只Plan | AST、symbol、dependency closure scope guard | 是 | 2B-SCOPE-004 | UT-RT-025 | 已关闭 |
| 26 | 不import HTTP，改用 subprocess/curl/socket反射联网 | 2B无任何间接I/O | scope guard查call graph/dynamic import/subprocess/env/file | 是 | 2B-SCOPE-001/005 | UT-RT-026 | 已关闭 |
| 27 | `available_balance`与各locked字段同时成为独立真相且矛盾 | 派生字段必须一致 | AS定义公式并在入口重算验证 | 是 | 2B-RISK-006 | UT-RT-027 | 原 BLOCKER B1，已关闭 |
| 28 | Plan同时保存可由字段推导的另一个input hash且两者矛盾 | 每个身份只有一个真相 | 不保存泛化plan_input_hash；plan_id由全字段唯一派生 | 是 | 2B-ID-001/002 | UT-RT-028 | 原 BLOCKER B2，已关闭 |
| 29 | 把实际 funding debit、Fill price、position state塞入2B | 2C事实不得进2B | Schema列举并Scope guard禁止 | 是 | 2B-SCOPE-004 | UT-RT-029 | 已关闭 |
| 30 | Requirement无测试或测试无Requirement | 双向集合必须相等 | acceptance matrix冻结 Test ID；未来CI反向检查 | 是 | 2B-SCOPE-005 | UT-RT-030 | 原 BLOCKER B3，已关闭 |
| 31 | RT-31 STOP trigger被转下一分钟ExitPlan | protective exit只在2C | ScheduledExitReason closed enum；Scope禁protective Plan | 是 | 2B-LIFE-009 | UT-RT-031 | 无XI/XP，已关闭 |
| 32 | RT-32 HALTED阻止HALT_EXIT | HALTED仅禁新Entry | subject/reason映射禁止Exit使用EXPERIMENT_HALTED | 是 | 2B-LIFE-008 | UT-RT-032 | HALT_EXIT fixture已关闭 |
| 33 | RT-33 同Candidate因账户不同产生不同Intent | Intent不读AS/HALTED/position | 输入边界与ID payload排除账户 | 是 | 2B-LIFE-007 | UT-RT-033 | 账户不变性fixture已关闭 |
| 34 | RT-34 open相同但修改HLCV令Plan ID变 | Plan只读open Snapshot | closed Snapshot不含HLCV；hash只含open-visible fields | 是 | 2B-SCHEMA-009 | UT-RT-034 | Entry/Exit property已关闭 |
| 35 | RT-35 BTC/ETH batch rejection强制单symbol/hash | subject cardinality按kind | PortfolioBatchSubjectRef包含symbol tuple和多hash | 是 | 2B-SCHEMA-011 | UT-RT-035 | tagged union已关闭 |
| 36 | RT-36 CONTRACT_RULE_UNAVAILABLE当正常未交易提高收益 | 证据缺失不得筛选交易 | Backtest联合映射为EXECUTION_PATH_INVALID | 是 | 2B-RISK-010 | UT-RT-036 | 报告分类与gate已关闭 |
| 37 | RT-37 LONG TP高于stop但fee reserve按stop | cash reserve覆盖冻结价格包络 | PRICE-F10+COST-F10使用max | 是 | 2B-COST-006 | UT-RT-037 | reserve fixture已关闭 |
| 38 | RT-38 funding规划价高于entry但reserve固定entry | funding使用同envelope basis | FUND-F12/F13改为max basis | 是 | 2B-COST-007 | UT-RT-038 | LONG/SHORT fixture已关闭 |
| 39 | RT-39 用未来contract snapshot重建过去primary Plan | APPROX primary无lookahead | PRIOR_ONLY要求evidence≤query；HINDSIGHT独立 | 是 | 2B-RULE-008 | UT-RT-039 | gate+水印已关闭 |
| 40 | RT-40 pending reserve>available被max(0)吞掉 | 非法AS必须暴露 | 先验证pending≤available；CASH-F22无max | 是 | 2B-RISK-007 | UT-RT-040 | DATA_INVALID已关闭 |
| 41 | RT-41 base risk超1%被转quantity zero | risk cap有明reason | RISK-F20先判TOTAL_RISK_ALREADY_AT_LIMIT | 是 | 2B-RISK-008 | UT-RT-041 | priority早于qty已关闭 |
| 42 | RT-42 无batch completeness只scale BTC | 同target完整集合 | CompletenessSnapshot+PortfolioPlanningBatch是scaling前置 | 是 | 2B-PORT-007 | UT-RT-042 | partial batch拒绝已关闭 |
| 43 | RT-43 ExitIntent提前要求target step对齐 | target rule未知 | XI只验证positive+position equality；target才检step | 是 | 2B-LIFE-011 | UT-RT-043 | rollover fixture已关闭 |
| 44 | RT-44 Contract/Cost字段变但content hash不变 | content hash必须自证 | 正式hash排除ID/hash后重算，Plan复制同名字段 | 是 | 2B-RULE-007 | UT-RT-044 | mutation fixture已关闭 |
| 45 | RT-45 同reason在Entry/Exit得错误Disposition | disposition依赖subject+stage | 冻结联合映射，无RETRYABLE disposition | 是 | 2B-SCHEMA-011 | UT-RT-045 | matrix property已关闭 |
| 46 | RT-46 伪造Candidate错ID/hash却用NO_SETUP reason降级 | 非法Candidate必须DATA_INVALID | CANDIDATE_NOT_ACTIONABLE仅与已验证NO_SETUP匹配 | 是 | 2B-LIFE-001 | UT-RT-046 | Candidate边界fixture已关闭 |
| 47 | RT-47 同open配不同合法watermark导致Snapshot/Plan ID变化 | Snapshot身份只含open事实 | Snapshot hash排除watermark；Plan只引用Snapshot hash | 是 | 2B-SCHEMA-016,2B-TIME-013 | UT-RT-047 | identity invariant已关闭 |
| 48 | RT-48 completeness只列BTC并遗漏同target ETH | expected/resolution必须双射 | 正式CompletenessSnapshot逐Intent唯一终态 | 是 | 2B-PORT-008 | UT-RT-048 | missing resolution DATA_INVALID |
| 49 | RT-49 ScalingResult与另一个Batch配对 | Batch→Scaling链不可拼接 | Scaling保存并验证batch ID/hash与成功投影 | 是 | 2B-PORT-009 | UT-RT-049 | cross-batch DATA_INVALID |
| 50 | RT-50 修改item_input_hash隐含输入但item仍通过 | 禁止不可自证opaque hash | V1删除item_input_hash；只认closed payload链 | 是 | 2B-SCHEMA-019 | UT-RT-050 | field不存在 |
| 51 | RT-51 current_equity改变但valuation/equity evidence不变 | equity可重放 | 固定wallet+UPnL及eligible mark-open evidence | 是 | 2B-RISK-011 | UT-RT-051 | aggregate mismatch DATA_INVALID |
| 52 | RT-52 open-risk/pending数字变但记录集合/hash不变 | 聚合逐记录自证 | AEB携带记录IDs/hashes与聚合重算 | 是 | 2B-RISK-012 | UT-RT-052 | aggregate mismatch DATA_INVALID |
| 53 | RT-53 supplemental tests因不在acceptance被误判孤儿 | registry取五文档并集 | MASTER_TEST_REGISTRY_V1分类并双向比较 | 是 | 2B-ID-008,2B-SCOPE-006 | UT-RT-053 | supplemental正式登记 |

## 红队发现并关闭的 BLOCKER

| BLOCKER | 初始风险 | 关闭方式 | 关闭证据 |
|---|---|---|---|
| B1 账户余额双重真相 | `available_balance`、locks、pending 的包含关系不清，会双扣或重复使用 | 冻结 AS 公式：available 不含 pending，`deployable=available-pending_plan_reserve`；入口重算一致性 | Spec 5.14、CASH-F22、2B-RISK-006 |
| B2 泛化 input hash 与字段身份冲突 | 保存 `plan_input_hash` 又保存各字段，可能二者矛盾 | 删除泛化result/plan input hash；只保留可自证content hash和正式ID | Spec 3.3/3.4、5.3、2B-ID-001/006/007 |
| B3 需求/测试追踪可能单向 | 文档有测试名但实现可新增孤儿测试 | 冻结 Requirement/Test 双集合 CI 规则和唯一 Test ID | Acceptance matrix 末节、2B-SCOPE-005 |
| B4 48h 起点在 Plan 与 Fill 间可能漂移 | 2B无Fill却要算funding upper bound | V1以 target execution time 为入场事件；2C Fill 必须同一 event time，否则路径 INVALID/提升版本 | TIME-F03、Spec 16 |
| B5 Exit trigger职责越界 | 2B若判断stop/TP会偷做2C | 冻结scheduled ExitCondition；protective reason不进2B | Spec 5.4、LIFE-004/009 |
| B6 target缺失的等待/失败混淆 | forward未到与历史缺口可能同reason | 方案A；factory前调为precondition error，watermark越过且缺失才path invalid | Spec 6/12、TB-007–009 |
| B7 Entry生命周期顺序 | Plan在scaling前产生 | 冻结Intent→Sizing→Batch→Scaling→accepted item→Plan | LIFE-003/010、GF-LIFECYCLE-FINAL-PLAN |
| B8 计划性/保护性退出混淆 | stop/TP/liquidation可被延迟到下一open | ScheduledExitReason closed enum，protective 2C-only，HALTED不阻Exit | LIFE-008/009、RT-31/32 |
| B9 target Snapshot/watermark语义 | 完整Kline导致未来泄漏 | open-only closed Snapshot+方案A前置条件 | SCHEMA-009、TIME-008/009 |
| B10 planning batch/账户阶段 | 顺序调用偏置资金分配 | 正式batch completeness+同target post-funding/exits pre-entry AS | PORT-001/007、TIME-010/011 |
| B11 Rejection subject/disposition | 单symbol/hash和全局reason映射不能表达batch/exit | SubjectRef union+三元联合映射，删RETRYABLE disposition | SCHEMA-005/011、Spec 11 |
| B12 回测选择偏差 | 证据缺失被当普通未交易 | EXECUTION_PATH_INVALID独立类别与晋级禁止 | RISK-010、RT-36 |
| B13 ID/content hash缺口 | 对象字段与hash可漂移 | 全正式对象ID/hash表+精确payload+边界重算 | ID-006/007、GF-CONTENT-HASH-CLOSURE |
| B14 nested scaling schema不完整 | accepted/rejected item身份不稳定 | 独立closed payload、item ID/hash、排序key和无再分配 | SCHEMA-012/013、PORT-006 |
| B15 reserve价格基础低估 | LONG TP手续费或funding按低价预留 | max(entry,stop,TP) envelope basis | COST-006/007、PRICE-F10 |
| B16 funding cap无证据 | 0.0001被误称无条件cap | FundingRiskConfig Snapshot、coverage/mode/watermark/stress | FUND-007–009 |
| B17 APPROX未来泄漏 | 未来exchangeInfo伪装当时已知 | PRIOR_ONLY primary；HINDSIGHT诊断隔离 | RULE-008/009、TIME-012 |
| B18 Account风险证据 | 只信聚合Decimal，max吞异常 | set hashes/model version、pending bound、base-risk先判 | RISK-006–009 |
| B19 Exit quantity/rule rollover | XI使用未知target step | XI只验positive+position；target mismatch path invalid，不量化 | LIFE-011、GF-EXIT-RULE-ROLLOVER |
| B20 配置/范围/调用语义 | hash漏版本、None/等待语义不定 | 精确config hash payload、explicit Snapshot/watermark、factory precondition | ID-006、TIME-008–011 |
| B21 Snapshot与Watermark身份耦合 | 晚消费改变Snapshot/Plan ID | Snapshot hash彻底排除watermark；Watermark使用独立source identity | SCHEMA-016/017、RT-47 |
| B22 Batch完整性只看成功结果 | 失败Intent可被静默遗漏并偏置缩量 | CompletenessSnapshot记录expected全集和逐Intent唯一终态；Scaling绑定Batch | SCHEMA-018、PORT-008/009、RT-48/49 |
| B23 Accepted item opaque hash | item边界无法重算隐藏输入 | 删除item_input_hash；closed Schema和正式对象链为唯一身份 | SCHEMA-019、RT-50 |
| B24 Account aggregate缺少可重放证据 | equity/risk/pending可与hash脱钩 | AEB记录集合、valuation basis、逐项聚合重放 | SCHEMA-020、RISK-011/012、RT-51/52 |
| B25 测试注册只覆盖acceptance | supplemental测试被误判或文档声明不实现 | Master Registry取五文档Test ID并集并与pytest metadata双向相等 | ID-008、SCOPE-006、RT-53 |

所有 BLOCKER 已在规格、需求矩阵和测试 ID 中关闭；剩余 BLOCKER：`0`。

## FOLLOW-UP（不阻塞 2B 规格）

1. 2C 必须验证实际 FillEvent 时间与 2B target 相同；否则不能继续使用 2B 的 48h funding reserve。
2. 2C Ledger 必须实现 wallet funding 只记一次，并用 reducer 证明 reserve 只是分类。
3. 2C 要单独冻结 stop/TP/estimated liquidation 的分钟内 baseline/conservative 路径；2B 不代替该设计。
4. 2D 报告必须分层展示 VERIFIED 与 APPROXIMATED，不能汇总伪装为同一证据等级。

## OPTIONAL

1. 已批准的 114 个 Requirement 按实施计划拆成10个TDD Task，但不得改变公式或边界。
2. 可增加形式化 JSON Schema 文件；若加入，它必须从本文字段生成并接受同一 Requirement 追踪，不能成为第二真相源。

## 最终红队结论

- BLOCKER：0 未关闭。
- FOLLOW-UP：4，均属于 2C/2D 明确后续边界。
- OPTIONAL：2，不影响 2B 冻结完整性。
- 2B 不存在需要编码时临时决定的问题。
