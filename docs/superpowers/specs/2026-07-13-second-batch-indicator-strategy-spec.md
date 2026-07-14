# 第二批指标引擎与 StrategyCandidate 规范

日期：2026-07-13
修订日期：2026-07-14
状态：2A 条件批准；完成本次修订后可实施 2A，2B–2D 未授权
正式版本：`BTC_ETH_PA_STRATEGY_V1_1`

```text
BTC_ETH_PA_STRATEGY_V1_1
STRATEGY_CANDIDATE_SCHEMA_V1
VALIDATION_FAILURE_SCHEMA_V1
INDICATOR_CONFIG_V1
DECISION_VISIBLE_INPUT_V1
PRE_ROLL_POLICY_V1_EXACT_250D_100X4H
```

`INDICATOR_CONFIG_V1` 的 Canonical 配置固定为：

```text
python_implementation = CPython
python_version = 3.12.13
ema_version = EMA_RECURSIVE_V1_FLOAT64
ema_periods_daily = [50, 200]
atr_version = ATR_WILDER_V1_FLOAT64
atr_period_4h = 14
donchian_version = DONCHIAN_PREVIOUS_20_V1_DECIMAL
donchian_lookback_4h = 20
numeric_boundary_version = FLOAT64_TO_DECIMAL_15SIG_HALF_EVEN_V1
pre_roll_policy_version = PRE_ROLL_POLICY_V1_EXACT_250D_100X4H
```

生产入口若不是 CPython 3.12.13 必须 fail closed；不得在其他 Python 版本复用 `INDICATOR_CONFIG_V1` 或宣称 0 ULP。平台、完整 Python build 和依赖锁继续进入 `dependency_lock_hash`。

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

### 2.2 唯一 pre-roll 算法

版本：`PRE_ROLL_POLICY_V1_EXACT_250D_100X4H`。

1. 对每个 symbol，以训练区间 `training_start_utc_ms` 为唯一播种锚点。
2. 严格选择训练起点之前、`close_time_utc_ms < training_start_utc_ms` 的最后 **精确 250 根连续 1D** 和最后 **精确 100 根连续 4H**；多余历史不得进入初始种子。
3. 250D/100×4H 均须已收盘、UTC 严格连续并通过原生周期交叉验证。任一数量不足即 `PRE_ROLL_INSUFFICIENT`，不得缩短、复制、插值或跨缺口补齐。
4. 训练、验证和锁定 OOS 共享同一递推状态；跨 split 边界绝不重新播种。split 标签不得进入指标值、Candidate Canonical bytes 或 `candidate_id`。
5. pre-roll bar 只用于指标状态，不生成 Candidate、交易、账本或绩效。
6. 若运行中发现 1D 或 4H 缺口，在缺口后的第一根 bar 开始新 segment，并以该 bar 作为 EMA/TR 的新内部种子；缺口决策点输出 `DATA_SEGMENT_NOT_CONTINUOUS`，随后连续 bar 在各指标重新满足 `min_periods` 前输出 `INDICATOR_WARMING_UP`。
7. 新 segment 不读取缺口前指标状态。EMA200 需要连续 200 根 1D，EMA50 需要 50 根 1D，ATR14 需要 14 根 4H，Donchian20 决策需要当前 bar 前 20 根 4H；全部满足后方可恢复 Candidate。

同一决策时刻存在多个失败时，优先级严格冻结为：

```text
PRE_ROLL_INSUFFICIENT
> DATA_SEGMENT_NOT_CONTINUOUS
> INDICATOR_WARMING_UP
```

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
- V1 生产实现必须采用固定运算顺序的标量 Python `float` 递推；禁止以 pandas/NumPy 向量化、并行归约、FMA 或代数重排替代该运算顺序。
- Python 实现版本、解释器版本和目标平台必须进入 `dependency_lock_hash`。只有相同锁定运行时、相同输入和相同标量运算顺序才适用 0 ULP 门槛；运行时变化必须提升指标版本并重新审批 Golden Fixture。

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
3. 令 `d = Decimal.from_float(x)`，使用 `e = d.copy_abs().adjusted()` 取得十进制调整指数；禁止通过 float `log10`、字符串格式化或平台数学库推导指数。
4. 量化单位为 `Decimal(1).scaleb(e - 14)`。
5. 使用 `ROUND_HALF_EVEN` 量化到 15 位有效数字。
6. 负零规范为 `Decimal("0")`。

指标内部不舍入。仅在写入 Candidate 或与 Decimal close 比较前执行上述转换。Candidate 阶段没有 contract rule，因此 EMA/ATR Decimal 不按 tick 量化；tick 量化只属于后续 Entry/Exit ExecutionPlan。

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

输出：`market_view=LONG`、`market_reason=BULL_DONCHIAN_BREAKOUT`。

### 8.2 SHORT

```text
trend_state == BEAR
AND current_4h_close < donchian_low_previous_20
```

输出：`market_view=SHORT`、`market_reason=BEAR_DONCHIAN_BREAKOUT`。

### 8.3 NO_SETUP 的唯一 Canonical 语义

- Canonical `market_view` 只能是 `LONG | SHORT | NO_SETUP`，不再存在 `setup_state` 字段。
- `NO_SETUP` 只是确定性市场结论，不是风险、资金、持仓、HALT 或执行拒绝。
- 旧版展示层可以把 `NO_SETUP` 映射为文案 `NO_TRADE`，但该兼容值不得写入 Canonical JSON、Candidate、哈希输入、确定性 ID 或任何下游领域对象。
- 对旧数据的迁移只允许执行单向显示兼容映射；不得由 `NO_TRADE` 反推或重建新的 Candidate。

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
market_reason
decision_close
daily_close
trend_state
ema50_daily
ema200_daily
atr14_4h
donchian_high_previous_20
donchian_low_previous_20
decision_visible_input_hash
decision_visible_input_version = DECISION_VISIBLE_INPUT_V1
indicator_config_hash
strategy_config_hash
code_commit
dependency_lock_hash
created_by = PYTHON_DETERMINISTIC
```

约束：

- `schema_version=STRATEGY_CANDIDATE_SCHEMA_V1`、`strategy_id=BTC_ETH_PA_STRATEGY`、`strategy_version=BTC_ETH_PA_STRATEGY_V1_1`。
- Candidate 只表达 `LONG | SHORT | NO_SETUP` 市场结论和该结论的可复现指标快照，不携带 entry intent、execution anchor、execution delay 或任何其他执行计划字段。
- 0/1/2 分钟延迟由 2B 根据 Candidate `decision_time_utc_ms` 与独立 execution config 计算；改变延迟不得改变 Candidate Canonical bytes 或 `candidate_id`。
- Candidate 不含 `entry_price`、stop、TP、quantity、fee、margin、contract rule、maintenance margin、portfolio state 或 rejection。
- Candidate 不含完整区间 `strategy_data_content_hash`、dataset/acquisition manifest/hash、Index/audit hash 或 execution data hash。
- 领域对象不可变，未知字段 fail closed。

### 9.1 decision_visible_input_hash

`decision_visible_input_hash` 只覆盖该 decision time 实际可见且影响结论的输入：

```text
SHA256(Canonical({
  decision_visible_input_version,
  symbol,
  decision_time_utc_ms,
  training_start_utc_ms,
  active_daily_segment_from_seed_through_selected_daily_bar,
  active_4h_segment_from_seed_through_decision_bar,
  pre_roll_policy_version,
  visible_validation_state,
  indicator_versions
}))
```

- 初始 segment 从精确 250D/100×4H pre-roll 的第一根开始；缺口重置后从新 segment 第一根开始。
- `visible_validation_state` 只包含上述可见范围的 closed/continuity/native-aggregation 状态。
- `indicator_versions` 固定包含 EMA、ATR、Donchian、float64→Decimal 和 `INDICATOR_CONFIG_V1`。
- 完整回测区间的 `strategy_data_content_hash` 仍保存在实验 Manifest，用于整体数据审计，但明确排除在 Candidate Canonical 对象和 `candidate_id` 之外。
- 修改 `decision_time_utc_ms` 之后的任意数据、下载时间、采集 Manifest 或 execution config，不得改变既有 Candidate 的指标值、Canonical bytes 或 ID。

`candidate_id`：

```text
cand_ + first_24_hex(SHA256(Canonical(
  StrategyCandidate 的全部字段，排除 candidate_id 自身
)))
```

因此任何 Candidate 业务字段变化都会改变 ID；Candidate Schema 中不存在的 execution intent/delay 和完整区间 dataset hash 不可能影响 ID。

## 10. ValidationFailure

Schema 固定为：

```text
schema_version = VALIDATION_FAILURE_SCHEMA_V1
failure_id
reason
symbol
decision_time_utc_ms
affected_interval
decision_visible_input_hash       # 无法构造时为 null
expected_values
observed_values
gap_intervals
indicator_config_hash
code_commit
dependency_lock_hash
created_by = PYTHON_DETERMINISTIC
```

`failure_id` 是上述全部字段排除自身后的 Canonical SHA-256 前 24 hex，前缀 `val_`。

允许原因至少包含：

```text
PRE_ROLL_INSUFFICIENT
DATA_SEGMENT_NOT_CONTINUOUS
NATIVE_AGGREGATION_NOT_VALID
DAILY_BAR_NOT_AVAILABLE
INDICATOR_WARMING_UP
INDICATOR_NON_FINITE_OR_NON_POSITIVE
INDICATOR_BOUNDARY_INVALID
DECISION_VISIBLE_INPUT_HASH_MISMATCH
SCHEMA_VERSION_UNSUPPORTED
UNCLOSED_BAR
```

ValidationFailure 保存 symbol、decision time、受影响数据范围、gap intervals、期望/实际版本和内容哈希；不保存方向。

Candidate 与 ValidationFailure 的全部时间字段只能来自已验证市场数据的事件时钟：4H/1D bar 的 open/close time 或实验清单冻结的确定性边界。下载时间、进程时间、系统当前时间和其他本地 wall clock 不得进入领域对象、Canonical JSON 或确定性 ID；如报告外壳需要 `generated_at`，它只能作为非确定性展示元数据并明确排除在所有内容哈希之外。

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

- BULL 且 `close=donchian_high`：NO_SETUP。
- BULL 且 `close=donchian_high+最小 Decimal 单位`：LONG。
- BEAR 且 `close=donchian_low`：NO_SETUP。
- BEAR 且 `close=donchian_low-最小 Decimal 单位`：SHORT。
- daily close 或 EMA 相等：NEUTRAL。

### 11.5 Segment 和样本边界样例

- 训练末尾、验证开头和 OOS 开头使用同一递推状态。
- 插入 1 根 4H 缺口后必须开始新 segment，并在 warm-up 完成前只产生 ValidationFailure。
- 改变 split 标签但不改变数据内容和决策时刻，不得改变指标值或 Candidate bytes。
- 在 decision time 之后追加、删除或修改任意未来 bar，不得改变过去 Candidate 的指标、Canonical bytes 或 `candidate_id`。

## 12. 2A 验收门槛

1. Golden Fixture 全部逐字节通过。
2. 参考纯 Python 实现与生产实现均采用锁定版本的标量 Python `float` 固定顺序递推；在相同解释器、平台和依赖锁下，对随机有限 Decimal OHLC 序列逐点一致，EMA/ATR 允许差异为 0 ULP。
3. 相同输入顺序或输入容器顺序变化不改变输出。
4. 所有 Candidate 均没有执行、仓位、成本、完整区间 dataset hash 或 contract 字段。
5. ValidationFailure 与 `NO_SETUP` 不混用；Canonical 产物中不存在 `NO_TRADE` 或 `setup_state`。
6. 2A 源码静态守卫证明不导入 GUI、AI、execution、risk、events、ledger 或交易客户端。
7. 未经 2A 单独批准，不得开始 2B。
8. 改变 execution delay/config 或 decision time 之后的数据，不得改变既有 Candidate 或 ID。
9. pre-roll 精确使用 250D/100×4H；少一根、跨缺口、跨 split 重播种和缺口后未 warm-up 均有失败测试。
