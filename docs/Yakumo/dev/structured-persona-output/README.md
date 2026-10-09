# Persona 结构化输出计划

本文档集记录 Persona Expression 结构化输出协议、当前实现边界和后续阶段。当前代码事实以本目录的阶段记录、[Interaction 模块文档](../../modules/interaction.md)和[通用输出契约文档](../output-contract.md)为准。

## 当前状态

- Canonical Schema 和当前严格 `persona_expression` tool-call 主路径已完成迁移。
- Core 会把结果解析并校验为 `PersonaExpressionResult`。Persona 请求要求协议级 tool call，不接受自由文本或 prompt-only JSON 作为成功结果；不兼容候选在发起请求前被排除。
- Core 已把新字段贯穿 Personal 路由、即时/最终输出和 Interaction Result Contributor。Persona 改写的插件文本使用 `plugin_reply` purpose；插件可以从只读 `InteractionResultView` 读取结构化结果。
- Provider 原生 JSON Schema/JSON mode、XML/Markdown 解析器、TTS 标签注入与清理，以及外部插件的独立迁移和真实平台验收仍未完成。

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
  },
  "effect_calls": []
}
```

顶层只允许以上六个必填字段。`turn_action` 是调用场景允许值中的单个字符串；`speech` 是用户可见文本；`actions` 是非空字符串组成的简单动作意图数组（动作意图由 Prompt 约束，Schema 不验证动作词语法）；`thought` 是角色简短心理想法；`tendency` 是角色当前的 Plutchik 八维情绪；`effect_calls` 是按本轮已注册 effect schema 构造的插件调用数组。

## 阶段状态

| 阶段 | 状态 | 代码边界 |
| --- | --- | --- |
| 准备阶段：冻结 Canonical Schema | 已完成 | 六个字段、字段含义、情绪维度和值域已确定。 |
| 第一阶段：迁移当前 tool call | 已完成 | Schema、Prompt、解析、校验、Personal/Core 输出消费和结果贡献视图已使用新字段。 |
| 第二阶段：Provider 输出策略 | 未实施 | 目前 Persona 仍要求协议级 `persona_expression` tool call；通用契约类型的预留不等于 Persona 已接入。 |
| 第三阶段：XML、Markdown parser | 未实施 | 当前没有 Persona XML/Markdown parser。 |
| 第四阶段：TTS 标签适配 | 未实施 | `speech` 是 TTS 文本来源；本协议尚未实现标签 Prompt 注入和清理。 |
| 文档、插件迁移和运行验收 | 文档已按当前代码更新；外部集成验收待完成 | Core 破坏性移除旧字段；依赖方需分别迁移并进行真实平台验收。 |

详细字段约束、阶段验收和未完成事项见各阶段文档。新功能读取运行时结构化结果时，应通过 Interaction Result Contributor 的 `view`；不要解析 provider 私有响应或从可见文本反推状态。
