# 第二阶段：Provider 输出策略

**状态：未实施。** 当前 Persona 仍使用严格的协议级 persona_expression tool call。本文是后续计划，不代表 Persona 已接入 JSON 文本或 Provider 原生结构化输出。

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
| Persona JSON/XML/Markdown 输出 | 尚未接入 Persona 主路径；Persona 不以自由 JSON 文本作为成功 fallback。 |

当前 persona_expression 的严格 tool-call 路径是唯一已完成并启用的结构化输出方案。评估通用契约代码时，需要区分类型或兼容入口的存在与 Persona 实际选择的请求路径。

## 策略类别

后续 Provider 调研至少分别记录：

| 类别 | Provider 实际约束 | 响应形态 | 必须验证的事项 |
| --- | --- | --- | --- |
| 协议级 tool call | 要求调用指定的 persona_expression 虚拟工具。 | 工具调用参数对象。 | Provider 是否能强制指定工具、是否会混入普通文本、流式返回如何组装。 |
| JSON mode | Provider 要求响应为 JSON 文本；通常只约束语法或顶层对象。 | 普通文本通道中的 JSON。 | 必须由 Core 继续校验字段、类型、枚举、范围和动态 effect schema。 |
| 原生 JSON Schema / structured output | Provider 在生成时按给定 Schema 约束结构；具体保证取决于 API。 | Provider 定义的结构化或 JSON 响应。 | Schema 子集支持、动态 effect schema、严格模式保证及响应解析方式。 |
| Prompt-only JSON | 只在 Prompt 中要求 JSON，不由 Provider 协议强制。 | 普通文本。 | 格式失败率、有限修复策略；此能力目前不满足 Persona 的 fail-closed 主路径要求。 |

Provider 宣称支持 JSON，不等于支持原生 JSON Schema。JSON mode 也不能免除本地 Canonical Schema 校验。

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

- 六个顶层字段精确匹配。
- turn_action 符合本次请求允许的枚举。
- speech、actions、thought 类型有效。
- tendency 恰好包含八个规定维度，每项为 -10..10 的整数。
- effect_calls 符合本轮按事件筛选出的动态 effect schema 及必发规则。
- 允许 silent 时，speech、actions、effect_calls 为空。

## 验证与启用门槛

每个 Provider/模型/策略组合至少记录：

- 请求参数和 Schema 是否按预期发出。
- 原始响应类型及字段提取结果。
- Canonical Schema 成功率、解析失败率、纠正重试率。
- 完整响应延迟、首 token 延迟和 token 消耗。
- effect_calls 保真率。
- 模型版本、endpoint 和测试时间。

只有请求构造、解析、语义校验和端到端 Provider 验收都通过后，才考虑启用对应组合。单个组合通过，不代表该 Provider 的所有模型或 endpoint 均通过。

