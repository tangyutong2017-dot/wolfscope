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

纯 Python Schema、Ledger、九座位 Registry 和确定性 Event Projector 已完成。

M2-2b 离线部分也已完成：`RoleClaim`、`CheckClaim`、`AlignmentClaim`、`StanceClaim`、`VoteIntentClaim` 和 `VoteRecommendationClaim` 使用严格联合类型；Claim 必须引用原文片段，未来时间、重复 Claim 和无法定位原文的 Claim 会被删除并分类审计。

语言认知层使用独立的 `ClaimAlignment(good/werewolf)`，不复用 Engine 的 `Camp`。`good` 表示好人阵营，`villager` 只表示具体的普通村民角色：“好人身份”映射为 `AlignmentClaim(good)`，“普通村民”映射为 `RoleClaim(villager)`，预言家验出好人的结果映射为 `CheckClaim(good)`。这一边界避免把神职错误降格为村民，同时保持 M1 规则与 Replay Schema 不变。

`EvidencePipeline` 会批量提取当前尚未缓存的公开发言，并以服务端源事件 ID 建立不可变 `PublicSpeechAnnotation` 缓存。不同玩家即使因为私人事件拥有不同的本地 Event ID，也只触发一次公共提取；分发后仍使用各自本地 Event ID 和 Evidence ID。提取器失败会缓存脱敏失败状态，RawSpeech 永远保留且 Engine 不受阻塞。

AgentScope 公共语义提取器已经实现并接入 HybridProvider 的可选决策前同步。提取 Prompt 只接收 `item_id`、天数、发言者、发言场景和公开原文，明确禁止判断真假、推断身份、补全隐含信息、处理策略或把转述变成发言者本人的查验。输出只允许六类 Claim，并要求 `supporting_text` 逐字来自原文。

提取调用拥有独立的模型、token、延迟、格式修复和脱敏失败追踪；一次结构化修复仍失败时，Pipeline 缓存失败状态并继续使用 RawSpeech。Fake/Stub 已验证完整单日混合局在每条公开话语上只提取一次：首夜遗言一次、八名存活玩家白天发言八次，共九个缓存条目。

解析边界采用“宽传输、严语义”：AgentScope 工具 Schema 明确列出 Claim 字段、类型名称和枚举契约，但只负责保证批次、item 和 Claim 字典能够传输；返回后由本地 Python 逐条使用严格 `PublicClaim` 联合类型校验。合法 Claim 进入不可变缓存，非法 Claim 单独丢弃并记录字段路径、错误类型和脱敏输入摘要，不再导致同一段发言中的合法 Claim 一起丢失。缓存状态会标记为 `PARTIAL` 并保存拒绝数量和原因，RawSpeech 始终保留。

2026-08-07 已完成一次 `deepseek-v4-flash` 真实 Claim 提取冒烟。输入只包含7号的一段公开发言，模型首次结构化通过，耗时4044 ms，输入2285 token、输出436 token。结果正确生成 `RoleClaim`、`CheckClaim` 和 `VoteRecommendationClaim`；“请大家投1号”没有被误标为发言者本人的 `VoteIntentClaim`，也没有产生真假判断或额外身份推断。所有 `supporting_text` 均可在原文中定位。

首次完整 Agent+Evidence 单日 API 测试中，16/16 次玩家决策成功，但公开文本解析仅4/9次成功。第4次成功解析的输出恰好达到原配置的1200 token，后五次长发言均在生成和格式修复阶段报告 `missing_structured_output`，说明思考输出与 Claim 数量耗尽了结构化 tool call 的输出预算。

解析器已针对“只做文本解析”的任务改为非思考模式，温度固定为0，最大输出提高到2000 token；每段最多8条互不重复的 Claim，summary 最长60字，supporting_text 最长80字。玩家决策仍保留原思考配置，模型选择策略也没有改变：开发使用 Flash，正式实验使用 Pro。

投票 Claim 额外要求 `supporting_text` 在同一原文片段中同时出现投票/放逐动作和明确目标座位，禁止从前一句继承目标。真实 API 验证中，宽松传输层首次返回后，本地校验正确接收7号的身份声明、首夜查杀和归票建议三条 Claim，拒绝数为0；独立失败样本也验证非法投票 Claim 会被逐条隔离并输出字段级诊断。

语义数据集当前定位为真实失败回归样本库，不主动扩充为完整人工 Gold，也不使用非穷尽标注计算正式 Precision/Recall。只有发现明确解析错误或 Evidence 影响决策时才增补案例；一对一匹配器、Forbidden 检查和盲测运行器作为回归诊断基础设施保留。这样优先推进 Agent 对 Evidence 的实际使用，避免在 M2 阶段投入过多人工标注和 API token。

`EvidenceContextBuilder` 已把玩家本地 Ledger 转为一次决策使用的紧凑快照：硬事实和规则推导全部保留，身份/查验 Claim 永久保留，其他软 Claim 只保留最近30条，RawSpeech 不重复进入快照。HybridProvider 在每次决策前完成 Ledger 同步并将快照写入 `AgentDecisionInput`。模型可在 `evidence_ids` 中引用实际使用的本地证据；Runtime 会删除不存在或属于其他座位的引用并写入审计 Trace。Prompt 明确区分 VERIFIED、RULE_DERIVATION 与 CLAIMED，避免把公开声明当作真相。
