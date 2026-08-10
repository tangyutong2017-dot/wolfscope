# M2-8 决策复杂度与智能降级

## 目标

减少完整局的重复上下文、推理耗时和无效重试，同时保证局部模型失败不会立刻退化成与局面无关的固定动作。模型档位不路由：当前正式对局各层统一使用 DeepSeek Flash，只有思考方式、输入投影和输出契约发生变化。

## 初始复杂度

- `L0 FULL`：狼人、预言家、女巫和猎人默认使用完整授权认知输入。
- `L1 COMPACT`：普通村民默认使用紧凑输入，公共 Claim 已被 Brief 概括时不再重复发送，白天发言只保留最近三条原文。
- 村民被公开查杀、本人受压、进入五人残局、PK 或遗言时升级到 L0。

复杂度描述输入丰富度，不再等同于是否启用 thinking：

- 狼队整体规划、L0 白天发言、竞选发言、PK 和遗言保留 thinking。
- 普通 L1 发言直接使用 non-thinking。
- 投票、上警选择、退水、警长投票、验人、女巫行动、发言顺序、猎人枪权和警徽移交都是有限动作，首轮直接使用 non-thinking。
- 投票 Brief 只保留与当轮候选人有关的身份声明、查验、投票意向、立场和冲突；`balanced` 仍保留原始发言。
- 上警选择、退水、警长投票、验人和发言顺序不携带与当前动作无关的历史 Evidence；任务字段与 StrategyBrief 保留。
- 对具有 `candidates` 或 `eligible_targets` 的动作，Gateway 会为本轮动态生成目标枚举 Schema。非法目标不能作为有效结构穿过模型边界，首次违规进入短 L2 修复，Runtime 的确定性合法性检查仍作为最后防线。

普通发言和投票的结构化输出预算均为 2000 token；最终公开字数仍由分阶段 `SpeechPolicy` 独立限制。

## 失败降级

```text
按任务选择首次 Flash thinking / non-thinking 决策
        ↓ 结构化缺失、请求异常或 Schema 失败
L2 同一 Flash non-thinking + 最小授权输入 + 简化发言 Schema
        ↓ 再次失败
L3 玩家视角内的确定性局面保底
```

L2 不重发完整 Evidence 和 SituationBrief，只保留玩家状态、合法任务字段、最近必要发言、局面标签和最高优先级方法。普通发言先返回 `SpeechRepairDecision`，本地补齐 confidence 和空审计引用后再校验为正式 `SpeechDecision`。

L3 发言根据被查杀、预言家对跳、票型冲突和残局等确定性标签生成；狼人投票优先遵循合法团队共同目标，预言家投票优先使用自己的真实查杀。没有确定性合法依据时才弃票。L3 不把他人公开声明升级为事实。

## 诊断

每条模型记录保存：

- `initial_complexity_level`
- `final_complexity_level`
- `complexity_reason`
- 各次尝试的 thinking 状态

完整局汇总同时统计 thinking/non-thinking 调用数，并按初始复杂度统计首次成功、L2救回、L3保底、token 和延迟。该数据用于后续比较成本、稳定性与策略质量，不用单一胜负替代工程评测。
