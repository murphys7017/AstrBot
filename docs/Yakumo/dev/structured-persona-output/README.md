# Persona 结构化输出计划

本文档集记录 Persona Expression 结构化输出协议、当前实现边界和后续阶段。当前代码事实以本目录的阶段记录、[Interaction 模块文档](../../modules/interaction.md)和[通用输出契约文档](../output-contract.md)为准。

## 当前状态

- 内部 Canonical Result 和表达通道 `persona_expression` 已完成首轮迁移；表达/effect 双通道运行时已实施，仍待真实 Provider 组合验收。
- Core 分别解析表达和 effect 通道，再聚合并校验为 `PersonaExpressionResult`。`persona_expression` 承载表达；当前事件有已注册且适用的 effect 时，同一模型响应还要求独立 `persona_effect_batch` tool call。无适用 effect 时不提供 effect 工具。若首轮漏掉任一通道，Core 会以隔离请求只补缺失通道；若两路都缺失，则依次补表达和 effect。已解析的必发 effect 校验失败时，也会额外请求模型修复 effect batch。
- Provider 页面提供结构化输出稳定性诊断：可编辑默认 Persona JSON 示例，选择 JSON、XML 或 semantic Markdown；JSON 可选 Prompt-only、Provider 原生 JSON mode 或 Provider 原生 JSON Schema，对单个对话模型最多请求 10 次并检查格式、字段结构和类型。DeepSeek、OpenAI Chat Completions、OpenAI Responses 与 Gemini 已接入原生 JSON 探测，OpenAI Chat Completions 与 Responses 另支持 JSON Schema，MiniMax Token Plan 当前仅 Prompt-only；结果含可复制的单次探测记录，但不会自动持久化，也不改变 Persona 主路径。
- Core 已把新字段贯穿 Personal 路由、即时/最终输出和 Interaction Result Contributor。Persona 改写的插件文本使用 `plugin_reply` purpose；插件可以从只读 `InteractionResultView` 读取结构化结果。
- Provider JSON/语义 XML/语义 Markdown Prompt 稳定性诊断及原生 JSON/JSON Schema 探测已接入；结果不持久化。Persona Response 的格式选项只控制表达通道；适用 effect 仍通过同一响应中的独立 terminal tool call 返回。TTS 标签注入与清理、外部插件的独立迁移和真实 Provider 组合验收仍未完成。

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

上例是内部聚合结果，不是单个 Provider payload。表达通道只包含 `turn_action`、`segments`；适用 effect 使用参数仅含 `effect_calls` 的 `persona_effect_batch` 独立 tool call，并与表达在同一模型响应中返回。无适用 effect 时不提供该工具，内部聚合结果以空数组表示。`turn_action` 是调用场景允许值中的单个字符串；每个 `segments` 元素包含 `speech`、`actions`、`thought` 和 `tendency`。文本平台使用按顺序拼接的 `segments[].speech`，TTS 使用原始分段并按顺序逐段合成。

## 阶段状态

| 阶段 | 状态 | 代码边界 |
| --- | --- | --- |
| 准备阶段：冻结 Canonical Schema | 已完成 | 内部聚合字段、表达和 effect 分通道、segment 字段、情绪维度和值域已确定。 |
| 第一阶段：迁移当前 tool call | 双通道已实施，待真实 Provider 验收 | 首轮表达使用 `persona_expression`；适用插件 effect 使用同一响应中的 `persona_effect_batch`。缺失通道时只补缺失通道一次，Core 聚合后仍沿用现有下游接口。 |
| 第二阶段 2A：JSON Prompt 稳定性诊断 | 已完成 | Provider 页面支持编辑 JSON 示例并对指定对话模型请求 10 次，结果只用于 Prompt 遵循诊断，不改变 Persona 主路径。 |
| 第二阶段 2B：Provider 能力矩阵与 JSON mode | 已完成首轮 | 支持 JSON/XML/Markdown 的 Prompt-only 探测，以及 DeepSeek、OpenAI Chat Completions、OpenAI Responses、Gemini 的原生 JSON 探测；OpenAI Chat Completions 和 Responses 另支持 JSON Schema，MiniMax Token Plan 当前仅 Prompt-only；结果可复制但不持久化，Persona Response 可显式选择格式。 |
| 第二阶段 2C：原生 JSON Schema / structured output | 首轮已接入 | OpenAI Chat Completions/Responses 的 JSON Schema 请求参数已接入 Persona Response；仍需按模型和 endpoint 做真实组合验收。 |
| 第三阶段：XML、Markdown parser | 首轮已完成 | 语义 XML/Markdown parser 已接入 Persona Response；不接受把 JSON 嵌入 XML/Markdown 的方式。 |
| 第四阶段：TTS 标签适配 | 分段消费已实施，标签未实施 | 文本平台使用拼接文本；TTS 按 `segments[].speech` 分段消费。本协议尚未实现标签 Prompt 注入和清理。 |
| 文档、插件迁移和运行验收 | 文档已按当前代码更新；外部集成验收待完成 | Core 破坏性移除旧字段；依赖方需分别迁移并进行真实平台验收。 |

详细字段约束、阶段验收和未完成事项见各阶段文档。新功能读取运行时结构化结果时，应通过 Interaction Result Contributor 的 `view`；不要解析 provider 私有响应或从可见文本反推状态。
