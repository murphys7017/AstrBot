# Prompt Module

记录 AstrBot 当前 prompt/context 构建机制、问题和目标演进方向。

## 当前入口

### 主链路

- `astrbot/core/astr_main_agent.py`
- `astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py`
- `astrbot/core/agent/runners/tool_loop_agent_runner.py`
- `astrbot/core/provider/sources/*`

### 当前核心对象

- `ProviderRequest`
- `Message`
- `ToolSet`

## 当前构建机制

### 1. 主 Agent 先构造 `ProviderRequest`

`astrbot/core/astr_main_agent.py` 负责：

- 选择 Provider
- 获取 Conversation 和历史消息
- 提取当前消息文本、图片、文件、引用消息
- 构造 `ProviderRequest`

当前 `ProviderRequest` 主要字段：

- `prompt`: 当前轮用户文本
- `system_prompt`: 系统指令字符串
- `contexts`: 历史消息
- `image_urls`: 图片引用
- `extra_user_content_parts`: 附加到当前用户消息的额外内容块
- `func_tool`: 当前轮可用工具集合

### 2. 多个模块继续修改同一个 `ProviderRequest`

主链路中，以下内容会继续写入同一个请求对象：

- `prompt_prefix`
- persona prompt
- persona begin dialogs
- skills prompt
- toolset
- subagent handoff tools
- knowledge base 结果
- safety prompt
- sandbox/local runtime prompt
- tool calling prompt
- live mode prompt

### 3. 插件在最终调用前继续改写

`OnLLMRequestEvent` 在主链路中发生于：

- 主 Agent 已经基本完成 request 构建
- Agent runner reset 之前

插件当前可以直接修改：

- `req.prompt`
- `req.system_prompt`
- `req.contexts`
- `req.func_tool`

### 4. Runner 和 Provider 再次做组装

当前系统里还有两层后置组装：

1. `ToolLoopAgentRunner.reset()`
   - 将 `system_prompt` 插为 system message
   - 将 `contexts` 作为历史消息
   - 将 `prompt/image_urls/extra_user_content_parts` 组装成当前 user message

2. Provider source
   - 再根据 OpenAI / Anthropic / Gemini / Ark 等格式生成最终 payload
   - 图片编码逻辑也在这一层或更早的层发生

## 当前判断

当前系统不是“没有 prompt builder”，而是“没有统一的 prompt/context builder”。

现状更接近：

1. request builder
2. prompt decorator
3. message assembler
4. provider payload converter

这些职责分散在不同模块中，没有统一中间层。

## 当前主要问题

### 1. 同一个 `system_prompt` 中混合多个语义层

当前混合在一起的内容包括：

- 人格扮演
- skills 说明
- 工具调用规则
- subagent 路由说明
- 插件动态注入
- safety / runtime / KB 等系统附加内容

问题：

- 来源不清晰
- 优先级不清晰
- 冲突难以定位
- 顺序难以管理

### 2. context 构建是“边收集边 append”

当前流程更接近：

- 收到一个信息
- 立即写进 `ProviderRequest`
- 继续被下游模块改写

问题：

- 缺少统一决策点
- 不容易判断哪些信息应该进入 LLM
- 不容易判断哪些信息只应该影响执行器或 provider

### 3. 图片处理过早进入 provider 细节

当前多条链路会较早将图片转为：

- `base64://...`
- `data:image/...;base64,...`

问题：

- 通用 context 层过早感知 provider 细节
- 日志和调试信息容易膨胀
- 不同 provider 难以复用统一图片引用模型

### 4. 旁路链路未统一

除了主链路，还有：

- third-party agent runner
- cron 唤醒主 Agent
- background task 唤醒主 Agent
- 插件 SDK 直接调用 LLM

这些链路都和 prompt/context 构建相关，但没有统一收口。

## 理想形态

如果不考虑兼容性，推荐采用“先收集、后筛选、先建模、再渲染”的结构。

### 1. 先收集

统一收集：

- 用户输入
- 会话历史
- persona
- skills
- tools
- subagent
- KB
- 图片/附件
- 平台限制
- 插件扩展

### 2. 再判断

统一判断：

- 哪些信息和本轮有关
- 哪些信息应该给 LLM
- 哪些信息只应该给执行器
- 哪些信息需要裁剪、摘要、延后处理

### 3. 中间表示

推荐引入结构化中间层，而不是直接拼字符串。

示例：

```python
PromptIR(
    identity=[],
    policy=[],
    capabilities=[],
    delegation=[],
    context=[],
    attachments=[],
    extensions=[],
)
```

### 4. 最后编译

按 provider 能力将中间表示编译为：

- system message
- history messages
- current user message
- tool schema
- image payload

## 推荐分层

推荐至少拆成以下语义层：

- `identity`: persona、口吻、角色设定
- `policy`: safety、平台规则、运行时限制
- `capability`: skills、tools、computer use 能力
- `delegation`: subagent 路由和 handoff 规则
- `context`: 历史消息、当前用户消息、KB、附件说明
- `extension`: 插件或运行时补丁

## 推荐实现方向

### 最小侵入路线

第一阶段不改变对外兼容面，只做内部收口：

1. 保留 `ProviderRequest`
2. 保留 `OnLLMRequestEvent`
3. 引入统一 `PromptEngine` 或 `ContextBuilder`
4. 把现有 prompt 相关逻辑抽成固定 stage
5. 最终仍然写回 `ProviderRequest`

### 理想路线

如果允许破坏兼容性，目标应该是：

1. 用结构化中间表示替代“字符串 append”
2. 插件扩展中间表示，而不是直接 patch 最终 request
3. 图片始终保留为引用对象，直到 provider compile 阶段再决定编码方式
4. 允许并行收集 persona / skill / KB / attachment / routing 信息
5. 统一由一个 compiler 生成最终 provider payload

## 当前结论

当前 prompt/context 系统的主要问题不是功能不足，而是边界不清晰。

当前最缺的不是新的 prompt 文本模板，而是：

- 统一 context builder
- 明确 prompt 语义层
- 统一中间表示
- 明确 provider compile 边界

在当前代码基础上，最稳的演进方式是先收口，再抽象，再替换。
