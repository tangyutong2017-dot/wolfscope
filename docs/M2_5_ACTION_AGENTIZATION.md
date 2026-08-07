# M2-5 行动 Agent 化

## 边界

本阶段逐项从 `DeterministicSupportProvider` 移交行动所有权，但不把规则裁决交给模型。`HybridProvider` 只把 Engine 已生成的角色授权 Observation 转为座位隔离的 `AgentDecisionInput`；Runtime 校验事件、Evidence、Strategy 和合法目标，Engine 再执行最终领域校验与原子结算。

## 已完成：警长阶段

- `sheriff_signup`：九名玩家同时决定是否上警。
- `sheriff_campaign`：候选人按 seed 固定顺序发言，后置位只看到已经公开的发言。
- `sheriff_withdrawal`：所有候选人在相同完整竞选信息上同时退水。
- `sheriff_vote`：只有原始警下玩家可以在剩余候选人中投票或弃票。

Engine 继续负责候选资格、同时语义、发言顺序、计票、平票流警和唯一候选人当选。Flash 定向验证25次调用中23次成功，两次请求异常使用最小竞选发言安全降级，流程合法结束。

## 已完成：夜间角色决策

- `wolf_target`：当前存活狼队中最小座位作为协调座位，代表狼队提交唯一刀口；任务明确允许战术性自刀。未来可将该单点协议替换为 MessageHub 狼队协商而不修改 Engine。
- `seer_target`：预言家只能从 Engine 给出的未重复合法目标中选择。
- `witch_action`：女巫在狼人目标确定后收到本夜刀口、药物状态、能否自救和合法毒药目标，返回 `pass/save/poison`。

每种模型失败都有确定性合法降级：狼队选择首个非狼合法目标、预言家选择首个合法目标、女巫保留药物过夜。模型提交越界目标时 Runtime 记录 `illegal_target` 并执行同一降级，避免错误进入 Engine 中断对局。

2026-08-07 Flash 定向验证3次调用全部成功：狼队刀4号，预言家查验3号，女巫看到4号刀口后使用解药，Engine 结算为空死亡名单。共4959输入 token、1357输出 token、约14.6秒累计延迟，6次有效 Strategy 引用且无非法引用。

## 下一步

## 已完成：死亡技能和遗言

- 警长通过 `speech_direction` 选择白天发言方向。
- 平票玩家通过 `pk_speech` 完成顺序PK发言。
- 被放逐玩家通过 `last_words` 在死亡状态变更前发表遗言。
- 首夜死亡玩家通过显式 `build_terminal_action` 视图完成 `death_last_words`；普通 `PlayerViewBuilder.build` 仍拒绝死者，终局入口只由 Engine 控制的死亡链调用。
- 可开枪猎人通过 `hunter_target` 选择合法存活目标或不开枪；死亡原因仍由 Engine 判断，毒杀猎人不会收到枪权任务。
- 死亡警长通过 `badge_transfer` 选择合法存活目标或撕毁警徽。

猎人任务会收到本人刚发表的遗言，警徽任务会收到本次猎人目标，作为连续行动的最小上下文。自然语言与下一次随机模型决策不强制语义一致，但每次正式结构化动作均独立校验、记录并由 Engine 执行。

Flash 边界验证模拟“首夜中刀猎人同时当选警长”，按死亡遗言、猎人枪权、警徽处理顺序完成3次决策。最终验证中枪权和警徽调用成功，遗言请求异常后使用可审计最小遗言降级；流程未中断、猎人不开枪、警徽被撕毁。

## 下一步

运行完整多日 Agent 终局，生成 GOD Replay，并验证终局、调用追踪和失败降级在长期循环中保持一致。
