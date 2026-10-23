# Output Contract

记录当前结构化输出约束的统一链路。这里描述的是跨 prompt、render、request、provider 和 parser 的公共机制，不属于 interaction decision 私有实现，也不属于某个 renderer 的私有规则。

## 目标

输出约束不再只依赖“请输出 JSON”这类软 prompt 文本，而是作为一等数据贯穿完整调用链：

`prompt 声明 -> render 编译 -> request 投影 -> provider 落地 -> response 解析`

当前第一目标是让高约束场景脱离“手写自由文本 JSON prompt”。其中：

- 普通 Interaction 的 Personal Response Plan 默认使用 JSON 文本 + Prompt-only 表达，并要求 `turn_action`；只有显式配置 `tool_call` 时才使用严格 `persona_expression`
- 当前事件存在已注册且适用的 Persona Effect 时，同一模型响应还要求独立 terminal `persona_effect_batch` tool-call
- Persona 表达格式可以配置为 JSON、XML、Markdown 或严格 `persona_expression` Tool Call；所有文本格式都进入同一 Canonical Schema，effect 数据不放进表达 payload

## 核心类型

### `OutputContract`

文件：

- `astrbot/core/output_contract.py`

字段：

- `mode`: `text | json_object | tool_call`
- `strict`: 是否要求强约束
- `schema`: JSON object schema 或 tool call 参数 schema
- `preferred_tool_name`: 首选工具名
- `allow_text_fallback`: parser 是否允许文本 fallback

`OutputContract` 表达“希望得到什么输出”，不表达 provider 应该如何组织私有 payload。

### `CompiledOutputContract`

文件：

- `astrbot/core/output_contract.py`

字段：

- `contract`
- `strategy`: `prompt_only | protocol_tool_call | protocol_native_json`
- `degraded`
- `degrade_reason`
- `tool_name`
- `tool_schema`
- `fallback_prompt_text`

`CompiledOutputContract` 表达 renderer 对契约的编译结果。provider 应优先消费这个 compiled binding，而不是重新从裸 `OutputContract` 推导 schema。

## 数据流

1. 目标调用通过 `PromptRenderProfile.output_contract` 声明契约；Engine 在目标副本的 meta 中承载它。无 Profile 的底层调用仍可从 ContextPack meta 读取兼容声明。
2. `BasePromptRenderer._compile_output_contract(...)` 读取声明并生成 `CompiledOutputContract`。
3. 派生 renderer 通过 `resolve_output_contract_strategy(...)` 声明协议级能力。
4. `RenderResult` 同时携带 `output_contract` 和 `compiled_output_contract`。
5. `ProviderRequestAdapter` 把两者投影到 `ProviderRequest`。
6. provider 调用优先消费 `compiled_output_contract`，再兼容旧入口的裸 `output_contract`。
7. response parser 根据契约决定是否允许文本 fallback。

## 策略边界

### `protocol_tool_call`

当前 strict 结构化输出的主实现。

- OpenAI-compatible provider 使用 function tool / required tool choice。
- Anthropic-compatible provider 使用 tool schema / required tool choice。
- renderer 只产出 tool name 和 tool schema，不直接构造 provider 私有 payload。

### `protocol_native_json`

保留策略名，当前还不是通用实现目标。后续如果某个 provider 有稳定原生 JSON schema 通道，可以在不改变 `OutputContract` 的前提下补 provider-specific 落地。

### `prompt_only`

这里需要区分两种情况：

1. `tool_call -> prompt_only`

- 这是协议级能力不可用时的受控降级。
- `RenderResult.metadata` 中应体现 `output_contract_degraded=True`。

2. `json_object -> prompt_only`

- 这是把 JSON 要求写入 Prompt 的落地方式，不应误读为 Provider 原生 JSON mode 或 JSON Schema 约束。
- Persona Response 默认就是 JSON 文本 + `prompt_only`，属于正常配置，不是从 Tool Call 降级。可按 Provider 实测显式选择原生 JSON 约束、XML、Markdown 或严格 Tool Call。

因此，`prompt_only` 本身只表示“最终通过 prompt 文本约束落地”，不自动等价于“失败降级”。

- fallback 文本由 `build_output_contract_fallback_prompt(...)` 统一生成。
- 只有 `tool_call` strict 契约降到 `prompt_only` 时，才应标记 `degraded=True`。
- 通用 renderer/provider 的 JSON mode 与 JSON Schema 能力按 Provider adapter 和显式配置判断；Persona 的 Provider 页面稳定性测试只提供诊断，不自动切换生产设置。`prompt_only` 不代表 Provider 原生执行 JSON Schema 约束。
- OpenAI-compatible 与 Anthropic source 中将没有 compiled binding 的 strict `json_object` 转换为 tool-call schema，是旧兼容入口，不等同于原生 JSON mode。
- 当高约束业务选择 `tool_call` 契约时，默认优先要求协议级 tool-call；若业务明确允许受控降级，parser 必须仍按固定 schema 解析 prompt-only JSON，不能接受自由文本。
- Persona 默认 JSON + Prompt-only 路径不要求 `protocol_tool_call`；只有显式配置 `expression_output_format="tool_call"` 时，`persona_expression` 才要求协议级 Tool Call。适用 Persona Effect 的 `persona_effect_batch` 始终是独立的严格 Tool Call 通道。

## Renderer 职责

renderer 负责把声明编译成策略：

- `BasePromptRenderer`: 对非 text 输出契约默认编译为 `prompt_only`；仅 `strict tool_call` 降到 `prompt_only` 时记为 `degraded`。
- `OpenAIPromptRenderer`: 对 `tool_call` 编译为 `protocol_tool_call`，保持 OpenAI-compatible message/tool schema 形态。
- `AnthropicPromptRenderer`: 对 `tool_call` 编译为 `protocol_tool_call`，保持 Anthropic content block/tool schema 形态。
- `MiniMaxPromptRenderer`: 根据 provider 是否支持强制 tool choice 决定策略；MiniMax
  Token Plan 不支持这一能力，因此严格 `tool_call` 编译为 `prompt_only`。只有明确声明
  支持该能力的其他 MiniMax renderer provider 才使用 `protocol_tool_call`。

renderer 不负责：

- 直接设置 provider 私有 payload。
- 决定 parser 是否接受文本 fallback。
- 在业务 prompt 中手写大段结构化输出约束。

## Provider 职责

provider 负责把 compiled binding 落到自身协议：

- 优先使用 `CompiledOutputContract.tool_name` 和 `tool_schema` 构造单工具集。
- strict tool call 场景必须要求 tool choice。
- 不支持协议级策略时必须显式失败或受控降级，不能静默忽略。
- 裸 `OutputContract` 兼容路径只用于旧调用点迁移，后续应逐步删除。

当前已真实处理 `protocol_tool_call` 的基础 provider：

- `ProviderOpenAIOfficial` 及其 OpenAI-compatible 子类
- `ProviderAnthropic` 及支持强制 tool choice 的 Anthropic-compatible 子类

MiniMax Token Plan 的 Anthropic-compatible API 支持普通工具调用，但不支持
`required` / `any` 或指定工具形式的强制 `tool_choice`。因此其严格 tool-call
契约会编译为 `prompt_only`：这可以服务于明确允许 JSON 降级的通用场景，但不会成为
Persona 的候选。普通业务 FunctionTool 仍按 MiniMax 原生 `auto` 工具调用运行。

Gemini、VolcEngine Ark 等 provider 当前没有 provider-specific renderer。strict contract 到达这些 provider 时，应按场景策略显式失败或受控降级。

## Core Router and Personal Response

普通 Interaction 由独立 Core Router 判断是否进入 Core；Router 与 Personal 表达并行，Core 等待路由结果。Router 使用独立、限额的 `CORE_ROUTER` PromptTarget，不接收 Persona 提示或人格记忆。Persona 默认以 JSON 文本 + Prompt-only 约束表达自然语言和 Personal 回复选择，解析结果经 Canonical Schema 校验；用户可显式选择 JSON 原生约束、XML、Markdown 或严格 `persona_expression` Tool Call。当前事件存在已注册且适用的 Persona Effect 时，同一模型响应还通过独立的 `persona_effect_batch` Tool Call 承载 effect。

运行规则：

- `turn_action=reply`：Personal 发出本轮可见回复；它不决定是否进入 Core。
- `turn_action=silent`：仅允许合格的群聊候选，且表达的 `segments` 必须为空；如果启用了 effect 通道，其 `effect_calls` 也必须为空。
- Core Router 选择进入 Core 后，Core Planner 生成 `execute + CoreTaskSpec`；Persona payload 不包含路由决定或任务规格。
- 无适用 effect 时不提供 `persona_effect_batch`；Core 聚合的结果仍包含空 `effect_calls` 数组。
- 适用 effect 时，同一响应必须恰好返回一次 `persona_effect_batch`；正常生成不单独请求 effect，已解析的必发 effect 校验失败时沿用现有 effect batch 校正请求。
- 结构化输出不携带 Planner 推理、Core task spec 或用户不可见的控制理由。

## Persona Visible Reply

persona visible-reply 是当前主要高约束消费者。

当前默认契约：

- `expression_output_format="json"`
- `expression_output_mode="prompt_only"`
- Provider 返回的表达文本必须解析并通过 Canonical Schema 校验；普通自由文本不算成功
- 严格表达 `tool_call` 是可显式选择的配置，不是默认值
- `persona_expression` Schema 固定为 `turn_action`、`segments`；每个 `segments` 元素包含 `speech`、`actions` 和 `tendency`
- 有适用 effect 时，独立 `persona_effect_batch` Schema 只包含 `effect_calls`；两路结果在同一响应后聚合

字段含义：

- `turn_action` 是 Personal 回复选择，普通表达为 `reply`；允许静默的群聊候选还可选择 `silent`。是否进入 Core 由独立 Router 判断。
- `segments[].speech` 按顺序拼接为文本平台使用的整合文本；TTS 消费保留每个分段并按顺序逐段合成。
- `segments[].actions` 是简单动作意图数组，由后续动作模型解释，不带参数。Schema 只校验数组元素为非空字符串；简单动作词、不带参数的限制由 Persona Prompt 表达。
- `segments[].tendency` 表示角色当前的 Plutchik 八维情绪强度：`Joy`、`Trust`、`Fear`、`Surprise`、`Sadness`、`Disgust`、`Anger`、`Anticipation`；规范化后每项为 `0..10` 整数。模型应直接输出该范围；Core 对整数越界值执行边界裁剪，负数按 `0`、大于 `10` 按 `10` 处理，其他结构或类型错误仍拒绝。该字段由 AstrBot Core 拥有并校验，插件通过只读 `InteractionResultView` 读取；NeuroBrain 等外部状态引擎应在宿主适配层转换它，不反向修改该字段。
- `effect_calls` 保持现有插件 effect 执行协议，与 `actions` 分开。
- Core 不再接受 `spoken_reply` 或 `speech_cues`；TTS 标签注入与清理留待后续适配器阶段。

运行规则：

- 默认 JSON + Prompt-only、XML 和 Markdown 表达由对应文本解析器恢复为 Canonical 结果；显式 Tool Call 表达由 `persona_expression` 返回。适用 effect 始终由同一响应中的独立 `persona_effect_batch` 返回。
- Provider 选择会在模型请求前验证所选表达格式和本轮所需的 effect Tool Call 能力；不兼容的候选会被筛除，若不存在兼容候选则以 `unsupported_output_contract` 失败。Provider 稳定性测试结果不自动作为生产配置。
- 自由文本不算成功。缺少表达通道时，只有本轮同时启用 effect 通道才会尝试一次隔离表达补全，否则结果失败。缺少本轮要求的 effect 调用时会尝试一次 effect-only 补全；两个通道都缺失时依次补全。补全失败后结果失败，重复调用或无效的 batch 顶层结构直接拒绝。
- `effect_calls` 是内部聚合结果中的固定字段；无适用 effect 时模型响应省略 effect tool call，聚合结果为空数组。
- 具体 effect 的 `arguments` 由注册的 effect schema 决定；注册表先按当前事件执行 `event_filter`，不适用的 effect 不进入本轮 effect tool schema。

## 观测字段

`RenderResult.metadata` 需要保留：

- `output_contract_requested`
- `output_contract_strategy`
- `output_contract_degraded`
- `output_contract_degrade_reason`

主请求日志和 render/apply 摘要应能看到 `output_contract` 与 `compiled_output_contract`，用于判断当前场景到底是协议级支持、受控降级，还是未声明输出契约。

## 后续收口

- 逐步删除 provider 中裸 `OutputContract` 重建 schema 的旧入口。
- 给 Gemini / VolcEngine Ark 等 provider 增加明确 renderer family 或 provider-specific renderer。
- 将更多结构化提取、修复器、prompt-json 分析场景迁移到同一契约链路。
- 继续减少业务模块手写“只输出 JSON”文本，统一走 fallback compiler。
