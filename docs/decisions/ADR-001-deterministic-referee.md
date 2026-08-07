# ADR-001：使用确定性裁判主持游戏

- 状态：Accepted
- 日期：2026-08-06

## 背景

狼人杀包含严格的阶段顺序、私有信息、技能限制、死亡结算和胜负条件。LLM 输出具有随机性，也可能产生格式错误和违规行动。

## 决策

由纯 Python `GameEngine` 维护真实状态并裁决规则。顶层 `GameEngine` 是阶段顺序和天数推进的唯一所有者，并组合 `NightEngine`、`SheriffElectionEngine`、`DawnAnnouncementEngine`、`DayEngine` 和 `DeathResolutionEngine`；阶段引擎不自行推进整局循环。玩家 Agent 只能通过角色限定的 Observation 返回结构化决策，由引擎验证后执行。AgentScope 不持有或修改上帝状态。

## 后果

- 规则可以在无模型环境下测试和复现。
- 非法行动不会破坏游戏状态。
- Agent 表现变化可以与规则实现变化分开分析。
- 需要维护明确的 Agent—Engine 契约。
