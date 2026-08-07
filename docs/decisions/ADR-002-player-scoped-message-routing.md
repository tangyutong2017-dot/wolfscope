# ADR-002：采用玩家视图和领域消息路由，不依赖旧版 MsgHub

- 状态：Accepted
- 日期：2026-08-06

## 背景

AgentScope 1.x 的 `MsgHub` 常用于群聊和游戏示例，但本项目当前锁定的 AgentScope 2.0.5 不公开 `agentscope.pipeline.MsgHub`。AgentScope 2.x Agent Service 中的 `MessageBus` 是服务会话和分布式事件基础设施，不等同于游戏领域的信息权限系统。

## 决策

使用 `GameMessageRouter` 按 `public`、`wolves`、`private`、`god` 四种可见性投影事件，再构造不可变的 `PlayerView`。玩家工具只能闭包捕获自己的 `PlayerView`，不能接收 `GameState`。

领域事件和视图不依赖 AgentScope 类型；进入玩家 Agent 前再转换为 AgentScope `Msg`。

## 后果

- 信息边界可以通过普通单元测试验证。
- AgentScope 升级不会改变游戏领域协议。
- 狼队频道和角色私信需要由项目自行实现。
- 未来若 AgentScope 提供合适的 Hub，可在适配层接入。
