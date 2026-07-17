# 第二批 2C 精简红队

状态：`FROZEN_FOR_TDD_IMPLEMENTATION`。以下 34 个场景仅覆盖未来数据污染、事件顺序、经济量守恒、路径确定性和范围越界。

| ID | 攻击/故障 | 必须防御 | 严重度 |
|---|---|---|---|
| RT-01 | decision time 后数据改写历史 Candidate | 历史 Candidate/Intent/Fill hash 不变 | BLOCKER |
| RT-02 | 未闭合 1m bar 进入引擎 | fail closed，不产生交易事件 | BLOCKER |
| RT-03 | 用 minute high/low 改写 open Entry | Entry 只消费 2B expected fill | BLOCKER |
| RT-04 | 对 expected fill 再施加滑点 | 成交/费用测试失败 | BLOCKER |
| RT-05 | Scheduled Exit 与 Entry 顺序互换 | 固定先退出再 Entry planning | BLOCKER |
| RT-06 | funding 与同刻退出顺序互换 | 固定先 funding 后退出 | BLOCKER |
| RT-07 | 新 Entry 错付同刻 funding | 只结算进入分钟前仓位 | BLOCKER |
| RT-08 | Plan/funding/close ID 重放 | idempotency 集拒绝第二次经济变动 | BLOCKER |
| RT-09 | stop 用 mark、liquidation 用 trade | 强类型数据源校验失败 | BLOCKER |
| RT-10 | stop/TP 同分钟静默选择有利结果 | 两个 policy 路径均记录 PATH_AMBIGUOUS | BLOCKER |
| RT-11 | stop/liquidation 跨流强行判序 | baseline proxy 与 conservative worst 显式记录 | BLOCKER |
| RT-12 | gap 仍按 trigger 成交 | 必须使用 open reference | BLOCKER |
| RT-13 | maintenance 缺失/过期仍持仓 | 路径 INVALID | BLOCKER |
| RT-14 | 估算爆仓声称交易所精确 | 强制版本、来源和估算水印 | BLOCKER |
| RT-15 | fee 在 Plan 与 Ledger 双扣 | Plan 只校验，Ledger 只扣一次 | BLOCKER |
| RT-16 | reserve 释放计收入或 funding 收入增 reserve | lock 与 wallet 完全分离 | BLOCKER |
| RT-17 | BTC/ETH逐Intent独立Sizing、按遍历顺序抢现金，或item失败后重分配 | 同一分钟只调用一次真实2B批量链；唯一Account/Batch/Scaling；批后冲突整批INVALID | BLOCKER |
| RT-18 | 平仓后 margin 未释放/释放两次/旁路改账户 | reducer 守恒与 close idempotency | BLOCKER |
| RT-19 | close 恢复后清除 HALT 或 PathResult 截到 halt | HALT 永久，halt/final 时间分离 | BLOCKER |
| RT-20 | HALT 后开新仓或阻断退出 | Entry 永久禁用，已有仓退出继续 | BLOCKER |
| RT-21 | 关键缺口后继续止损或伪造 Equity | INVALID terminal 输出，关键 mark 缺失无 Equity | BLOCKER |
| RT-22 | acquisition 时间进入 run hash | 同内容重采集必须同 run ID | BLOCKER |
| RT-23 | dict/文件系统顺序改变输出 | Canonical 稳定排序与双运行 hash | BLOCKER |
| RT-24 | 引入 GUI、LLM、API Key、HTTP/create_order、2D | scope guard 阻止 | BLOCKER |
| RT-25 | 用未来模拟账户状态预生成 EntryPlan 并固定回放 | 完整 run 类型/接口拒绝；目标分钟调用 2B | BLOCKER |
| RT-26 | 等到首次歧义才建路径或连续 20 个歧义分钟指数 fork | 两路径从run开始存在，歧义前经济前缀一致，active path 始终恰为2 | BLOCKER |
| RT-27 | 仓位 open 已退出却用 minute extreme 触发 HALT | 暴露集合排除 open 已平仓仓位 | BLOCKER |
| RT-28 | Scheduled Exit 条件不明、NO_SETUP 误触发、原因重复成交 | 四类来源和优先级闭式校验 | BLOCKER |
| RT-29 | experiment end 用最后 close 临时平仓或 end 后开仓 | 仅配置 open 退出，数据不足 INVALID | BLOCKER |
| RT-30 | Scheduled Exit 先于 open gap stop/liq/TP | open protective gate 前置并取消计划退出 | BLOCKER |
| RT-31 | 实际不利 funding 超 reserve 后先扣wallet/释放reserve再INVALID或继续模拟 | 保存record/payment/reserve证据，预提交 `FUNDING_RESERVE_EXCEEDED` + PathInvalidEvent，无Ledger/position部分修改 | BLOCKER |
| RT-32 | fee/funding 同时扣 wallet 与 isolated margin | 固定 isolated margin 不变，单一 Ledger 扣款 | BLOCKER |
| RT-33 | SimulationConfig 时间未对齐或初始 locks/peak 任意 | 闭式 schema 与 fail closed | BLOCKER |
| RT-34 | available 负数用 `max(0)` 修补 | 账户不变量失败即 INVALID | BLOCKER |

## 红队通过标准

- 每个场景至少一个直接失败测试；RT-10、11、17、19、20、21、25、26、27、28、29、30、31、32 必须同时进入 Property 或 Timeline Golden。
- RT-25 必须证明完整运行的公开接口没有“最终 Plan stream”字段，且日志/输出显示 Plan 在目标分钟由 2B 返回。
- RT-17 必须使用真实2B生产函数证明BTC LONG与ETH SHORT共享唯一账户快照、Batch和ScalingResult；输入逆序不改变结果，量化拒绝不触发重分配，批后现金/风险/证据冲突不得静默删除交易。
- RT-26 对连续 20 个歧义分钟断言每一分钟 active path count 恰为2，并以Property证明无歧义经济输出一致、首次歧义前缀一致且只从该分钟起允许分化。
- RT-27 必须区分 open 已退出、intraminute 退出、持有到 close 三种暴露集合。
- RT-31 必须检查失败前后wallet、locks、position reserve/events完全不变，并保留独立于HALT Timeline的失败hash。
- 防御必须由闭式类型、Canonical identity、纯 reducer invariant 或 scope guard 自动判定，不依赖日志文本或人工观察。
- 红队不得扩展到 2D、GUI、LLM、网络或自动交易。
