# 第二批 2C 验收矩阵

状态：`DRAFT_FOR_ONE_TIME_HUMAN_REVIEW`。本矩阵完整展开 48 项冻结 Requirement，并定义 16 个必须逐事件 Golden Timeline Fixture。

## A. Requirement → 验收证据（48）

| ID | 冻结行为 | 最小验收证据 |
|---|---|---|
| 2C-LIFE-001 | 只消费目标分钟到期且此前已存在的 Plan | 未来 Plan 注入不改变历史前缀 |
| 2C-LIFE-002 | 每分钟严格执行 `MINUTE_EVENT_ORDER_V1` | 事件类型序列 Golden |
| 2C-LIFE-003 | Plan/Candidate 不被 2C 修改或重算 | 输入 Canonical bytes 前后相同 |
| 2C-LIFE-004 | 一个 plan_id 最多消费一次 | 重复输入只产生一次 Fill |
| 2C-LIFE-005 | Scheduled Exit 先于同刻 Entry | 退出释放资金后才批量入场 |
| 2C-LIFE-006 | HALTED 只允许退出 | HALT 后 Entry 取消且 Exit 可执行 |
| 2C-LIFE-007 | INVALID 立即终止路径 | INVALID 后无 Fill/Ledger/Equity 推演 |
| 2C-LIFE-008 | BTC/ETH 同分钟事件稳定排序 | `(symbol, plan_id)` 顺序恒定 |
| 2C-FILL-001 | Entry fill 等于 Plan expected fill | 无第二次滑点 |
| 2C-FILL-002 | Scheduled Exit 等于 ExitPlan expected fill | 无第二次滑点 |
| 2C-FILL-003 | stop 仅由 trade OHLC 触发 | mark 不触发 stop |
| 2C-FILL-004 | TP 仅由 trade OHLC 触发 | mark 不触发 TP |
| 2C-FILL-005 | 爆仓仅由 mark OHLC 触发 | trade 不触发 liquidation |
| 2C-FILL-006 | gap-at-open 使用 open 加一次不利滑点 | LONG/SHORT 双向 Golden |
| 2C-FILL-007 | 多触发生成 baseline/conservative | 两路径均标 PATH_AMBIGUOUS |
| 2C-FILL-008 | 一仓位一分钟最多一个退出 Fill | 冲突场景无重复平仓 |
| 2C-COST-001 | 入场费恰好扣一次 | wallet delta 与 fee ledger 一致 |
| 2C-COST-002 | 退出费恰好扣一次 | Trade 与 ledger 同值不双扣 |
| 2C-COST-003 | funding 使用真实 timestamp/rate/mark | 历史 fixture 精确 Decimal |
| 2C-COST-004 | funding 边界为进入分钟前持仓 | 同刻退出支付、新入场不支付 |
| 2C-COST-005 | 正负费率与 LONG/SHORT 符号正确 | 四象限参数测试 |
| 2C-COST-006 | reserve 释放与实际支付分离 | 无少算、重复或锁死余额 |
| 2C-POS-001 | 每 symbol 最多一个逐仓单向仓位 | 反向/重复 Entry fail closed |
| 2C-POS-002 | BTC 与 ETH 可并存且独立保证金 | 双仓 timeline |
| 2C-POS-003 | quantity 与 origin Plan 完全一致 | 2C 禁止重算或加仓 |
| 2C-POS-004 | 估算爆仓公式和 mmr tier 版本化 | LONG/SHORT 独立参考公式 |
| 2C-POS-005 | mmr 缺失/过期且持仓时 INVALID | 不假设安全 |
| 2C-POS-006 | 爆仓输出估算水印 | 不声称 Binance 精确值 |
| 2C-ACCT-001 | equity=wallet+unrealized | 每个 reducer 后断言 |
| 2C-ACCT-002 | available 等于 wallet 减全部 locks | 每事件重放一致 |
| 2C-ACCT-003 | 同一资金不可被两个 Plan 使用 | batch 原子 gate |
| 2C-ACCT-004 | margin/reserve lock-release 守恒 | 入场至退出完整 ledger |
| 2C-ACCT-005 | 单笔 0.5%、组合 1% 继承 2B 且消费前复核 | 篡改 Plan 被拒绝 |
| 2C-ACCT-006 | 峰值回撤 >=10% 永久 HALTED | intraminute 与 close 两种触发 |
| 2C-ACCT-007 | HALTED 区间不计算误导性完整年化 | PathResult 终点为 halt time |
| 2C-DATA-001 | 影响到期事件/持仓的 trade 缺口 INVALID | trade-gap fixture |
| 2C-DATA-002 | 持仓期间 mark 缺口 INVALID | mark-gap fixture |
| 2C-DATA-003 | 持仓跨 funding 点缺记录 INVALID | funding-gap fixture |
| 2C-DATA-004 | 空仓无事件 mark 缺口只告警 | Candidate/历史前缀不阻断 |
| 2C-DATA-005 | index 缺失始终只作审计告警 | 路径状态不变 |
| 2C-ID-001 | 相同输入逐字节相同输出 | 双运行目录 hash 相同 |
| 2C-ID-002 | acquisition 元数据不影响 run ID | 重新下载同内容 identity 相同 |
| 2C-ID-003 | Event/Ledger/Trade/Equity 各自闭合 hash | 单字段篡改验证失败 |
| 2C-ID-004 | 路径 fork 共享父 hash 且子 ID 唯一 | baseline/conservative identity Golden |
| 2C-SCOPE-001 | 无 GUI/PyQt import | AST/import-closure guard |
| 2C-SCOPE-002 | 无 LLM/API Key/鉴权 | token 与 import guard |
| 2C-SCOPE-003 | 无 HTTP/交易/create_order | AST 与 socket monkeypatch guard |
| 2C-SCOPE-004 | 无绩效晋级、walk-forward、OOS/网格 | 文件和符号范围 guard |

## B. Golden Timeline Fixtures（16）

每个 fixture 固定完整输入 Canonical JSON、期望 Event 序列、Ledger、Trade、Equity、路径状态与最终 hash。

| Fixture | 场景 | 必须证明 |
|---|---|---|
| TL-01 | 正常 LONG 入场后 TP | Entry/fee/position/TP/realized PnL |
| TL-02 | 正常 SHORT 入场后 stop | SHORT 符号、stop fee、亏损 |
| TL-03 | 同分钟 stop 与 TP | PATH_AMBIGUOUS 双路径 |
| TL-04 | 同分钟 stop 与估算爆仓 | trade/mark 双源冲突与最差路径 |
| TL-05 | funding 与 TIME_EXIT 同刻 | 先 funding 后退出 |
| TL-06 | LONG gap 跳过 stop | open reference + 一次不利滑点 |
| TL-07 | SHORT gap 跳过 stop | 对称公式与 tick 量化 |
| TL-08 | BTC/ETH 同时持仓 | batch 资金守恒和稳定顺序 |
| TL-09 | HALT 后有 Exit 和新 Entry | Exit 允许、Entry 取消 |
| TL-10 | 持仓期间 trade 缺口 | 从 DATA_GATE 起 INVALID |
| TL-11 | 持仓期间 mark 缺口 | 不继续假设保护有效 |
| TL-12 | funding 点缺失 | 跨越仓位路径 INVALID |
| TL-13 | 空仓 mark 缺口 | 只告警，不阻断后续有效 Plan |
| TL-14 | 正/负 funding × LONG/SHORT | 四象限 wallet delta |
| TL-15 | intraminute 回撤触发 HALT 后 close 恢复 | 仍永久 HALTED |
| TL-16 | 相同输入重复运行 | 所有输出逐字节一致 |

## C. 最低交付验收

- 输入 BTC/ETH 1m trade/mark、funding、Candidate、Plan 和版本化模型证据。
- 输出字段齐全的 TradeRecord、逐分钟/逐事件 EquityPoint、`VALID|INVALID|HALTED` PathResult。
- 16 个 Timeline Golden 与独立 Decimal 参考实现通过。
- 所有 48 Requirement 必须至少绑定一个显式测试；每个测试反向只引用已登记 Requirement。
- 默认测试不得创建 QApplication、网络连接、API Key 窗口或交易请求。
