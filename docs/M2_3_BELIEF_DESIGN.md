# M2-3 BeliefState 设计

## 目标

BeliefState 是每个玩家根据自己的 EvidenceLedger 构造的主观局面模型。它不读取 GameState、GOD Replay 或其他玩家账本，也不让 LLM 直接填写概率。当前 `wolfscope.cognition.beliefs.BeliefState` 是 M2 的正式实现；`contracts.py` 中同名类型是 M0 早期接口草图，后续兼容清理时再移除。

## v1 确定性基线

- 使用标准九人角色数量建立先验，并扣除当前玩家确定知道的角色。
- 自己身份为 one-hot 概率。
- 狼人视角中的狼队友为狼人 one-hot；该信息不会进入其他玩家状态。
- 预言家真实狼人查验将目标设为狼人 one-hot。
- 预言家真实好人查验将目标狼人概率设为0，其余好人角色按剩余角色先验重新归一化。
- 公开 `RoleClaim` 只登记为“有人这样声称”，不直接改变身份概率。
- 两名及以上玩家肯定声称同一个唯一神职时，建立 `unique_role_counterclaim` 冲突，并保留本地 Evidence ID。
- 同一玩家先后肯定声明两个不同具体身份，或对同一身份先肯定后否认时，建立 `self_role_claim_conflict`。只检查玩家对自己的身份声明，不把他人转述算作自相矛盾。
- 同日实际放逐票与该玩家投票前最后一次无条件 `VoteIntentClaim` 不一致时，建立 `vote_behavior_conflict`。条件性意向和面向他人的投票建议不参与该判断。
- trust_score 当前固定为0；软发言、站边和票型尚不改变概率。

当前概率是可解释的边际启发式，不是满足全局角色组合约束的联合贝叶斯后验。后续每次软更新必须记录 Evidence ID 和更新因子，才能进入正式 BeliefState。

## 下一步

1. 已增加投票专用 `DecisionBrief`：确定性汇总候选人基线、身份声明、公开查验、冲突和当日最后投票意向，不生成投票推荐。
2. 第一阶段同时发送 DecisionBrief、原始发言和 EvidenceContext；完成真实局对照后再决定是否移除全量发言。
   首次真实局发现狼人利用“首夜没有前置信息”的错误规则叙述带偏好人，因此 Brief 额外提供三条确定性规则提醒，并在 Trace 中分别统计 Brief 证据引用与仅 Context 证据引用。
   Brief 同时收录当前日指向投票候选人的最新明确 stance：每个 `(speaker, target)` 只保留最后一条，全局最多24条；第三方转述和条件性态度不进入该结构。
3. 投票上下文提供三档可审计模式：`full` 保留原始发言及全部 EvidenceContext；`balanced` 保留原始发言但移除与 Brief 重复的公共 Claims；`compact` 同时移除原始发言。后两档只允许引用硬事实、规则推导和 Brief 已展示的 Evidence ID。
4. Strategy接入前的去重模型投影与层级边界见 `M2_4_STRATEGY_INPUT_DESIGN.md`。
3. 在现有可审计冲突之上设计权重；冲突目前只作为结构化信号，不会直接修改身份概率或可信度。
4. 最后才评估 LLM可信度评分，保留纯确定性基线用于 M3 消融。
