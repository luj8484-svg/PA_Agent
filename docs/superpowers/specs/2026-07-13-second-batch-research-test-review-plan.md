# 第二批研究验证、测试与分阶段评审计划

日期：2026-07-13
状态：设计评审稿；不是实施授权

## 1. 分阶段提交原则

第二批拆为四个可独立拒绝、独立验收的子批次：

```text
2A 指标与 StrategyCandidate 纯函数
2B ExecutionPlan、风险与仓位纯函数
2C 1m 事件引擎、双路径与账本
2D 样本治理、研究验证与报告
```

每个子批次流程：设计确认 → 测试先行 → 最小实现 → 本批验收报告 → 独立代码审查。前一批通过不自动授权后一批。

## 2. 2A 设计交付与测试清单

### 2.1 计划交付

- 隔离 `research_backtest/domain`、`indicators` 和 `strategy` 包。
- frozen StrategyCandidate、ValidationFailure 和枚举 Schema。
- EMA、ATR、Donchian、pre-roll、segment 和 float64→Decimal 纯函数。
- `INDICATOR_GOLDEN_V1` 与 `STRATEGY_GOLDEN_V1` Canonical fixtures。
- 静态守卫，禁止导入 execution/risk/events/ledger/GUI/AI/HTTP。

### 2.2 单元与性质测试

- EMA 首种子、`min_periods=N`、恒定序列、单点跳变、NaN/Inf 拒绝。
- ATR 首 TR、14 根算术种子、第 15 根 Wilder 递推、gap reset。
- Donchian `high[t-20:t]`/`low[t-20:t]`、相等不突破、当前 bar 不泄漏。
- pre-roll 250D/100×4H、split 边界连续、缺口后重新 warm-up。
- 15 位有效数字、round-half-even、负零、极大/极小有限值。
- 1D bar 的 `close_time <= decision_time`，未来日线不可见。
- LONG、SHORT、NO_TRADE/NO_SETUP 及每个 reason 的 truth table。
- ValidationFailure 与市场无 setup 互斥。
- Candidate 禁止 stop/TP/quantity/contract/cash/margin 字段。
- 任意输入容器顺序下 Candidate Canonical bytes 不变。

### 2.3 2A 验收门槛

- 所有 Golden Fixture 和 property tests 通过。
- 两个独立实现（简单参考循环与生产函数）逐点一致。
- 2A package 无第二批后续模块和外部 I/O。
- 代码/配置/依赖改变时 Candidate ID 改变；采集时间改变时不改变。
- 审核者书面批准后才允许 2B。

## 3. 2B 设计交付与测试清单

### 3.1 计划交付

- ExecutionPlan、ExecutionRejection Schema。
- tick/step 定向 Decimal 量化。
- fee/slippage/funding buffer、stop/TP、unit risk 和 required cash 纯函数。
- VERIFIED/APPROXIMATED contract archive resolver。
- maintenance tier resolver 和估算 liquidation price 纯函数。
- 同时计划共同缩量纯函数。

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

### 3.3 2B 验收门槛

- 全部计算使用 Decimal；AST/类型守卫禁止交易边界使用 float。
- 每个 rejection 原因有独立测试，不借用 NO_TRADE。
- 同时缩量在 symbol 排列的全排列上逐字节一致。
- APPROXIMATED 路径带显式水印且不能满足 forward gate。
- 无 minute engine、funding settlement、ledger 或绩效代码。
- 审核者书面批准后才允许 2C。

## 4. 2C 设计交付与测试清单

### 4.1 计划交付

- 不可变 minute event、Fill、Funding、EstimatedLiquidation、LedgerEntry Schema。
- `MINUTE_EVENT_ORDER_V1` transaction engine。
- baseline/conservative path policy。
- isolated account、reserve、margin、PnL、equity、drawdown reducer。
- COMPLETED/INVALID/HALTED terminal state。
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
cash >= 0                         # V1 不允许借款
locked_initial_margin >= 0
fee_reserve >= 0
funding_reserve >= 0
available_cash = cash - all_locks
position quantity 与 margin 一一对应
闭仓后 quantity/margin/reserve 全部归零
累计 ledger delta 与状态差一致
所有 path 的 event_seq 连续且唯一
```

随机事件序列必须证明：无重复资金、无重复 fee、无负数量、无幽灵仓位、重放幂等、序列顺序改变时 fail closed。

### 4.5 HALT 测试

- drawdown `9.999...%` 不触发；恰好 `10%` 触发。
- equity、peak equity 和 drawdown 只在每分钟 mark close snapshot 更新；该分钟此前的 fee/funding/fill 现金变化在此 snapshot 统一反映。
- HALT_TRIGGERED 后取消全部未执行 Candidate/Plan。
- 下一有效 1m open 全平；关键数据缺失则 INVALID。
- HALTED 后无现金曲线填充、无完整区间 CAGR。

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
- 若共同交集不足 66 个完整月，实验不满足 forward gate；不得缩短 OOS。
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

完整 Cartesian grid 为 243 个组合。它只用于敏感性报告，不允许把 OOS 最佳点回写为 V1。

独立压力轴：

- execution delay：0、1、2 分钟。
- fee/slippage multiplier：1.0、1.5、2.0。
- path：baseline、conservative。
- contract mode：VERIFIED 基准；APPROXIMATED 仅诊断，单独报告。

## 7. 基准比较

所有基准使用相同样本、1 倍资本约束、taker fee、slippage、真实 funding 和 terminal 规则：

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

置信区间冻结：

- OOS 每日净收益：7 日 moving-block bootstrap，10,000 次，seed `20260713`，95% 双侧 percentile CI。
- OOS 交易序列 Profit Factor：按连续 5 笔交易 moving-block bootstrap，10,000 次，同一 seed，95% 双侧 percentile CI。
- 无交易或分母为零时 PF CI 标为 `UNDEFINED`，不能视为通过。
- bootstrap 实现和依赖版本进入实验 ID。

## 9. 前向模拟硬门槛

只有 VERIFIED、1 倍、锁定 OOS 的 baseline 和 conservative 同时满足以下全部条件，才可以提交“前向模拟设计申请”；仍不能直接启动模拟：

1. OOS 至少 18 个完整月。
2. 合计至少 60 笔闭合交易，BTC/ETH 各至少 20 笔。
3. 两条路径均 `COMPLETED`，无 INVALID、无 HALTED。
4. 两条路径净收益均为正，最大回撤严格低于 10%。
5. conservative 在 2 倍 fee/slippage 下净收益不低于 0。
6. 至少 3 个 walk-forward 窗口，至少三分之二净收益为正，任何窗口不 HALTED。
7. 每日净收益 bootstrap 95% CI 下界大于 0。
8. Profit Factor bootstrap 95% CI 下界大于 1.0。
9. 243 个局部网格组合中至少 70% 在 conservative、1 倍成本下净收益为正；基准点不是孤立峰值。
10. 所有可交易/持仓分钟具有 VERIFIED contract 和 maintenance coverage。
11. 数据验证 100% 通过；没有被忽略的关键 gap。
12. 同实验重复运行，Candidate、Plan、Rejection、Fill、事件、账本、指标和报告逐字节一致。

APPROXIMATED、2 倍杠杆、人工排除亏损区间或修改 OOS 后得到的结果不能满足门槛。

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
2. `market_view=NO_TRADE` 与 `setup_state=NO_SETUP` 的兼容方案。
3. Golden Fixture 数值、pre-roll 和缺口 reset。
4. Candidate、Plan、Rejection、Fill 和事件字段。
5. stop/TP、成本、unit risk、required cash 和开放风险公式。
6. 同时计划缩量不二次分配余额。
7. VERIFIED/APPROXIMATED 的用途与 forward gate 限制。
8. 估算强平模型及其非精确声明。
9. 1m 事件步骤 1–13 和同一分钟矩阵。
10. HALT 只在每分钟 mark close snapshot 评估的提案。
11. 66 个月最低共同数据、18 月锁定 OOS 和 walk-forward。
12. 243 组合敏感性网格、基准和 bootstrap 方法。

## 12. 当前明确限制

- 1m OHLC 不能恢复分钟内真实路径，因此必须保留双路径。
- 没有历史盘口，slippage 只能是版本化假设和压力测试。
- 当前 exchangeInfo 不能证明历史 contract rule；VERIFIED archive 可能限制可用样本。
- maintenance tier 历史档案可能不完整；缺失会减少可交易区间，不能静默近似。
- 估算强平不等于 Binance 实际强平。
- 回测和统计门槛通过也不能保证未来收益。
- 本文件获批前不得创建第二批业务代码；获批后仍从 2A 单独开始。
