# WolfScope

WolfScope 是一个基于 AgentScope 的九人狼人杀多智能体博弈与评测项目。它关注的不是“让九个模型轮流聊天”，而是三个更难的问题：如何严格隔离每名玩家的信息、如何把长对话转化成可审计证据、如何让不稳定的模型输出安全地驱动确定性规则引擎。

项目采用“确定性 Python 裁判 + 九个座位隔离 Agent”架构。身份、夜间结算、可见性和胜负判断由 Engine 独占；LLM 只能读取自己的 `PlayerView`，并通过严格 Schema 提交一次结构化行动。固定 seed 可复现实验，完整 GOD 事件流写入 JSON Replay。

## 项目亮点

- **信息隔离**：PUBLIC、WOLVES、PRIVATE、GOD 四级事件路由，Agent 无法读取上帝 `GameState`。
- **认知流水线**：公开发言只提取一次并缓存为 Claim；每个座位独立维护 Evidence、Belief、DecisionBrief 与 StrategyBrief。
- **认识论边界**：公开身份和查验始终是 `claimed`，不会被错误升级为 Engine 认证事实；对跳双方的查验归属严格分离。
- **规则与策略解耦**：Engine 负责合法性，策略层只提供粗粒度方法；预言家警徽流、狼队悍跳时间线等关键行为另有本地硬约束。
- **可审计降级**：结构化输出失败依次经过格式修复、复杂度降级和确定性兜底，所有失败原因与 Token/延迟写入 Trace。
- **自动评测**：批量固定 seed 运行真实完整局，统计胜负、弃票、放逐阵营、神职技能、警徽流、Schema 成功率和复杂度降级。

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
                  └── GameMessageRouter → PlayerView
                                             ↓
公开发言 → ClaimExtractor → EvidenceLedger（每座位隔离）
                              ↓
              Belief / DecisionBrief / StrategyBrief
                              ↓
                    AgentScope structured output
                              ↓
                 Runtime 校验 → Engine 执行
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

## AgentScope 用在什么地方

AgentScope 位于模型适配层，而不是规则内核：

- `PlayerRuntimeRegistry` 为1–9号座位创建隔离 Runtime，避免共享私有上下文。
- `AgentScopeModelGateway` 调用模型并请求 Pydantic 结构化输出。
- 同一个 Gateway 同时服务玩家决策与公共 Claim 提取，但两者拥有独立 Schema、Trace 和失败诊断。
- Thinking/non-thinking、Token预算、请求超时和复杂度降级由任务类型控制。
- `ScriptedProvider` 不会被正式对局动态调用，仅保留为无需API的确定性规则回归工具。

Engine、PlayerView、Evidence 和 Replay 均不依赖 AgentScope 类型，因此规则测试不需要模型或网络。

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

当前包含204项自动化测试，覆盖确定性规则内核、AgentScope决策、警长竞选、夜间角色、死亡技能、完整多日终局和Replay往返，以及EvidenceLedger、公共Claim、警徽流、查验归属、悍跳时间线、ID隔离、失败降级和自动评测聚合。

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

## 结项评测

最终固定 seed 评测使用 DeepSeek V4 Flash、`balanced` 投票上下文和最多8天限制：

| 指标 | 结果 |
|---|---:|
| 完成对局 | 8 / 8 |
| 玩家决策 | 522 |
| 最终结构化成功率 | 97.3% |
| L3确定性兜底率 | 2.7% |
| 放逐投票弃票率 | 1.5% |
| 好人 / 狼人胜利 | 1 / 7 |
| 放逐狼人 / 好人 | 8 / 11 |
| 猎人开枪 | 6 / 7次机会 |
| 预言家警徽传给本人查杀 | 0 |

- [结项评测报告](artifacts/evaluation/portfolio-final-v1/report.md)
- [代表性好人胜利 Replay（seed 15）](artifacts/evaluation/portfolio-final-v1/replays/seed-15.json)

8局样本用于工程稳定性验收，不足以估计真实阵营胜率。当前结果仍呈明显狼人优势，说明“共享信息较少的好人如何形成稳健共识”尚未完全解决；这是项目明确保留的后续研究方向，而不是被隐藏的展示数据。

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

## 项目边界与后续方向

当前版本已完成 M1 确定性规则内核、M2 完整 Agent 对局与 M3 自动评测，可作为作品集版本结项。正式 `AgentGameProvider` 不依赖 Support，九名玩家统一使用同一模型档位，不做按身份模型路由。

后续方向刻意不纳入本次结项范围：扩大评测样本、校准好人工作共识、建立失败样本驱动的 Claim 标注集、加入更精细的对手模型，以及扩展更多角色和板子。项目不开发Web对局前端，展示以README、评测报告和Replay为主。
