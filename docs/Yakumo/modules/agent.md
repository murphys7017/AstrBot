# Agent Modules

## 主 Agent 文件

### `astrbot/core/astr_main_agent.py`

职责：

- 为当前消息选择 Provider
- 获取当前 Conversation
- 处理 Persona 注入
- 处理 Skills Prompt 注入
- 处理 Knowledge Base 注入
- 处理 ToolSet 组装
- 处理 SubAgent handoff 工具注入
- 处理 sandbox/local runtime 工具注入
- 构建并启动 Agent Runner

说明：

- 当前主 Agent 的核心入口
- 同时承担了编排层、能力装配层、部分运行时策略层的职责

问题：

- 文件职责过大
- 和 `star.Context`、Persona、Skill、KB、Tool、Sandbox 高耦合

## Agent 上下文

### `astrbot/core/astr_agent_context.py`

职责：

- 定义 `AstrAgentContext`
- 当前字段主要是 `context: Context` 和 `event: AstrMessageEvent`

说明：

- 这里的 `Context` 实际是插件系统上下文
- 这是当前 Agent 与插件运行时耦合最明显的地方之一

重构关注点：

- 后续应该替换为更窄的 `AgentServices` 或 `AgentRuntimeFacade`

## Tool 执行

### `astrbot/core/astr_agent_tool_exec.py`

职责：

- 执行 function tools
- 执行 handoff tools
- 执行 MCP tools
- 处理 send_message_to_user 等主 Agent 相关工具
- 将工具调用和 Agent Runner 串起来

说明：

- 这是主 Agent 与工具体系的执行桥梁

## Agent 内核

### `astrbot/core/agent/*`

重要子模块：

- `agent.py`: Agent 定义
- `run_context.py`: 运行时上下文包装
- `tool.py`: ToolSet、FunctionTool 等基础类型
- `tool_executor.py`: 工具执行抽象
- `message.py`: Agent 消息结构
- `response.py`: Agent 响应结构
- `hooks.py`: Agent Hooks 基类
- `runners/tool_loop_agent_runner.py`: Tool Loop 主执行器

说明：

- 这一层相对接近“可抽离的内核”
- 但仍然引用了部分 AstrBot 业务模型

## SubAgent

### `astrbot/core/subagent_orchestrator.py`

职责：

- 从配置中读取子 Agent 定义
- 构造 `HandoffTool`
- 将子 Agent 暴露给主 Agent 使用

说明：

- 当前它并不自己执行 Agent
- 它更像 handoff tool 的装配器

重构关注点：

- 未来可以演进成跨服务的 SubAgent Registry / Router

## 当前判断

如果要推进 Yakumo，Agent 层建议拆成三层：

1. Agent Kernel
2. Main Agent Orchestrator
3. Capability Injection Layer

当前这些职责几乎都堆在 `astr_main_agent.py`
