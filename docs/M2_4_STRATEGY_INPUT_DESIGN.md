# M2-4 Agent 输入与 Strategy 分层

## 目标

在加入 Strategy 前先固定模型输入职责，避免 PlayerView、任务观察、Evidence、Situation 和 Strategy 重复描述同一局势。完整 `PlayerView`、`PublicGameSummary` 和领域 Observation 继续留在 Python 信任边界内用于权限与一致性校验；模型只接收去重投影。

## 模型输入

1. `StaticRules`：稳定公开规则，位于 System Prompt；不包含任何玩家身份真相。
2. `player_context`：当前座位、规则集、天数、阶段、本人角色和私有角色状态、公开存活/死亡座位与警长。
3. `task_context`：当前发言或投票所需的合法任务字段，不重复 actor/voter、天数和角色。
4. `evidence_context`：玩家本地的事实、规则推导，以及 Full 模式下的公共 Claim 索引；不序列化 owner 和 revision 元数据。
5. `situation_brief`：当前内部仍由 `DecisionBrief` 实现，模型侧统一称 SituationBrief；只描述主观概率、身份/查验声明、冲突、最新投票意向和 stance，不给出投票建议。
6. 后续 `strategy_brief`：只包含 priorities、options 和 risk_flags，引用现有 Evidence ID，不复制玩家状态、发言、票型和 Situation 字段。

## 三档投票上下文

- `full`：保留原始发言、Evidence 公共 Claims 和 SituationBrief，作为信息完整基线。
- `balanced`：保留原始发言与 SituationBrief，隐藏重复的 Evidence 公共 Claims。
- `compact`：只保留 SituationBrief 与硬事实/规则推导，不发送原始发言和重复公共 Claims。

无论使用哪种模式，Engine、PlayerView、EvidenceLedger 和 Replay 均保留完整数据。Balanced/Compact 中未展示且未进入 SituationBrief 的 Claim ID 不可被模型引用。

## Strategy 边界

StrategyBuilder 可以读取 PlayerContext、EvidenceLedger、BeliefState、SituationBrief 和任务约束，但输出不得再次包含这些输入的镜像。合法的增量结构为：

```text
StrategyBrief
├── priorities：当前最重要的战略目标
├── options：可选打法、适用条件、收益、风险和目标座位
└── risk_flags：信息泄露、规则误推、身份暴露、分票和胜负边界风险
```

Strategy 不读取 GOD Replay，不替 Engine 判定规则，不把公开 Claim 当成事实，也不直接决定最终行动。LLM仍在一次结构化决策中选择策略与行动，Trace记录其引用的 Strategy ID 和 Evidence ID。

## 粗颗粒度 v1

当前实现采用最小静态角色手册加少量动态风险：一句角色目标、最多3项优先级、5种方法和3条警告。本地 `StrategyBuilder` 不调用模型；发言与投票结果通过 `strategy_ids` 声明实际采用的方法，Runtime剔除并记录伪造ID。更细策略树、对手模型、RAG、长期规划和学习型策略留作后续扩展。

## 狼队共享战术计划

单狼各自看到“可以悍跳、冲锋、倒钩或隐藏”仍可能全部选择低风险隐藏，形成局部最优。为提供最低限度的团队协调，狼队协调座位在每次 `wolf_target` 决策中同时生成私有 `WolfTeamPlan`：

- `objective`：隐藏、预言家对跳、压制预言家或混合路线；
- `primary_claimant` / `claimed_role`：唯一主跳狼及其伪装身份；
- `fake_check_target` / `fake_check_alignment`：悍跳预言家的完整假查验；
- `assignments`：每只存活狼的 `claimant/support/distance/hide` 姿态。

Runtime 校验计划天数、存活狼人集合、唯一主跳狼和假查验字段一致性。合法计划进入 `AgentGameProvider.wolf_team_plan_history`，并只注入狼人后续的 `StrategyBrief`；好人视图和 Strategy 均不包含该字段。完整局诊断保存每夜计划，标准 GOD Replay 仍只记录 Engine 信息。模型调用失败时使用“全员隐藏、无人悍跳”的确定性合法计划，不中断对局。
