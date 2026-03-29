# Prompt Development Plan

记录当前对 AstrBot prompt/context 系统的整体开发思路。

## 核心判断

当前 AstrBot 的主要问题不是缺少 prompt 内容，而是缺少统一的构建流程。

当前代码更接近：

1. 一边收集信息
2. 一边修改 `ProviderRequest`
3. 多个模块持续追加 `system_prompt`
4. 最后由 runner 和 provider 再次组装

这套方式能工作，但不利于继续扩展 persona、skills、tools、subagent、plugin、KB、图片等能力。

## 开发目标

目标不是简单增加一个新的 prompt 模板，而是建立统一流程：

1. 收集信息
2. 选择信息
3. 渲染结果
4. 交给 LLM

简化表达：

`Collect -> Select -> Render -> Execute`

## 总体思路

### 1. Collect

先统一收集本轮请求涉及的全部原始信息。

信息来源包括：

- 当前用户输入
- 当前会话历史
- 当前 persona
- 当前可用 skills
- 当前可用 tools
- 当前 subagent 配置
- 当前 KB 检索结果
- 当前图片、文件、引用消息
- 当前平台限制和运行时限制
- 当前插件扩展结果

这一阶段只负责“收集”，不直接拼 prompt。

### 2. Select

对收集到的信息做统一选择和裁剪。

这一阶段要回答的问题：

- 哪些信息和本轮请求有关
- 哪些信息应该给 LLM
- 哪些信息不应该给 LLM，只应该给执行器
- 哪些信息应该进入 system 层
- 哪些信息应该进入 context/history 层
- 哪些信息应该进入 tool/schema 层
- 哪些信息需要裁剪、摘要或延后处理

这一阶段是整个系统最关键的“决策点”。

### 3. Render

将经过选择后的结果渲染成最终请求。

这里不只是渲染字符串，还包括：

- system message
- history messages
- current user message
- tool schema
- image payload
- provider-specific payload

这一阶段应该尽量靠后，使 provider 相关细节不要提前污染通用 context 层。

### 4. Execute

将渲染后的结果交给：

- internal agent runner
- third-party runner
- provider source

这一阶段不再继续做大规模 prompt 拼装，只负责执行。

## 推荐分层

建议将最终给 LLM 的信息拆成几个明确语义层，而不是混在一个大 `system_prompt` 中：

- `identity`
  persona、角色设定、说话风格
- `policy`
  safety、平台规则、运行时规则
- `capability`
  skills、tools、computer use 能力
- `delegation`
  subagent 路由和 handoff 规则
- `context`
  会话历史、当前输入、附件说明、KB 结果
- `extension`
  插件和运行时动态补丁

这些层先独立存在，再在渲染阶段合并。

## 对当前代码的改造思路

### 第一阶段：收口

目标：

- 不改变现有外部行为
- 不破坏插件体系
- 不改变 `ProviderRequest` 对外语义

做法：

1. 引入统一 `PromptEngine` 或 `ContextBuilder`
2. 将当前 scattered 的 prompt 逻辑收口到一个固定流程中
3. 保留 `OnLLMRequestEvent` 时机
4. 最终仍然输出 `ProviderRequest`

这一阶段的重点不是重写，而是统一入口。

### 第二阶段：分层

目标：

- 不再直接向 `system_prompt` 随意追加字符串
- 让 persona、skills、tools、subagent、plugin 拥有清晰边界

做法：

1. 引入内部 `PromptSegment`
2. 为每个 segment 增加：
   - `source`
   - `layer`
   - `priority`
   - `content`
3. 统一由 renderer 合并为最终 `ProviderRequest`

这一阶段的重点是“先分层，再渲染”。

### 第三阶段：中间表示

目标：

- 让 prompt 构建不再依赖字符串 append
- 让 provider 差异下沉到 compile 阶段

做法：

1. 引入结构化中间表示，例如 `PromptIR`
2. 图片始终先保留为引用对象，不提前转 base64
3. provider-specific 编码延后到 compiler
4. 让 plugin 扩展中间表示，而不是直接 patch 最终 request

这一阶段的重点是“语义化建模”。

## 推荐的内部流程

推荐的新主链路：

1. `collect_context(event, conversation, runtime)`
2. `select_context(collected, request_intent)`
3. `build_segments(selected)`
4. `render_request(segments, provider_profile)`
5. `execute_request(rendered_request)`

## 推荐的数据模型

### CollectedContext

用于承载原始收集结果。

应包含：

- user input
- attachments
- history
- persona data
- skills data
- tools data
- subagent data
- kb data
- platform/runtime data
- plugin contributions

### SelectedContext

用于承载已经完成选择和裁剪的结果。

应包含：

- llm-visible content
- executor-only content
- deferred content
- filtered attachments
- filtered history

### PromptSegment

用于承载单一语义层的可渲染片段。

建议字段：

- `id`
- `layer`
- `source`
- `priority`
- `content`

### RenderedRequest

用于承载最终给 runner/provider 的结果。

建议字段：

- system messages
- history messages
- current user message
- tool schema
- image payload
- provider extras

## 为什么采用这种路线

### 1. 更适合 AstrBot 当前能力形态

AstrBot 已经同时承载：

- persona
- skills
- tools
- subagent
- plugin
- KB
- cron/background wake
- multimodal input

这些能力继续混在同一个 `system_prompt` 中，会越来越难维护。

### 2. 更容易定位冲突

有了 collect/select/render 三段式之后，可以更容易回答：

- 这段信息从哪里来
- 为什么被选中
- 为什么被送进 LLM
- 最后被渲染到了哪里

### 3. 更容易支持不同 provider

图片、tool schema、system message、特殊 payload 都应该在 render/compile 阶段处理，而不是在通用逻辑层提前耦合。

### 4. 更容易做并行收集

后续如果要优化性能，可以并行收集：

- persona
- skills
- KB
- quote message
- image analysis

但最终仍然统一选择和渲染。

## 当前不建议做的事

当前阶段不建议：

- 直接推倒重写整个 `ProviderRequest` 体系
- 让多个异步任务并发修改同一个 request 对象
- 用多个 LLM 子任务分别生成 persona/tool/subagent prompt 再拼接
- 过早引入复杂的多 Agent prompt planning

当前最优先的是先把流程收口。

## 当前结论

当前整体开发思路可以概括为一句话：

先把 AstrBot 的 prompt 构建从“边收集边追加字符串”，改造成“先收集信息、再选择信息、最后渲染给 LLM”。

进一步展开：

1. 统一收集上下文
2. 统一做本轮选择
3. 统一渲染最终请求
4. 最后再执行

这条路线既适合作为长期重构方向，也适合作为短期最小侵入改造的指导原则。
