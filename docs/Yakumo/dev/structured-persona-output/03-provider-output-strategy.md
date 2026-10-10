# 第二阶段：Provider 输出策略

**状态：2A/2B 已完成首轮实现。** Provider 页面提供不持久化的 10 次稳定性诊断；Persona Response 已可按配置选择 `tool_call`、JSON、XML 或 Markdown，并把响应解析回 Canonical Schema。默认仍是严格的协议级 `persona_expression` tool call；原生 JSON/JSON Schema 只在选择 JSON 且适配器声明支持时发送。

## 目标

按具体 Provider、模型和 API endpoint 评估结构化输出方式，让每种 Persona 请求选择已验证且合适的传输路径。Provider 可以返回 JSON 文本，也可以提供原生结构化输出约束；两者能力不同，不能只根据“支持 JSON”判断。

无论请求如何传输，成功结果都必须解析成同一个 PersonaExpressionResult，并通过现有 Canonical Schema 与语义校验。不能因为某个 Provider 支持一种输出格式，就隐式改变全局默认路径。

## 当前代码基线

| 能力或类型 | 当前实现 |
| --- | --- |
| Persona 请求契约 | mode=tool_call、strict=true、preferred_tool_name=persona_expression、allow_text_fallback=false。 |
| Persona Provider 选择 | 只接受可使用协议级 tool call 的候选；不兼容候选在请求前筛除。 |
| 通用 OutputContract.mode | 有 text、json_object、tool_call。 |
| 通用编译策略类型 | 有 prompt_only、protocol_tool_call、protocol_native_json；protocol_native_json 目前是策略类型预留，不代表已经有通用 JSON Schema renderer/provider 路径。 |
| 通用 JSON object Prompt | json_object 可生成 JSON-only Prompt 文本；这本身不表示 Provider 原生执行 JSON Schema 约束。 |
| Provider 页面格式稳定性测试 | 已提供手动诊断入口：用户可编辑 JSON 示例，选择 JSON、XML 或 semantic Markdown；JSON 可选 Prompt-only、Provider 原生 JSON mode 或 Provider 原生 JSON Schema（按适配器能力启用），并检查格式语法、根对象、字段集合和示例推断出的类型；不修改配置，也不改变 Persona 主路径。 |
| Persona Response 生产输出 | 在 Interaction Middleware / Persona Response 中选择输出格式和约束模式；JSON、XML、Markdown 均经过专用 parser 与 Canonical Schema 校验，失败即按现有 provider fallback/错误链路处理，不把一种格式隐式当作另一种格式。 |

`tool_call` 仍是默认且最严格的路径；其他格式是显式配置的生产路径，不会从诊断结果自动切换。用户应先在 Provider 页面测试，再在 Persona Response 选择相同格式和（仅 JSON 可用的）原生约束模式。

## 策略类别

后续 Provider 调研至少分别记录：

| 类别 | Provider 实际约束 | 响应形态 | 必须验证的事项 |
| --- | --- | --- | --- |
| 协议级 tool call | 要求调用指定的 persona_expression 虚拟工具。 | 工具调用参数对象。 | Provider 是否能强制指定工具、是否会混入普通文本、流式返回如何组装。 |
| JSON mode | Provider 要求响应为 JSON 文本；通常只约束语法或顶层对象。 | 普通文本通道中的 JSON。 | 必须由 Core 继续校验字段、类型、枚举、范围和动态 effect schema。 |
| 原生 JSON Schema / structured output | Provider 在生成时按给定 Schema 约束结构；具体保证取决于 API。 | Provider 定义的结构化或 JSON 响应。 | Schema 子集支持、动态 effect schema、严格模式保证及响应解析方式。 |
| Prompt-only JSON | 只在 Prompt 中要求 JSON，不由 Provider 协议强制。 | 普通文本。 | 格式失败率、有限修复策略；此能力目前不满足 Persona 的 fail-closed 主路径要求。 |

Provider 宣称支持 JSON，不等于支持原生 JSON Schema。JSON mode 也不能免除本地 Canonical Schema 校验。

Provider 页面中的稳定性测试用于快速观察模型能否遵循可编辑示例结构。`Prompt-only` 只通过 Prompt 要求输出；JSON 的 `Provider-native JSON mode` 对 OpenAI Chat Completions、OpenAI Responses 和 DeepSeek 发送其适配器支持的原生 JSON 参数，对 Gemini 发送 `response_mime_type="application/json"`；OpenAI Chat Completions 与 Responses 另外支持原生 JSON Schema 探测。MiniMax Token Plan 当前仅声明 Prompt-only，不声明原生 JSON/JSON Schema。两种适配器都可能连接不支持相应参数的自定义 endpoint，模型也可能有单独限制。原生模式第一次请求出错后会停止后续探测；只有状态码和错误内容明确指向 JSON mode 参数不受支持时才标记 endpoint/model 不支持，其他错误报告为未判定的请求失败。诊断请求使用单次底层调用，不经过适配器正常对话的恢复循环。

JSON mode 只约束 JSON 输出语法，不会将可编辑示例自动转换成原生 JSON Schema；JSON、XML 和 Markdown 模式都由本地校验器检查格式、根对象、字段集合和示例推断出的 JSON 类型。原生 JSON Schema 探测会将非空对象字段设为 required，并对空数组保留未知 item schema；Provider 是否接受该 Schema 仍需按 endpoint/model 实测。校验会递归比较对象字段；非空数组使用示例第一个元素作为元素模板，空数组只验证数组类型。XML/Markdown 使用语义字段节点或标题解析回统一对象，两者都不嵌入 JSON；同一 parser 约束用于 Persona Response 生产解析。诊断通过只说明该次模型/endpoint 的样本表现，生产响应仍执行完整 Canonical Schema 和 effect 校验。

原生 JSON mode 测试通过专用 Provider 诊断入口以单次底层请求执行每轮测试，避免适配器恢复循环放大请求次数；正常对话继续使用现有恢复策略。完整 Provider/模型/endpoint 能力矩阵、模型响应性能比较和 Persona 主路径策略选择仍属于 2B 后续工作。

每次诊断结果附带可复制的 JSON 探测记录：Provider ID 和 adapter type、模型 ID、endpoint origin 主机及其指纹、UTC 测试时间、平均/中位延迟、逐次校验结果，以及原生 JSON mode 能力判定。endpoint 路径、原始 URL、凭据和查询参数不会放入记录；默认 endpoint 以未显式配置标记。能力判定区分未测试、适配器不支持、endpoint 明确拒绝、探测请求失败但未判定，以及 endpoint 接受请求。`request_accepted` 只证明该次请求成功，不证明十次结构检查全部通过，也不证明其他模型或 endpoint 具有同等能力。

探测记录目前由用户手动复制，不会自动写入数据库或形成跨 Provider 的持久矩阵。Prompt-only 结果的原生 JSON mode 能力始终标为未测试。持久化矩阵、批量对比及其更新/过期规则仍需另行设计。

## 当前适配器能力快照

该表只描述当前代码允许发起的诊断请求，不代表所有模型或 endpoint 实际接受请求，也不代表 Persona 生产路径已切换。

| 适配器 | Prompt-only JSON/XML/Markdown | Provider-native JSON | Provider-native JSON Schema | 备注 |
| --- | --- | --- | --- | --- |
| `deepseek_chat_completion` | 支持 | 支持 JSON | 不支持 | 原生 JSON 使用 `response_format={"type":"json_object"}`；严格 Persona tool call 仍受 Beta endpoint 且关闭 thinking 限制。 |
| `minimax_token_plan` | 支持 | 不支持 | 不支持 | Anthropic-compatible Token Plan 适配器当前不构造原生 JSON 参数；Persona tool call 仍按 M3/M3.1 模型限制。 |
| `openai_chat_completion` | 支持 | 支持 JSON | 支持 | Chat Completions 使用 `response_format`；诊断请求单次执行，不进入正常恢复循环。 |
| `openai_responses` | 支持 | 支持 JSON | 支持 | Responses API 使用 `text.format`；同时消费新旧 JSON 诊断入口参数。 |
| `googlegenai_chat_completion` | 支持 | 支持 JSON | 不支持 | 使用 `response_mime_type="application/json"`。 |

## 能力矩阵与选择

能力应按 Provider、模型、API endpoint 和必要的部署选项记录，至少覆盖：

- 是否支持强制协议级 tool call，以及能否指定 persona_expression。
- 是否支持 JSON mode。
- 是否支持原生 JSON Schema 或等价的严格 structured output。
- 实际支持的 Schema 关键字和动态 schema 限制。
- 流式与非流式调用的响应形态。
- 请求构造和响应解析所需的 provider-specific 适配。

不预先规定 tool call、JSON mode 与原生 JSON Schema 的全局优先级。由实测比较每个候选路径的完整响应时间、首 token 延迟、token 消耗、解析成功率、重试率和 effect_calls 保真率，再决定是否为特定 Provider/模型启用。

在新路径通过验证并显式启用前，现有 Persona tool-call 行为保持不变。若请求所选策略不可用或响应不合格，应报告可诊断失败；不能把失败悄悄转换成自由文本回复。

## Prompt、请求与解析边界

每种实际启用的策略都需要对应的请求构造：

- tool call：要求调用 persona_expression，沿用当前动态参数 Schema。
- JSON mode：要求 Provider 返回 JSON 文本，并说明业务字段含义；响应仍经本地完整校验。
- 原生 JSON Schema：将兼容的 Canonical Schema 投影给 Provider，同时验证 Provider 生成的真实 Schema 与响应符合约束。
- Prompt-only JSON：只能作为经过显式审批的实验路径；必须有固定提取和校验规则，不能将普通自然语言猜成结构化结果。

策略专属解析器只负责提取 Provider 响应，不负责放宽业务语义。所有策略最终都必须检查：

- 三个顶层字段精确匹配：`turn_action`、`segments`、`effect_calls`。
- 每个 `segments` 元素都包含 `speech`、`actions`、`thought` 和 `tendency`。
- turn_action 符合本次请求允许的枚举。
- speech、actions、thought 类型有效。
- tendency 恰好包含八个规定维度，每项为 -10..10 的整数。
- effect_calls 符合本轮按事件筛选出的动态 effect schema 及必发规则。
- 允许 silent 时，segments、effect_calls 为空。

当前 Core 对必发 effect 执行失败或一次纠正；解析器会记录并跳过无效的可选 effect，不承诺任何格式下的无效可选调用都会令整条 Persona 响应失败。

## 验证与启用门槛

每个 Provider/模型/策略组合至少记录：

- 请求参数和 Schema 是否按预期发出。
- 原始响应类型及字段提取结果。
- Canonical Schema 成功率、解析失败率、纠正重试率。
- 完整响应延迟、首 token 延迟和 token 消耗。
- effect_calls 保真率。
- 模型版本、endpoint 和测试时间。

只有请求构造、解析、语义校验和端到端 Provider 验收都通过后，才考虑启用对应组合。单个组合通过，不代表该 Provider 的所有模型或 endpoint 均通过。
