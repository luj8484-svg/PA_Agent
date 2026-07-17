# 第二批 2C 精简红队

状态：`DRAFT_FOR_ONE_TIME_HUMAN_REVIEW`。只保留会导致未来数据污染、顺序错误、经济量错误、不守恒、不确定或范围越界的 24 个场景；普通命名和扩展偏好不是 BLOCKER。

| ID | 攻击/故障 | 必须防御 | 严重度 |
|---|---|---|---|
| RT-01 | 在 decision time 后替换 Candidate 输入 | 历史 Candidate/Plan/Fill hash 不变 | BLOCKER |
| RT-02 | 未闭合 1m bar 进入引擎 | fail closed，不产生事件 | BLOCKER |
| RT-03 | 用分钟 high/low 改写 open Entry | Entry 只能消费 Plan expected fill | BLOCKER |
| RT-04 | 对 expected fill 再施加滑点 | 费用/成交 Golden 立即失败 | BLOCKER |
| RT-05 | Scheduled Exit 与 Entry 顺序互换 | 固定先退出后 batch gate | BLOCKER |
| RT-06 | funding 与同刻退出顺序互换 | 固定先 funding 后退出 | BLOCKER |
| RT-07 | 新 Entry 错付同刻 funding | 只对进入分钟前仓位结算 | BLOCKER |
| RT-08 | 同一 funding timestamp 重放 | idempotency 集拒绝第二次入账 | BLOCKER |
| RT-09 | stop 用 mark、liquidation 用 trade | 数据源类型校验失败 | BLOCKER |
| RT-10 | stop/TP 同分钟悄悄选择有利结果 | 必须双路径并 PATH_AMBIGUOUS | BLOCKER |
| RT-11 | stop/liquidation 跨流强行判序 | baseline proxy + conservative worst 显式记录 | BLOCKER |
| RT-12 | gap 仍按 trigger 成交 | 必须改用 open reference | BLOCKER |
| RT-13 | maintenance tier 缺失仍继续持仓 | 路径 INVALID | BLOCKER |
| RT-14 | 将估算爆仓声称为交易所精确值 | schema 必须含估算水印/版本/来源 | BLOCKER |
| RT-15 | entry/exit fee 在 Plan 与 Ledger 双扣 | Plan 值只校验，Ledger 只扣一次 | BLOCKER |
| RT-16 | reserve 释放又计作收入 | reserve 只改变 lock，不改变 wallet | BLOCKER |
| RT-17 | 两个同时 Plan 顺序抢占同一现金 | batch 先整体 gate，再稳定应用 | BLOCKER |
| RT-18 | 平仓后 margin 未释放或释放两次 | position-close idempotency 与守恒断言 | BLOCKER |
| RT-19 | close 恢复后清除 intraminute HALT | HALT 永久、终点固定在首次 breach | BLOCKER |
| RT-20 | HALTED 后仍开新仓 | Entry 永久取消，Exit 仍运行 | BLOCKER |
| RT-21 | trade/mark/funding 关键缺口后继续止损 | 从 data gate 终止 INVALID | BLOCKER |
| RT-22 | acquisition 时间进入 run hash | 重新采集同内容必须同 ID | BLOCKER |
| RT-23 | dict/文件系统顺序改变输出 | Canonical 稳定排序与双运行 hash | BLOCKER |
| RT-24 | 引入 GUI、LLM、API Key、HTTP/create_order 或绩效晋级 | scope guard 阻止合入 | BLOCKER |

## 红队通过标准

- 每个场景至少一个直接失败测试；RT-10、RT-11、RT-17、RT-19、RT-21 还必须进入 Timeline Golden。
- 防御不得依赖日志文本或人工观察，必须由类型、Canonical identity、reducer invariant 或 scope guard 自动判定。
- 红队不得扩展 2C 范围；发现非关键可用性建议只记 NOTE，不新增 Requirement/BLOCKER。
