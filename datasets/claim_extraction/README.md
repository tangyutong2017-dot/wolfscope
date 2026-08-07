# 公共发言 Claim 标注集

`gold_v1.jsonl` 每行是一条独立公开发言。当前首批样本均为 `draft`，需要人工复核后才能改为 `reviewed` 并纳入正式指标。

## 标注原则

- 只标原文明说的内容，不标推理得到的结论。
- `supporting_text` 必须逐字复制自 `text`，不要改写。
- `expected_claims` 是必须提取的语义；`forbidden_claims` 是特别需要防止的高风险误提取模式。
- `summary` 不属于 Gold 标注，因为不同措辞不应影响语义评分。
- 不确定时宁可不标，并在 `note` 中说明歧义。
- `review_status=draft` 表示尚未形成正式 Gold；两人或两轮审核一致后改为 `reviewed`。

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
