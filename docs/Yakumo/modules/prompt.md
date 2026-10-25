# Prompt Module

`astrbot/core/prompt/*` 负责把运行时事实确定性地转换成模型请求。它是模型可见输入的唯一主链路，但不负责决定是否回复、执行工具、写入记忆或发送消息。

Prompt 自身使用的 safety、persona fallback、tool-call、live mode、sandbox 和 citation
文本由 `prompt.resources` 持有。Cron/background-task 唤醒提示仍属于 Agent 资源，不由
Prompt 模块反向读取 `astr_main_agent_resources`。

## 当前主链路

```text
Fact Sources
  -> Context Collectors
  -> PromptContextBuilder
  -> canonical / derived ContextPack
  -> CoreExecutionSpec（Core 目标）
  -> project_context_pack(target)
  -> PromptRenderProfile
  -> PromptLayoutInterface
  -> PromptTreeBuilder / PromptTree
  -> Provider Renderer
  -> RenderResult
  -> NativeExecutionAdapter / ProviderRequestAdapter
  -> Provider / Agent Runner
```

这是一条确定性数据管线。目标投影、布局和序列化都不调用 LLM，也不存在 LLM Selector。

## 功能边界

| 层 | 负责 | 不负责 |
|---|---|---|
| Collector | 从官方运行时、Interaction 和插件读取事实，输出命名明确的 `ContextSlot` | 拼最终 Prompt、做路由决策、写 memory、调用模型 |
| `PromptContextBuilder` | 合并事实、检测冲突、生成带版本的新 `ContextPack` 快照 | 按目标裁剪、决定物理消息布局 |
| Target Projection | 按 Core Planner、Persona、Core 做白名单、裁剪和诊断清理 | 生成指令、调用模型、修改规范 Pack |
| `PromptRenderProfile` | 提供目标局部的 system/request prompt、输出契约、输入后缀和精确隐藏项 | 声明共享事实、判断 Provider 能力、修改原始 Pack |
| Layout / Tree | 把逻辑 slot 放入 provider-neutral 语义树 | 选择业务事实、生成 Provider 私有 payload |
| Provider Renderer | 编译 system/messages/media/tool schema/output contract | 选择目标上下文、执行工具、决定业务路由 |
| Execution Preparation | 在目标渲染前把 Core 的 `ContextPack`、TaskSpec、执行历史、能力和执行身份组合成 provider-neutral `CoreExecutionSpec` | 保存 RenderResult、执行 Provider 协议、重做事实收集 |
| Native Adapter | 复用 `ProviderRequestAdapter` 把 `RenderResult` 写入官方 `ProviderRequest`，并带入已装配的实际工具 | 重新投影 Prompt、选择任务、替换官方 Hook |
| Provider / Runner | 落地协议并执行模型或工具循环 | 回头收集、投影或修补 Prompt 事实 |

## 收集与构建

### Collector

默认 Collector 覆盖 system、persona、input、session、policy、memory、official conversation history、插件显式 context、skills、tools、subagent、knowledge 和 Core Execution History。Execution History 是 optional、Core-only 的独立 ledger 投影，不属于可见 Conversation。Interaction 先建立不含普通插件扩展的基础事实 Pack，再基于它单次派生普通 Prompt Extension / Interaction Prompt Contributor Pack；Persona 阶段继续派生本轮待表达材料。

Collector 只返回事实：

- 同一次收集中，同名 slot 的不同值会触发 `PromptContextConflictError`。
- Core Collector 默认 `required`，异常会终止构建；只有显式 `failure_policy="optional"` 的 Collector 才记录诊断后继续。当前 `MemoryCollector` 是 optional。
- 插件 Prompt Extension Collector 采用插件隔离策略：异常或无效项会记录告警并跳过，不中断核心 Collector。
- `lifecycle="static"` 只表示同一 event、同一 config 和同一 `ProviderRequest` 对象内可复用，是 turn-static，不是跨回合或全局缓存。
- Collector 不应执行 memory 写入、路由判断或有副作用的工具调用。

### PromptContextBuilder

`PromptContextBuilder` 是规范构建和阶段派生的统一入口。`build(base=...)` 每次返回新快照，不修改输入 Pack，并维护：

- `context_version`
- `collection_scopes`
- `slot_count`
- Collector 与缓存诊断

跨阶段新增或替换事实必须经过 Builder。`ContextPack` 数据类型本身仍然可变，供收集和渲染内部使用；业务模块不得把直接 `add_slot()`、`slots.pop()` 或原地改值当作跨阶段 API。进入 `CoreExecutionSpec` 时，slots、meta、TaskSpec、执行历史和可序列化 capability 描述会被深拷贝，避免后续构建侧变更影响已经准备的执行事实；Native `ToolSet` 是唯一明确保留的实时执行句柄。

Interaction 使用两层 single-flight。`interaction_base` 收集 system、persona、input、session、memory、history、附件摘要和官方群聊上下文等可信控制面事实；Personal 与 Core Planner 的首个请求在这一层完成后即可渲染。需要完整插件上下文的调用才启动并复用唯一的 `interaction_plugin_context` task；Core 等待它，普通 Persona 即时计划按既有策略尽力使用或等待它。`progress` 与 `proactive` 等轻量 Persona 调用不等待完整 plugin context pack，但 Persona 表达构建仍可收集面向 `persona` 的 Prompt Extension；稳定扩展可进入 `extension.system`；动态 `extension.context` 必须逐条显式声明适用的 `context_views`，并在采集及 View 投影两处复核。插件执行能力不因此进入轻量 View。两层都来自同一基础事实源，业务模块不得重新查询历史、memory、输入或 session，也不得把插件扩展重新塞回 Planner。

媒体事实遵循同一边界：基础 `InputCollector` 只记录原始图片、引用图片、媒体内容块和文件记录，不调用图片转述或文件提取服务。非视觉 Personal、Planner 或 Core 在绑定实际 Provider 后，才通过 `PromptContextBuilder(base=...)` 派生本地媒体事实；视觉 Provider 直接消费原始图片。Provider 调用前的模态门同时检查上下文消息和额外内容块，避免只清理 `image_urls` 造成绕过。

## 目标投影

`project_context_pack(...)` 从 Pack 深拷贝出隔离视图。所有模型渲染都会先排除 `llm_exposure="never"`；显式目标还会同时执行固定代码规则和 slot 级 `meta.targets`。未传 `target` 的渲染默认使用 `Core` 投影，绝不绕过目标白名单。敏感事实仍应在 Collector 产生前最小化，不能把渲染过滤当作日志或进程内保密机制。

| 目标 | 当前可见范围 | 明确排除 |
|---|---|---|
| Core Planner | 当前输入、附件计数、时间、说话者、清理后的近期历史、topic/short-term memory | 完整人格、插件扩展、插件目录、Personal 计划、effect、实际工具 schema |
| Persona | 完整人格、官方历史、群聊上下文、memory/persona state、当前输入、待表达材料和 Core 结果；普通即时轮额外输出 `turn_action` | policy、knowledge、执行能力、Core 私有执行上下文 |
| Core | 官方历史、群聊上下文、当前输入和附件、system/policy、tools、skills、knowledge、subagent、插件执行上下文、`CoreTaskSpec`、有限 Core Execution History | 完整人格、persona state、待表达材料、effect 语义 |

Persona 的普通即时计划与 Core Planner 只共享事实来源，不共享模型 Prompt、决策或输出。投影中的历史长度、字段清理和诊断移除属于确定性安全边界，不是“让模型自己忽略”。Persona 的历史先保留最近连续片段，再从最多 300 个候选回合中选取与当前输入、引用文本、topic state 或 short-term memory 相关的较早锚点；锚点通过尾部历史摘录提供，两部分共同受既有 token 预算约束。

## Context View

`PromptTarget` 决定哪一种模型角色消费事实；`PromptContextView` 决定该角色在某一次调用需要看见哪一组事实。View 在 Target 投影之前应用，不能由 `PromptRenderProfile.hidden_slot_names` 代替；后者只适合 Profile 局部的精确兼容隐藏，不负责共享事实选择。

当前 Persona View：

- `turn_plan`：使用基础事实、官方历史、Persona 状态和 Persona 专属的 system 扩展，保留既有历史预算；不自动带入话题/短期摘要或完整 plugin context pack。构建时会把当前 View 允许的挂载类型和消费目标告知支持该钩子的 Collector，避免生成 Persona/Core 不会消费的扩展；最终 slot 白名单仍由 Renderer 强制执行。
- `olv_stream`：沿用同一基础事实边界，使用更紧的历史预算；不会自动带入话题/短期摘要，并且只请求该 View 允许的插件扩展挂载。
- `final_result`：保留既有来源和质量预算，`source_text` 仍由请求指令定义为权威结果。
- `progress`：使用基础事实，不等待完整 plugin context pack；允许稳定的 `system.global`、人格摘要、Persona 专属的 `extension.system`、本轮已截断的进度材料和已发送的单条确认，不继承旧目标局部 `system.base`、历史、memory、旧结果或媒体派生；`extension.context` 仅接收显式声明适用于 `progress` 的条目；本阶段的职责指令仍由 Profile 显式写入。
- `proactive`：使用基础事实，不等待完整 plugin context pack；允许稳定的 `system.global`、人格摘要、Persona 专属的 `extension.system`、已截断的 Observation 材料、最多两轮历史（最多约 1200 token）和有限的 topic/short-term/persona memory，不带当前用户输入或媒体派生；`extension.context` 仅接收显式声明适用于 `proactive` 的条目。

### Persona 上下文使用规则

Persona 的不同调用 View 会选择不同 slot；缺失的历史或 Memory 不得靠猜测补齐。各类上下文的语义边界如下：

- `conversation.history` 是官方 Conversation 的历史轮次，可用于回答当前明确指向的先前对话、消解“刚才/那个”等指代，并维持称呼、关系和语气。历史 assistant 文本能说明先前说过什么，不能单独证明其中外部事实仍然正确或某项操作已经成功。
- `memory.topic_state` 提供当前话题摘要与置信度；`memory.short_term` 提供短期摘要和未解决焦点；按配置检索到的 `memory.experiences`、`memory.long_term_memories` 提供相关经历或长期记录；`memory.persona_state` 提供熟悉度、信任、亲近感和表达偏好。它们是经过选择或摘要的连续性材料，只在相关时使用，不视为当前状态的权威证明。默认 `turn_plan` 和 `OLV_STREAM` View 只保留当前历史与 Persona 状态，不自动带入 topic/short-term 摘要、长期记忆或经历；模型只能使用本轮实际投影的 Memory slot。
- 当前系统指令与用户本轮请求决定行为边界；本轮输入、已确认的 Core/插件结果及明确失败事实决定当前答复的事实内容。最新用户更正优先于旧历史或 Memory。没有当前执行结果时，不得依据旧记录声称当前状态、数值、能力或操作结果。
- `conversation.pending_execution_continuity` 来自 Core Execution Ledger，表示某项 Core 工作被新消息打断；它不是 Conversation history、Memory，也不是成功结果。该字段只投影给 Core Router/Planner，Persona 不直接消费它；是否继续执行由独立 Router 决定。

Renderer 结果会记录 `context_view`、来源要求、实际 slot 和目标预算；Interaction 额外记录阶段、保留历史数和近似 token 数，供生产 trace 检查。

插件 Prompt Extension 的 `meta.targets` 只允许 `persona`、`core`。普通 extension 未声明目标时只属于 Core。Planner 不挂载插件扩展或插件目录；群聊近期上下文等官方事实若需进入控制面，必须由 AstrBot 内部明确标记的核心 Collector 以结构化上下文槽提供。插件自行设置 `official_context` 不会获得控制面权限。

## Render Profile

`PromptRenderProfile` 在目标投影后应用到一个新的目标视图，当前支持：

- `system_prompt`：提供目标自己的系统指令，并写入 Profile 专有的 `system.base`。Collector 从初始 `ProviderRequest.system_prompt` 收集的稳定全局指令始终位于独立的 `system.global`；Profile 不会隐式拼接或继承另一目标的 `system.base`。
- `request_prompt`：成为最终模型请求命令，不写入共享事实。
- `output_contract`：写入目标树的输出契约元数据。
- `input_text_suffix`：只追加到字符串类型的 `input.text`。
- `hidden_slot_names`：按完整 slot 名精确隐藏，不支持通配符，也不能替代目标投影的安全规则。

Profile 是“如何使用事实”的局部策略，不是 Collector。Core Planner 和 Persona 的指令与输出协议属于 Profile；当前消息、历史、待表达材料和插件信息仍必须由 Collector 提供。

### Persona 阶段指令

Persona 的 Prompt 分成两层，避免让一次调用同时解释彼此无关的阶段：

- `system_prompt` 只声明稳定职责、`persona_expression` 输出契约，以及当前事件有适用 effect 时使用的 `persona_effect_batch` schema 和不泄露内部材料的共同边界。
- `request_prompt` 只声明本次阶段任务：Personal 即时表达只允许按场景选择 `reply` 或 `silent`，不决定是否进入 Core；独立 Core Router 使用自己的结构化契约判断路由。结果表达以 `source_text` 为唯一事实来源；进度表达区分流式观察、单个工具运行中和单个工具完成。

Core Router 使用独立的 `CORE_ROUTER` PromptTarget：只接收当前输入与引用文本、有限近期历史、待续执行任务摘要、附件概况和时间，不接收能力摘要。Persona 提示、人格记忆、Personal 回复、插件目录及工具清单不会进入该目标；实际能力在路由后由 Core 执行阶段解析。

流式观察不是工具回执，因此不能宣称工具、来源、结果或整轮任务已完成。单个工具完成也只代表该步骤结束；只有 Core 最终结果才可表达为整轮完成。`input.visible_reply_material.progress_stage` 是这一语义的结构化事实，不能再依靠文案猜测。

## Layout、Tree 与 Renderer

`PromptTreeBuilder` 只接收目标视图和 `PromptLayoutInterface`。Layout 决定逻辑 group 的启用范围、节点路径和 slot 到树节点的落位；PromptTree 是 provider-neutral 中间表示。

`PromptLayoutInterface` 通过单一 `render_group(...)` 明确 Builder 的完整依赖，不再要求调用方隐式实现一组动态方法。默认实现仍处于过渡态：`DefaultPromptLayout.render_group(...)` 内部委托 `BasePromptRenderer` 中既有的 provider-neutral 落位方法；选中的 OpenAI/Anthropic/MiniMax Renderer 不参与目标数据选择。后续只需迁移默认实现，不再改变 Layout 公共契约。

Provider Renderer 只编译已经形成的树：

- `OpenAIPromptRenderer`
- `AnthropicPromptRenderer`
- `MiniMaxPromptRenderer`
- `DeepSeekPromptRenderer`
- `BasePromptRenderer`

它负责 system/messages、content blocks、媒体、工具 schema 和 `OutputContract` 的协议策略。Provider metadata 的 `prompt_renderer_family` 只选择序列化家族，不改变目标投影或 Layout。

### 模型可见字段与缓存布局（2026-10-25）

框架追踪信息保留在运行时、数据库和诊断中，进入模型的投影只携带任务语义：

- Core 当前任务不暴露 `platform_id`、`session_id` 和任意 `metadata`。稳定的 Persona/Core 协作指令保留在 system；任务意图、摘要、执行要求和建议能力位于历史之后、当前输入之前的临时 `context/core_execution` 消息。
- Core 执行历史位于 `context/core_execution_history`，不再随任务变化改写 system。Ledger 的模型投影省略 execution/task/turn/parent/executor ID 和内部 attempt；保留状态、任务、结果与错误。历史工具证据通过工具名称和参数关联返回值，持久化原始记录及当前工具协议中的调用 ID 不变。
- Runtime Observation 的模型投影省略 batch/observation/correlation ID，保留来源、时间和业务 payload；不递归删除业务 payload 中的同名字段。过期、取消、Gate 和去重仍使用原始 Observation。
- Extension 的插件身份仍用于过滤、分组和诊断；序列化统一使用 `extension` 标签，保留标题和内容。Session 请求包装和 MiniMax 的可见 metadata 不再携带会话、用户、群组、conversation ID 或 Python handler 路径。群聊消息内用于区分参与者的业务身份不在本批次删除。
- Memory 正文继续使用既有字段白名单，关系状态不向模型输出 `persona_id`；MiniMax 不再从 metadata 重新暴露 Memory 的 conversation/UMO。Memory 读取、更新以及原始 debug 数据不变。
- Persona 的轻量 View 使用同一份确定性人格投影，不再只依赖少数固定标题；无法识别的作者原文仍保留在投影中。动作请求复用 `persona.summary`，不另起一套人格摘要模型。
- Persona 历史保持近期连续回合作为前缀；相关的较早回合放进 `context/history_recall` 尾部消息，并明确标记为有间隔的历史摘录。历史不再仅凭报错关键词整条删除用户或助手文本；私有 reasoning/thinking/tool_calls 字段仍不进入对话历史。近期窗口本身滚动时仍可能改变前缀，本轮未引入跨回合缓存状态。
- `extension.context` 的 `context_views` 在采集和已有 Pack 投影两处都校验，避免复用 Pack 时把只属于其他 View 的动态扩展带入模型。
- Provider-neutral renderer 默认把 `context/runtime` 放在消息尾部；原生 JSON Schema 模式由请求协议承载 schema，避免把完整 schema 再复制进 system 文本。
- JSON 表达保留 schema，移除重复的完整 JSON 示例；XML/Markdown 仍保留各自语法示例。完整请求的文本估算补上原生输出 schema，`effective_request` 明确标记 `enforced=false`，不代表已经实施总请求硬预算，也不估算图像/音频 token。

AG99live 的配套修改在其源码仓库：Pre-Action 的角色原文和轴能力前置到 system，用户输入及状态留在 user；Independent Motion 的检索示例和最近动作移入当前请求尾部，固定规则与能力保留在 system；Performance Curve 不再接收 turn/message ID。动作仍逐 segment 请求，不合并等待整段回复，不改人格原文、动作语义、历史窗口、混合器或输出契约。

Passive 调度、远程模型护栏和 NeuroBrain 的 `step`/状态结构按用户要求暂缓。以上检查只能证明源码布局和字段边界；实际 DeepSeek 命中率、首包延迟、语音与 Live2D 质量仍需重启后的真实对话验证，不预先承诺命中比例。

## RenderResult 与 Apply

`RenderResult` 承载 `prompt_tree`、`system_prompt`、`messages`、`tool_schema`、输出契约、metadata 和可选 `request_prompt`。

完整 PromptTree 只保留在进程内 `prompt_tree` 字段供 Apply 使用，不复制到常规 metadata，也不写入 DEBUG 结构日志；日志只记录截断预览、slot 名和计数。

`ProviderRequestAdapter` 的规则是：

- 没有 `request_prompt`：最后一条 user message 拆成 `ProviderRequest.prompt`，此前消息进入 `contexts`，媒体转为 content parts。
- 存在 `request_prompt`：所有渲染消息保留为 `contexts`，Profile 命令成为 `ProviderRequest.prompt`。
- Adapter 会替换模型可见的 system、contexts、prompt、媒体和输出契约。
- Adapter 不修改 `func_tool`、provider、conversation、session 或 runner 配置。

`RenderResult.tool_schema` 与 `ProviderRequest.func_tool` 当前不是同一执行事实源。前者是渲染/诊断产物，后者仍由 Main Agent 的能力装配负责；在统一工具能力模型完成前，不得假定修改 `tool_schema` 就会注册可执行工具。

## 主链路接入

### Interaction

Interaction 每轮先建立基础 Pack；Personal 按 View 选择基础事实，只有需要插件富化的消费者才启动对应目标与 View 的 single-flight 任务。普通即时表达不等待完整插件 Pack，而是在基础事实之上收集允许的 Persona 扩展；表达 Prompt 会另行收集目标为 Persona 的 Prompt Extension，并由 View 白名单限制可见 mount。Core Router 与 Personal 并行工作，Router 只读取独立的有限上下文；路由到 Core 后，Planner 从基础 Pack 整理 `CoreTaskSpec`，随后 Main Agent 等待 Core 目标的插件扩展 task，再加入阶段性的任务规格、工具、知识和执行历史并渲染 Core 目标。

### 非 Interaction Core

普通 Main Agent 直接运行默认 Collector，不使用 Interaction 的 Planner/Persona Profile。`astr_main_agent` 装配运行时工具和 Runner，从完整 Pack 形成 `CoreExecutionSpec`，随后按 Native 目标渲染并由 Native Adapter 转为官方请求，不再手写另一套模型可见 Prompt。SubAgent Collector 仍属于这一 Native 收集路径；通用 Snapshot 不再设置独立 SubAgent 字段，但 Native Pack/ToolSet 暂时保留兼容信息。

### 官方钩子

官方 `on_llm_request` 是最终路由分支的低层请求钩子，执行顺序在该分支的统一 Prompt Apply 之后。非 Interaction 流程保持 Core 行为；Interaction turn 中，LLM 生命周期目标按配置、插件类 `interaction_runtime_target` 声明、Persona 默认值依次解析，只有最终为 `core` 的插件才进入 Core。插件拥有的 LLM Tool 独立按 `plugin_capability_targets.<plugin>.tools` 用户覆盖、工具 `tool_targets` 声明和 Core 默认值解析。该钩子适合修改最终请求参数或兼容旧插件，不是给 Planner 或 Persona 内部工具调用贡献共享事实的入口，也不保证覆盖这些轻量模型调用。

需要贡献模型可见事实的插件应使用 `PromptExtensionCollectorInterface`。插件开发接口见中英文 Prompt Extension 指南。

## 输出契约边界

```text
OutputContract
  -> CompiledOutputContract
  -> RenderResult / ProviderRequest
  -> provider protocol or controlled prompt-only fallback
  -> response parser
```

Core Planner 使用独立的 `core_execution_plan` 契约，且 Core Router 路由到 Core 后 Planner 必须返回 `execute`。Persona 默认要求 JSON 文本 + Prompt-only 约束，JSON/XML/Markdown parser 校验后均转换为同一 Canonical 结果；严格 `persona_expression` tool call 仅在配置显式选择时使用。每个结果包含 `turn_action` 和 `segments`；segment 含用户可见 speech、动作词数组 actions 和 Plutchik 八维情绪 tendency。当前事件存在已注册且适用的 Persona Effect 时，同一模型响应还通过独立 `persona_effect_batch` tool call 返回 `effect_calls`；无适用 effect 时不提供该工具。Core 将表达与 effect 聚合为内部 Persona 结果。`turn_action` 只按调用场景选择 `reply` 或 `silent`，Core 路由不由 Persona 输出决定。两个 Persona 输出通道都不是业务工具；业务 `FunctionTool` 只按 `plugin_capability_targets.<plugin>.tools` 的显式授权进入 Persona 或 Core。具体 Motion、Live2D 或设备协议属于插件，不属于 Prompt 主流程。Provider 页面 10 次格式测试仅提供稳定性参考，不自动保存结果或切换 Persona 设置。

Personal Policy 的 `personal_policy_decision` 同样是严格协议 tool call，不接受 prompt-only JSON 降级；不支持 `protocol_tool_call` 的 Provider 必须在渲染和模型调用前 fail-closed。轻量 Persona View 仍可保留当前事件允许的 Persona Effect 注册事实，因为 effect schema 会作为条件性独立 terminal tool 提供，而不是可自由带入的输入插件上下文；其 schema 成本应由完整请求大小诊断单独观测。

## 当前限制

- `DIAG request.prepare` 使用单调时钟记录人格解析、工具清单选择、准入筛选、
  Schema 快照构建和 waiting hook 耗时，包含 turn ID、目标与数量，不记录内容。
  waiting hook 日志另含 lifecycle ID；没有实际执行的缓存阶段不会重复计时。
  `DIAG provider.controls` 在 Anthropic/MiniMax 与 DeepSeek 的流式及非流式 SDK 调用前，
  按 SDK 的 extra_body 覆盖规则记录最终 thinking.type、budget_tokens、effort 和 max_tokens。
  未发送 thinking 时标为 provider_default；该日志证明请求参数，不证明服务端内部行为。
  两类日志均为 DEBUG，未输出 Prompt、思考正文、图片或凭据。

- 构建诊断通过 `DIAG prompt.timings` 和受控 Trace 的 `prompt.timings` 记录普通/插件 Collector
  耗时、缓存命中、产物数量，以及快照合并、目标投影、Profile、树构建、Provider 渲染/重编译和
  Request Apply 耗时。时间采用单调时钟，不记录上下文值；并发 Collector 耗时不能直接相加为总耗时。
  `ContextPack.meta.collector_timings`、`build_timings`、`RenderResult.metadata.render_timings`
  和 `PromptApplyResult.duration_ms` 可用于关联各阶段。成功 Apply 的耗时也写入 RenderResult metadata。
- 必需采集器默认传播失败；显式 optional 失败写入 `collector_failures`，静态失败结果不缓存。
  工具能力解析失败按必需失败处理；知识检索按显式 optional 处理。其他混合采集器现有的局部
  降级策略仍保留，不应把它们当成已经全量迁移到统一策略。
- `llm_exposure="redacted"` 没有字段级规则时，目标投影隐藏整个槽值，并移除可能含原文的
  metadata；ContextPack Trace 同样隐藏该槽。结构化槽可能因此不被渲染。需要部分保留的内容应
  在 Collector 中完成选择性脱敏后标记为 `allowed`；`never` 仍表示不进入模型。

- Provider renderer family、输出契约能力和工具能力还没有统一成一个 capability 声明。
- `ContextCatalog` 的 required/lifecycle/redaction 等字段多数仍是描述和告警，不是完整运行时强约束。
- `ContextPack` 仍是可变数据类型，跨阶段不可变性依赖 Builder 使用约定和测试。
- `DefaultPromptLayout` 内部仍复用 Base Renderer 的 provider-neutral 落位实现，但 Builder 依赖的 `render_group(...)` 契约已经稳定。
- `tool_schema` 与实际 `func_tool` 尚未统一事实源。
- 上下文预算、Collector 并发和更细的敏感字段脱敏需要在上述边界稳定后继续处理。
- Collector 的官方兼容签名仍直接接收 `AstrMessageEvent`、插件 `Context` 和
  `ProviderRequest`；这使 Prompt 可以统一事实，却还不能独立于 AstrBot runtime contracts。
- Provider 的协议 tool adapter 已迁入 `provider.output_contract_tools`，不再反向导入
  Prompt。该 adapter 仍使用 Native `ToolSet`；完整中性 capability contract 尚未形成。

后续处理顺序见 `docs/Yakumo/prompt-development-plan.md`。
