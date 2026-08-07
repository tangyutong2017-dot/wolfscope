# M2-1 认知玩家接入设计

## 目标

M2-1 先验证一条最小但真实的认知决策链：Engine 产生玩家可见信息，`PlayerViewBuilder` 构造隔离视图，座位专属 `PlayerRuntime` 请求结构化决策，Engine 最终校验并执行行动。

本阶段只接入两类公开决策：白天发言和放逐投票。夜间技能、警长竞选、自爆之外的死亡处理仍由现有 `ScriptedProvider` 驱动，等接口稳定后再逐项替换。

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

2026-08-07 已完成一次 `deepseek-v4-flash` 单玩家发言冒烟：结构化结果首次通过，未触发格式修复或 fallback；耗时 4428 ms，输入 1335 token、输出 333 token。尚未执行投票冒烟，也尚未把发言和投票 Gateway 接入完整游戏 Provider。
