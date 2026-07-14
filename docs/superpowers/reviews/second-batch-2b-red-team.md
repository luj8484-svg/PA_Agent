# 2B Codex 自我红队

日期：2026-07-14

方法：逐项尝试构造经济非法但 Schema 可接受的对象、身份绕过、资金重复使用、未来数据泄漏、顺序偏置和范围越界。
攻击场景数：`30`。红队后未关闭 BLOCKER：`0`。

| # | Attack scenario | Expected invariant | Current design response | 验收矩阵覆盖 | Requirement ID | Test ID | 未覆盖时修订 |
|---:|---|---|---|---|---|---|---|
| 1 | 构造字段类型合法但 LONG stop≥entry 的 Plan | 经济几何必须 strict | final object 重算几何；PRICE_GEOMETRY_INVALID | 是 | 2B-COST-005 | UT-RT-001 | 已在 PRICE-F05–08 与 schema 后置校验冻结 |
| 2 | 直接调用 dataclass 构造空/错 ID | 正式对象 ID 不可绕过 | `__post_init__` 重算；工厂 payload→ID→final | 是 | 2B-ID-001 | UT-RT-002 | 已关闭 |
| 3 | 两个计划分别读取同一 available balance | 同刻共享一次 AS 并 batch scale | 同 target 必须一个 PortfolioScalingResult | 是 | 2B-PORT-001 | UT-RT-003 | 已关闭 |
| 4 | BTC/ETH 各满足0.5%但加既有风险超1% | 总风险含 open+pending+batch | RISK-F21/SCALE-F23，final 再校验 | 是 | 2B-RISK-005 | UT-RT-004 | 已关闭 |
| 5 | step quantization 用 ceil 令风险超预算 | quantity 只 floor，final risk重算 | QTY-F16 + RISK-F17 | 是 | 2B-QTY-001,2B-RISK-004 | UT-RT-005 | 已关闭 |
| 6 | entry fill 已加滑点，unit risk 再加 slippage amount | 滑点只在 fill 一次 | RISK-F13 不含独立 slippage 项 | 是 | 2B-COST-001,2B-RISK-001 | UT-RT-006 | 已关闭 |
| 7 | exit fee 同时放 unit risk、required cash 两次以上 | 经济 reserve 一次，风险估计一次 | 两个语义字段值可相同但 required_cash只加一次；AS只锁一次 | 是 | 2B-COST-004,2B-RISK-006 | UT-RT-007 | 已关闭 |
| 8 | wallet 与 isolated margin 各扣一次 funding | wallet 是唯一经济账户 | AS 明确 isolated 为派生视图；2B只 reserve不扣款 | 是 | 2B-RISK-006 | UT-RT-008 | 已关闭 |
| 9 | 48h 资金费固定×6低估 | 逐窗口枚举 `(entry,maxExit]` | FUND-F11，±1s 可得到7 | 是 | 2B-FUND-006 | UT-RT-009 | 已关闭 |
| 10 | APPROX 去掉水印后送 Live | APPROX 永不 live eligible | mode payload强制 watermark；gate DATA_INVALID | 是 | 2B-RULE-002/003 | UT-RT-010 | 已关闭 |
| 11 | 过期 rule 保留正确数值继续 Plan | validity 是 Plan 必要输入 | target∉`[from,to)`→expired | 是 | 2B-TIME-005 | UT-RT-011 | 已关闭 |
| 12 | 在 Candidate 时读取下一1m open预构造 EP | Intent/Plan 分阶段 | EI schema无price；EP created=target | 是 | 2B-LIFE-002/003 | UT-RT-012 | 已关闭 |
| 13 | 用 `now()` 让 plan_created/ID 每次不同 | event clock唯一 | created必须等于target；scope禁止clock | 是 | 2B-TIME-007 | UT-RT-013 | 已关闭 |
| 14 | full dataset hash含未来数据，未来变化改历史对象 | decision/target visible hashes | Intent/Plan字段排除full interval hash | 是 | 2B-ID-003 | UT-RT-014 | 已关闭 |
| 15 | 输入 list 顺序改变 scale/item输出 | 无领域顺序输入先排序 | `(symbol,result_id)` Canonical排序 | 是 | 2B-PORT-002 | UT-RT-015 | 已关闭 |
| 16 | BTC_FIRST先耗尽现金，系统性拒绝ETH | 所有同刻先独立算再共同scale | batch target key；禁止sequential allocation | 是 | 2B-PORT-001/002 | UT-RT-016 | 已关闭 |
| 17 | ETH缩量后below minimum，把释放额度给BTC | scale只计算一次 | rejected item不触发重算 | 是 | 2B-PORT-004 | UT-RT-017 | 已关闭 |
| 18 | LONG/SHORT directional gap 公式互换 | adverse方向按side冻结 | GAP-F01分别定义并有monotonic property | 是 | 2B-GAP-001/002 | UT-RT-018 | 已关闭 |
| 19 | threshold相等因Decimal量化/`>=`随机拒绝 | equality必须接受 | 未量化P0/ATR，严格`>` | 是 | 2B-GAP-003 | UT-RT-019 | 已关闭 |
| 20 | tick量化让 stop/entry/TP重合 | final几何重新校验 | PRICE_GEOMETRY_INVALID | 是 | 2B-COST-005 | UT-RT-020 | 已关闭 |
| 21 | 输入负费用/数量或 Decimal NaN/Inf | 所有经济值有限且合法 | Schema/Cost snapshot fail DATA_INVALID | 是 | 2B-COST-004,2B-ID-002 | UT-RT-021 | 已关闭 |
| 22 | 多拒绝原因返回依赖 validator 调用顺序 | 收集事实后唯一priority | 2B_REJECTION_PRIORITY_V1 | 是 | 2B-ID-005 | UT-RT-022 | 已关闭 |
| 23 | contract values入Plan但rule hash/version留在ID外 | 所有语义依赖进入ID | coverage id/hash/version全在Plan | 是 | 2B-RULE-006 | UT-RT-023 | 已关闭 |
| 24 | dict/hash迭代顺序导致Canonical变化 | serializer完全确定 | sort keys/集合领域排序；100次fixture | 是 | 2B-ID-002 | UT-RT-024 | 已关闭 |
| 25 | 在2B添加 Fill/Position/Ledger helper | 2B只Plan | AST、symbol、dependency closure scope guard | 是 | 2B-SCOPE-004 | UT-RT-025 | 已关闭 |
| 26 | 不import HTTP，改用 subprocess/curl/socket反射联网 | 2B无任何间接I/O | scope guard查call graph/dynamic import/subprocess/env/file | 是 | 2B-SCOPE-001/005 | UT-RT-026 | 已关闭 |
| 27 | `available_balance`与各locked字段同时成为独立真相且矛盾 | 派生字段必须一致 | AS定义公式并在入口重算验证 | 是 | 2B-RISK-006 | UT-RT-027 | 原 BLOCKER B1，已关闭 |
| 28 | Plan同时保存可由字段推导的另一个input hash且两者矛盾 | 每个身份只有一个真相 | 不保存泛化plan_input_hash；plan_id由全字段唯一派生 | 是 | 2B-ID-001/002 | UT-RT-028 | 原 BLOCKER B2，已关闭 |
| 29 | 把实际 funding debit、Fill price、position state塞入2B | 2C事实不得进2B | Schema列举并Scope guard禁止 | 是 | 2B-SCOPE-004 | UT-RT-029 | 已关闭 |
| 30 | Requirement无测试或测试无Requirement | 双向集合必须相等 | acceptance matrix冻结 Test ID；未来CI反向检查 | 是 | 2B-SCOPE-005 | UT-RT-030 | 原 BLOCKER B3，已关闭 |

## 红队发现并关闭的 BLOCKER

| BLOCKER | 初始风险 | 关闭方式 | 关闭证据 |
|---|---|---|---|
| B1 账户余额双重真相 | `available_balance`、locks、pending 的包含关系不清，会双扣或重复使用 | 冻结 AS 公式：available 不含 pending，`deployable=available-pending_plan_reserve`；入口重算一致性 | Spec 5.10、CASH-F22、2B-RISK-006 |
| B2 泛化 input hash 与字段身份冲突 | 保存 `plan_input_hash` 又保存各字段，可能二者矛盾 | 删除泛化 plan input hash；只保留来源对象 hash 和由全字段派生的 plan_id | Spec 3.3、5.2、2B-ID-001 |
| B3 需求/测试追踪可能单向 | 文档有测试名但实现可新增孤儿测试 | 冻结 Requirement/Test 双集合 CI 规则和唯一 Test ID | Acceptance matrix 末节、2B-SCOPE-005 |
| B4 48h 起点在 Plan 与 Fill 间可能漂移 | 2B无Fill却要算funding upper bound | V1以 target execution time 为入场事件；2C Fill 必须同一 event time，否则路径 INVALID/提升版本 | TIME-F03、Spec 16 |
| B5 Exit trigger职责越界 | 2B若判断stop/TP会偷做2C | 冻结 `ExitConditionSnapshot` 为上游事实；2B只做未来open Intent/Plan | Spec 2、5.3、LIFE-004 |
| B6 target缺失的等待/失败混淆 | forward未到与历史缺口可能同reason | watermark未到只等待；watermark越过且缺失才实验 INVALID | Spec 11、Time TB-007–009 |

所有 BLOCKER 已在规格、需求矩阵和测试 ID 中关闭；剩余 BLOCKER：`0`。

## FOLLOW-UP（不阻塞 2B 规格）

1. 2C 必须验证实际 FillEvent 时间与 2B target 相同；否则不能继续使用 2B 的 48h funding reserve。
2. 2C Ledger 必须实现 wallet funding 只记一次，并用 reducer 证明 reserve 只是分类。
3. 2C 要单独冻结 stop/TP/estimated liquidation 的分钟内 baseline/conservative 路径；2B 不代替该设计。
4. 2D 报告必须分层展示 VERIFIED 与 APPROXIMATED，不能汇总伪装为同一证据等级。

## OPTIONAL

1. 人工审核可要求把 66 个 Requirement 再按未来实现 PR 拆成多个编码批次，但不得改变公式或边界。
2. 可增加形式化 JSON Schema 文件；若加入，它必须从本文字段生成并接受同一 Requirement 追踪，不能成为第二真相源。

## 最终红队结论

- BLOCKER：0 未关闭。
- FOLLOW-UP：4，均属于 2C/2D 明确后续边界。
- OPTIONAL：2，不影响 2B 冻结完整性。
- 2B 不存在需要编码时临时决定的问题。
