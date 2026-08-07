# M2-6 完整 Agent 终局验收

## 本地确定性验收

测试专用 `AdaptiveFakeGateway` 只根据当前授权 `AgentDecisionInput` 生成合法结构化动作，完整经过 `AgentGameProvider`、九座位 Runtime、PlayerView 和真实 Engine。seed 42 固定身份局在第3天因神职全灭结束，模型路径调用超过30次，标准 GOD Replay 写入后可由 `ReplayWriter.read` 完整读回，最后事件为 `game_finished`。

该测试证明的不是策略质量，而是所有可能触发的 Provider 接口已经从 Support 迁移到 Agent 路径，昼夜循环能推进到规则胜负，且终局结果可以复盘。

## 真实 Flash 端到端对局

运行配置：

- 模型：`deepseek-v4-flash`
- seed：42（由 `GameFactory` 确定性发牌）
- 投票上下文：`balanced`
- 运行保护：8天
- 正式 Provider：`AgentGameProvider`
- Evidence：公开发言只解析一次并缓存，再分发到各玩家账本

结果：

- 第2天结束，狼人阵营因全部神职死亡获胜。
- 54次玩家决策：44次成功、10次安全降级。
- 18次公开语义提取全部成功，生成44个 Claims。
- 玩家决策消耗244573输入 token、49269输出 token；语义提取消耗30756输入 token、4273输出 token。
- 产生44个连续 GOD 事件，Replay 写入后立即通过严格读取校验。
- 114次有效 Strategy ID 引用；2个截断或空 ID 被 Runtime 删除并记录。
- 正式 Provider 不持有 `DeterministicSupportProvider`，不存在 Support 接管动作。

10次降级由7次结构化输出缺失和3次请求异常构成，没有非法目标或越权信息导致的降级。降级率是后续 M3 稳定性和成本实验的基线问题，不影响本次端到端验收；相反，这局验证了模型局部失败不会中断完整规则终局。

## 关键 Replay 路径

本地运行会生成两份互不混淆的 JSON：

- `replays/live/full-game-seed-42.json`：标准 GOD Replay，只包含角色、胜负和 Engine EventLog。
- `replays/live/full-game-seed-42-diagnostics.json`：模型调用、token、延迟、失败和语义提取诊断。

`replays/live/` 默认忽略 Git，避免将大体积原始诊断直接提交。进入作品集整理阶段后，再从标准 Replay 复制精选且稳定的样例，并生成截图和案例分析。

## 复现命令

```bash
wolfscope-smoke full-game \
  --vote-context-mode balanced \
  --seed 42 \
  --max-days 8 \
  --output replays/live/full-game-seed-42-diagnostics.json \
  --replay-output replays/live/full-game-seed-42.json \
  --summary-only
```
