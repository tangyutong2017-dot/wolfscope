# M2-1 认知玩家接入设计

## 目标

M2-1 先验证一条最小但真实的认知决策链：Engine 产生玩家可见信息，`PlayerViewBuilder` 构造隔离视图，座位专属 `PlayerRuntime` 请求结构化决策，Engine 最终校验并执行行动。

首个切片接入白天发言和放逐投票；后续已将警长上警、竞选发言、同时退水和警下投票纳入同一座位隔离 Runtime。夜间技能和死亡处理继续逐项替换。

## 模型策略

| 场景 | 模型路径 | 是否真实请求 |
|---|---|---|
| 自动化测试 | `FakeModelGateway`，记录为 Flash 配置 | 否 |
| M2-1 接口冒烟 | `deepseek-v4-flash` | 是 |
| 正式对局与 M3 实验 | `deepseek-v4-pro` | 是 |

同一局九名玩家使用同一个模型配置，不依据角色、阶段或任务动态路由。这样既保证正式对局能力一致，也避免模型差异干扰 M3 的基线、消融和策略评测。

配置对象不保存 API 密钥。密钥只在真实 Gateway 初始化时从环境变量读取，且不得写入 Replay 或调用记录。

## 接口边界

```text
GameEngine
  -> PlayerViewBuilder（唯一信息授权边界）
  -> AgentDecisionInput（PlayerView + 派生公开摘要 + 当前任务）
  -> PlayerRuntime[seat]（座位隔离与视图版本检查）
  -> ModelGateway（Fake / 后续 AgentScope 实现）
  -> SpeechDecision | VoteDecision
  -> Engine 合法性校验与执行
```

`PublicGameSummary` 只能从 `PlayerView` 派生，不能再次读取上帝 `GameState`。`AgentDecisionInput` 会校验任务行动者与视图持有者一致；`PlayerRuntime` 会再次校验座位归属，并拒绝比已处理版本更旧的玩家视图。

## 九玩家隔离

每个座位拥有独立的 `PlayerRuntime`、Gateway 实例、视图版本和调用记录。未来接入 AgentScope 后，Agent、memory、tool context 和短期认知状态也必须归属于单个座位，不允许九名玩家共享可读写记忆。

EventLog 与 `PlayerViewBuilder` 继续充当信息流权威。本阶段不引入 MessageHub，以免出现框架消息历史与规则事件日志两套真相来源。

## 结构化决策

发言结果包括行动类型、公开发言、简短意图、置信度以及证据/策略引用。狼人只有在观察中明确允许时才可能提交自爆，最终合法性仍由 Engine 判断。

投票结果包括目标、公开理由、置信度以及证据/策略引用。Schema 负责格式约束；候选集合、存活状态、是否允许弃票等规则约束由 Engine 执行，避免把裁判职责交给 LLM。

系统只保存简洁决策依据、引用 ID 和结构化结果，不保存模型隐藏思维链。

## 调用追踪

每次调用至少记录座位、任务、模型名称、是否启用思考、成功状态、延迟、重试次数、输入/输出 token 和错误类型。M2-1 的 Fake Gateway 已覆盖成功与 Schema 校验失败；真实 Gateway 的超时、重试和安全降级将在接入 AgentScope 时补齐。

## M2-1 验收边界

- 九个 Runtime 相互隔离。
- 不能把其他座位的 `PlayerView` 交给当前 Runtime。
- 上帝事件不能通过输入摘要泄漏。
- 发言和投票输出必须通过严格 Schema。
- 成功与失败调用均可审计。
- 默认测试不联网、不消耗 token。
- Flash 冒烟测试通过后，再把两个决策接入混合 Provider 跑完整九人局。

## 当前实现状态

离线部分已经完成：AgentScope DeepSeek 模型适配器会把授权快照转换成一条 system message 和一条 user message，调用框架的 structured output 接口，失败时最多进行一次格式修复。若调用方显式开启安全降级，发言会变为可审计的中性发言，投票会变为弃票；调用记录保留原失败状态并标记 `fallback_used=true`。

2026-08-07 已完成 `deepseek-v4-flash` 单玩家冒烟：发言结构化结果首次通过，耗时 4428 ms，输入 1335 token、输出 333 token；投票在 `(1, 7)` 对跳预言家候选中选择合法目标 7 号，首次通过，耗时 9909 ms，输入 1690 token、输出 759 token。两次调用均未触发格式修复或 fallback。

投票冒烟同时显示：在正式 Evidence 账本尚未实现时，模型会自行生成 `event_id:1` 一类引用格式。混合 Provider 接入前需要明确区分玩家本地事件引用与 M2-2 Evidence ID，避免把未验证的自由字符串当作有效证据。

该问题现已通过协议收紧解决：M2-1 决策只接受整数 `event_ids`，Runtime 会根据当前 `PlayerView.visible_events` 删除并记录越权或不存在的引用。`evidence_ids` 与 `strategy_ids` 暂不出现在模型输出中，分别等待 M2-2 Evidence 账本和后续策略库提供真实 ID 后再加入。

## 过渡 Provider

`ScriptedProvider` 继续专用于 M1 精确回归，不再作为 LLM 正式路径的依赖。M2 过渡期由 `HybridProvider` 将普通发言和放逐投票交给座位独立 Runtime，其余接口交给不包含狼人杀策略的 `DeterministicSupportProvider`。Support 只返回简单合法选择，随着 Agent 行动覆盖增加而逐项退出。

## 警长阶段 Agent 化

`HybridProvider` 已将 `sheriff_signup`、`sheriff_campaign`、`sheriff_withdrawal` 和 `sheriff_vote` 路由给各自座位的 Runtime。模型只收到当前 `PlayerView`、合法候选范围、当时已公开的竞选发言、Evidence 与粗粒度 Strategy；Engine 仍独占同时收集语义、随机发言起点、候选资格、计票和流警裁决。模型失败分别降级为不上警、最小竞选发言、维持候选资格和弃票。

2026-08-07 的 Flash 定向验证共25次决策：9次上警、8次竞选发言、8次退水。23次成功；8号和9号竞选发言遇到请求异常后使用安全降级，不影响流程。8名候选人中7名同时退水，7号成为唯一候选人并合法当选。Trace 记录67次有效 Strategy 引用和1次被过滤的截断 Strategy ID。完整本地结果保存在忽略 Git 的 `replays/live/`，避免大 Trace 污染仓库。

Fake Gateway 已完成一局 `max_days=1` 的完整集成验证：第一夜、无人竞选警长、首夜死亡公布、八名存活玩家发言、同时投票、放逐与猎人死亡链均由真实 Engine 推进。测试同时确认 Support 没有接管发言或投票，且任何玩家的投票输入都不包含其他玩家尚未公布的票。

## 真实单日混合局

2026-08-07 使用 `deepseek-v4-flash` 完成首局真实 `max_days=1` 混合对局。固定身份中1、2、3号为狼人，7号为预言家；4号首夜死亡。八名存活玩家各完成一次发言和一次同时投票，共16次模型决策。最终1号以5票被放逐，7号获得3票，对局按运行保护正常结束。

- 15/16 次结构化决策成功。
- 1次发言在一次格式修复后仍失败，成功使用中性发言 fallback。
- 总输入 52686 token，总输出 8961 token。
- 累计模型延迟 155938 ms。
- 没有非法投票、越权事件引用或 Engine 中断。

该局证明了九座位隔离 Runtime、动态 PlayerView、真实 AgentScope 调用、同时投票和 Engine 死亡链能够共同工作，也暴露了两个后续问题：完整快照与任务观察存在重复信息，导致投票输入增长到约四千 token；狼人阵营虽然形成了协同话术，却反复使用“白天起跳的预言家为何没有在前一夜被刀”这一时间因果错误。前者需要上下文压缩，后者将作为 M2-2 证据账本、时间线和认知检查的明确回归案例。

针对5号发言的结构化失败，调用追踪现已补充逐次尝试记录。每次尝试区分 `generation` 与 `schema_repair` 阶段，记录成功状态、延迟、可获得的 token 和脱敏失败分类，例如 `missing_structured_output`、`schema_validation`、`empty_response` 或 `request_exception`。系统仍不保存失败原文或隐藏思维链，格式修复上限仍为一次。
