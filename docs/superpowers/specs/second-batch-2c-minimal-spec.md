# 第二批 2C 最小事件引擎冻结规范

状态：`DRAFT_FOR_ONE_TIME_HUMAN_REVIEW`

父基线：`b07cd9e7dd56cfb628400ef0878c6610d4d6b894`
目标：以最小、确定性的逐分钟事件闭环，把 2A `StrategyCandidate` 与 2B `EntryExecutionPlan` / `ExitExecutionPlan` 转化为可审计的历史模拟成交、逐仓仓位、账户状态、逐笔交易和权益序列。

## 1. 权威边界

- Python 确定性规则仍是唯一交易与撮合决策源；无 GUI、LLM、API Key、鉴权、HTTP 交易客户端或下单能力。
- 市场仅限 Binance USDⓈ-M `BTCUSDT`、`ETHUSDT` 永续，逐仓、单向持仓、固定 1 倍杠杆。
- 输入只接受已规范化、UTC、已收盘的 1m trade/mark 数据、真实历史资金费率、2A Candidate、2B Plan、版本化成本/合约/维持保证金证据。
- 2C 不重新生成 Candidate，不重新计算 2B quantity/risk，不修改 Plan；只验证、消费、撮合、记账。
- 爆仓永远称为“估算爆仓”；必须记录 maintenance-margin 模型版本、来源、有效期和 `VERIFIED|APPROXIMATED` 模式，不声称精确复刻 Binance。
- 不包含 Sharpe、Profit Factor、walk-forward、OOS 晋级、参数网格、仪表盘、通知、paper/live 自动化。

## 2. 架构与不可变输出

单线程 `MinuteEventEngine` 按 `(minute_open_utc_ms, path_kind)` 顺序运行纯 reducer：

1. `InputSlice`：该分钟可用的 trade/mark/funding/plan/contract/cost 数据及内容哈希。
2. `EngineState`：账户、BTC/ETH 逐仓仓位、待执行 Plan、峰值权益、路径状态。
3. `Event`：机器可读的事实，不携带可变 before/after 状态。
4. `LedgerEntry`：双边平衡的不可变经济变动。
5. `StateSnapshot`：由 reducer 根据前状态和 Event 生成；Event 不保存独立状态真相。
6. `TradeRecord`、`EquityPoint`、`PathResult`：Canonical JSON Lines，最终按稳定键排序并计算内容哈希。

路径状态闭集：`VALID | INVALID | HALTED`。`HALTED` 允许既有仓位退出但永久禁止新 Entry；`INVALID` 立即终止该路径，不再推演保护性成交或补造数据。

## 3. 数值、身份与守恒

- 价格、数量、手续费、资金费、保证金、余额、PnL 全用 `Decimal`；不得从 binary float 构造。
- trade/mark 指标或审计计算可用 `float64`，但进入任何经济边界前必须转回 Decimal 并按对应 tick/step 量化。
- Canonical 规则沿用 2B：UTF-8、键排序、无空白、枚举取值、UTC 毫秒整数、Decimal 规范字符串、数组顺序有语义。
- `simulation_run_id` 只依赖数据内容、样本区间、Candidate/Plan、成本/合约/资金费/爆仓模型版本、代码与依赖版本；采集时间和 acquisition manifest 不得进入。
- 相同 Canonical 输入必须逐字节产生相同 Event、Ledger、Trade、Equity 和最终 hash。
- 每个 reducer 后强制守恒：`equity = wallet_balance + unrealized_pnl`；`available_balance = wallet_balance - locked_initial_margin - locked_fee_reserve - locked_funding_reserve - pending_plan_reserve`。
- 同一 `plan_id` 只能消费一次；同一 funding timestamp、fee obligation、position close 只能入账一次。

## 4. 输入契约与可见性

每个市场分钟 `M=[M.open, M.open+60s)` 在引擎处理时必须已经闭合。策略可见性仍截止于 Plan/Candidate 的既有 decision watermark；2C 读取完整分钟 OHLC 仅用于历史成交与风险事件，不反向改变 Plan。

强制输入：

- trade 1m：open/high/low/close、open/close time、`is_closed=true`、内容 hash；用于 Entry、计划退出、stop、TP 和成交价格。
- mark 1m：open/high/low/close、`is_closed=true`、内容 hash；用于估算爆仓、未实现 PnL、equity/HALT。
- funding：symbol、nominal timestamp、真实 rate、结算 mark price 或可证明的 mark-open 绑定、内容 hash。
- Plan 证据：完整 2B Canonical 对象及所绑定成本、合约、账户和 batch hashes。
- maintenance margin：symbol、tier/notional range、mmr、effective interval、source hash、mode、model version。
- index 仍只作审计；缺失只告警，不改变路径状态。

缺口语义：空仓且无到期 Plan/事件时，trade 或 mark 缺口只记录；影响 Entry/Exit/持仓估值的 trade 缺口、持仓期间 mark 缺口、持仓跨越的 funding 结算缺失均从该分钟 `DATA_VALIDATION` 事件起将路径置为 `INVALID` 并终止。

## 5. 唯一逐分钟事件顺序

每一分钟严格执行以下顺序，版本名 `MINUTE_EVENT_ORDER_V1`：

1. `LOAD_CLOSED_INPUTS`：加载已闭合 trade/mark bar、该时点 funding、到期 Plan；校验 UTC、hash、连续性。
2. `FAIL_CLOSED_DATA_GATE`：按当前仓位和到期事件解释缺口；若关键缺失，写 `PATH_INVALID` 并终止。
3. `OPENING_POSITION_RECONCILIATION`：验证上分钟状态、Plan reservation、合约/成本/maintenance 版本有效期和一次消费集合。
4. `FUNDING_SETTLEMENT`：对进入该分钟前仍持有且结算时点命中的仓位结算真实资金费；同刻退出仍须结算，新 Entry 不结算。
5. `SCHEDULED_OPEN_EXITS`：按 `HALT_EXIT, TREND_EXIT, TIME_EXIT, EXPERIMENT_END` 优先级消费 ExitPlan，在 trade open 以 Plan 的 `expected_exit_fill_price` 成交。
6. `OPEN_EQUITY_AND_HALT_GATE`：用 mark open 重算权益；若相对历史峰值回撤 `>=10%`，先置 `HALTED`，本分钟禁止新 Entry。
7. `ENTRY_BATCH_GATE`：只接受处理时间前已存在、目标时间等于本分钟、未消费且未取消的完整 2B batch；先整体验证资金/风险/单向仓位，再按 `(symbol, plan_id)` 排序。
8. `ENTRY_FILLS`：以 `EntryExecutionPlan.expected_entry_fill_price` 作为实际模拟价，不再次加滑点；同时扣入场费、建立逐仓仓位并将 pending reserve 转为 margin/fee/funding locks。
9. `INTRAMINUTE_TRIGGER_DISCOVERY`：trade bar 检测 stop/TP，mark bar 检测估算爆仓；开盘已越过触发价视为 gap-at-open。
10. `AMBIGUITY_FORK`：若无法从 1m 数据确定多个触发的先后，为当前状态生成 `BASELINE` 与 `CONSERVATIVE` 子路径，均记录 `PATH_AMBIGUOUS`。
11. `PROTECTIVE_OR_LIQUIDATION_EXITS`：各路径只执行选中的唯一退出，扣退出费、释放锁定资金、实现 PnL、关闭仓位。
12. `MARK_TO_MARKET_CLOSE`：以 mark close 计算未实现 PnL，生成 wallet/margin/equity/available balance 快照和该分钟 equity point。
13. `INTRAMINUTE_DRAWDOWN_HALT`：用该分钟对组合最不利的 mark extremes 计算审计最低权益；最低或 close 权益相对历史峰值回撤 `>=10%` 即永久 `HALTED`。
14. `CANONICAL_COMMIT`：按稳定顺序写 Event/Ledger/Trade/Equity hashes，更新下分钟状态。

## 6. 成交、费用与资金费公式

### 6.1 Entry 与计划退出

- Entry actual fill 必须等于 2B `expected_entry_fill_price`；不得基于同一成本模型再次滑点。
- Scheduled Exit actual fill 必须等于 2B `ExitExecutionPlan.expected_exit_fill_price`。
- `fee = abs(quantity * fill_price) * effective_fee_rate`，入场与每次退出各扣一次；Plan 中 `entry_fee` 是校验值而不是第二次扣款。

### 6.2 stop、TP 与 gap

非 gap 触发以 trigger 为 reference，再施加一次退出方向的不利滑点；结果应等于同版本 Plan 的 expected protective fill。gap-at-open 时 reference 改为 trade open：卖出乘 `(1-slippage)`，买入乘 `(1+slippage)`，之后按 tick 以不利方向量化。禁止先使用已含滑点价格再重复滑点。

### 6.3 真实资金费

`notional = quantity * funding_mark_price`。令 `side_sign=+1` 表示 LONG、`-1` 表示 SHORT：

`wallet_delta = -(side_sign * notional * historical_funding_rate)`。

正费率时 LONG 支付、SHORT 收取；负费率相反。每个 nominal timestamp 每仓位恰好一次。资金费 reserve 按原风险上限逐事件释放，实际资金费只通过 wallet ledger 记一次；退出时释放剩余 reserve。

## 7. 逐仓仓位与估算爆仓

每个 symbol 最多一个 `IsolatedPosition`：side、quantity、entry time/price、initial margin、remaining fee/funding reserves、stop/TP、maintenance evidence、origin plan/batch hashes。BTC 与 ETH 可同时持仓，资金通过账户锁定字段共享但不可重复使用。

估算模型 `LINEAR_USDT_ISOLATED_LIQ_ESTIMATE_V1`：令 `M` 为当前逐仓 margin、`q` 为数量、`P` 为 entry price、`r` 为对应 tier 的 maintenance margin rate：

- LONG：`liq = max(0, (q*P - M) / (q*(1-r)))`
- SHORT：`liq = (M + q*P) / (q*(1+r))`

LONG 用 mark low、SHORT 用 mark high 检查；开盘已越过则使用 mark open 作为估算退出 reference，否则使用 liq。结果带 `ESTIMATED_NOT_EXCHANGE_EXACT` 水印。maintenance 证据缺失或超出有效期且当时有仓位，路径 `INVALID`。

## 8. 同分钟歧义双路径

先处理 gap-at-open；其优先于所有 intraminute 触发。剩余多个触发时：

- `BASELINE`：选择相对各自分钟 open 的绝对百分比距离最小者；相等时 `LIQUIDATION > STOP > TAKE_PROFIT`。
- `CONSERVATIVE`：枚举 1m OHLC 能支持的首触发候选，选择产生最低 minute-end equity 的结果；相等使用同一优先级。
- 两条路径均保存候选集合、选择理由和共同父 snapshot hash；即使结果相同也保留两条记录。
- 不允许用 close、未来分钟或后续资金费选择当分钟路径。

## 9. Trade、Ledger 与 Equity 输出

`TradeRecord` 至少包含：symbol、direction、entry_time、entry_price、exit_time、exit_price、quantity、entry_fee、exit_fee、total_fees、funding、gross_pnl、net_pnl、exit_reason、origin plan/candidate/batch IDs、path kind、内容 hash。

`gross_pnl`：LONG 为 `q*(exit-entry)`，SHORT 为 `q*(entry-exit)`；`net_pnl = gross_pnl - entry_fee - exit_fee + funding_wallet_delta_sum`。

Ledger 类型闭集：`ENTRY_FEE, EXIT_FEE, FUNDING, REALIZED_PNL, MARGIN_LOCK, MARGIN_RELEASE, FEE_RESERVE_LOCK/RELEASE, FUNDING_RESERVE_LOCK/RELEASE`。所有经济量只从 Ledger reducer 推导，不允许 TradeRecord 反向改账户。

每分钟每路径至少一个 `EquityPoint`：event time、wallet、locked margin/reserves、available、unrealized、equity、peak、drawdown、path state、state hash。

## 10. 冻结 Requirements（48）

| 范畴 | Requirement IDs | 数量 |
|---|---|---:|
| 生命周期与顺序 | `2C-LIFE-001..008` | 8 |
| 成交与触发 | `2C-FILL-001..008` | 8 |
| 费用与资金费 | `2C-COST-001..006` | 6 |
| 仓位与爆仓 | `2C-POS-001..006` | 6 |
| 账户与风险 | `2C-ACCT-001..007` | 7 |
| 数据与路径 | `2C-DATA-001..005` | 5 |
| 身份与回放 | `2C-ID-001..004` | 4 |
| 范围与安全 | `2C-SCOPE-001..004` | 4 |
| **总计** |  | **48** |

逐项语义由验收矩阵唯一展开；实现不得新增未评审的 Requirement 或改变事件顺序版本。

## 11. 进入编码的硬门槛

- 四份文档经人工一次性审核明确批准。
- 48 项 Requirement、16 个 timeline fixtures、24 个 red-team 场景无语义冲突。
- 2B Plan 消费、资金费边界、费用不重复、双路径和 INVALID/HALTED 终止语义全部冻结。
- 编码阶段仍不得加入 GUI、LLM、API Key、网络交易或 paper/live 自动化。
