# WolfScope

WolfScope 是一个基于 AgentScope 的九人狼人杀多智能体博弈与评测项目。项目采用“确定性 Python 裁判 + 角色隔离的 Agent 决策”架构：游戏规则、真实身份、信息可见性和胜负判断由 Engine 掌握，LLM 只能根据自己的玩家视角提交结构化行动。

M1 确定性游戏内核已经完成。无需调用 LLM，即可用固定 seed 和严格剧本运行完整九人局并生成上帝视角 JSON Replay。项目现已进入 M2；九玩家隔离、Evidence、SituationBrief、粗粒度角色 Strategy、公开发言/放逐投票和警长竞选 Agent 决策链均已接入。

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

当前包含 192 项自动化测试，覆盖确定性规则内核、AgentScope 决策、警长竞选 Agent、夜间角色 Agent、死亡技能/遗言 Agent、完整多日 Agent 终局和 Replay 往返，以及 EvidenceLedger、规则推导、公共 Claim、失败回归样本、Evidence/Strategy 引用审计、分阶段发言长度控制、ID 隔离、失败降级和自动评测聚合。

## 运行 M3 自动评测

真实评测会调用 DeepSeek API。配置 `.env.local` 后，可对固定 seeds 串行运行完整 Agent 对局：

```bash
set -a
source .env.local
set +a
wolfscope-eval --seeds 1,2,3 --output-dir artifacts/evaluation/flash-baseline-v1
```

每局结束都会增量保存，意外中断后可使用同一配置恢复：

```bash
wolfscope-eval --seeds 1,2,3 \
  --output-dir artifacts/evaluation/flash-baseline-v1 \
  --resume
```

评测目录包含逐局 GOD Replay、完整调用诊断、失败记录、机器可读的 `summary.json` 和作品集可直接引用的中文 `report.md`。无需调用 API 即可重新聚合：

```bash
wolfscope-eval --aggregate-only \
  --output-dir artifacts/evaluation/flash-baseline-v1
```

## 项目文档

- [项目立项书](PROJECT_PROPOSAL.md)
- [规则对比与最终规则](docs/RULES_COMPARISON.md)
- [M1 验收结果](docs/M1_ACCEPTANCE.md)
- [旧版迁移计划](docs/MIGRATION_PLAN.md)
- [第一版缺陷回归矩阵](docs/V1_REGRESSION_MATRIX.md)
- [M2-1 认知玩家接入设计](docs/M2_1_DESIGN.md)
- [M2-2 EvidenceLedger 设计](docs/M2_2_EVIDENCE_DESIGN.md)
- [M2-5 行动 Agent 化](docs/M2_5_ACTION_AGENTIZATION.md)
- [M2-6 完整 Agent 终局验收](docs/M2_6_FULL_GAME_ACCEPTANCE.md)
- [M2-7 发言长度策略](docs/M2_7_SPEECH_POLICY.md)
- [M2-8 决策复杂度与智能降级](docs/M2_8_COMPLEXITY_POLICY.md)
- [M3-1 自动对局评测](docs/M3_1_GAME_EVALUATION.md)
- [架构决策记录](docs/decisions/)

## 当前阶段

M1 已完成，M2 已跑通完整 Agent 对局。正式 `AgentGameProvider` 不依赖 Support，公开发言/投票、警长、夜间角色、PK/遗言、猎人枪权、发言方向和警徽处理均由座位隔离 Runtime 决策。seed 42 的真实 Flash 对局在第2天由狼人屠神结束：54次玩家决策、18次语义提取、44个 GOD 事件，标准 Replay 已通过写入/读取校验。`ScriptedProvider` 只保留为确定性回归工具；正式实验中的九名玩家统一使用 DeepSeek Flash，不做动态模型路由。
