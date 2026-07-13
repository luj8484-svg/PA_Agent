# 第二批生命周期、风险与 1 分钟事件规范

日期：2026-07-13
状态：设计评审稿；未授权 2B/2C 实施

## 1. 固定版本提案

```text
EXECUTION_PLAN_SCHEMA_V1
EXECUTION_REJECTION_SCHEMA_V1
FILL_EVENT_SCHEMA_V1
EXEC_DELAY_V1_NEXT_4H_OPEN_PLUS_MINUTES
FEE_V1_ASSUMED_TAKER_5BP
SLIPPAGE_V1_BASE
FUNDING_BUFFER_V1_1BP_X6
RISK_V1_SINGLE_0P5_PORTFOLIO_1P0
PORTFOLIO_SCALE_V1_SIMULTANEOUS_NO_REDISTRIBUTION
MARGIN_MODE_V1_ISOLATED_ONE_WAY_1X
MM_EST_V1_LINEAR_TIER
LIQ_EST_V1_MARK_OHLC
PATH_POLICY_V1_BASELINE_CONSERVATIVE
HALT_V1_CLOSE_EQUITY_10PCT
```

修改任何公式、优先级、枚举或量化方向必须提升对应版本。

## 2. ExecutionPlan

### 2.1 字段

```text
schema_version
plan_id
plan_kind = ENTRY | EXIT
candidate_id                  # ENTRY 必填，规则退出可为空
origin_event_id               # EXIT 必填
symbol
side = LONG | SHORT
action = OPEN | CLOSE
decision_time_utc_ms
eligible_time_utc_ms
plan_created_time_utc_ms
expires_time_utc_ms
order_type = MARKET_AT_1M_OPEN
trigger_basis = TRADE_1M
reference_price
entry_fill_price              # ENTRY
stop_trigger_price            # ENTRY
take_profit_trigger_price     # ENTRY
stop_fill_estimate            # ENTRY
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
strategy_data_content_hash
execution_data_content_hash
config_hash
code_commit
dependency_lock_hash
```

Plan 生成后不可变。ENTRY Plan 的 reference/fill/stop/TP/quantity 只能在目标执行分钟已可见的 1m open 到达后产生，不能在 Candidate 时提前写入。

### 2.2 plan_id

`plan_id` 是上述字段去除 `plan_id` 后的 Canonical SHA-256 前 24 hex，前缀 `plan_`。acquisition metadata 不参与。

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
position_quantity_before
position_quantity_after
cash_before
cash_after
execution_data_content_hash
fee_version
slippage_version
code_commit
```

- `fill_price` 已含本次滑点。
- `slippage_amount=abs(fill_price-reference_price)*quantity` 仅审计；PnL、费用和 unit risk 不再扣一次。
- 所有退出为全平，不允许部分 fill。
- `fill_id` 按去除自身后的 Canonical bytes 派生。

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

若 LONG stop/TP 不满足 `stop < entry < TP`，或 SHORT 不满足 `TP < entry < stop`，应产生 `ExecutionRejection/PRICE_GEOMETRY_INVALID` 并使实验 fail closed。它依赖 entry fill、ATR 和 tick 量化，因此属于执行边界错误，不属于 Candidate ValidationFailure，也不属于市场无 setup。

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

## 6. 资金费

对结算前已持仓的数量 `q>0`：

```text
funding_cash_change = -side_sign * q * settlement_mark_price * funding_rate
LONG side_sign = +1
SHORT side_sign = -1
```

- 只使用第一批保存的真实 funding rate 和返回的 settlement mark price。
- 结算时刻前已有仓位先结算；同刻退出在后；同刻新仓不参与本次结算。
- funding 现金变化同时进入账户现金和估算 isolated margin balance，明确这是 `MM_EST_V1` 的保守研究假设。
- 缺少结算记录、币种不符、mark price 非正或时刻不覆盖持仓：路径 `INVALID/FUNDING_EVENT_MISSING_OR_INVALID`，不按零回填。

仓位 sizing 缓冲：

```text
funding_buffer_per_unit = entry_fill * 0.0001 * 6
```

真实 funding 始终完整计入现金：不利 funding 先按 `min(abs(cash_change), remaining_funding_reserve)` 消耗 reserve，超出 reserve 的部分仍继续减少现金；有利 funding 增加现金但不增加或提前释放 reserve。reserve 只是一项可用资金锁定，不是损失上限；平仓时释放剩余 reserve。

## 7. unit risk、仓位与现金

### 7.1 单位风险

```text
price_loss_per_unit = abs(entry_fill-stop_fill_estimate)
entry_fee_per_unit = entry_fill*f
exit_fee_per_unit = stop_fill_estimate*f
funding_buffer_per_unit = entry_fill*0.0001*6

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
funding_reserve = quantity*entry_fill*0.0001*6
required_cash = initial_margin+entry_fee+exit_fee_reserve+funding_reserve
```

`available_cash` 是账户现金减去所有已锁定 initial margin、退出费用 reserve、funding reserve 和已批准未成交 Plan reserve。资金不能重复使用。

### 7.3 开放风险

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
  available_cash / sum(unscaled_required_cash)
)

scaled_qty_i = floor_to_step(raw_qty_i*scale)
```

缩量后对每个 symbol 重新计算风险、现金、minQty、minNotional 和价格几何：

- 不把量化释放的剩余资金二次分配。
- 量化为零或低于最小值的单独拒绝。
- 其他计划不因一个计划被拒绝而重新放大。
- `BTC_FIRST`、`ETH_FIRST` 和输入 dict 顺序必须产生逐字节相同结果。

## 9. 历史 contract rule 模式

### 9.1 VERIFIED

`VERIFIED` 版本必须包含：symbol、tick、step、minQty、minNotional、状态、来源、原始证据 hash、`effective_from`、`effective_to`、审核人/流程和 schema version。回放 timestamp 必须落在半开区间 `[effective_from,effective_to)`；版本不得重叠。

### 9.2 APPROXIMATED

`APPROXIMATED` 只允许在独立诊断实验中使用：

- 来源可以是当前 exchangeInfo、最接近快照或官方公开规则重建。
- 必须记录 approximation method、距离回放时刻、假设有效区间和证据 hash。
- 实验 ID 和报告标题必须包含 `APPROXIMATED`。
- APPROXIMATED 结果不能与 VERIFIED 结果合并统计，不能满足前向模拟硬门槛。

严格基准实验使用 `CONTRACT_POLICY_VERIFIED_ONLY_V1`。缺少 VERIFIED 覆盖时保留 Candidate，ExecutionRejection=`CONTRACT_RULE_UNAVAILABLE`；若持仓期间规则/maintenance coverage 消失，路径 INVALID。

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
5. **到期 EXIT Plan**：执行未在步骤 4 处理的确定性规则退出。
6. **到期 ENTRY Candidate/Plan**：读取该分钟 open，生成 Plan/拒绝；同刻全部 ENTRY 共同缩量，退出释放的现金可用。
7. **ENTRY Fill**：执行批准 Plan；同刻新仓不参与步骤 2 funding。
8. **分钟内触发集合**：用 trade high/low 判断 stop/TP，用 mark high/low 判断估算强平。
9. **路径政策**：按 baseline/conservative 决定无法排序的分钟内事件。
10. **分钟 close 估值**：使用 mark close 更新未实现 PnL、equity、peak equity 和 drawdown。
11. **HALT 判定**：close equity drawdown `>=10%` 产生 `HALT_TRIGGERED`，取消未执行 Candidate/Plan；现有仓位在下一有效 1m open 退出。
12. **4H/1D close 后处理**：仅在相应 bar 已收盘后更新指标、生成新 Candidate 或趋势 EXIT intent；它们最早在未来版本化执行时刻生效。
13. **原子提交**：同时写事件、ledger delta、state hash 和 minute commit hash。

步骤 1–13 版本化为 `MINUTE_EVENT_ORDER_V1`。

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
HALTED      10% 回撤触发并完成下一有效 open 全平
```

`HALT_TRIGGERED` 后禁止新仓；若下一 open 所需关键数据缺失，终态为 INVALID 而非 HALTED。HALTED/INVALID 后不延长现金曲线，报告实际 terminal time、存续天数和删失原因。

## 15. 2B/2C 必须证明的性质

1. Candidate 不因 contract/risk/cash 失败消失。
2. fill 已含滑点且不会重复扣除。
3. 同时缩量与输入顺序无关。
4. 资金、margin 和 reserve 不重复使用。
5. 同刻 funding、退出和入场符合冻结顺序。
6. 所有分钟内组合命中矩阵都有 baseline/conservative Golden Fixture。
7. 关键数据缺失后没有任何假设 stop 或伪造 fill。
8. APPROXIMATED 结果不能通过 forward gate。
9. 回撤恰好 10% 时触发 HALT。
10. 所有事件和账本重复运行逐字节一致。
