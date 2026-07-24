# Binance USD-M 数据就绪审计

最终状态: `DATA_COVERAGE_INSUFFICIENT`

2D 是否获准: `false`

## 数据来源

仅使用 `https://fapi.binance.com` 的六个 allowlisted 公共 GET 端点; 未使用 API Key、账户、订单、第三方或合成数据。

## 当前共同覆盖

- BTC/ETH、trade/mark/funding 共同起点: 2026-07-01T00:00:00Z
- 共同终点: 2026-07-18T16:00:00.001000Z
- 共同覆盖: 17.666667 天, 要求约 2008.833750 天 (66个月)
- 可用性质: `DIAGNOSTIC_ONLY`

## 在线真实性抽样

固定 seed `20260719`, 规则 `SHA256_LOWEST_RANK_BY_SEED_NAMESPACE_TIMESTAMP_V1`。

matched=160, mismatched=0, missing_from_remote=0, missing_from_local=0

## 后续最小更新方案 (仅设计, 未实现)

每个 UTC 4H 收盘后等待一分钟, 以 Binance serverTime 为唯一闭合判据进行公共 REST 增量刷新; 分页断点恢复、限次重试, 关键流缺口 fail closed。校验通过后才调用现有确定性 Candidate/ExecutionPlan; 不需要 API Key, 不连接账户, 不实现 WebSocket、自动下单或长期后台服务。

## 结论

当前数据覆盖不足 66 个月, 因此仅可用于 `DIAGNOSTIC_ONLY`, 不得称为正式 OOS, 也不得继续 2D。
