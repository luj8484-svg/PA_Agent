# 第二批生命周期、风险与 1 分钟事件规范

日期：2026-07-13
修订日期：2026-07-14
状态：设计评审稿；未授权 2B/2C 实施

## 1. 固定版本提案

```text
ENTRY_EXECUTION_PLAN_SCHEMA_V1
EXIT_EXECUTION_PLAN_SCHEMA_V1
EXECUTION_REJECTION_SCHEMA_V1
FILL_EVENT_SCHEMA_V1
EXEC_DELAY_V1_NEXT_4H_OPEN_PLUS_MINUTES
FEE_V1_ASSUMED_TAKER_5BP
SLIPPAGE_V1_BASE
FUNDING_BUFFER_V2_SCHEDULE_MAX_COUNT
FUNDING_SCHEDULE_ASSUMED_8H_V1
RISK_V1_SINGLE_0P5_PORTFOLIO_1P0
PORTFOLIO_SCALE_V1_SIMULTANEOUS_NO_REDISTRIBUTION
MARGIN_MODE_V1_ISOLATED_ONE_WAY_1X
MM_EST_V1_LINEAR_TIER
LIQ_EST_V1_MARK_OHLC
PATH_POLICY_V1_BASELINE_CONSERVATIVE
HALT_V2_1M_CLOSE_EQUITY_10PCT
INTRAMINUTE_DRAWDOWN_AUDIT_V1
```

修改任何公式、优先级、枚举或量化方向必须提升对应版本。

## 2. EntryExecutionPlan 与 ExitExecutionPlan

共享一个带大量条件字段的 `ExecutionPlan` 被禁止。入场和退出是两个独立、不可变 Schema；二者可以实现共享的只读协议，但不得以 `plan_kind` 加 nullable 字段模拟联合类型。

### 2.1 EntryExecutionPlan 字段

```text
schema_version
plan_id
candidate_id
symbol
side = LONG | SHORT
decision_time_utc_ms
eligible_time_utc_ms
plan_created_time_utc_ms
expires_time_utc_ms
order_type = MARKET_AT_1M_OPEN
trigger_basis = TRADE_1M
reference_price
entry_fill_price              # ENTRY
stop_trigger_price
take_profit_trigger_price
stop_fill_estimate
quantity
notional
unit_risk
planned_risk
risk_budget
initial_margin
entry_fee
exit_fee_reserve
funding_reserve
required_cash
leverage = 1
margin_mode = ISOLATED
position_mode = ONE_WAY
execution_delay_minutes
execution_delay_version
fee_version
slippage_version
funding_buffer_version
risk_version
portfolio_scaling_version
contract_rule_mode
contract_rule_version
contract_rule_content_hash
maintenance_margin_version
liquidation_estimate_version
decision_visible_input_hash
execution_data_content_hash
config_hash
code_commit
dependency_lock_hash
```

Entry Plan 生成后不可变。其 reference/fill/stop/TP/quantity 只能在目标执行分钟已可见的 1m open 到达后产生，不能在 Candidate 时提前写入。

### 2.2 ExitExecutionPlan 字段

```text
schema_version
plan_id
origin_event_id
origin_candidate_id
position_id
symbol
side = LONG | SHORT
exit_reason = STOP | TAKE_PROFIT | TIME_EXIT | TREND_EXIT | HALT_EXIT | EXPERIMENT_END | ESTIMATED_LIQUIDATION
decision_time_utc_ms
eligible_time_utc_ms
plan_created_time_utc_ms
expires_time_utc_ms
order_type
trigger_basis
reference_price
quantity
execution_delay_minutes
execution_delay_version
fee_version
slippage_version
contract_rule_mode
contract_rule_version
contract_rule_content_hash
execution_data_content_hash
config_hash
code_commit
dependency_lock_hash
```

Exit Plan 不复制 Entry Plan 的 initial margin、入场 fee、stop、TP、funding reserve、unit risk 或风险预算字段。由分钟内估算强平直接产生的强制退出可以在同一原子事件内生成并消费 Exit Plan，但仍须保留独立 `plan_id`。

### 2.3 plan_id 与领域时间源

`plan_id` 是上述字段去除 `plan_id` 后的 Canonical SHA-256 前 24 hex，前缀 `plan_`。acquisition metadata 不参与。

Candidate、Entry/Exit Plan、Rejection、Fill、Event、Ledger 和 StateSnapshot 的所有时间只能来自市场事件时钟或实验事件时钟。允许来源是已验证 bar/funding timestamp、由冻结规则从其确定性推导的 eligible/expiry timestamp，以及实验清单冻结的起止边界。禁止调用本地 wall clock 填充 `created_at` 或参与领域对象及确定性 ID；下载/报告 wall-clock 元数据必须位于领域外壳并排除在内容哈希之外。

## 3. ExecutionRejection

```text
schema_version
rejection_id
candidate_id
symbol
rejected_at_utc_ms
stage = EXECUTION_DATA | CONTRACT | GAP | POSITION | RISK | CASH | QUANTIZATION | HALT
reason
observed_values
required_values
relevant_version_hashes
path_id
```

原因枚举：

```text
EXECUTION_DATA_MISSING
EXECUTION_TARGET_MINUTE_MISSING
GAP_TOO_LARGE
CONTRACT_RULE_UNAVAILABLE
CONTRACT_RULE_EXPIRED
MAINTENANCE_MARGIN_UNAVAILABLE
EXISTING_POSITION
EXPERIMENT_HALTED
RISK_LIMIT
INSUFFICIENT_MARGIN
BELOW_MIN_QTY
BELOW_MIN_NOTIONAL
QUANTITY_ZERO_AFTER_SCALING
PLAN_EXPIRED
PRICE_GEOMETRY_INVALID
```

Rejection 不得改写或删除 LONG/SHORT Candidate。市场报告和执行拒绝报告必须分栏。

## 4. FillEvent

```text
schema_version
fill_id
plan_id
candidate_id
path_id
symbol
side
action
fill_time_utc_ms
fill_reason
quantity
reference_price
slippage_rate
slippage_amount
fill_price
notional
fee_rate
fee_amount
execution_data_content_hash
fee_version
slippage_version
code_commit
```

- `fill_price` 已含本次滑点。
- `slippage_amount=abs(fill_price-reference_price)*quantity` 仅审计；PnL、费用和 unit risk 不再扣一次。
- 所有退出为全平，不允许部分 fill。
- `fill_id` 按去除自身后的 Canonical bytes 派生。
- FillEvent 只保存已经发生的交易事实，不保存 `cash_before/after`、`position_quantity_before/after` 或账户快照。状态前后值只能由 Ledger reducer 以旧 StateSnapshot 加 FillEvent 推导；若测试中保留 before/after，只能作为 reducer assertion，禁止作为另一状态源持久化。

## 5. 费用、滑点与量化

### 5.1 常量

- taker fee `f=Decimal("0.0005")`。
- BTC baseline 单边滑点 `s=Decimal("0.0001")`。
- ETH baseline 单边滑点 `s=Decimal("0.0002")`。
- 成本压力 run 同时将 fee/slippage 乘 `1.5` 或 `2.0`；真实 funding 不乘压力倍数。

### 5.2 定向价格

```text
LONG entry  = ceil_to_tick(P0*(1+s))
SHORT entry = floor_to_tick(P0*(1-s))

LONG stop trigger  = ceil_to_tick(entry_fill-2*ATR)
SHORT stop trigger = floor_to_tick(entry_fill+2*ATR)

LONG TP trigger  = floor_to_tick(entry_fill+3*ATR)
SHORT TP trigger = ceil_to_tick(entry_fill-3*ATR)

LONG stop estimate  = floor_to_tick(stop_trigger*(1-s))
SHORT stop estimate = ceil_to_tick(stop_trigger*(1+s))
```

若 LONG stop/TP 不满足 `stop < entry < TP`，或 SHORT 不满足 `TP < entry < stop`，仅对该笔计划产生 `ExecutionRejection/PRICE_GEOMETRY_INVALID`；Candidate 和其他 symbol/时刻的实验路径继续。只有由非有限数、Schema/版本不一致或无法重放等系统性错误导致价格几何无法判断时，才按对应数据/数值原因使路径 INVALID。价格几何拒绝依赖 entry fill、ATR 和 tick 量化，因此不属于 Candidate ValidationFailure，也不属于市场无 setup。

实际退出 fill：

- 市价/开盘退出使用当前 trade 1m open 作为 reference，再按退出方向施加滑点和定向 tick 量化。
- 盘中 stop 使用 stop trigger 为 reference，再施加退出滑点。
- 盘中 TP 使用 TP trigger 为 reference，再施加退出滑点。
- 估算强平使用估算 liquidation trigger 作为 reference，并记录 `ESTIMATED_LIQUIDATION`；不额外假装知道 Binance 清算成交价。

### 5.3 手续费

```text
fee_amount = abs(quantity * fill_price) * f
```

手续费使用 Decimal，不额外按 tick/step 量化；Canonical 存储完整 Decimal。若未来使用交易所实际费用精度，必须提升 fee version。

### 5.4 GAP_TOO_LARGE 的冻结定义

版本：`ENTRY_GAP_FILTER_V1_DIRECTIONAL_ATR`。只对到期 LONG/SHORT Entry Candidate 检查：

```text
P0 = 目标执行分钟、施加滑点前的 trade 1m open
decision_close = Candidate 冻结的当前 4H close
atr_snapshot = Candidate 冻结的 ATR14_4H

LONG directional_gap  = P0 - decision_close
SHORT directional_gap = decision_close - P0

reject GAP_TOO_LARGE iff
  directional_gap > gap_atr_multiple * atr_snapshot
```

- 基准 `gap_atr_multiple=Decimal("0.5")`；`ROBUSTNESS_HEURISTIC_V1` 仅测试 `0.4/0.5/0.6`。
- 负的 directional gap 表示价格向有利方向或反向跳空，接受；等于阈值也接受，比较必须严格 `>`。
- `P0`、decision close、ATR 都使用未按 contract tick 量化的冻结参考值；Entry fill 随后才施加滑点和 tick 量化。
- ATR 非有限/非正、目标分钟缺失或 reference price 非正属于数据/数值失败，不得伪装为 `GAP_TOO_LARGE`。
- LONG/SHORT 方向、参考价、ATR snapshot、multiple、directional gap 和阈值必须写入 Rejection 的 observed/required values。

## 6. 资金费

对结算前已持仓的数量 `q>0`：

```text
funding_cash_change = -side_sign * q * settlement_mark_price * funding_rate
LONG side_sign = +1
SHORT side_sign = -1
```

- 只使用第一批保存的真实 funding rate 和返回的 settlement mark price。
- 结算时刻前已有仓位先结算；同刻退出在后；同刻新仓不参与本次结算。
- funding 经济变化只记一次 wallet debit/credit；估算 isolated margin 视图引用该笔变化，不得再次经济扣款。
- 缺少结算记录、币种不符、mark price 非正或时刻不覆盖持仓：路径 `INVALID/FUNDING_EVENT_MISSING_OR_INVALID`，不按零回填。

V1 资金费时刻表 `FUNDING_SCHEDULE_ASSUMED_8H_V1` 使用 UTC `00:00/08:00/16:00`，并保守允许每个名义结算时刻的实际事件位于 `[nominal-1000ms, nominal+1000ms]`。缓冲结算次数不是固定常数：

```text
max_settlement_count = count of schedule settlement windows
                       that can intersect (entry_time, exit_time]
funding_buffer_per_unit = entry_fill * 0.0001 * max_settlement_count
```

`max_settlement_count(schedule_version, entry_time, exit_time)` 必须枚举版本化 schedule 窗口并取最大可能次数。48 小时持有期在该保守边界下最多为 7 次：入口附近名义时刻可能在 entry 后结算，且终点附近时刻仍落入 `(entry, exit]`；因此不得固定乘 6。实际 funding 仍严格按真实事件逐笔结算，缓冲次数只用于 sizing/reserve。

真实 funding 始终完整计入 wallet：不利 funding 先按 `min(abs(cash_change), remaining_funding_reserve)` 消耗 reserve 分类，同时只对 wallet 记一次 debit；超出 reserve 的部分仍只记一次 wallet debit 并产生 `FUNDING_RESERVE_EXCEEDED`。有利 funding 对 wallet 记一次 credit，但不增加或提前释放 reserve。reserve 只是 wallet 内的一项可用资金锁定，不是独立资产或损失上限；平仓时释放剩余锁定。

## 7. unit risk、仓位与现金

### 7.1 单位风险

```text
price_loss_per_unit = abs(entry_fill-stop_fill_estimate)
entry_fee_per_unit = entry_fill*f
exit_fee_per_unit = stop_fill_estimate*f
funding_buffer_per_unit = entry_fill*0.0001*max_settlement_count(
  FUNDING_SCHEDULE_ASSUMED_8H_V1, entry_time, exit_time
)

unit_risk = price_loss_per_unit
          + entry_fee_per_unit
          + exit_fee_per_unit
          + funding_buffer_per_unit

risk_budget = pre_entry_equity*0.005
raw_quantity = risk_budget/unit_risk
quantity = floor_to_step(raw_quantity)
```

数量量化后重新计算全部金额。不得向上取整满足 minQty/minNotional。

### 7.2 1 倍逐仓现金需求

```text
notional = abs(quantity*entry_fill)
initial_margin = notional
entry_fee = notional*f
exit_fee_reserve = abs(quantity*stop_fill_estimate)*f
funding_reserve = quantity*entry_fill*0.0001*max_settlement_count(
  FUNDING_SCHEDULE_ASSUMED_8H_V1, entry_time, exit_time
)
required_cash = initial_margin+entry_fee+exit_fee_reserve+funding_reserve
```

### 7.3 账户、Ledger 与隔离保证金视图

Ledger reducer 冻结以下唯一会计定义：

```text
wallet_balance    = 初始钱包 + realized_pnl - fees + funding_cash_changes
locked_margin     = 已成交逐仓仓位锁定的 initial margin
fee_reserve       = 存量仓位的退出费用锁定 + 已批准未成交 Entry Plan 的入场/退出费用锁定
funding_reserve   = 所有存量仓位和已批准未成交 Entry Plan 的资金费锁定
plan_margin_lock  = 已批准未成交 Entry Plan 的入场保证金锁定
available_balance = wallet_balance
                    - locked_margin
                    - fee_reserve
                    - funding_reserve
                    - plan_margin_lock
unrealized_pnl    = 按当前 mark 估值的未实现损益
equity            = wallet_balance + unrealized_pnl
```

`locked_margin`、各 reserve 和 plan lock 都是 wallet 内部分类，不是额外经济扣款。开仓时释放 Entry Plan 的入场 fee lock、对 wallet 记一次 entry fee，并把其余分类迁移为持仓锁定；平仓释放分类、记一次 exit fee 和一次 realized PnL。Funding 只能产生一笔 wallet debit/credit；isolated margin balance 是由仓位初始分配、该仓位归属的 funding adjustment 和 unrealized PnL 派生的风控视图，不是第二本现金账。

若不利 funding 超过 reserve，记录 `FUNDING_RESERVE_EXCEEDED` 并立即重新计算 available balance 和估算强平。若未触发估算强平但 `available_balance < 0`，V1 不允许外部补款、借贷或跨仓转账，路径进入经济终态 `BANKRUPT`；这不是数据 `INVALID`。每个事件原子提交 `LedgerDelta` 和 reducer 生成的 `StateSnapshot`，其 before/after 只由 reducer 重放验证。

### 7.4 开放风险

每个仓位在入场时冻结：

```text
reserved_open_risk = planned_risk
```

固定 stop 的 V1 在退出前不降低该值；已付 entry fee 也不从该安全额度返还。这样组合开放风险是保守且与事件顺序无关的。新计划的剩余风险：

```text
remaining_risk = max(0, current_equity*0.01-sum(reserved_open_risk))
```

## 8. 同时计划等比例缩量

同一 `eligible_time_utc_ms` 的所有 ENTRY 草案按 symbol 排序只用于 Canonical 输出，不用于分配。

```text
scale = min(
  1,
  remaining_risk / sum(unscaled_planned_risk),
  available_balance / sum(unscaled_required_cash)
)

scaled_qty_i = floor_to_step(raw_qty_i*scale)
```

缩量后对每个 symbol 重新计算风险、现金、minQty、minNotional 和价格几何：

- 不把量化释放的剩余资金二次分配。
- 量化为零或低于最小值的单独拒绝。
- 其他计划不因一个计划被拒绝而重新放大。
- `BTC_FIRST`、`ETH_FIRST` 和输入 dict 顺序必须产生逐字节相同结果。

### 8.1 同时缩量 Golden Fixture

版本：`PORTFOLIO_SCALE_GOLDEN_V1_SYNTHETIC`。这是纯数学 fixture，不声称代表任何历史 Binance contract rule：

```text
remaining_risk = 750
sum(unscaled_planned_risk) = 1000       => risk_scale = 0.75
available_balance = 90000
sum(unscaled_required_cash) = 100000    => cash_scale = 0.90
scale = min(1, 0.75, 0.90) = 0.75

BTC raw_quantity = 1.001, step = 0.001  => scaled_quantity = 0.750
ETH raw_quantity = 10.01, step = 0.01   => scaled_quantity = 7.50
ETH synthetic minQty = 8.00              => BELOW_MIN_QTY
```

ETH 拒绝后 BTC 必须保持 `0.750`，不得把 ETH 释放的风险或现金重新分配。`[BTC,ETH]`、`[ETH,BTC]`、`BTC_FIRST` 和 `ETH_FIRST` 的 Plan/Rejection Canonical bytes、最终锁定金额和状态 hash 必须完全相同。

## 9. 历史 contract rule 模式

### 9.1 VERIFIED

`VERIFIED` 版本必须包含：symbol、tick、step、minQty、minNotional、状态、来源、原始证据 hash、`effective_from`、`effective_to`、审核人/流程和 schema version。回放 timestamp 必须落在半开区间 `[effective_from,effective_to)`；版本不得重叠。

### 9.2 APPROXIMATED

`APPROXIMATED` 可以用于独立诊断和带水印的 paper simulation 研究：

- 来源可以是当前 exchangeInfo、最接近快照或官方公开规则重建。
- 必须记录 approximation method、距离回放时刻、假设有效区间和证据 hash。
- 实验 ID 和报告标题必须包含 `APPROXIMATED`。
- Paper simulation 的样本交集使用已审批 `APPROXIMATED` 规则版本自身声明的有效覆盖区间，不强制叠加 VERIFIED 覆盖；审批证据、有效期和压力测试必须完整保留。
- APPROXIMATED 结果不能与 VERIFIED 结果合并统计，必须进行规则区间和成本压力测试，只能支持无真实资金的 Paper Simulation Gate。
- APPROXIMATED 永远不能直接支持 Live Eligibility Gate、实盘链路或自动交易。

Live Eligibility 相关严格实验使用 `CONTRACT_POLICY_VERIFIED_ONLY_V1`。缺少 VERIFIED 覆盖时保留 Candidate，ExecutionRejection=`CONTRACT_RULE_UNAVAILABLE`；若持仓期间规则/maintenance coverage 消失，路径 INVALID。

## 10. 维持保证金和估算强平

### 10.1 maintenance tier

版本记录每个 notional tier 的 lower/upper bound、MMR、cumulative deduction、来源、hash、有效期和 VERIFIED/APPROXIMATED 模式。

```text
maintenance_margin(P) = abs(q*P)*mmr-cumulative_deduction
```

若计算值小于零，数据/版本非法，不能 clamp 为零。

### 10.2 估算模型

版本：`MM_EST_V1_LINEAR_TIER` / `LIQ_EST_V1_MARK_OHLC`。令：

- `E` 为 entry fill。
- `q>0`。
- `B` 为当前估算 isolated margin balance，初值为 initial margin，之后由 funding cash changes 调整。
- `D` 为 tier cumulative deduction。
- `m` 为 MMR。

在单一 tier 内：

```text
LONG estimated_liquidation_price
  = (q*E-B-D)/(q*(1-m))

SHORT estimated_liquidation_price
  = (B+q*E+D)/(q*(1+m))
```

求解后必须重新选择该价格对应 tier 并迭代，直到 tier 稳定；最多遍历全部 tier 一次。无稳定 tier、分母非正、价格非正或版本缺失均使路径 INVALID。

估算触发条件：

```text
isolated_margin_balance + unrealized_pnl(mark_price)
<= maintenance_margin(mark_price)
```

该模型不包含 Binance 的保险基金、实际 liquidation fee、ADL、实时 wallet 细节、逐笔 mark path 或交易所内部舍入，因此输出只能称 `estimated_liquidation`。

## 11. 1 分钟事件顺序

每个 UTC minute `t` 以一个原子 transaction 处理。任何阶段 INVALID 后不得继续假设保护措施有效。

1. **上下文数据门**：判断 trade/mark/funding/contract 缺口在当前空仓、计划、持仓和结算上下文中是否关键。
2. **资金费结算**：对 `t` 前已持有且跨越结算点的仓位结算真实 funding。
3. **mark open 强平检查**：若 mark open 已满足估算强平条件，两条路径均先产生 EstimatedLiquidationEvent。
4. **trade open 风险退出**：对存量仓位依次检查 stop gap、HALT_EXIT、TIME_EXIT、TREND_EXIT、TP gap；相同 open fill 时原因优先级按此顺序冻结。
5. **到期 ExitExecutionPlan**：执行未在步骤 4 处理的确定性规则退出。
6. **到期 ENTRY Candidate**：读取该分钟 open，生成 EntryExecutionPlan/拒绝；同刻全部 ENTRY 共同缩量，退出释放的现金可用。
7. **ENTRY Fill**：执行批准的 EntryExecutionPlan；同刻新仓不参与步骤 2 funding。
8. **分钟内触发集合**：用 trade high/low 判断 stop/TP，用 mark high/low 判断估算强平。
9. **路径政策**：按 baseline/conservative 决定无法排序的分钟内事件。
10. **分钟 close 估值**：使用 mark close 更新未实现 PnL、equity、peak equity 和 drawdown。
11. **HALT 与盘中审计**：1m close equity drawdown `>=10%` 产生 `1M_CLOSE_EQUITY_HALT_TRIGGERED`；保留所有市场 Candidate，取消已批准未成交 Entry Plan，后续 LONG/SHORT Candidate 在执行层产生 `EXPERIMENT_HALTED`。现有仓位在下一有效 1m open 退出。另用本分钟 mark OHLC 不利极值计算盘中回撤估算并记录审计事件。
12. **4H/1D close 后处理**：仅在相应 bar 已收盘后更新指标、生成新 Candidate 或趋势 EXIT intent；它们最早在未来版本化执行时刻生效。
13. **原子提交**：同时写事件、ledger delta、state hash 和 minute commit hash。

步骤 1–13 版本化为 `MINUTE_EVENT_ORDER_V1`。

### 11.1 intraminute drawdown breach 审计

`INTRAMINUTE_DRAWDOWN_AUDIT_V1` 必须在步骤 2–7 的 open 事件全部处理完成后、步骤 8 分钟内 stop/TP/强平触发前，冻结 `intraminute_open_position_snapshot`。审计只使用该快照中的仓位：LONG 使用本分钟 mark low，SHORT 使用 mark high 估算最低 equity；open 已退出的仓位不纳入，open 新入场的仓位纳入。多 symbol 时把各自不利极值同时相加作为保守代理，明确标记为非同步路径估算而非可成交的精确组合轨迹。

```text
estimated_intraminute_drawdown
  = (peak_close_equity - conservative_intraminute_equity)
    / peak_close_equity
```

估算值 `>=10%` 记录 `INTRAMINUTE_DRAWDOWN_BREACH_ESTIMATE`，与 close HALT 使用相同的包含边界。它不替代也不提前触发基于 1m close 的 `1M_CLOSE_EQUITY_HALT`，但锁定 OOS 只要出现一次该事件，就不得通过 Paper Simulation 或 Live Eligibility 的 forward gate，即使该分钟 close 未触发 HALT。

## 12. baseline/conservative 和 PATH_AMBIGUOUS

### 12.1 开盘可排序

- mark open 已估算强平：两路径均强平，后续 stop/TP/计划不执行。
- mark open 未强平但 trade open 越过 stop：两路径均 stop gap 退出。
- 已在 open 退出的仓位不再检查该分钟 high/low。

### 12.2 分钟内不可排序

当 open 未触发，但同一分钟范围显示多个事件可能发生：

| 命中集合 | baseline | conservative | 记录 |
|---|---|---|---|
| stop + TP | stop | stop | `STOP_TP_BOTH_HIT` |
| stop + liquidation | stop | liquidation | `PATH_AMBIGUOUS` |
| TP + liquidation | TP | liquidation | `PATH_AMBIGUOUS` |
| stop + TP + liquidation | stop | liquidation | `PATH_AMBIGUOUS` + `STOP_TP_BOTH_HIT` |
| 仅 stop | stop | stop | 无歧义 |
| 仅 TP | TP | TP | 无歧义 |
| 仅 liquidation | liquidation | liquidation | 无歧义 |

两条路径从同一个 minute-start state 深复制，使用相同数据/配置 hash，之后拥有独立 path ID、事件、账本、terminal state 和报告。禁止在分钟结束后挑选表现较好的路径。

## 13. 缺口上下文

- trade 缺失且影响 Candidate 所需 4H/1D 聚合、入场、退出或持仓保护：路径 `INVALID`。
- mark 缺失且有持仓或需估值/强平检查：路径 `INVALID`。
- mark 缺失但空仓、无到期计划且无相关事件：记录缺口，不阻断 Candidate。
- funding 结算点缺失且仓位跨越：路径 `INVALID`。
- contract/maintenance 版本在持仓期间无覆盖：路径 `INVALID`。
- Index 始终只产生审计告警。

INVALID 立即停止该路径，不继续现金曲线、不计算完整区间年化。

## 14. 退出和终态

- Stop/TP 固定，全平。
- 时间退出：首个 `timestamp >= fill_time+48h` 的有效 1m open。
- 趋势退出：4H close 时观察最近有效 1D；LONG 不再 BULL、SHORT 不再 BEAR 时创建下一 `EXEC_DELAY_V1` 时刻 EXIT intent。
- 同 symbol 持仓期间的新 LONG/SHORT Candidate 保留，但入场执行拒绝 `EXISTING_POSITION`。
- 退出后最早从下一根完整 4H close 重新生成可执行 setup。

终态：

```text
COMPLETED   正常到实验终点且仓位已按终点退出
INVALID     关键数据/版本/数值无法继续
HALTED      1M_CLOSE_EQUITY_HALT 触发并完成下一有效 open 全平
BANKRUPT    经济余额不足且 V1 不允许补款/借贷，数据本身仍可有效
```

`1M_CLOSE_EQUITY_HALT_TRIGGERED` 后禁止新仓，但市场层继续生成并保存 Candidate；未成交 EntryExecutionPlan 被取消，后续 LONG/SHORT Candidate 在执行层得到 `EXPERIMENT_HALTED`。若下一 open 所需关键数据缺失，终态为 INVALID 而非 HALTED。HALTED/INVALID/BANKRUPT 后不延长现金曲线，报告实际 terminal time、存续天数和删失原因。

## 15. 2B/2C 必须证明的性质

1. Candidate 不因 contract/risk/cash 失败消失。
2. fill 已含滑点且不会重复扣除。
3. 同时缩量与输入顺序无关。
4. 资金、margin 和 reserve 不重复使用。
5. 同刻 funding、退出和入场符合冻结顺序。
6. 所有分钟内组合命中矩阵都有 baseline/conservative Golden Fixture。
7. 关键数据缺失后没有任何假设 stop 或伪造 fill。
8. APPROXIMATED 结果只能通过带水印、压力测试后的 Paper Simulation Gate，不能通过 Live Eligibility Gate。
9. 1m close 或盘中估算回撤恰好 10% 均命中各自 `>=10%` 边界；盘中估算命中但 close 未触发时只记审计，并阻断 forward gate。
10. 所有事件和账本重复运行逐字节一致，且 wall clock 变化不改变任何领域对象或确定性 ID。
11. Funding 在 wallet 与 isolated 风控视图中只产生一次经济扣款，reserve 超额和 BANKRUPT 路径均有 Golden Fixture。
12. FillEvent 不含状态 before/after，StateSnapshot 可由相同事件流经 Ledger reducer 唯一重建。
