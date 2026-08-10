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

## 局面感知策略 v2

当前实现保留小型策略输入，但从固定角色手册升级为确定性局面选择：一句角色目标、两项优先级、最多3种方法、3条警告和一组紧凑 `situation_tags`。标签只表达玩家视角内可验证的结构，例如单/多预言家声明、本人收到公开查杀、身份或票型冲突、轮次与残局压力；狼人额外拥有队友受压和主跳队友等私有标签。好人 Strategy 会拒绝狼队私有标签。

每次只选择“一条角色或狼队姿态方法 + 一条最高优先级局面方法 + 事实/声明分离”，不会叠加全部匹配策略，也不会规定发言结构。本地 `StrategySituationBuilder` 和 `StrategyBuilder` 均不调用模型；所有决策通过 `strategy_ids` 声明实际采用的方法，Runtime剔除并记录伪造 ID。更细策略树、对手模型、RAG、长期规划和学习型策略留作后续扩展。

神职只在关键任务替换一条基础方法：预言家第一天有资格时必须报名上警，验高信息量未知位、竞选时交代真实查验与警徽流、遗言留下完整查验；女巫比较救毒留药的轮次价值，无压力竞选和常规发言默认隐藏底牌；猎人依据查验、冲突和票型决定枪权，早期目标完全不可区分时允许不开枪，但残局或遗言已有明确最高怀疑时优先开枪，且遗言与随后独立枪权任务严格分离。白天投票不能只以“信息不足”为由弃票，听完发言后应比较相对怀疑形成明确票向。这些方法不规定发言模板，也不增加每次 StrategyBrief 的条目上限。

第一天只有一名预言家声明者且不存在身份对跳或直接自相矛盾时，公共认知将其标记为高可信工作假设：信任分为 `0.75`，好人角色优先沿其公开查验分析，猎人不得仅以“身份未认证”为由将其作为枪击目标。该状态不改变角色概率、不构成 Engine 身份确认，并在第一天结束后自动失效，后续必须结合新增查验、票型与警徽流重新评估。

警长报名意愿由与身份无关的seed参数控制：每局固定2个 `high`、3个 `medium` 和4个 `low` 座位。预言家及狼队主跳者覆盖该参数必须报名；其余玩家按意愿决定，避免按身份机械禁止上警。

规则必然推导会进入策略警告：`standard-9-v1` 中狼人每夜必须选择刀口，不存在空刀，因此当日平安夜必然表示女巫使用解药。该结论已同时存在于玩家Evidence和Strategy，模型不得继续表达“也可能空刀”。

## 狼队共享战术计划

单狼各自看到“可以悍跳、冲锋、倒钩或隐藏”仍可能全部选择低风险隐藏，形成局部最优。为提供最低限度的团队协调，狼队协调座位在每次 `wolf_target` 决策中同时生成私有 `WolfTeamPlan`：

- `objective`：隐藏、预言家对跳、压制预言家或混合路线；
- `primary_claimant` / `claimed_role`：唯一主跳狼及其伪装身份；
- `fake_check_target` / `fake_check_alignment`：悍跳预言家的完整假查验；
- `focus_target` / `plan_reason`：本轮共同施压目标和不超过一句的计划依据；除纯隐藏计划外，共同目标不得为空；
- `assignments`：每只存活狼的 `claimant/support/distance/hide` 姿态。

Runtime 校验计划天数、存活狼人集合、共同目标合法性、唯一主跳狼和假查验字段一致性。每夜由协调狼随刀口决策重新生成当日计划；合法计划进入 `AgentGameProvider.wolf_team_plan_history`，并只注入狼人后续的 `StrategyBrief`。每只狼根据自己的 assignment 获得不同的执行方法，好人视图和 Strategy 均不包含计划或私有标签。完整局诊断保存每夜计划，标准 GOD Replay 仍只记录 Engine 信息。模型调用失败时使用“全员隐藏、无人悍跳”的确定性合法计划，不中断对局。
