# 第二批 2C 验收矩阵

状态：`FROZEN_FOR_TDD_IMPLEMENTATION`。本矩阵追踪 60 项 Requirement、23 个 Timeline Golden；测试名是编码阶段必须落地的稳定注册名。

缩写：`U`=unit，`P`=property，`TL`=timeline golden。实现路径均位于 `pa_agent/research_backtest/simulation/`，测试位于 `tests/research_backtest/simulation/`。

## A. Requirement 双向追踪（60）

| ID | 冻结行为 | 显式测试 / Property 或 Golden | 实现 | 红队 |
|---|---|---|---|---|
| 2C-LIFE-001 | Candidate→Intent→目标分钟调用 2B Entry planner | `test_entry_plan_is_built_at_target_minute`; TL-01 | `planning.py` | RT-25 |
| 2C-LIFE-002 | 完整 run 禁止预生成最终 Plan 作为权威输入 | `test_full_run_rejects_prefabricated_plan_stream`; P-01 | `inputs.py` | RT-25 |
| 2C-LIFE-003 | Exit condition→Intent→目标 open 调用 2B Exit planner | `test_exit_plan_is_built_at_target_open`; TL-05 | `planning.py` | RT-28 |
| 2C-LIFE-004 | TIME_EXIT 只源于 origin Plan maximum exit | `test_time_exit_source_and_boundary`; TL-20 | `planning.py` | RT-28 |
| 2C-LIFE-005 | TREND_EXIT 只在 closed 4H 且失去持仓方向 | `test_trend_exit_closed_boundary`; TL-21 | `planning.py` | RT-28 |
| 2C-LIFE-006 | HALT_EXIT 下一可用 open 且 HALTED 不阻止 | `test_halt_exit_survives_entry_disable`; TL-09 | `planning.py` | RT-20 |
| 2C-LIFE-007 | EXPERIMENT_END 在配置 open 退出且禁止新仓 | `test_experiment_end_exit_open`; TL-22 | `engine.py` | RT-29 |
| 2C-LIFE-008 | 同刻 Scheduled 原因优先且只成交一次 | `test_scheduled_reason_priority`; P-02 | `planning.py` | RT-28 |
| 2C-LIFE-009 | `MINUTE_EVENT_ORDER_V2` 14 阶段唯一 | `test_minute_event_order_v2`; TL-17 | `engine.py` | RT-05,RT-06 |
| 2C-LIFE-010 | 同一 Plan/Intent 最多消费一次 | `test_plan_intent_idempotency`; P-03 | `engine.py` | RT-08 |
| 2C-LIFE-011 | HALT 后 Entry 永久取消、退出继续 | `test_halt_absorbing_but_drains_positions`; TL-23 | `engine.py` | RT-19,RT-20 |
| 2C-LIFE-012 | BTC/ETH 同分钟稳定顺序与原子 batch | `test_dual_symbol_batch_order`; TL-08 | `engine.py` | RT-17 |
| 2C-FILL-001 | Entry fill 等于 2B expected fill，无二次滑点 | `test_entry_fill_exact_plan_price`; TL-01 | `fills.py` | RT-03,RT-04 |
| 2C-FILL-002 | Scheduled fill 等于 ExitPlan expected fill | `test_scheduled_fill_exact_plan_price`; TL-05 | `fills.py` | RT-04 |
| 2C-FILL-003 | stop 只由 trade OHLC 触发 | `test_stop_trade_source_only`; P-04 | `triggers.py` | RT-09 |
| 2C-FILL-004 | TP 只由 trade OHLC 触发 | `test_tp_trade_source_only`; P-04 | `triggers.py` | RT-09 |
| 2C-FILL-005 | 估算爆仓只由 mark OHLC 触发 | `test_liquidation_mark_source_only`; P-04 | `liquidation.py` | RT-09 |
| 2C-FILL-006 | open gap 优先级 LIQ>STOP>TP>Scheduled | `test_open_gap_priority`; TL-17..19 | `triggers.py` | RT-30 |
| 2C-FILL-007 | gap 使用 open reference 加一次不利滑点 | `test_gap_fill_long_short`; TL-06,TL-07 | `fills.py` | RT-12 |
| 2C-FILL-008 | 非 gap stop/TP 用 trigger reference | `test_non_gap_protective_fill`; P-05 | `fills.py` | RT-04 |
| 2C-FILL-009 | 每仓位每分钟最多一个 Exit Fill | `test_one_exit_per_position_minute`; P-06 | `engine.py` | RT-10 |
| 2C-FILL-010 | open 保护退出取消 Scheduled Plan | `test_open_exit_cancels_scheduled`; TL-18 | `engine.py` | RT-30 |
| 2C-COST-001 | entry fee 恰好一次且 Plan 只校验 | `test_entry_fee_once`; P-07 | `ledger.py` | RT-15 |
| 2C-COST-002 | exit fee 恰好一次 | `test_exit_fee_once`; P-07 | `ledger.py` | RT-15 |
| 2C-COST-003 | funding 用真实 timestamp/rate/mark | `test_historical_funding_decimal`; TL-14 | `funding.py` | RT-07 |
| 2C-COST-004 | funding 边界：旧仓付、同刻退仍付、新仓不付 | `test_funding_boundary`; TL-05 | `funding.py` | RT-06,RT-07 |
| 2C-COST-005 | LONG/SHORT × 正负费率符号正确 | `test_funding_sign_quadrants`; TL-14 | `funding.py` | RT-07 |
| 2C-COST-006 | reserve release 只解锁、不进 wallet | `test_reserve_release_not_income`; P-08 | `ledger.py` | RT-16 |
| 2C-COST-007 | planned slice 每事件释放，退出释放余量 | `test_funding_reserve_slices`; TL-23 | `funding.py` | RT-16 |
| 2C-COST-008 | funding 收入不增加 reserve | `test_funding_income_does_not_grow_reserve`; TL-14 | `funding.py` | RT-16 |
| 2C-COST-009 | 不利 funding 超 reserve 即 INVALID | `test_funding_reserve_exceeded_invalid`; TL-23 | `funding.py` | RT-31 |
| 2C-POS-001 | 每 symbol 最多一个逐仓单向仓位 | `test_one_way_position_limit`; P-09 | `positions.py` | RT-17 |
| 2C-POS-002 | quantity/stop/TP/risk 与 origin Plan 一致 | `test_position_preserves_plan_geometry`; TL-01 | `positions.py` | RT-25 |
| 2C-POS-003 | isolated margin 恒等 origin initial_margin | `test_fixed_isolated_margin`; P-10 | `positions.py` | RT-32 |
| 2C-POS-004 | fee/funding 不改变 isolated margin | `test_fee_funding_wallet_only`; TL-23 | `ledger.py` | RT-32 |
| 2C-POS-005 | LONG/SHORT 爆仓参考公式独立一致 | `test_liquidation_reference`; P-11 | `liquidation.py` | RT-14 |
| 2C-POS-006 | maintenance 缺失/过期且持仓即 INVALID | `test_maintenance_evidence_fail_closed`; TL-11 | `liquidation.py` | RT-13 |
| 2C-POS-007 | 爆仓输出估算水印/版本/来源 | `test_liquidation_watermark`; P-12 | `liquidation.py` | RT-14 |
| 2C-ACCT-001 | 初始 wallet/equity/peak 与 locks 固定 | `test_initial_account_state`; P-13 | `domain.py` | RT-33 |
| 2C-ACCT-002 | equity=wallet+unrealized | `test_equity_identity`; P-14 | `ledger.py` | RT-18 |
| 2C-ACCT-003 | available=wallet-全部 locks | `test_available_identity`; P-14 | `ledger.py` | RT-18 |
| 2C-ACCT-004 | 所有经济量只由 Ledger reducer 改变 | `test_ledger_is_only_mutator`; P-15 | `ledger.py` | RT-18 |
| 2C-ACCT-005 | margin/reserve lock-release 守恒且不双扣 | `test_lock_release_conservation`; P-16 | `ledger.py` | RT-15,RT-16 |
| 2C-ACCT-006 | available<0、locks无覆盖、margin<=0 即 INVALID | `test_account_invariant_fail_closed`; P-17 | `ledger.py` | RT-34 |
| 2C-ACCT-007 | 0.5%/1% 风险由当前状态调用 2B 复核 | `test_planner_sees_current_account_risk`; TL-08 | `planning.py` | RT-25 |
| 2C-ACCT-008 | 回撤 >=10% 永久 HALTED | `test_halt_absorbing`; TL-15 | `halt.py` | RT-19 |
| 2C-ACCT-009 | HALT 后继续退出并分离 halt/final 时间 | `test_halt_result_times`; TL-23 | `engine.py` | RT-19,RT-20 |
| 2C-ACCT-010 | intraminute 暴露集合遵循 V1 保守政策 | `test_intraminute_exposure_policy`; P-18 | `halt.py` | RT-27 |
| 2C-DATA-001 | 关键 trade 缺口 INVALID | `test_contextual_trade_gap`; TL-10 | `inputs.py` | RT-21 |
| 2C-DATA-002 | 持仓期间关键 mark 缺口 INVALID | `test_contextual_mark_gap`; TL-11 | `inputs.py` | RT-21 |
| 2C-DATA-003 | 跨 funding 点记录缺失 INVALID | `test_contextual_funding_gap`; TL-12 | `inputs.py` | RT-21 |
| 2C-DATA-004 | 空仓无事件缺口仅记录 | `test_flat_irrelevant_gap_nonblocking`; TL-13 | `inputs.py` | RT-21 |
| 2C-DATA-005 | index 始终仅审计 | `test_index_audit_only`; P-19 | `inputs.py` | RT-21 |
| 2C-DATA-006 | INVALID 有 terminal 输出且不伪造 Equity | `test_invalid_terminal_without_fake_equity`; TL-11 | `engine.py` | RT-21 |
| 2C-ID-001 | SimulationConfig 闭式、UTC 对齐、内容寻址 | `test_simulation_config_identity`; P-20 | `domain.py` | RT-33 |
| 2C-ID-002 | run ID 含真实 2A/2B/config/data 依赖且无 acquisition | `test_run_identity_dependencies`; P-21 | `identity.py` | RT-22,RT-25 |
| 2C-ID-003 | 最多两个稳定 path identity 且逐字节可回放 | `test_bounded_paths_and_replay`; TL-16 | `ambiguity.py` | RT-23,RT-26 |
| 2C-SCOPE-001 | 无 GUI/PyQt/LLM/API Key/auth import | `test_simulation_scope_imports`; P-22 | `scope_guard.py` | RT-24 |
| 2C-SCOPE-002 | 无 HTTP/socket/create_order/交易接口 | `test_simulation_has_no_network_surface`; P-23 | `scope_guard.py` | RT-24 |
| 2C-SCOPE-003 | 无 2D 绩效/晋级/paper/live | `test_simulation_scope_files_symbols`; P-24 | `scope_guard.py` | RT-24 |

## B. Golden Timeline Fixtures（23）

| Fixture | 场景 | 必须证明 |
|---|---|---|
| TL-01 | 正常 LONG 动态规划入场后 TP | 目标分钟调用 2B、单次 fee、Plan geometry |
| TL-02 | 正常 SHORT 动态规划入场后 stop | SHORT 符号与实际成交 |
| TL-03 | 同分钟 stop 与 TP | 两个固定 policy、PATH_AMBIGUOUS |
| TL-04 | 同分钟 stop 与估算爆仓 | trade/mark 分源与最差选择 |
| TL-05 | funding 与 TIME_EXIT 同刻 | 先 funding、再动态 ExitPlan |
| TL-06 | LONG open gap 越过 stop | open reference + 一次不利滑点 |
| TL-07 | SHORT open gap 越过 stop | 对称公式和 tick 量化 |
| TL-08 | BTC/ETH 同分钟规划 | 当前账户、原子 batch、稳定顺序 |
| TL-09 | HALT 后旧仓 Exit 与新 Entry | Exit 继续、Entry 禁止 |
| TL-10 | 持仓关键 trade 缺口 | PathInvalidEvent 与终止 |
| TL-11 | 持仓关键 mark 缺口 | terminal PathResult、无假 Equity |
| TL-12 | 有仓位跨 funding 点但记录缺失 | INVALID |
| TL-13 | 空仓无事件 mark 缺口 | 只告警，不阻后续 Candidate |
| TL-14 | 正负 funding × LONG/SHORT | 四象限 wallet delta、收入不增 reserve |
| TL-15 | intraminute 回撤触发后 close 恢复 | 仍永久 HALTED |
| TL-16 | 相同规范输入重复运行 | 输出逐字节一致，path<=2 |
| TL-17 | TIME_EXIT 同刻 mark open 越过 liq | LIQ 优先、Scheduled 取消 |
| TL-18 | TREND_EXIT 同刻 trade open 跳过 stop | STOP 优先、无双平仓 |
| TL-19 | Scheduled Exit 与 TP open gap 同刻 | TP 优先、原因审计 |
| TL-20 | maximum_exit_time 边界 | TIME_EXIT 仅由 origin Plan 产生 |
| TL-21 | closed 4H trend 失去方向 | TREND_EXIT；NO_SETUP 不单独触发 |
| TL-22 | experiment end open | 全平、无新 Entry、无 close 临时价 |
| TL-23 | HALT 后两分钟退出且 funding 超 reserve 分支 | halt/final 时间分离、reserve fail closed |

## C. 验收计数与门槛

- 显式业务测试、Property 测试、Timeline Golden、Requirement 追踪测试分别计数；生成式追踪测试不得描述成完全独立交易场景。
- 60/60 Requirement 必须双向注册；未知 Requirement 或无测试/实现绑定均失败。
- 23 个 Timeline 必须固定 Canonical 输入、Event/Ledger/Trade/Equity/PathResult 和最终 hash。
- 默认测试不得创建 QApplication、API Key 窗口、网络连接或交易请求。
- 完整 run 必须动态调用 2B planner；只允许局部 Golden 以 `LOCAL_PLAN_FIXTURE_ONLY` 注入 Plan。
