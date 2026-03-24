# Yakumo Target State

目标是将当前单体式 AstrBot 重构为“主 Agent 平台 + 多能力平台”的架构。

## 目标结构

### 1. Agent Platform

作为主服务器部署。

职责：

- 统一网关
- 对外 API
- 主 Agent
- 会话路由
- provider/stt/tts/message platform/persona/database 的基础接口访问
- subagent 调度
- 认证、配置、观测、状态管理

这一层负责“决策、编排、路由”，不负责承载所有具体能力实现。

### 2. Capability Platforms

作为一个或多个独立平台或服务部署。

职责：

- 子 Agent 服务
- 插件服务
- Skills 服务
- Tool 执行服务
- Sandbox/Browser/Python/Shell 服务
- Knowledge Base 服务
- Cron 服务

这一层负责“执行、扩展、专用能力”。

## 最终运行效果

### 1. 主服务器只保留核心控制面

主服务器接收来自消息平台或 WebUI 的请求，完成：

- 用户会话识别
- 人格选择
- provider 选择
- 主 Agent 推理
- 子能力委派
- 结果汇总与回传

### 2. 子能力通过统一协议接入

插件、skills、subagent、tools 不再直接耦合到主 Agent 内部，而是通过统一协议或统一注册中心接入。

推荐统一抽象：

- `AgentService`
- `ToolRegistry`
- `CapabilityRegistry`
- `PersonaResolver`
- `ConversationStore`
- `ProviderGateway`
- `MessageGateway`

### 3. 主 Agent 只关注编排

主 Agent 的目标不是直接承载所有逻辑，而是：

- 判断是否直接回答
- 判断是否委派给子 Agent
- 判断是否调用插件/技能/工具
- 汇总外部能力返回结果
- 生成最终输出

### 4. 多平台并行扩展

最终可以支持：

- 一个主 Agent 平台
- 多个面向不同场景的子 Agent 平台
- 多个独立插件或工具执行节点
- 不同部署环境下的水平扩展

## 目标分层

### 1. Kernel Layer

纯 Agent 内核：

- runner
- tool loop
- handoff
- response
- context model

### 2. Platform Layer

主平台：

- 主 Agent
- API gateway
- 会话、人格、provider、消息平台接口
- orchestration

### 3. Capability Layer

扩展能力：

- plugins
- skills
- sandbox tools
- subagents
- kb
- cron

## 目标收益

### 1. 架构收益

- 主 Agent 与能力实现解耦
- 插件、技能、工具不再直接侵入内核
- 系统边界更清晰

### 2. 工程收益

- 更容易测试
- 更容易替换底层实现
- 更容易做独立部署和灰度发布
- 更容易控制资源隔离

### 3. 产品收益

- 能支持多 Agent 协作
- 能支持不同能力节点独立扩容
- 能支持后续演进成真正的平台化架构

## 第一阶段不追求的效果

第一阶段目标不是立刻完成全面分布式化。

第一阶段只要求做到：

- 把 Agent 基础接口抽出来
- 把主 Agent 平台和能力平台的代码边界拆出来
- 让插件、skills、tools、subagent 可以通过统一边界接入

等代码边界稳定后，再决定哪些模块独立进程化、哪些模块继续保留在同一部署单元。
