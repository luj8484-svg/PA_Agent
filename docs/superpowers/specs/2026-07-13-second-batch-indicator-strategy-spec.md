# 第二批指标引擎与 StrategyCandidate 规范

日期：2026-07-13
状态：设计评审稿；未授权 2A 实施
规范版本提案：`BTC_ETH_PA_STRATEGY_V1_1_DRAFT`

## 1. 输入与输出

指标引擎只消费通过第一批验证的、已收盘、UTC 对齐的 Binance 永续成交 K 线：

- 1D：EMA50、EMA200 和趋势状态。
- 4H：ATR14、Donchian 20 和 Candidate 决策。
- 1m 不参与 Candidate 指标；只在后续执行/事件层使用。

每个有效 4H close time 必须产生且只产生以下之一：

- 一个不可变 `StrategyCandidate`；或
- 一个不可变 `ValidationFailure`。

禁止以账户、持仓、资金、contract rule、费用、滑点或 HALT 状态抑制 Candidate。

## 2. 连续性和 pre-roll

### 2.1 连续有效序列

指标按 `(symbol, interval, open_time_utc_ms)` 严格升序。序列必须满足：

- 1D 相邻 open time 差严格为 86,400,000ms。
- 4H 相邻 open time 差严格为 14,400,000ms。
- 所有 bar `is_closed=true`。
- 该周期聚合与 Binance 原生周期通过 `AGG_VALIDATION_V1`。

缺口之后不得沿用缺口之前的 EMA/ATR 状态。缺口后的第一根属于新 segment，必须重新满足全部 warm-up；缺口本身生成数据层事实，在决策时映射为 `ValidationFailure/DATA_SEGMENT_NOT_CONTINUOUS`。

### 2.2 pre-roll 规则

- 每个研究 split 从其之前最近的连续 segment 读取 pre-roll。
- 研究起点前至少 250 根有效 1D 和 100 根有效 4H。
- 指标跨训练、验证、锁定 OOS 边界连续递推，不在边界重新播种。
- pre-roll bar 只用于指标，不允许生成交易、账本或绩效。
- 锁定 OOS 的 pre-roll 可以读取 OOS 起点以前的数据，不能读取 OOS 终点以后或未来修订数据。

若研究起点不满足数量或连续性，整个 symbol/split 标记 `PRE_ROLL_INSUFFICIENT`，不得缩短 warm-up 或回填。

## 3. EMA 的精确定义

对 period `N` 和 float64 close `x_t`：

```text
alpha = float64(2 / (N + 1))
ema_1 = x_1
ema_t = alpha*x_t + (1-alpha)*ema_(t-1)
```

- 版本：`EMA_RECURSIVE_V1_FLOAT64`。
- `adjust=false`。
- `min_periods=N`。
- 第一根 close 是内部递推种子；前 `N-1` 根输出状态为 `WARMING_UP`，不能用于比较。
- close 从 Canonical Decimal 以 `float(decimal_string)` 一次转换为 IEEE-754 binary64；禁止中间转 float32。
- NaN、Inf 或非正 close 产生 ValidationFailure。
- 本规范不依赖 pandas 的默认 EWM 行为；即便使用 pandas，输出必须逐位匹配本递推定义。

V1 固定 `EMA50_D`、`EMA200_D`。敏感性实验不允许在基准 run 中修改周期。

## 4. ATR14 的精确定义

版本：`ATR_WILDER_V1_FLOAT64`。

```text
TR_1 = high_1 - low_1
TR_t = max(high_t-low_t,
           abs(high_t-close_(t-1)),
           abs(low_t-close_(t-1)))

ATR_14 = mean(TR_1 ... TR_14)
ATR_t = (13*ATR_(t-1) + TR_t) / 14, t > 14
```

- OHLC Decimal 先各自一次转换为 float64。
- 第 14 根才有首个有效 ATR；前 13 根为 `WARMING_UP`。
- `ATR <= 0`、NaN 或 Inf 产生 `ValidationFailure/INDICATOR_NON_FINITE_OR_NON_POSITIVE`。
- 不使用简单移动 ATR，不使用 pandas `ewm` 的隐式种子。

## 5. Donchian 20 的精确定义

版本：`DONCHIAN_PREVIOUS_20_V1_DECIMAL`。

对当前 4H 索引 `t`：

```python
previous_highs = high[t - 20:t]
previous_lows = low[t - 20:t]
donchian_high = max(previous_highs)
donchian_low = min(previous_lows)
```

- 包含 `t-20` 至 `t-1` 共 20 根；不含当前 bar。
- 至少第 21 根 4H bar 才能评估。
- 使用原始 Canonical Decimal high/low，不转 float64。
- 当前 close 与边界严格比较；相等不是突破。

## 6. float64 到交易边界 Decimal

版本：`FLOAT64_TO_DECIMAL_15SIG_HALF_EVEN_V1`。

对有限 float64 `x`：

1. 若 `x == 0`，输出 `Decimal("0")`。
2. 用 `Decimal.from_float(x)` 得到该 binary64 的精确 Decimal 值。
3. `e=floor(log10(abs(x)))`。
4. 量化单位为 `Decimal(1).scaleb(e-14)`。
5. 使用 `ROUND_HALF_EVEN` 量化到 15 位有效数字。
6. 负零规范为 `Decimal("0")`。

指标内部不舍入。仅在写入 Candidate 或与 Decimal close 比较前执行上述转换。Candidate 阶段没有 contract rule，因此 EMA/ATR Decimal 不按 tick 量化；tick 量化只属于 ExecutionPlan。

## 7. 1D 趋势状态

在 4H `decision_time_utc_ms`，只允许选择 `close_time_utc_ms <= decision_time_utc_ms` 的最近已收盘 1D bar。

```text
BULL:
  daily_close > EMA200_D
  AND EMA50_D > EMA200_D

BEAR:
  daily_close < EMA200_D
  AND EMA50_D < EMA200_D

NEUTRAL:
  其他全部有效组合，包括任意相等
```

若找不到有效已收盘 1D、EMA 未 warm-up 或输入不连续，产生 ValidationFailure，不生成无 setup Candidate。

## 8. 确定性市场规则

### 8.1 LONG

```text
trend_state == BULL
AND current_4h_close > donchian_high_previous_20
```

输出：`market_view=LONG`、`setup_state=SETUP`、`market_reason=BULL_DONCHIAN_BREAKOUT`。

### 8.2 SHORT

```text
trend_state == BEAR
AND current_4h_close < donchian_low_previous_20
```

输出：`market_view=SHORT`、`setup_state=SETUP`、`market_reason=BEAR_DONCHIAN_BREAKOUT`。

### 8.3 NO_SETUP 与 NO_TRADE 的兼容语义

此前规范已使用 `market_view=NO_TRADE`，本轮评审要求使用 `NO_SETUP`。为避免破坏既有审计语义，本设计不把风险拒绝混入市场结论，冻结为：

- Canonical `market_view` 仍为 `LONG | SHORT | NO_TRADE`。
- 新增 `setup_state = SETUP | NO_SETUP`。
- `market_view=NO_TRADE` 时 `setup_state` 必须为 `NO_SETUP`。
- LONG/SHORT 时 `setup_state` 必须为 `SETUP`。
- `NO_SETUP` 不是风险、资金、持仓或 HALT 拒绝。

无 setup 原因：

| 1D 状态 | 4H 状态 | market_reason |
|---|---|---|
| NEUTRAL | 任意有效值 | `TREND_NEUTRAL` |
| BULL | 未向上突破且未向下逆势突破 | `NO_BREAKOUT` |
| BEAR | 未向下突破且未向上逆势突破 | `NO_BREAKOUT` |
| BULL | close < previous Donchian low | `BREAKOUT_AGAINST_TREND` |
| BEAR | close > previous Donchian high | `BREAKOUT_AGAINST_TREND` |

若同一 close 同时高于 high 且低于 low，说明边界或数据非法，产生 ValidationFailure，不能选择方向。

## 9. StrategyCandidate 字段和约束

```text
schema_version
candidate_id
strategy_id
strategy_version
symbol
decision_time_utc_ms
decision_bar_open_time_utc_ms
market_view
setup_state
market_reason
entry_intent
eligible_4h_open_utc_ms
execution_delay_version
decision_close
daily_close
trend_state
ema50_daily
ema200_daily
atr14_4h
donchian_high_previous_20
donchian_low_previous_20
strategy_data_content_hash
strategy_data_bundle_version
indicator_config_hash
strategy_config_hash
code_commit
dependency_lock_hash
created_by = PYTHON_DETERMINISTIC
```

约束：

- LONG/SHORT 的 `entry_intent=NEXT_4H_OPEN_MARKET`；NO_TRADE 为 null。
- `eligible_4h_open_utc_ms` 是 decision bar close 后的下一 UTC 4H open。
- Candidate 不含 `entry_price`、stop、TP、quantity、fee、margin、contract rule、maintenance margin、portfolio state 或 rejection。
- Candidate 不含 acquisition manifest/hash、Index/audit hash 或 execution data hash。
- 领域对象不可变，未知字段 fail closed。

`candidate_id`：

```text
cand_ + first_24_hex(SHA256(Canonical({
  schema_version,
  strategy_version,
  symbol,
  decision_time_utc_ms,
  market_view,
  setup_state,
  market_reason,
  strategy_data_content_hash,
  indicator_config_hash,
  strategy_config_hash,
  code_commit,
  dependency_lock_hash
})))
```

## 10. ValidationFailure

允许原因至少包含：

```text
PRE_ROLL_INSUFFICIENT
DATA_SEGMENT_NOT_CONTINUOUS
NATIVE_AGGREGATION_NOT_VALID
DAILY_BAR_NOT_AVAILABLE
INDICATOR_WARMING_UP
INDICATOR_NON_FINITE_OR_NON_POSITIVE
INDICATOR_BOUNDARY_INVALID
STRATEGY_DATA_HASH_MISMATCH
SCHEMA_VERSION_UNSUPPORTED
UNCLOSED_BAR
```

ValidationFailure 保存 symbol、decision time、受影响数据范围、gap intervals、期望/实际版本和内容哈希；不保存方向。

## 11. Golden Fixture V1

fixture 版本：`INDICATOR_GOLDEN_V1`。实现时必须将下列输入和预期输出写入 Canonical JSON；fixture manifest 自身的 SHA-256 纳入指标测试配置。

### 11.1 EMA3 种子和 min_periods 最小样例

输入 close：`1, 2, 3, 4, 5`，`alpha=0.5`。

| 1-based index | 内部 EMA | 对策略可见 |
|---:|---:|---|
| 1 | 1 | null |
| 2 | 1.5 | null |
| 3 | 2.25 | 2.25 |
| 4 | 3.125 | 3.125 |
| 5 | 4.0625 | 4.0625 |

### 11.2 ATR14 Wilder 种子最小样例

- 前 14 个 TR 均为 `2`，第 14 根 `ATR14=2`。
- 第 15 个 TR 为 `4`，内部 ATR 为 `30/14`。
- 15 位有效数字边界值为 `2.14285714285714`。

### 11.3 Donchian off-by-one 样例

- 前 20 根 high 为 `101..120`，low 为 `99..80`。
- 第 21 根决策 bar 的 previous high 必须为 `120`，previous low 必须为 `80`。
- 修改第 21 根当前 high/low 不得改变 previous Donchian。
- 删除第 1 根或错误使用 `[t-20:t-1]` 必须使测试失败。

### 11.4 决策边界样例

- BULL 且 `close=donchian_high`：NO_TRADE/NO_SETUP。
- BULL 且 `close=donchian_high+最小 Decimal 单位`：LONG。
- BEAR 且 `close=donchian_low`：NO_TRADE/NO_SETUP。
- BEAR 且 `close=donchian_low-最小 Decimal 单位`：SHORT。
- daily close 或 EMA 相等：NEUTRAL。

### 11.5 Segment 和样本边界样例

- 训练末尾、验证开头和 OOS 开头使用同一递推状态。
- 插入 1 根 4H 缺口后必须开始新 segment，并在 warm-up 完成前只产生 ValidationFailure。
- 改变 split 标签但不改变数据内容和决策时刻，不得改变指标值或 Candidate bytes。

## 12. 2A 验收门槛

1. Golden Fixture 全部逐字节通过。
2. 参考纯 Python 实现与生产实现对随机有限 Decimal OHLC 序列逐点一致；EMA/ATR 允许的差异为 0 ULP。
3. 相同输入顺序或输入容器顺序变化不改变输出。
4. 所有 Candidate 均没有执行、仓位、成本或 contract 字段。
5. ValidationFailure 与 NO_TRADE/NO_SETUP 不混用。
6. 2A 源码静态守卫证明不导入 GUI、AI、execution、risk、events、ledger 或交易客户端。
7. 未经 2A 单独批准，不得开始 2B。
