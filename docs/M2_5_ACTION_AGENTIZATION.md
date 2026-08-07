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

将猎人开枪、警徽移交、放逐遗言、首夜死亡遗言、PK发言和警长发言方向逐项交给 Agent，然后运行完整多日终局并生成 GOD Replay。
