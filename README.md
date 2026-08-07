# WolfScope

WolfScope 是一个基于 AgentScope 的九人狼人杀多智能体博弈与评测项目。项目采用“确定性 Python 裁判 + 角色隔离的 Agent 决策”架构：游戏规则、真实身份、信息可见性和胜负判断由 Engine 掌握，LLM 只能根据自己的玩家视角提交结构化行动。

当前完成的是 M1 确定性游戏内核。无需调用 LLM，即可用固定 seed 和严格剧本运行完整九人局并生成上帝视角 JSON Replay。AgentScope 认知玩家、证据账本、概率推理和策略工具将在 M2 接入。

## 当前功能

- 标准九人屠边局：3 狼人、3 平民、预言家、女巫、猎人
- 首夜技能结算后先竞选警长，再公布首夜死亡
- 狼人自刀、预言家查验、女巫救毒限制
- 警长竞选、退水、1.5 票权、发言方向和警徽移交
- 白天发言、基础自爆、同时投票、平票 PK 和一次重投
- 猎人死亡链、被毒禁枪和枪杀目标无遗言
- 屠狼、屠神、屠民胜负判断；同批次同时达成时好人优先
- PUBLIC、WOLVES、PRIVATE、GOD 四级事件可见性
- 类型化 ScriptedProvider 和未消费行动审计
- seed 固定发牌、发言顺序和确定性 Replay

## 架构

```text
GameEngine（唯一推进阶段和天数）
├── NightEngine
├── SheriffElectionEngine
├── DawnAnnouncementEngine
├── DayEngine
└── DeathResolutionEngine

GameEngine → EventLog → GOD-view replay.json
                  └── GameMessageRouter → 玩家授权事件
```

顶层 `GameEngine` 只编排阶段；各阶段 Engine 负责规则校验和状态变更。Provider 只能接收角色限定的 Observation，不能读取上帝 `GameState`。

## 环境安装

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

项目当前固定使用 AgentScope 2.0.5。

## 运行 M1 验收对局

安装项目后，无需设置 `PYTHONPATH`：

```bash
wolfscope-m1 all --output-dir replays --overwrite
```

也可以只运行一局：

```bash
wolfscope-m1 good-win-seed-42 --output-dir replays --overwrite
```

内置四个确定性剧本：

| 剧本 | 预期结果 |
|---|---|
| `good-win-seed-42` | 好人消灭全部狼人 |
| `wolves-eliminate-deities-seed-42` | 狼人屠神 |
| `wolves-eliminate-civilians-seed-42` | 狼人屠民 |
| `hunter-tie-break-seed-42` | 猎人开枪后双方同时达成条件，好人优先 |

每局生成一个 `replays/<game-id>.json`。Replay 包含全员身份、最终结果、最终存活座位，以及 Engine 产生的完整 PUBLIC、WOLVES、PRIVATE 和 GOD 事件流。

## 运行测试

```bash
python -m unittest discover -s tests
```

M1 当前包含 79 项自动化测试，覆盖状态模型、夜晚、警长、白天、死亡链、胜负、PlayerView 信息隔离、完整循环、第一版缺陷回归、ScriptedProvider 和 Replay 确定性。

## 项目文档

- [项目立项书](PROJECT_PROPOSAL.md)
- [规则对比与最终规则](docs/RULES_COMPARISON.md)
- [M1 验收结果](docs/M1_ACCEPTANCE.md)
- [旧版迁移计划](docs/MIGRATION_PLAN.md)
- [第一版缺陷回归矩阵](docs/V1_REGRESSION_MATRIX.md)
- [架构决策记录](docs/decisions/)

## 当前阶段

M1 的规则内核、完整 `PlayerView` 构建器和对局 Replay 已经跑通。提交首个 Git 里程碑前，还将把第一版项目中的关键失败模式整理为明确的回归测试。随后进入 M2：AgentScope 玩家、证据账本、信念概率、策略库和决策工具。
