# 第一版缺陷回归矩阵

本表把第一版的规则风险和失败案例映射到 WolfScope M1 的自动化测试。已有精确覆盖时不复制测试；缺失的跨模块行为集中放入 `tests/regression/`。

## M1 已覆盖

| 第一版风险或规则 | 新版保证 | 覆盖测试 |
|---|---|---|
| Provider 可直接读取完整 `GameState` | 决策协议只接收角色或阶段限定 Observation；Player 工具只闭包 PlayerView | `test_agentscope_tool_is_read_only_and_player_scoped`、`test_m1_player_view.py` |
| 首夜先公布死亡再竞选警长 | 首夜内部结算后先竞选，之后才公布死讯 | `test_engine_runs_first_night_election_dawn_day_then_loops` |
| 首夜待死亡玩家可能提前得知死亡 | pending death 不改变公开存活状态，仍可参选 | `test_pending_dead_player_can_run_and_win`、`test_pending_death_remains_publicly_alive` |
| 狼队可能返回空刀口 | 狼人必须提交当前存活目标，缺失目标原子拒绝 | `test_wolves_cannot_submit_a_missing_kill_target` |
| 女巫可能自救、自毒或同夜救毒 | 结构化 WitchAction 一次只能表达一种行动，并校验自救、自毒和资源 | `test_witch_cannot_save_herself`、`test_witch_cannot_poison_herself` |
| 解药用完后仍看到刀口 | 只有解药存在时才发送刀口 Observation 和 PRIVATE 事件 | `test_used_antidote_hides_future_victim` |
| 预言家查验依赖自然语言再次提取 | Engine 直接生成结构化 PRIVATE `seer_result` | `test_seer_result_and_witch_victim_are_private`、`test_seer_sees_only_own_private_result_and_checked_state` |
| 非法夜间行动造成部分状态修改 | 完整命令校验失败时状态、阶段和事件保持不变 | `test_invalid_action_does_not_partially_mutate_state_or_events` |
| 后询问的投票者看到先前票型 | 首轮和重投分别以相同 Observation 同时收集 | `test_votes_are_simultaneous_and_abstention_is_allowed` |
| 退水玩家错误恢复警下投票权 | 原始上警者退水后仍不能投警长票 | `test_withdrawn_candidate_does_not_regain_vote` |
| 所有人上警时错误尝试警下投票 | 无警下玩家时直接流警 | `test_all_players_running_for_sheriff_produces_no_sheriff` |
| 平票重投轮数不稳定 | 只进行一次 PK 重投，仍平票则无人出局 | `test_tied_players_pk_and_do_not_revote`、`test_revote_tie_means_no_exile` |
| 猎人开枪前提前判断胜负 | 完整死亡链结束后统一判胜 | `test_hunter_chain_tie_prioritizes_good_win`、`test_hunter_boundary_ends_with_both_wolves_and_deities_eliminated` |
| 被毒猎人错误开枪 | poison 是唯一禁止开枪的死因 | `test_poisoned_hunter_cannot_shoot` |
| 猎人枪杀目标错误获得遗言 | 枪杀目标直接进入死亡链且无遗言 | `test_hunter_shot_target_has_no_last_words` |
| 警徽移交给死亡玩家或遗漏枪杀警长 | 猎人链结束后按当前存活名单处理警徽 | `test_hunter_shoots_sheriff_then_badge_is_resolved` |
| 重复胜负检查产生重复结束事件 | Winner Resolution 幂等 | `test_winner_resolution_is_idempotent` |
| LangGraph reducer 导致事件重复 | M1 不使用 LangGraph；EventLog 单点追加并校验连续 ID | `test_write_and_read_preserves_complete_god_event_stream` |
| 相同 seed 只能固定发牌 | seed 固定发牌和顺序，ScriptedProvider 固定决策，Replay 字节一致 | `test_same_seed_produces_same_deal`、`test_same_result_writes_byte_identical_json` |
| 最大天数被误报为规则平局 | 明确标记 `max_days_reached`，不设置 winner | `test_max_days_is_infrastructure_stop_not_a_draw` |
| Replay JSON 整数键回读后变化 | Engine 事件 payload 在写入前即使用 JSON 合法字符串键 | `test_write_and_read_preserves_complete_god_event_stream` |
| 领域规则与 LLM 框架耦合 | `wolfscope.game` 不导入 AgentScope | `test_game_domain_does_not_import_agentscope` |

## 延后到 M2 的认知失败

以下问题属于 Agent 如何理解和表达信息，而不是 M1 裁判规则。M1 已保证原始信息边界，M2 再建立专门指标：

| 第一版失败案例 | M2 处理方式 |
|---|---|
| 狼人在公开发言中泄露夜间刀口 | 发言前私密信息泄漏检查；Replay 记录泄漏指标 |
| 被救玩家被错误推断为“可能自救女巫” | Evidence Ledger 区分公开事实、个人私密事实和主观假设；策略规则禁止把未知救药机制当成硬事实 |
| LLM 输出合法但理由与证据无关 | Decision 强制引用 Evidence 和 strategy IDs，并进行发言前反思 |

这些项目不能由 M1 ScriptedProvider 证明“智能解决”，因此不计入确定性裁判的完成条件。
