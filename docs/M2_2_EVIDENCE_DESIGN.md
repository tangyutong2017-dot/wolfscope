# M2-2 EvidenceLedger 设计

## 目标与边界

EvidenceLedger 只回答“当前玩家观察到了什么、来源是什么、何时发生、何时获知”，不保存身份概率、信任分、策略建议或上帝真相。九名玩家分别拥有追加式账本，Evidence ID 使用 `p{seat}-e{sequence}` 本地连续编号。

## 信息层次

```text
Engine Event / Own Role State
  → VERIFIED 或 OBSERVED Evidence

Public Speech
  → RawSpeech（Python 必定保留）
  → PublicSpeechAnnotation（后续只提取一次）
  → CLAIMED Evidence

EvidenceLedger
  → 后续 BeliefState
```

`VERIFIED` 表示对当前玩家而言由规则或 Engine 确认；`OBSERVED` 表示确定观察到发言行为；`CLAIMED` 只表示某玩家提出了命题，不代表命题为真。

## 时间与来源

每条记录区分 `occurred_at` 与 `known_at`，二者都只使用玩家本地顺序。例如女巫刀口发生于 `night_wolf`，女巫在 `night_witch` 才获知。来源只暴露玩家本地 Event ID 或自己的角色状态字段，服务端 GOD Event ID 不进入模型输入。

账本通过内部去重键和 `last_processed_view_event_id` 增量同步完整 PlayerView，重复同步不会添加记录，旧视图会被拒绝。

## 确定性映射

- 私人事实：自己身份、狼队友、狼刀目标、真实查验、女巫刀口和女巫行动。
- 警长事实：报名、退水、实际投票、当选或流警。
- 公共事实：天亮死亡、平安夜、放逐票、放逐结果、自爆、猎人行动和警徽处理。
- 公开话语：竞选发言、普通发言、PK 发言和遗言先保存为 RawSpeech。
- GOD 结算、具体夜间死因和内部 fallback 不进入玩家账本。

公开票型按每名投票者拆成独立 `ActualVoteFact`，便于后续比较发言意图与真实投票。

## 规则必然推导

只有在冻结的 `standard-9-v1` 下，Python 才产生以下 `RULE_DERIVATION`：

- `peaceful_night` 必然推出女巫使用解药，但不能推出被救者。
- `dawn_deaths` 同时公布两名夜间死者，必然推出女巫使用毒药，但不能区分刀口和毒口。
- `hunter_did_not_shoot` 直接确认该玩家是猎人且选择不开枪。
- 普通死亡后没有枪声，不能排除猎人身份。

## 当前状态

纯 Python Schema、Ledger、九座位 Registry 和确定性 Event Projector 已完成。公共 Claim 的严格 Schema、一次性 LLM 提取、缓存和账本分发属于 M2-2b，尚未接入 Agent Prompt。
