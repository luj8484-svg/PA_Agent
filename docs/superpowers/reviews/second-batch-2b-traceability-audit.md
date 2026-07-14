# 2B 规格冻结完整性与追踪审计

日期：2026-07-14

审计基线：`fork/main@07004498a7091519a4fb08c323a1dde5b97ced6d`
结论：候选冻结包内部完整；等待人工一次性审核。未授权编码。

## 1. 交付计数

| 项目 | 数量 | 权威文件 |
|---|---:|---|
| Requirement/主验收矩阵行 | 66 | `second-batch-2b-acceptance-matrix.md` |
| 主 Unit Test ID | 66 | 同上 |
| Property Test 映射 | 66 行均有 | 同上 |
| Golden Fixture 映射 | 66 行均有 | 同上 |
| 非法状态 | 30 | `second-batch-2b-illegal-state-matrix.md` |
| 时间边界案例 | 20 | `second-batch-2b-time-boundary-matrix.md` |
| Golden Fixture 计划 | 45 | `second-batch-2b-golden-fixture-plan.md` |
| 红队攻击场景 | 30 | `second-batch-2b-red-team.md` |
| 红队 BLOCKER | 6 个发现、6 个关闭、0 个未关闭 | 同上 |
| 未决设计问题 | 0 | frozen spec 第16节 |

## 2. Requirement 分类

| Prefix | 数量 | 设计入口 | 测试入口 |
|---|---:|---|---|
| 2B-LIFE | 6 | Spec 6 | Acceptance A |
| 2B-SCHEMA | 8 | Spec 4–5 | Acceptance A |
| 2B-TIME | 7 | Spec 7/12 | Acceptance B、Time matrix |
| 2B-GAP | 4 | GAP-F01、Spec 10 | Acceptance C |
| 2B-COST | 5 | PRICE/COST formulas | Acceptance D |
| 2B-FUND | 6 | Spec 8 | Acceptance E |
| 2B-RULE | 6 | Spec 5.6/9 | Acceptance F |
| 2B-RISK | 6 | RISK/CASH formulas、Spec 5.10 | Acceptance G |
| 2B-QTY | 4 | QTY/MIN formulas | Acceptance G |
| 2B-PORT | 4 | SCALE formulas | Acceptance H |
| 2B-ID | 5 | Spec 3 | Acceptance I |
| 2B-SCOPE | 5 | Spec 14 | Acceptance J |
| 合计 | 66 | 全覆盖 | 全覆盖 |

## 3. 需求→设计→测试链

每条 Requirement 行均包含：描述、不变量、唯一数据来源、合法/非法输入、预期输出、Failure/Rejection、边界、Unit Test、Property Test、Golden Fixture、未来实现文件和状态。追踪规则：

```text
Requirement ID
  -> frozen spec section / Formula ID / Schema field
  -> exactly named Unit Test ID
  -> Property Test family
  -> Golden Fixture ID
  -> planned implementation file
```

未来测试函数必须声明 Requirement ID；CI 比较“矩阵 Test ID 集合”和“测试声明 Test ID 集合”完全相等。非法状态、时间边界和红队测试作为主 Requirement 的附加 Test ID，不创造没有 Requirement 的独立语义。

## 4. 字段唯一来源审计

| 字段族 | 唯一真相源 | 被拒绝的第二来源 |
|---|---|---|
| Candidate side/time/ATR/close | 2A StrategyCandidate | 2B 重新计算趋势/方向 |
| Intent target | TIME-F01/F02 + delay config | 搜索下一个现存 bar、wall clock |
| Plan reference price | target trade 1m open | mark/index/future close |
| Contract tick/step/minimum | ContractRuleCoverage | 当前 exchangeInfo 静默回填 |
| Fee/slippage/cap | CostModelSnapshot | account/API 动态查询 |
| Funding count | FundingScheduleSnapshot windows | 固定×6/×7 |
| Quantity | sizing formula→portfolio scale | 手工 minimum 向上取整 |
| Available balance | AS 派生公式 | 任意独立外部字段 |
| Pending cash/risk | AS pending_plan_reserve/risk | 重复包含在 available/existing open risk |
| Continuity/data validity | 上游已验证 inputs/watermark | 全局历史 bool |
| Object identity | 全字段 Canonical ID | 外部 mutable input hash |

## 5. 状态唯一来源审计

- Candidate 不因执行拒绝被改写。
- Intent、Plan、Rejection 均 immutable；不存在 `status` mutable 字段。
- Plan 是否接受由 final object 或 Rejection tagged output 表达，不在 Plan 内再保存 accepted bool。
- Contract mode 由 tagged union 表达，不用 nullable rule fields。
- Scaling item 由 accepted/rejected union 表达，不同时保存 quantity 和 rejection reason。
- Account snapshot 来自上游一次性快照；2B 不产生新账户状态。
- 退出条件由 ExitConditionSnapshot 提供；2B 不保存第二套 trigger truth。

## 6. 提交前 12 项完整性检查

| # | 检查 | 结果 | 证据 |
|---:|---|---|---|
| 1 | 每个 Requirement 至少一个测试 | PASS | 66/66 行有 Unit Test ID |
| 2 | 每个测试至少一个 Requirement | PASS by design | Test ID 只能从矩阵/专项矩阵生成；未来 CI 双集合校验 |
| 3 | 每个领域字段唯一来源 | PASS | Spec 5 + 本文第4节 |
| 4 | 每个状态只有一个真相源 | PASS | 本文第5节 |
| 5 | 每个时间字段来自事件时钟 | PASS | Spec 12 + Time matrix 来源表 |
| 6 | 每个公式有版本和舍入顺序 | PASS | Spec 7 共35个 Formula ID |
| 7 | 每个 ID 列出全部输入字段 | PASS | Spec 3.3；对象全字段排除自身 |
| 8 | 每个失败组合有确定性优先级 | PASS | Spec 11 rank 1–18 + Illegal组合矩阵 |
| 9 | 每个 APPROX 结果有水印 | PASS | Spec 5.2/5.6/9，2B-RULE-002 |
| 10 | 无2C/GUI/LLM/HTTP/交易越界 | PASS | Spec 1/14 + docs-only diff gate |
| 11 | 红队无未关闭 BLOCKER | PASS | 6/6 closed，0 open |
| 12 | 未决问题集中且不留编码决定 | PASS | Spec 16，未决=0 |

## 7. 版本与公式关联

| Version | Formula/Schema |
|---|---|
| EXECUTION_TIME_CONFIG_V1 | TIME-F01/F02 |
| MAX_HOLD_V1_EXACT_48H | TIME-F03 |
| GAP_POLICY_V1 | GAP-F01 |
| SLIPPAGE_MODEL_V1 | COST-F02、PRICE-F04/F07/F08/F09 |
| PRICE_GEOMETRY_V1 | PRICE-F05/F06 + strict geometry |
| FEE_MODEL_V1 | COST-F01/F09/F10/F11 |
| FUNDING_BUFFER_MODEL_V1 | FUND-F11/F12 |
| POSITION_SIZING_MODEL_V1 | RISK-F13–19、QTY-F16、CASH-F19/F20 |
| ACCOUNT_PLANNING_SNAPSHOT_SCHEMA_V1 | CASH-F01 |
| PORTFOLIO_SCALING_MODEL_V1 | RISK-F21/F22、CASH-F22/F23、SCALE-F23/F24 |
| CONTRACT_MINIMUM_V1 | MIN-F25 |
| LEVERAGE_POLICY_V1_FIXED_1X | LEV-F26 |
| 2B_REJECTION_PRIORITY_V1 | Spec 11 rank matrix |
| 2B_CANONICAL_VERSION_V1 | 所有正式对象 ID/bytes |

## 8. 范围审计规则

本设计分支允许路径只有：

```text
docs/superpowers/specs/second-batch-2b-frozen-spec.md
docs/superpowers/reviews/second-batch-2b-*.md
```

禁止修改 `pa_agent/`、`tests/`、`scripts/`、配置或依赖。提交前运行：

```text
git diff --name-only fork/main...HEAD
git diff --check
```

另行执行中英文占位符与模糊措辞扫描；当前规范公式中不使用近似语言。

## 9. 人工审核入口

人工一次性审核应集中确认：

1. Schema 字段是否过多或遗漏，但不得合并 Entry/Exit；
2. 35 个 Formula ID 的数值与舍入；
3. funding window 保守 7 次语义；
4. AS 的 available/pending/open-risk 分解；
5. APPROX Gate；
6. rejection priority；
7. 66 条需求与未来实现拆分。

若人工要求修改，必须一次性更新 spec、acceptance、illegal、time、golden、red-team 和本审计文件，然后再次进行同样完整性检查。人工书面批准前不得生成实现计划或业务/测试代码。
