# 公共发言 Claim 失败回归样本库

`gold_v1.jsonl` 保留早期命名，每行是一条独立公开发言。当前样本用于保存真实对局中发现的解析边界和失败案例，不追求穷尽长发言中的所有合法 Claim，也不作为正式 Precision、Recall 或 F1 数据集。

## 标注原则

- 只标原文明说的内容，不标推理得到的结论。
- `supporting_text` 必须逐字复制自 `text`，不要改写。
- `expected_claims` 是必须提取的语义；`forbidden_claims` 是特别需要防止的高风险误提取模式。
- `summary` 不属于 Gold 标注，因为不同措辞不应影响语义评分。
- 不确定时宁可不标，并在 `note` 中说明歧义。
- `review_status=reviewed` 只表示目标回归点已经人工确认，不代表该长发言完成了穷尽式 Gold 标注。

## 当前定位

只有出现 Schema 拒绝、明显误提取或漏提取、转述归属错误、投票目标错误，或错误 Evidence 实际影响 Agent 决策时，才新增回归样本。匹配器与 API 运行器保留作诊断工具，但当前总体指标不用于宣称模型质量；未来若建立穷尽式冻结测试集，再恢复正式 Precision/Recall 评测。

## 验证

```bash
wolfscope-validate-claims
```

也可验证指定文件：

```bash
wolfscope-validate-claims datasets/claim_extraction/gold_v1.jsonl
```

验证器会检查 JSONL 格式、字段枚举、Case ID 唯一性、Claim 必填字段、未来查验时间，以及 `supporting_text` 和 `condition` 是否确实来自原文。

## 来源说明

首批10条不是来自 M1 的四个 Scripted Replay；那些 Replay 的发言是测试占位文本。当前样本来自2026-08-07两次真实 `deepseek-v4-flash` 单日 API 对局输出，尚未保存为正式 Replay，因此使用 `run_id` 标记来源。后续完整 LLM 对局应直接写入 Replay，再由导出命令生成待标注模板。
