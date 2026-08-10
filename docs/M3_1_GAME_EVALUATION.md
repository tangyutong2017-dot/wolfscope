# M3-1 自动对局评测

## 目标

M3 不用单局胜负证明 Agent 强弱，而是把完整对局变成可重复、可恢复、可审计的工程评测。评测固定模型档位、规则、投票上下文和 seeds，串行调用 API，避免并发请求干扰延迟和服务稳定性。

## 命令

```bash
wolfscope-eval --seeds 1,2,3 \
  --vote-context-mode balanced \
  --max-days 8 \
  --output-dir artifacts/evaluation/flash-baseline-v1
```

也可以生成连续 seed：

```bash
wolfscope-eval --games 5 --start-seed 1
```

`--resume` 只接受与原 `config.json` 完全一致的 seeds、模型档位、上下文和最大天数，防止不同实验条件混入同一份报告。`--fail-fast` 用于开发诊断；默认单局失败会落盘并继续后续 seed。

## 产物

```text
artifacts/evaluation/<run>/
├── config.json
├── summary.json
├── report.md
├── diagnostics/
│   └── seed-<N>.json
├── replays/
│   └── seed-<N>.json
└── failures/
    └── seed-<N>.json
```

- `config.json`：实验边界，供恢复运行校验。
- `diagnostics`：逐次模型调用、复杂度、引用和语义提取记录。
- `replays`：Engine 产生的 GOD 视角事实流。
- `summary.json`：适合后续绘图或作品集数据处理。
- `report.md`：中文可读报告，包含逐局和分任务表格。

写入是增量的：每局结束或失败后都会更新汇总。`--aggregate-only` 可以离线从已有诊断重新生成报告。

## 指标

- 阵营胜负和终局原因；
- 平均天数、事件数和决策数；
- 最终成功率与真正的首次成功率；
- Thinking / Non-thinking 调用量；
- L2 结构修复与 L3 确定性兜底；
- 各任务调用、成功、修复和兜底；
- 决策与语义提取的 token、累计模型延迟。

## 解释边界

AgentScope 在部分结构化失败中无法返回 usage，因此 token 汇总可能低估失败尝试。累计模型延迟是各调用耗时之和，不等于未来并发执行时的墙钟时间。少量固定 seed 用于验证终局率、信息流和结构化稳定性，不能作为阵营平衡或模型博弈水平的统计结论。
