# WolfScope 项目立项书（讨论稿）

> 状态：Draft v0.2
> 日期：2026-08-06
> 当前阶段：M0 立项与技术验证
> 文档约定：标记为「已决定」的内容作为当前基线；标记为「待讨论」的内容在开发前共同确认。

## 1. 项目名称

- 英文名：**WolfScope**（已决定）
- 副标题：**An AgentScope-powered Multi-Agent Werewolf Arena**
- 中文描述：基于 AgentScope 的九人狼人杀多智能体博弈与评测系统

## 2. 项目背景

第一版狼人杀项目已经完成九人局的确定性规则引擎、事件日志、玩家私有视图、LLM 玩家、JSON 复盘，以及手写编排与 LangGraph 编排的对照实现。

第一版证明了基本架构可行，同时暴露了更值得研究的问题：

1. LLM 需要反复从长篇自然语言历史中恢复事实，容易遗漏关键信息。
2. 玩家缺少显式的证据、立场和身份概率表示，所谓“记忆”主要是原始对话。
3. 狼人杀策略集中写在 Prompt 中，难以按身份、阶段和局面精确调用。
4. 规则判断、概率计算、票型分析等任务也交给 LLM，结果不稳定且不可验证。
5. 发言生成与决策推理耦合，可能出现信息泄漏、身份矛盾和行动—发言不一致。
6. 单局案例可以说明现象，但缺少批量实验来量化 Agent 设计的实际效果。

因此，新项目不是对第一版的简单重写，也不是把模型调用替换为 AgentScope API，而是重新设计玩家 Agent 的认知结构，并通过可重复实验验证其价值。

## 3. 项目定位

### 3.1 一句话定义

> 一个基于 AgentScope 的九人狼人杀多智能体博弈系统，通过确定性裁判、严格私有信息边界、结构化信念、策略检索、概率工具和决策反思，使 LLM Agent 能进行更可靠的推理、欺骗、协作与投票，并用批量实验衡量这些机制的效果。

### 3.2 核心研究问题

> 与“完整历史 + 单次 Prompt”的基础 Agent 相比，结构化信念、策略检索、概率工具和反思机制能否显著提升 LLM Agent 在不完全信息博弈中的决策质量、逻辑一致性和信息纪律？

### 3.3 作品集价值

本项目主要展示以下能力：

- AgentScope Agent、Message/Event、Toolkit、Context 和 Middleware 的实际应用
- 多智能体中心化编排与对抗性信息隔离
- 确定性状态机和不可靠 LLM 输出之间的边界设计
- 事件溯源、可复盘性和结构化观测
- Agent 认知架构：感知、记忆、信念、策略、规划、反思
- 概率和图分析工具对 LLM 的增强
- 基线、消融实验和批量评测
- 面向 GitHub 作品集的工程文档与实验表达

## 4. 已决定的项目边界

### 4.1 游戏范围

- 九人标准局：3 狼人、1 预言家、1 女巫、1 猎人、3 平民
- 屠边规则
- 纯 AI 自动对局，人类作为观察者
- 包含警长竞选、警徽、夜间行动、白天发言、投票、平票处理和猎人开枪
- 第一夜先结算但不公布死亡，警长竞选完成后再公布首夜死讯
- 只实现基础狼人自爆，不实现双爆吞警徽和自爆指刀
- 预言家不能验自己或重复查验；查验结果直接进入其个人视图和证据账本
- 保留 Scripted Provider，用于确定性测试和两套编排的等价验证

### 4.2 展示方式

本项目**不开发 Web 前端**。最终作品集由以下内容组成：

1. 高质量中文 README
2. 系统架构图和玩家认知流程图
3. 精选 Replay 的终端或渲染截图
4. 一至三局典型案例分析
5. M3 批量实验结果、图表和结论
6. 可直接运行的命令行演示
7. 完整 Replay JSON 样例

### 4.3 暂不实现

- GitHub Pages 交互式前端
- 6–12 人通用板子
- 白痴、守卫、骑士等额外角色
- 人类实时加入游戏
- 账号、权限和在线房间系统
- AgentScope Agent Service 的完整多租户部署
- 强化学习或模型微调
- 自动修改 Prompt
- 原始思维链展示或保存
- 第一阶段即引入向量数据库和跨局长期记忆

## 5. 总体设计原则

### 5.1 确定性裁判，概率性玩家

游戏规则、阶段推进、行动合法性、死亡结算和胜负判断必须由普通 Python 代码实现。LLM 只能提出行动，不能修改规则和状态。

### 5.2 AgentScope 负责 Agent 运行时，不负责主持规则

AgentScope 用于承载玩家 Agent、模型、上下文、工具、消息、流式事件和 Middleware。游戏引擎仍是顶层 orchestrator。

不使用 AgentScope Agent Team 的 leader-worker 模式直接主持游戏，因为狼人杀是对抗性、不完全信息、严格回合制系统，不是共同完成任务的协作团队。

### 5.3 私有信息从数据入口隔离

每个 Agent 只能收到自己的 `PlayerView`。不能依赖 Prompt 告诉 Agent“不要读取”已经传入的秘密。

#### 关于 MsgHub / Message Hub

AgentScope 1.x 曾提供 `MsgHub`，用于将参与者加入同一消息中心并广播消息；旧版多智能体游戏示例经常采用这种写法。

本项目目标版本为 AgentScope 2.x。当前本地安装的 AgentScope 2.0.5 不再公开 `agentscope.pipeline.MsgHub`，2.x 文档中的 `MessageBus` 主要属于 Agent Service 的会话、事件流和分布式消息基础设施，不能与 1.x 的 `MsgHub` 混为一谈。因此本项目不依赖旧版 `MsgHub` API。

WolfScope 仍然需要“消息中心”的设计思想，但实现为游戏领域内的 `GameMessageRouter`：

- 公共频道：向所有仍在场的玩家广播公开发言和公开事件
- 狼队频道：只向存活狼人分发夜间协商消息
- 座位私信：只向预言家、女巫等指定座位发送技能结果
- 上帝频道：完整事件仅进入 Replay 和评测，不进入任何玩家上下文

路由器输出 AgentScope `Msg` 或可转换为 `Msg` 的领域消息，并在进入 Agent 前构造对应的 `PlayerView`。这样既使用 AgentScope 的消息抽象，又由游戏规则决定可见性。若后续锁定的 AgentScope 2.0.6 正式提供新的通用 Message Hub，再通过适配器评估接入，不改变信息边界和领域内核。

### 5.4 事实、信念和表达分离

- `GameState`：上帝掌握的真实世界状态
- `PlayerView`：某座位有权观察的事实
- `BeliefState`：该 Agent 对身份、关系和局势的主观判断
- `PublicSpeech`：Agent 决定向其他玩家公开表达的内容

### 5.5 计算交给工具，判断交给 LLM

规则约束、身份组合枚举、概率归一化、票型图和一致性检查尽量由确定性工具完成；LLM 负责提出假设、理解语言、权衡不确定性和生成自然发言。

### 5.6 不以“看起来聪明”代替评测

所有重要机制都必须能通过基线对照、消融实验或确定性测试验证。

## 6. 玩家 Agent 认知架构

### 6.1 决策流水线

```text
接收该座位可见的新事件
        ↓
Perception：抽取声明、立场、身份跳法和投票意图
        ↓
Evidence Ledger：写入带来源的证据账本
        ↓
Belief Update：更新身份概率、信任和局势假设
        ↓
Strategy Retrieval：按身份、阶段和局面检索策略
        ↓
Planning：提出多个候选行动及理由
        ↓
Tool Evaluation：计算概率、风险、收益和规则合法性
        ↓
Reflection：检查矛盾、越权信息和行动—发言一致性
        ↓
Final Action / Public Speech
```

### 6.2 感知层 Perception

感知层只处理当前新增的公开发言和事件，不反复扫描整局原始日志。输出结构化记录，例如：

```json
{
  "speaker": 2,
  "event_id": 23,
  "claim_type": "seer_result",
  "target": 7,
  "value": "wolf",
  "confidence": 0.98
}
```

确定性游戏事件不需要 LLM 再提取，例如死亡、投票和警长结果应直接由引擎生成结构化数据。只有自然语言发言中的声明、态度和意图需要抽取。

### 6.3 证据账本 Evidence Ledger

每条证据必须记录：

- 来源事件 ID
- 信息可见性
- 发言者和目标
- 证据类型
- 原始文本片段或摘要
- 确定事实或主观声明
- 当前是否被撤回、反驳或证伪

结论必须能追溯到证据，避免 Agent 凭空产生“记忆”。

### 6.4 信念状态 Belief State

每个玩家维护独立信念：

```json
{
  "role_probabilities": {},
  "trust_scores": {},
  "claimed_roles": {},
  "alliances": [],
  "contradictions": [],
  "active_hypotheses": [],
  "current_plan": null
}
```

概率是 Agent 的主观估计，不是真实身份的旁路泄漏。信念更新只能使用该座位可见的信息。

### 6.5 策略库 Strategy Library

策略库按以下维度组织：

- 身份：狼人、预言家、女巫、猎人、平民
- 阶段：首夜、警上、警下、白天发言、投票、残局
- 局面：单预言家、双预言家、平安夜、连续死亡、警徽流转等
- 战术：悍跳、冲锋、倒钩、隐藏神职、归票、票型分析

第一阶段使用版本控制下的 Markdown/结构化文本和确定性检索。是否升级为 AgentScope Skill 或 RAG，在 M3 后评估。

### 6.6 计算工具

计划向玩家 Agent 暴露只读工具：

- `get_public_facts`
- `query_evidence`
- `query_claim_history`
- `find_contradictions`
- `analyze_vote_graph`
- `enumerate_possible_worlds`
- `calculate_role_probabilities`
- `evaluate_action_candidates`
- `retrieve_strategy`
- `check_information_leak`
- `check_speech_consistency`

工具只能读取该玩家的视图和信念，不允许读取完整 `GameState`。

### 6.7 反思层 Reflection

最终行动提交前至少进行以下检查：

1. 行动是否合法？
2. 推理是否引用了自己无权知道的信息？
3. 发言是否与自己声称的身份一致？
4. 是否与此前公开立场直接矛盾？
5. 行动是否与发言中的投票意图一致？
6. 是否忽略了最新死亡、查验或票型事件？

系统保存简洁的“决策依据”和引用的证据 ID，不保存或展示模型原始思维链。

## 7. Agent 参数设计

### 7.1 模型运行参数

- 模型及供应商
- temperature / top_p（模型支持时）
- 最大输出长度
- reasoning budget（供应商支持时）
- 最大 ReAct 轮数
- 单次决策 token 预算
- 超时、重试和 fallback 模型

### 7.2 性格参数

- `aggressiveness`：攻击性
- `risk_tolerance`：风险偏好
- `deception`：欺骗倾向
- `leadership`：带队和归票倾向
- `trust_inertia`：改变既有判断的难度
- `claim_confidence`：表达确定性的程度
- `speech_length`：发言长度偏好

性格参数必须映射到策略选择、候选行动评分或表达方式，不能只作为装饰性 Prompt 文案。

### 7.3 认知参数

- 新事件感知窗口
- 证据衰减或保留策略
- 策略检索数量
- 候选行动数量
- 是否启用概率工具
- 是否启用反思
- 反思次数
- 工具调用和 token 上限

## 8. 概率推理路线

### 8.1 第一阶段：启发式分数

根据查验、身份冲突、发言矛盾、票型关系和信息泄漏等证据更新嫌疑分，再结合剩余角色数量进行约束和归一化。

### 8.2 第二阶段：可能世界枚举

枚举与该 Agent 已知事实一致的合法身份分配，对可能世界按软证据加权，计算每个座位属于各角色的边际概率。

### 8.3 第三阶段：行动期望效用

使用身份概率、当前轮次、神民存活风险、警徽和角色能力等因素，对投票、查验、用药、刀人等候选行动计算近似期望效用。

### 8.4 限制声明

语言证据的似然无法被精确建模，因此概率是决策辅助和可解释的主观估计，不宣称为严格的真实后验概率。

## 9. 技术架构

```text
GameEngine（唯一推进阶段和天数）
├── Domain Phase Engines
│   ├── NightEngine
│   ├── SheriffElectionEngine / DawnAnnouncementEngine
│   ├── DayEngine
│   └── DeathResolutionEngine
├── GameState / GameFactory
├── Rule Validation
├── Phase State Machine
├── Winner Resolution
├── Information Boundary
│   ├── Event Log
│   ├── Visibility Policy
│   └── PlayerView Builder
├── AgentScope Runtime
│   ├── 9 Player Agents
│   ├── Context / Message / Event
│   ├── Cognitive Tools
│   └── Middleware
├── Replay
│   ├── JSON Schema
│   ├── Terminal Renderer
│   └── Screenshot Artifacts
└── Evaluation
    ├── Batch Runner
    ├── Metrics
    ├── Baselines / Ablations
    └── Report Generator
```

## 10. 计划目录结构

```text
wolfscope/
├── src/wolfscope/
│   ├── game/              # 领域模型、规则和状态机
│   ├── views/             # 玩家视图和可见性
│   ├── agents/            # AgentScope 玩家适配
│   ├── cognition/         # 感知、证据、信念、规划、反思
│   ├── tools/             # 概率、票型、策略和一致性工具
│   ├── strategies/        # 版本化策略库
│   ├── replay/            # Schema、存储和终端渲染
│   ├── evaluation/        # 批量实验与指标
│   └── cli.py
├── tests/
│   ├── game/
│   ├── information_boundary/
│   ├── cognition/
│   ├── scripted_games/
│   └── evaluation/
├── replays/
│   ├── fixtures/
│   └── featured/
├── reports/
│   ├── figures/
│   └── experiments/
├── docs/
│   ├── architecture.md
│   └── decisions/
├── PROJECT_PROPOSAL.md
└── README.md
```

目录名和 Python 构建工具在 M0 阶段确定。

## 11. 里程碑

### M0：立项与技术验证

- [x] 形成项目立项讨论稿
- [x] 确认项目名、核心研究问题和最终范围
- [x] 确认 AgentScope 版本和 Python 版本：AgentScope 2.0.5，Python >= 3.11
- [x] 完成一个 AgentScope Agent + 自定义只读工具的离线 spike
- [x] 定义 `GameEvent`、`PlayerView`、`Evidence`、`BeliefState` 和 `Decision` Schema
- [x] 制定从第一版迁移与重写的边界
- [x] 写出第一批 Architecture Decision Records

完成标准：核心 Schema 和 AgentScope 接入方式经过小型验证，不在未知 API 上直接建设完整游戏。

### M1：确定性九人游戏内核

- [x] M1-1：建立规则配置、领域枚举和状态模型
- [x] M1-2：设计并实现顺序询问、角色专属视图、夜晚行动校验与原子结算
- [x] M1-3：实现 seed 固定竞选顺序、同时报名/退水、警下投票与待死亡公布；警徽实际处理留 M1-5
- [x] M1-4：实现 seed 固定发言顺序、警长方向、基础自爆、同时投票、PK 重投、放逐遗言及 M1-5 结算钩子
- [x] M1-5：实现统一死亡链、首夜遗言、猎人开枪、警徽处理及批次结束后的胜负结算
- [x] 由顶层 GameEngine 编排首夜特殊流程和后续昼夜循环，并由 GameFactory 使用 seed 确定性发牌
- [x] 完成九人局核心规则
- [x] 完成 PlayerViewBuilder、类型化角色私有状态、本地视图版本、规则集标识和玩家视图隔离测试
- [x] 完成类型化严格 ScriptedProvider，区分缺失动作与显式 `None`，并支持未消费动作审计
- [x] 建立第一版缺陷回归矩阵，复用已有精确测试并补齐无警下投票、空刀口、胜负幂等和领域解耦回归
- [x] 一条命令无 LLM 跑完四局确定性验收对局并生成上帝视角 JSON Replay

完成标准：规则、信息隔离和 Replay 可在无模型情况下独立验证。

### M2：AgentScope 认知玩家

- [ ] 九个独立 AgentScope 玩家
- [ ] 感知层和证据账本
- [ ] 信念状态与启发式身份概率
- [ ] 策略库与局面检索
- [ ] 票型和概率工具
- [ ] 候选行动规划
- [ ] 发言前反思和泄漏检查
- [ ] token、耗时、重试和工具调用追踪
- [ ] 完成至少一局真实模型端到端对局

完成标准：Agent 能引用结构化证据进行决策，行动合法，私有信息边界测试通过，并产生完整可审计 Replay。

### M3：评测、消融与作品集交付

- [ ] 建立单次 Prompt 基线 Agent
- [ ] 批量实验运行器
- [ ] 基线与完整认知 Agent 对照
- [ ] 关闭概率工具的消融实验
- [ ] 关闭策略检索的消融实验
- [ ] 关闭反思机制的消融实验
- [ ] 汇总胜率、质量、成本和稳定性指标
- [ ] 选择典型成功与失败 Replay
- [ ] 生成实验图表和 Replay 截图
- [ ] 完成中英文 README
- [ ] 完成架构图、认知流程图和实验结论

完成标准：README 能用可复查的数据回答“新 Agent 设计是否比第一版更好，以及代价是什么”。

## 12. 评测设计

### 12.1 系统可靠性

- 非法行动率
- 结构化输出解析失败率
- 重试率和 fallback 率
- 未授权信息进入 PlayerView 的次数
- Replay Schema 验证通过率
- 完整对局成功率

### 12.2 决策质量

- 好人投狼准确率
- 预言家查验收益
- 女巫用药有效性
- 狼人刀神/刀关键玩家比例
- 狼队友误伤或行动冲突率
- 发言意图与最终投票一致率

### 12.3 认知质量

- 明显规则逻辑错误数
- 公开发言私有信息泄漏数
- 自相矛盾发言数
- 虚构历史事件数
- 决策证据引用覆盖率
- 身份概率校准指标（待讨论具体采用 Brier Score 或其他指标）

### 12.4 博弈结果

- 阵营胜率
- 平均游戏天数
- 不同身份存活率
- 悍跳成功率
- 警长当选和警徽利用情况

### 12.5 成本与性能

- 每局模型调用次数
- 每局输入/输出 token
- 每次决策和整局延迟
- 每局估算费用
- 工具调用次数
- 反思机制带来的增量成本

## 13. 实验矩阵（初稿）

至少包含以下配置：

| 实验组 | 结构化信念 | 策略检索 | 概率工具 | 反思 |
|---|---:|---:|---:|---:|
| Baseline | 否 | 静态长 Prompt | 否 | 否 |
| Belief | 是 | 静态长 Prompt | 否 | 否 |
| Belief + Strategy | 是 | 是 | 否 | 否 |
| Belief + Strategy + Tools | 是 | 是 | 是 | 否 |
| Full Agent | 是 | 是 | 是 | 是 |

为控制成本，早期实验可以使用较少局数寻找明显问题；最终结果必须报告样本量、模型版本、模型参数、发牌 seed、失败局处理方式和不可复现性限制。

LLM 采样不能仅靠 seed 完全复现，因此：

- 规则等价性用 Scripted Provider 验证
- LLM 表现用多局统计而非单局结论
- 记录模型、参数、Prompt/策略版本和每局 Replay

## 14. 最终 README 内容

1. 项目一句话介绍和演示截图
2. 为什么重新设计第一版
3. 九人局与系统运行方式
4. 总体架构图
5. 玩家认知架构图
6. AgentScope 在项目中的具体职责
7. 私有信息隔离设计
8. 概率工具和策略检索设计
9. 基线与消融实验结果
10. 精选 Replay 案例
11. 已知局限、成本和未来方向
12. 安装、配置和运行命令

## 15. 风险与控制

### 风险 1：AgentScope 2.0.6dev API 变化

控制：M0 先做 spike；锁定版本或 commit；将 AgentScope 限制在适配层，避免领域内核直接依赖框架类型。

### 风险 2：认知流水线导致调用次数和成本过高

控制：确定性事件不调用模型；感知使用较小模型或批处理；只在关键决策启用强推理和反思；设置预算 Middleware。

### 风险 3：概率数字看似精确但缺少可信语义

控制：区分硬约束和软证据；公开计算方法；报告校准结果；将概率定义为主观决策辅助。

### 风险 4：策略库变成另一份超长 Prompt

控制：按身份、阶段和局面建立索引；限制每次检索条目；在 Replay 中记录实际使用的策略条目。

### 风险 5：实验变量过多，结论不清晰

控制：先固定板子和模型；采用逐项增加能力的消融矩阵；每轮只回答一个核心问题。

### 风险 6：作品集只展示复杂度，没有清晰结果

控制：最终 README 围绕“问题—设计—实验—结论”展开，优先展示三到五个最能说明价值的指标。

## 16. 第一版代码的处理原则

### 建议复用

- 九人板子和已确认的规则细节
- 确定性裁判思想
- 事件可见性和 `view_for` 测试案例
- Scripted Provider 思想
- JSON Replay 的历史数据与典型失败案例
- 警长、女巫、猎人、屠边等规则回归用例

### 建议重新实现或重构

- LLM 客户端和 Agent 封装
- Prompt 拼装方式
- 自然语言历史记忆
- 决策协议
- 玩家认知状态
- 批量评测和指标系统
- 终端 Replay 渲染

不直接复制整套旧工程，避免把旧结构和新框架耦合在一起。

## 17. 待讨论与待拍板事项

### P0：立项前必须确认

1. 第一阶段使用哪个模型作为主模型和哪个模型作为低成本感知模型。
2. 最终实验可接受的模型调用预算和对局数量。

### P1：M0/M1 期间确认

1. 使用 `uv` + `pyproject.toml`，还是继续使用 `pip` + `requirements.txt`。
2. 身份概率第一版采用纯启发式，还是直接加入可能世界枚举。
3. 策略库采用普通检索还是 AgentScope Skill。
4. Replay 截图采用终端富文本、静态 HTML 渲染，还是两者都做。
5. 是否保留 LangGraph 版作为历史对照，还是只在 README 中引用第一版结论。

## 18. 下一步

立项讨论通过后，按以下顺序推进：

1. 回答第 17 节 P0 问题并更新本文档为 v1.0。
2. 创建 ADR：为什么使用确定性裁判、为什么不用 Agent Team 主持、为什么取消 Web 前端。
3. 完成 AgentScope 技术 spike。
4. 定义五个核心 Schema。
5. 制定第一版代码和测试的迁移清单。
