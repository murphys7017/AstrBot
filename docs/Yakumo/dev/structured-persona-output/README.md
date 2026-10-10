# Persona 结构化输出计划

本文档集记录 Persona Expression 结构化输出协议、当前实现边界和后续阶段。当前代码事实以本目录的阶段记录、[Interaction 模块文档](../../modules/interaction.md)和[通用输出契约文档](../output-contract.md)为准。

## 当前状态

- Canonical Schema 和当前严格 `persona_expression` tool-call 主路径已完成迁移。
- Core 会把结果解析并校验为 `PersonaExpressionResult`。Persona 请求要求协议级 tool call，不接受自由文本或 prompt-only JSON 作为成功结果；不兼容候选在发起请求前被排除。
- Provider 页面提供结构化输出稳定性诊断：可编辑默认 Persona JSON 示例，选择 JSON、XML 或 semantic Markdown；JSON 可选 Prompt-only、Provider 原生 JSON mode 或 Provider 原生 JSON Schema，对单个对话模型最多请求 10 次并检查格式、字段结构和类型。DeepSeek、OpenAI Chat Completions、OpenAI Responses 与 Gemini 已接入原生 JSON 探测，OpenAI Chat Completions 与 Responses 另支持 JSON Schema，MiniMax Token Plan 当前仅 Prompt-only；结果含可复制的单次探测记录，但不会自动持久化，也不改变 Persona 主路径。
- Core 已把新字段贯穿 Personal 路由、即时/最终输出和 Interaction Result Contributor。Persona 改写的插件文本使用 `plugin_reply` purpose；插件可以从只读 `InteractionResultView` 读取结构化结果。
- Provider JSON/语义 XML/语义 Markdown Prompt 稳定性诊断及原生 JSON/JSON Schema 探测已接入；结果不持久化。Persona Response 可显式选择 tool call、JSON、XML 或 Markdown，生产响应会解析并校验为统一 Canonical Schema；原生 JSON Schema 仅按适配器能力启用。TTS 标签注入与清理、外部插件的独立迁移和真实平台组合验收仍未完成。

## 文档索引

- [总计划与代码现状](./00-overall-plan.md)
- [Canonical Schema 与字段规则](./01-contract-and-schema.md)
- [第一阶段：当前 tool-call 迁移记录](./02-tool-call-migration.md)
- [第二阶段：Provider 输出策略计划](./03-provider-output-strategy.md)
- [第三阶段：XML、Markdown 适配计划](./04-text-format-adapters.md)
- [第四阶段：TTS 与 speech 处理计划](./05-tts-speech-pipeline.md)
- [第五阶段：迁移、验证与发布清单](./06-migration-and-validation.md)

## Canonical Schema

```json
{
  "turn_action": "reply",
  "segments":[
    {
      "speech": "啊……怎么会这样？",
      "actions": ["lower_head"],
      "thought": "这件事出乎意料，让我感到遗憾",
      "tendency": {
        "Joy": 0,
        "Trust": 1,
        "Fear": 2,
        "Surprise": 8,
        "Sadness": 7,
        "Disgust": 0,
        "Anger": 1,
        "Anticipation": 0
      }
    }
  ],
  "effect_calls": []
}
```

顶层只允许三个必填字段：`turn_action`、`segments`、`effect_calls`。`turn_action` 是调用场景允许值中的单个字符串；每个 `segments` 元素包含 `speech`、`actions`、`thought` 和 `tendency`。文本平台使用按顺序拼接的 `segments[].speech`，TTS 使用原始分段并按顺序逐段合成；`effect_calls` 是按本轮已注册 effect schema 构造的插件调用数组。

## 阶段状态

| 阶段 | 状态 | 代码边界 |
| --- | --- | --- |
| 准备阶段：冻结 Canonical Schema | 已完成 | 三个顶层字段、segment 字段、情绪维度和值域已确定。 |
| 第一阶段：迁移当前 tool call | 已完成 | Schema、Prompt、解析、校验、Personal/Core 输出消费和结果贡献视图已使用新字段。 |
| 第二阶段 2A：JSON Prompt 稳定性诊断 | 已完成 | Provider 页面支持编辑 JSON 示例并对指定对话模型请求 10 次，结果只用于 Prompt 遵循诊断，不改变 Persona 主路径。 |
| 第二阶段 2B：Provider 能力矩阵与 JSON mode | 已完成首轮 | 支持 JSON/XML/Markdown 的 Prompt-only 探测，以及 DeepSeek、OpenAI Chat Completions、OpenAI Responses、Gemini 的原生 JSON 探测；OpenAI Chat Completions 和 Responses 另支持 JSON Schema，MiniMax Token Plan 当前仅 Prompt-only；结果可复制但不持久化，Persona Response 可显式选择格式。 |
| 第二阶段 2C：原生 JSON Schema / structured output | 首轮已接入 | OpenAI Chat Completions/Responses 的 JSON Schema 请求参数已接入 Persona Response；仍需按模型和 endpoint 做真实组合验收。 |
| 第三阶段：XML、Markdown parser | 首轮已完成 | 语义 XML/Markdown parser 已接入 Persona Response；不接受把 JSON 嵌入 XML/Markdown 的方式。 |
| 第四阶段：TTS 标签适配 | 分段消费已实施，标签未实施 | 文本平台使用拼接文本；TTS 按 `segments[].speech` 分段消费。本协议尚未实现标签 Prompt 注入和清理。 |
| 文档、插件迁移和运行验收 | 文档已按当前代码更新；外部集成验收待完成 | Core 破坏性移除旧字段；依赖方需分别迁移并进行真实平台验收。 |

详细字段约束、阶段验收和未完成事项见各阶段文档。新功能读取运行时结构化结果时，应通过 Interaction Result Contributor 的 `view`；不要解析 provider 私有响应或从可见文本反推状态。
