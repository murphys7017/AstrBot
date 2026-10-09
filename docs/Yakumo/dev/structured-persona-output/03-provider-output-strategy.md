# 第二阶段：Provider 输出策略协商

## 目标

在 Canonical Persona Schema 已稳定、tool call 主路径已迁移之后，根据实际 provider 和模型能力选择最合适的结构化输出方式。

本阶段不是简单把 tool call 替换成原生 JSON Schema，而是建立“能力检测 → 策略选择 → 请求构造 → 格式解析”的适配层。

## 1. 输出方式分类

| 策略 | 保证范围 | 解析方式 |
| --- | --- | --- |
| `protocol_tool_call` | provider 产生指定工具调用及参数 | 读取 tool-call arguments |
| `protocol_native_json_schema` | provider 原生约束 JSON Schema | 读取 JSON 并做语义校验 |
| `protocol_json_mode` | 通常只保证合法 JSON object | JSON 解析后做完整 Schema 校验 |
| `prompt_only_json` | 仅依赖 Prompt，无法严格保证格式 | JSON 提取、修复、校验和有限重试 |
| XML | 文本符合约定 XML 结构 | XML parser + Schema 校验 |
| Markdown | 文本符合约定 Markdown grammar | Markdown parser + Schema 校验 |

原生 JSON Schema 和 JSON mode 必须分开：JSON mode 可能只保证语法正确，不保证字段完整、类型正确或枚举正确。

## 2. Provider 能力描述

能力检测至少要区分 provider、模型和具体部署配置：

```text
supports_protocol_tool_call
supports_native_json_schema
supports_json_mode
supports_prompt_only_structured_output
supports_xml_prompt_format
supports_markdown_prompt_format
```

不能只根据厂商名称判断。相同 provider 下不同模型或 API endpoint 可能有不同能力。

## 3. 策略选择

在本阶段完成前，tool call 继续作为默认基准。后续可以按照以下优先级选择：

```text
tool call
  → native JSON Schema
  → JSON mode
  → prompt-only JSON
  → XML / Markdown 等文本格式
```

最终默认优先级必须通过真实数据决定，重点比较结构成功率、完整响应延迟、首 token 延迟、token 消耗和重试率。

## 4. Prompt 适配

每种策略必须生成自己的 Prompt，不得把所有格式要求拼接到同一段通用 fallback：

- tool call：要求调用 `persona_expression`。
- native JSON Schema：说明字段语义，由 provider 的 Schema 约束结构。
- JSON mode：要求只输出 JSON object，并说明八维情绪和其他字段规则。
- prompt-only JSON：禁止额外解释、代码围栏和非 JSON 文本，并允许有限修复。
- XML：规定固定标签、嵌套结构和转义规则。
- Markdown：规定固定标题或 fenced block，不接受自由格式文本猜测。

如果选择 XML 或 Markdown，Prompt 不应继续注入“禁止 XML/Markdown”的 JSON fallback 指令。

## 5. 统一解析管线

```text
Provider 原始响应
  → 策略专用提取器
  → 语法解析
  → Canonical Schema 类型校验
  → 语义校验
  → 有限纠正或失败
  → PersonaExpressionResult
```

所有策略都必须验证：

- `turn_action` 枚举。
- `speech`、`actions`、`thought` 类型。
- 八个 `tendency` 维度的完整性和范围。
- `silent` 的空输出约束。
- `effect_calls` 的动态 effect Schema。

解析器只负责把 provider 格式转换成规范对象，不能为不同格式创造不同业务语义。

## 6. 当前代码基础和缺口

现有 [`output_contract.py`](../../../../astrbot/core/output_contract.py) 已有 `json_object`、`tool_call` 和预留的 `protocol_native_json`，但原生 JSON Schema 尚未形成完整的通用 provider 实现。

现有 [`structured_json.py`](../../../../astrbot/core/prompt/structured_json.py) 主要负责 JSON 提取、代码块清理和 JSON 修复；当前没有通用 XML 或 Markdown 结构化 parser。

因此本阶段需要先补齐策略描述、provider renderer、请求转换、能力判断和统一解析边界，再逐个接入 provider。

## 7. 实测指标

每种 provider/模型/策略至少记录：

- 首 token 延迟。
- 完整响应延迟及 p50/p95。
- token 消耗。
- 严格结构成功率。
- 字段缺失和类型错误率。
- 解析失败率。
- 纠正重试率。
- fallback 率。
- 八维情绪范围遵循率。
- `actions` 简单词遵循率。
- `effect_calls` 保真率。

未达到稳定阈值时继续使用 tool call，不因为接口支持就自动切换默认策略。

