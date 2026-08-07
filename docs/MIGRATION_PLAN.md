# 第一版狼人杀迁移计划

## 目标

迁移经过验证的规则知识和失败案例，不复制第一版的 LLM 封装、Prompt 记忆方式或完整工程结构。

## 迁移原则

1. 先迁测试和规则规格，再迁实现。
2. 新领域层不得导入 AgentScope。
3. 新 Agent 只接收 `PlayerView`，不能读取旧版完整状态。
4. 每个旧 Replay 缺陷都转成回归测试或 M3 指标。
5. 不在迁移阶段扩展新角色和新板子。

## 文件级清单

| 第一版来源 | 处理方式 | 新位置 | 说明 |
|---|---|---|---|
| `werewolf/game/roles.py` | 重写并对照 | `src/wolfscope/game/roles.py` | 保留九人角色和阵营规则 |
| `werewolf/game/state.py` | 重写 | `src/wolfscope/game/state.py` | 使用严格 Schema 和单一真相来源 |
| `werewolf/game/events.py` | 概念迁移 | `contracts.py`、`message_router.py` | 先固定事件契约和可见性 |
| `werewolf/game/engine.py` | 分阶段迁移 | `src/wolfscope/game/engine.py` | 拆分状态机、结算和校验 |
| `werewolf/agents/base.py` | 不迁移 | `src/wolfscope/agents/` | 改为 AgentScope 2.x 适配器 |
| `werewolf/agents/prompts.py` | 提取知识后重写 | `src/wolfscope/strategies/` | Prompt 策略拆成可检索条目 |
| `werewolf/agents/protocol.py` | 重写 | `contracts.Decision` | 使用 Pydantic 和结构化输出 |
| `werewolf/llm/client.py` | 不迁移 | AgentScope model adapter | 不再维护通用模型客户端 |
| `replays/*.json` | 保留为研究材料 | `replays/legacy/` | 不保证直接兼容新 Schema |

## 必须迁移的规则回归场景

- 狼人必刀且允许自刀
- 女巫不能自救，同夜不能同时救毒
- 解药使用后的夜间信息权限
- 猎人被毒不能开枪
- 猎人被刀或放逐后的开枪链
- 警长 1.5 票
- 警徽移交和撕毁
- 平票重投和无人有效投票
- 屠神、屠民、屠狼胜负
- 胜负判定幂等

## 必须保留的失败案例

- 狼人在公开发言中泄露夜间刀口
- 7 号被救后仍被错误判断为可能自救女巫
- 过多玩家上警导致无警下投票者
- LangGraph 子图与 reducer 导致事件重复
- 相同 seed 只能固定发牌，不能固定 LLM 决策

## M1 迁移完成标准

- Scripted Provider 能跑完一局。
- 规则回归场景全部通过。
- 普通玩家无法读取狼队、角色私信或上帝事件。
- 新引擎不导入 `agentscope`。
- Replay 可通过新 Schema 验证。

详细覆盖关系见 [`V1_REGRESSION_MATRIX.md`](V1_REGRESSION_MATRIX.md)。纯认知类失败明确进入 M2，不与确定性裁判测试混淆。
