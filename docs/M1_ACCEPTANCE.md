# M1 确定性内核验收

运行命令：

```bash
wolfscope-m1 all --output-dir replays --overwrite
```

验收剧本：

| 剧本 | 结果 | 胜因 | 天数 | 事件数 |
|---|---|---|---:|---:|
| `good-win-seed-42` | 好人胜 | 狼人全灭 | 2 | 33 |
| `wolves-eliminate-deities-seed-42` | 狼人胜 | 神职全灭 | 3 | 46 |
| `wolves-eliminate-civilians-seed-42` | 狼人胜 | 平民全灭 | 3 | 49 |
| `hunter-tie-break-seed-42` | 好人胜 | 猎人开枪后狼人全灭；同时神职全灭时好人优先 | 4 | 58 |

每局输出一个 `replays/<game-id>.json`。Replay 保存全员身份、最终结果、最终存活座位，以及 Engine 产生的完整 `PUBLIC`、`WOLVES`、`PRIVATE` 和 `GOD` 事件流。

`PlayerViewBuilder` 验收覆盖公开存活和警长状态、角色专属资源、狼人队友、预言家查验、女巫刀口、上帝事件隔离、首夜待死亡隔离、死人拒绝、视图深拷贝，以及不暴露 GOD 全局事件编号缺口的玩家本地连续编号。
