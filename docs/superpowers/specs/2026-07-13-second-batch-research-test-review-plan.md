# 第二批研究验证、测试与分阶段评审计划

日期：2026-07-13
修订日期：2026-07-14
状态：2A 条件批准；2B–2D 未授权

## 1. 分阶段提交原则

第二批拆为四个可独立拒绝、独立验收的子批次：

```text
2A 指标与 StrategyCandidate 纯函数
2B Entry/Exit ExecutionPlan、风险与仓位纯函数
2C 1m 事件引擎、双路径与账本
2D 样本治理、研究验证与报告
```

每个子批次流程：设计确认 → 测试先行 → 最小实现 → 本批验收报告 → 独立代码审查。前一批通过不自动授权后一批。

## 2. 2A 设计交付与测试清单

### 2.1 计划交付

- 隔离 `research_backtest/domain`、`indicators` 和 `strategy` 包。
- frozen StrategyCandidate、ValidationFailure 和枚举 Schema。
- 正式版本：`BTC_ETH_PA_STRATEGY_V1_1`、`STRATEGY_CANDIDATE_SCHEMA_V1`、`VALIDATION_FAILURE_SCHEMA_V1`、`INDICATOR_CONFIG_V1`。
- EMA、ATR、Donchian、pre-roll、segment 和 float64→Decimal 纯函数。
- `INDICATOR_GOLDEN_V1` 与 `STRATEGY_GOLDEN_V1` Canonical fixtures。
- 静态守卫，禁止导入 execution/risk/events/ledger/GUI/AI/HTTP。

### 2.2 单元与性质测试

- EMA 首种子、`min_periods=N`、恒定序列、单点跳变、NaN/Inf 拒绝。
- ATR 首 TR、14 根算术种子、第 15 根 Wilder 递推、gap reset。
- Donchian `high[t-20:t]`/`low[t-20:t]`、相等不突破、当前 bar 不泄漏。
- pre-roll 严格精确 250D/100×4H、少一根失败、split 边界不重播种、缺口首点 reset 且后续重新 warm-up。
- 15 位有效数字、round-half-even、负零、极大/极小有限值。
- 1D bar 的 `close_time <= decision_time`，未来日线不可见。
- LONG、SHORT、NO_SETUP 及每个 reason 的 truth table；Canonical/ID 中出现 `NO_TRADE` 或 `setup_state` 必须失败，展示层兼容映射单独测试。
- ValidationFailure 与市场无 setup 互斥。
- Candidate 禁止 entry intent、execution anchor、execution delay、stop/TP/quantity/contract/cash/margin 和完整区间 dataset hash 字段。
- 任意输入容器顺序下 Candidate Canonical bytes 不变。
- `Decimal.from_float(x).adjusted()` 覆盖 subnormal、极小/极大有限值；AST 守卫禁止 float `log10` 推导十进制指数。
- 锁定 Python/平台版本的标量 float 固定顺序递推达到 0 ULP；向量化、FMA、代数重排或 wall clock 输入必须被守卫拒绝。
- `decision_visible_input_hash` 仅覆盖决策点可见 segment、验证状态和指标版本；修改未来数据或 execution config 不得改变历史 Candidate/ID。
- 同时存在失败时固定验证 `PRE_ROLL_INSUFFICIENT > DATA_SEGMENT_NOT_CONTINUOUS > INDICATOR_WARMING_UP`。

### 2.3 2A 验收门槛

- 所有 Golden Fixture 和 property tests 通过。
- 两个独立实现（简单参考循环与生产函数）逐点一致。
- 2A package 无第二批后续模块和外部 I/O。
- 代码/配置/依赖改变时 Candidate ID 改变；采集时间、本地 wall clock 改变时不改变。
- 0/1/2 分钟 execution delay 变化和 decision time 之后数据变化均不得改变历史 Candidate ID。
- 2A 只可提交指标、Golden Fixture、StrategyCandidate、ValidationFailure、确定性 LONG/SHORT/NO_SETUP 纯函数和静态守卫；不得出现 Plan/Rejection、费用、仓位、事件、账本或报告模块。
- 审核者书面批准后才允许 2B。

## 3. 2B 设计交付与测试清单

### 3.1 计划交付

- 独立 EntryExecutionPlan、ExitExecutionPlan 和 ExecutionRejection Schema；禁止 `plan_kind` 大联合 Schema。
- tick/step 定向 Decimal 量化。
- fee/slippage/funding buffer、stop/TP、unit risk 和 required cash 纯函数。
- VERIFIED/APPROXIMATED contract archive resolver。
- maintenance tier resolver 和估算 liquidation price 纯函数。
- 同时计划共同缩量纯函数。
- 版本化 funding schedule 的 `max_settlement_count(entry, exit)` 纯函数。

### 3.2 单元与性质测试

- LONG/SHORT 每种 entry/stop/TP/stop estimate 的 tick 边界和方向。
- fill/slippage/fee 恒等式；证明滑点只计一次。
- `unit_risk` 每项逐项 fixture 与总和。
- step 向下后重算 risk/notional/cash；绝不向上满足 minimum。
- minQty/minNotional、资金不足、risk cap、existing position、HALTED 的独立 rejection。
- 单笔恰好 0.5% 通过，超过最小 Decimal 单位拒绝/缩量。
- 组合恰好 1% 通过，超过时共同缩量。
- BTC_FIRST、ETH_FIRST、反向列表和不同 dict 插入顺序结果相同。
- 一个计划量化为零时不把余额重新分给另一个计划。
- contract rule 有效期半开边界、重叠、缺口、错误 symbol/hash。
- VERIFIED 与 APPROXIMATED 不能出现在同一实验依赖中。
- maintenance tier 边界、deduction、tier 迭代和无稳定 tier INVALID。
- Candidate 在 contract 缺失时仍存在，仅产生 rejection。
- `GAP_TOO_LARGE` 的 LONG/SHORT directional gap、严格 `>`、负 gap、等值边界、无效 ATR/reference 独立测试。
- 48h 在 `FUNDING_SCHEDULE_ASSUMED_8H_V1` 保守窗口内最多 7 次，且不同 entry/exit 对动态计数，不允许固定乘 6。
- `PORTFOLIO_SCALE_GOLDEN_V1_SYNTHETIC` 冻结 scale=`0.75`、BTC=`0.750`、ETH=`7.50→BELOW_MIN_QTY`，ETH 拒绝后不得向 BTC 二次分配。

### 3.3 2B 验收门槛

- 全部计算使用 Decimal；AST/类型守卫禁止交易边界使用 float。
- 每个 rejection 原因有独立测试，不借用 NO_TRADE。
- 同时缩量在 symbol 排列的全排列上逐字节一致。
- APPROXIMATED 路径带显式水印和压力测试，最多满足 Paper Simulation Gate，不能满足 Live Eligibility Gate。
- 无 minute engine、funding settlement、ledger 或绩效代码。
- 审核者书面批准后才允许 2C。

## 4. 2C 设计交付与测试清单

### 4.1 计划交付

- 不可变 minute event、Fill、Funding、EstimatedLiquidation、LedgerEntry Schema。
- `MINUTE_EVENT_ORDER_V1` transaction engine。
- baseline/conservative path policy。
- isolated account、reserve、margin、PnL、equity、drawdown reducer。
- COMPLETED/INVALID/HALTED/BANKRUPT terminal state。
- `MINUTE_PATH_GOLDEN_V1` 事件序列 fixture。

### 4.2 事件顺序测试

- funding 时刻前持仓先结算，同刻退出在后，同刻新仓不结算。
- mark open 强平优先于 trade open/计划。
- stop gap、HALT_EXIT、TIME_EXIT、TREND_EXIT、TP gap 原因优先级。
- 退出释放资金后同刻 ENTRY 的可用现金。
- 新 ENTRY 在入场分钟可被盘中 stop/TP/强平命中。
- stop+TP、stop+liq、TP+liq、三者全部命中的完整矩阵。
- PATH_AMBIGUOUS 分叉共享 minute-start hash，之后事件/账本独立。
- 不允许分钟结束后按收益选择路径。
- 48 小时边界前 1ms 不退出、恰好边界退出、缺口 INVALID。
- 趋势退出只使用已收盘 1D，在版本化延迟时刻执行。
- 持仓退出后下一完整 4H close 前不能重新入场。

### 4.3 数据缺口测试

- 空仓 mark gap 只告警；持仓 mark gap INVALID。
- 与 Candidate 聚合无关的 trade gap 与影响聚合的 trade gap 分开。
- 到期计划 target minute 缺失 INVALID，不顺延。
- 跨 funding 点缺记录 INVALID，不填零。
- 持仓期间 contract/maintenance coverage 消失 INVALID。
- Index 任意缺口不改变交易事件和账本 hash。

### 4.4 账本不变量/property tests

每个事件后必须满足：

```text
wallet_balance = initial_wallet + realized_pnl - fees + funding_cash_changes
locked_margin >= 0
fee_reserve >= 0
funding_reserve >= 0
plan_margin_lock >= 0
available_balance = wallet_balance - locked_margin - fee_reserve
                    - funding_reserve - plan_margin_lock
equity = wallet_balance + unrealized_pnl
position quantity 与 isolated margin 派生视图一一对应
闭仓后 quantity/margin/reserve 全部归零
累计 ledger delta 与 reducer 状态差一致
所有 path 的 event_seq 连续且唯一
```

随机事件序列必须证明：funding 只对 wallet 经济扣款一次、锁定分类不重复扣 cash、无重复 fee、无负数量、无幽灵仓位、重放幂等、序列顺序改变时 fail closed。Funding 超 reserve 必须记录事件并重新估算强平；若未强平但 available balance 为负，进入 BANKRUPT 而非数据 INVALID。

FillEvent 必须只含成交事实。所有 cash/position before-after 均由 reducer 和 StateSnapshot 生成；序列化 Fill 中出现独立 before/after 状态字段必须失败。

### 4.5 HALT 测试

- drawdown `9.999...%` 不触发；恰好 `10%` 触发。
- equity、peak equity 和 drawdown 只在每分钟 mark close snapshot 更新；该分钟此前的 fee/funding/fill 现金变化在此 snapshot 统一反映。
- 事件名固定为 `1M_CLOSE_EQUITY_HALT_TRIGGERED`。触发后保留并继续生成市场 Candidate，只取消未成交 EntryExecutionPlan；后续 LONG/SHORT Candidate 由执行层拒绝为 `EXPERIMENT_HALTED`。
- 下一有效 1m open 全平；关键数据缺失则 INVALID。
- HALTED 后无现金曲线填充、无完整区间 CAGR。
- 每分钟先处理全部 open 事件，再以分钟内触发前的仓位快照计算 LONG mark low/SHORT mark high 保守 intraminute drawdown audit；多 symbol 标为非同步估算。OOS 只要 `estimated_intraminute_drawdown >=10%`，即使 close 未触发 HALT，也不得通过任一 forward gate。

### 4.6 2C 验收门槛

- Golden event sequences 与实际 Canonical bytes 一致。
- baseline/conservative 全组合测试通过。
- 任一关键缺口后没有保护性止损假设或后续绩效。
- 事件重放与一次运行的最终账本逐字节一致。
- 不包含参数搜索、GUI、LLM、API Key 或交易接口。
- 审核者书面批准后才允许 2D。

## 5. 2D 样本治理

### 5.1 固定样本算法

对 BTC/ETH 必需数据和 VERIFIED 规则的共同连续交集，先冻结 `dataset_cutoff_utc`，然后按完整 UTC 月倒推：

- 锁定 OOS：最后 18 个完整月。
- 验证集：OOS 之前连续 12 个完整月。
- 训练集：验证集之前至少 36 个完整月。
- 若共同交集不足 66 个完整月，实验报告 `INSUFFICIENT_STATISTICAL_EVIDENCE` 且不满足 Paper Simulation/Live Eligibility Gate；不得缩短 OOS。
- pre-roll 从训练起点以前读取，交易/绩效严格从训练起点开始。

OOS 的起止、content hashes 和 manifest 在运行 OOS 前写入只追加锁文件。任何策略、参数、成本或代码变化都创建新实验，不能覆盖原 OOS。

### 5.2 walk-forward

仅在训练+验证时期做扩展窗口 walk-forward：

```text
initial train = 24 full months
validation window = 6 full months
step = 6 full months
minimum windows = 3
```

每窗只允许使用该窗 validation 以前的数据选择参数。锁定 OOS 不参与参数选择。

## 6. 参数、延迟和成本敏感性

V1 基准结构固定 EMA50/EMA200。局部稳健性网格：

```text
Donchian lookback: 16, 20, 24
ATR lookback:      12, 14, 16
stop ATR multiple: 1.6, 2.0, 2.4
TP ATR multiple:   2.4, 3.0, 3.6
gap ATR multiple:  0.4, 0.5, 0.6
```

完整 Cartesian grid 为 243 个组合，版本名固定为 `ROBUSTNESS_HEURISTIC_V1`。它是探索性稳健性启发式，不是置信区间、显著性检验或参数选择器；不允许把 OOS 最佳点回写为 V1。

基准点为 `(20,14,2.0,3.0,0.5)`。`baseline nearest-neighbor` 集合固定为基准点加上五个轴各自相邻的 `-1/+1` 网格点，共 11 个点；一次只能改变一个轴。每个 split/path/cost 场景必须同时报告：

- 11 点 nearest-neighbor pass count/rate。
- 243 点 full-grid pass count/rate。
- 基准点自身结果和距离基准最近的失败点。

门槛中的 full-grid 比例（若使用）必须标为 heuristic，不能解释为统计置信度。

独立压力轴：

- execution delay：0、1、2 分钟。
- fee/slippage multiplier：1.0、1.5、2.0。
- path：baseline、conservative。
- contract mode：VERIFIED 基准；APPROXIMATED 仅限带水印的诊断/paper simulation，压力测试并单独报告，绝不进入 Live Eligibility。

## 7. 基准比较

所有基准使用相同样本、1 倍资本约束、taker fee、slippage 和真实 funding。每个可持仓市场基准必须同时运行两种风险控制语义：

- `RAW_MARKET_NO_HALT`：不应用 10% HALT，只展示原始市场/规则表现；仍按数据 INVALID 终止。
- `SAME_HALT_RISK_CONTROL`：与策略完全相同的 `1M_CLOSE_EQUITY_HALT`、退出和删失规则。

策略的 HALTED 路径不得只与未 HALT 的 raw market benchmark 比较。CASH 作为审计基准同时输出两列但结果相同。

1. `CASH`：零收益现金，不产生 funding。
2. `BTC_BUY_HOLD_1X`、`ETH_BUY_HOLD_1X`：样本首个可执行分钟开多，末分钟退出。
3. `EQUAL_WEIGHT_BTC_ETH_1X`：首日各 50%，不再平衡，资金不重复使用。
4. `DAILY_EMA200_LONG_SHORT`：daily close 高于 EMA200 做多、低于做空、相等空仓，使用同一执行延迟。
5. `DONCHIAN20_NO_DAILY_FILTER`：仅 4H Donchian 突破，其他执行/风险规则相同。
6. `BTC_ETH_PA_V1` baseline/conservative。

买入持有和规则基准若缺关键 mark/funding/contract 数据，同样 INVALID，不能享受更宽松数据政策。

## 8. 指标和置信区间

每个 symbol、组合、路径和 split 分别报告：

- terminal state、terminal time、存续天数、删失原因。
- 净收益、年化收益（仅完整且足够长的 COMPLETED 路径）、最大回撤。
- 闭合交易数、胜率、平均盈亏、Profit Factor、期望值、平均持有期。
- fee、slippage、funding、estimated liquidation 分项。
- 风险利用率、现金利用率、rejection counts、gap/ambiguity counts。
- `report_status_axes`：数据有效性、风险门槛、统计证据、经济终态四个独立轴，不得压缩为单一 pass/fail。

状态语义冻结：

- `INVALID`：关键数据、版本或数值证据不足，路径无法继续。
- `RISK_GATE_FAILED`：数据有效，但最大回撤、HALT、盘中回撤审计或其他预先冻结的风险条件失败。
- `INSUFFICIENT_STATISTICAL_EVIDENCE`：数据和路径可计算，但交易数不足、CI 未定义或 CI 未跨越要求边界。
- `BANKRUPT`：经济终态；不能标作数据 INVALID。

同一实验可同时具有例如 `data=VALID`、`risk=RISK_GATE_FAILED`、`statistics=INSUFFICIENT_STATISTICAL_EVIDENCE`；报告必须保留各轴原因和证据。

置信区间冻结：

- OOS 每日净收益：7 日 moving-block bootstrap，10,000 次，seed `20260713`，95% 双侧 percentile CI。
- OOS 交易序列 Profit Factor：按连续 5 笔交易 moving-block bootstrap，10,000 次，同一 seed，95% 双侧 percentile CI。
- 无交易或分母为零时 PF CI 标为 `UNDEFINED`，不能视为通过。
- bootstrap 实现和依赖版本进入实验 ID。

## 9. 分离的研究门槛

### 9.1 Paper Simulation Gate

仅授权无真实资金、无交易接口的 paper simulation。允许 VERIFIED，也允许显式 `APPROXIMATED` 历史规则；后者的样本交集按已审批 APPROXIMATED 规则自身有效覆盖区间构造，不要求 VERIFIED 覆盖，但必须在实验 ID/标题/每页报告带水印、与 VERIFIED 分栏，并通过规则有效区间和更保守成本压力测试。锁定 OOS 的 baseline 和 conservative 必须同时满足：

1. OOS 至少 18 个完整月。
2. 合计至少 60 笔闭合交易，BTC/ETH 各至少 20 笔。
3. 两条路径均 `COMPLETED`，无 INVALID、无 HALTED、无 BANKRUPT。
4. 两条路径净收益均为正，最大回撤严格低于 10%。
5. conservative 在 2 倍 fee/slippage 下净收益不低于 0。
6. 至少 3 个 walk-forward 窗口，至少三分之二净收益为正，任何窗口不 HALTED。
7. 每日净收益 bootstrap 95% CI 下界大于 0。
8. Profit Factor bootstrap 95% CI 下界大于 1.0。
9. `ROBUSTNESS_HEURISTIC_V1` 同时报告 11 点 nearest-neighbor 和 243 点 full-grid 通过率；full-grid 至少 70% 在 conservative、1 倍成本下净收益为正，且基准 nearest-neighbor 不能表现为孤立峰值。
10. VERIFIED 实验要求全覆盖；APPROXIMATED 实验要求声明覆盖、带水印且压力测试通过。
11. 数据验证 100% 通过；没有被忽略的关键 gap。
12. 同实验重复运行，Candidate、Entry/Exit Plan、Rejection、Fill、事件、账本、指标和报告逐字节一致。

此外，锁定 OOS 不得出现 `INTRAMINUTE_DRAWDOWN_BREACH_ESTIMATE`。交易数不足或 CI 未定义必须报告 `INSUFFICIENT_STATISTICAL_EVIDENCE`，风险条件失败报告 `RISK_GATE_FAILED`，不能合并为 INVALID。

2 倍杠杆、人工排除亏损区间或修改 OOS 后得到的结果不能满足 Paper Simulation Gate。通过该 Gate 仍需单独审批才可开始 paper simulation，不得接 API Key、交易接口或真实资金。

### 9.2 Live Eligibility Gate

Live Eligibility 不是本批实盘授权，只是未来提交独立实盘设计评审的必要条件。它要求：

1. Paper Simulation Gate 已在 `VERIFIED` 历史规则下通过；APPROXIMATED 证据不计入。
2. 完整回放区间的 contract rule 与 maintenance margin 均为 VERIFIED，证据独立复核。
3. 已完成预先冻结周期的无真实资金 forward simulation，且表现满足单独冻结的 live gate 指标和置信区间。
4. forward simulation 无 INVALID、HALTED、BANKRUPT、盘中回撤 breach audit 或确定性偏差。
5. 由独立审核者完成二次批准；随后仍需另行设计密钥、权限、下单、熔断和人工接管，本批不实现。

APPROXIMATED 历史规则永远不能直接进入 Live Eligibility 或自动交易链路。

## 10. 验收测试命令设计

未来每个子批次必须提供独立命令；以下是评审要求的接口，不代表文件已存在：

```powershell
pytest tests/research_backtest/unit -v
pytest tests/research_backtest/property -v --hypothesis-seed=20260713
pytest tests/research_backtest/integration -v
pytest tests/research_backtest/acceptance -v
ruff check pa_agent/research_backtest tests/research_backtest
git diff --check
python -m compileall pa_agent/research_backtest
```

此外始终重跑第一批回归和安全守卫：

```powershell
pytest tests/research_data -v
pytest tests/research_data/test_binance_public_security.py tests/research_data/test_scope_guard.py -v
```

第二批必须新增源代码守卫，证明：

- 没有 `create_order(`。
- 没有账户/订单路径、POST/PUT/DELETE。
- 没有 API Key、secret、signature 字段。
- 没有导入 `pa_agent.ai`、`pa_agent.gui`、`pa_agent.orchestrator`。
- 没有 LLM、HTTP client 或网络调用。

## 11. 设计评审清单

评审者应逐项明确“接受/修改”：

1. 采用四阶段纯函数管线，而非单体或插件框架。
2. Canonical `market_view=LONG|SHORT|NO_SETUP` 与 display-only `NO_TRADE` 映射。
3. Golden Fixture 数值、pre-roll 和缺口 reset。
4. Candidate、EntryExecutionPlan、ExitExecutionPlan、Rejection、纯事实 Fill 和事件字段，以及领域事件时钟。
5. stop/TP、gap、成本、动态 funding buffer、unit risk、required cash 和开放风险公式。
6. 同时计划数值 Golden Fixture、缩量及拒绝后不二次分配余额。
7. VERIFIED/APPROXIMATED 的用途与 Paper Simulation/Live Eligibility Gate 限制。
8. 估算强平模型及其非精确声明。
9. 1m 事件步骤 1–13 和同一分钟矩阵。
10. `1M_CLOSE_EQUITY_HALT`、Candidate 保留和 intraminute drawdown audit。
11. 66 个月最低共同数据、18 月锁定 OOS 和 walk-forward。
12. `ROBUSTNESS_HEURISTIC_V1` 的 11 点/243 点报告、raw/same-HALT 双基准和 bootstrap 方法。

## 12. 当前明确限制

- 1m OHLC 不能恢复分钟内真实路径，因此必须保留双路径。
- 没有历史盘口，slippage 只能是版本化假设和压力测试。
- 当前 exchangeInfo 不能证明历史 contract rule；VERIFIED archive 可能限制可用样本。
- maintenance tier 历史档案可能不完整；缺失会减少可交易区间，不能静默近似。
- 估算强平不等于 Binance 实际强平。
- 回测和统计门槛通过也不能保证未来收益。
- 本次修订仍不得创建第二批业务代码。下一次若获单独授权，只能开始 2A：指标、Golden Fixture、StrategyCandidate、ValidationFailure 和确定性纯函数/静态守卫；2B–2D 仍未批准。
