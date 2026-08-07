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
- trust_score 当前固定为0；软发言、站边和票型尚不改变概率。

当前概率是可解释的边际启发式，不是满足全局角色组合约束的联合贝叶斯后验。后续每次软更新必须记录 Evidence ID 和更新因子，才能进入正式 BeliefState。

## 下一步

1. 从 BeliefState 生成短 `DecisionBrief`，包含狼人嫌疑排序、角色声明、对跳冲突和关键证据。
2. 让投票 Prompt 使用 DecisionBrief，减少重复发送全量发言。
3. 增加可审计的票型/发言一致性因子，再讨论公开查验如何依据预言家可信度传播。
4. 最后才评估 LLM可信度评分，保留纯确定性基线用于 M3 消融。
