# Persona 结构化输出计划

本文档集记录 Persona Expression 结构化输出协议、当前实现边界和后续阶段。当前代码事实以本目录的阶段记录、[Interaction 模块文档](../../modules/interaction.md)和[通用输出契约文档](../output-contract.md)为准。

## 当前状态

- 2026-10-17 非流式 N0–N7 已按限定范围实施并逐项提交：Memory 缓存/输出设备提前准备、松手截图重叠、v6 后到动作、段间动作交接、轻量能力摘要与文件 TTS 连接复用。完整 Electron 构建通过，真实对话性能与 Live2D 观感待验收；范围、提交和验证缺口见 [11 文档第 16 节](11-olv-nonstreaming-optimization-plan.md#16-2026-10-17-本会话实施记录)。

- OLV T0b/T1/T2/T3 已实现并完成局部验证：输入身份、PCM 生命周期、TTS 准入、动作特殊状态/期限、接收与播放解耦、双端信用；真实 M2、性能及身体表现仍待验收，T6 动作小记录未实施。下一步以 [14 剩余工作与现场验收](14-olv-remaining-work-and-acceptance.md)为准，提交证据见 [08 第 12、13 节](08-olv-full-streaming-execution-plan.md)。
- [07 低延迟分段投递](07-low-latency-segment-delivery.md)保留早期完整段阶段背景，不用于判断当前 M2 实现状态。

- Canonical Result、表达格式适配和条件性 effect 通道已实施，仍待真实 Provider 组合验收。表达默认是 JSON 文本 + Prompt-only；严格 `persona_expression` tool call 仅在显式配置时使用。
- Core 分别解析表达和 effect 通道，再聚合并校验为 `PersonaExpressionResult`。表达可由 JSON/XML/Markdown parser 恢复，或由显式选择的 `persona_expression` tool call 承载；当前事件有已注册且适用的 effect 时，同一模型响应还要求独立 `persona_effect_batch` tool call。无适用 effect 时不提供 effect 工具。若首轮漏掉任一通道，Core 会以隔离请求只补缺失通道；若两路都缺失，则依次补表达和 effect。已解析的必发 effect 校验失败时，也会额外请求模型修复 effect batch。
- Provider 页面提供结构化输出稳定性诊断：可编辑默认 Persona JSON 示例，选择 JSON、XML 或 semantic Markdown；JSON 可选 Prompt-only、Provider 原生 JSON mode 或 Provider 原生 JSON Schema，对单个对话模型最多请求 10 次并检查格式、字段结构和类型。DeepSeek、OpenAI Chat Completions、OpenAI Responses 与 Gemini 已接入原生 JSON 探测，OpenAI Chat Completions 与 Responses 另支持 JSON Schema，MiniMax Token Plan 当前仅 Prompt-only；结果含可复制的单次探测记录，但不会自动持久化，也不改变 Persona 主路径。
- Core 已把新字段贯穿 Personal 路由、即时/最终输出和 Interaction Result Contributor。Persona 改写的插件文本使用 `plugin_reply` purpose；插件可以从只读 `InteractionResultView` 读取结构化结果。
- Provider JSON/语义 XML/语义 Markdown Prompt 稳定性诊断及原生 JSON/JSON Schema 探测已接入；结果不持久化。Persona Response 的格式选项只控制表达通道；适用 effect 仍通过同一响应中的独立 terminal tool call 返回。TTS 标签注入与清理、外部插件的独立迁移和真实 Provider 组合验收仍未完成。

## 文档索引

| 阅读目的 | 文档 |
| --- | --- |
| 从当前状态接续工作、现场验收与完成标准 | [14 剩余工作与现场验收](14-olv-remaining-work-and-acceptance.md) |
| 全流式架构目标、约束与已提交实现证据 | [08 主任务书](08-olv-full-streaming-execution-plan.md) |
| 具体操作、状态机和验收反例 | [09 实施细则](09-olv-implementation-playbook.md) |
| 历史运行样本与测量口径 | [10 现场证据](10-olv-runtime-evidence-2026-10-17.md) |
| 普通 M0 优化与已完成范围 | [11 非流式任务书](11-olv-nonstreaming-optimization-plan.md) |
| 较早完整段投递设计 | [07 低延迟分段投递](07-low-latency-segment-delivery.md) |

基础协议与原阶段资料：

- [总计划与代码现状](00-overall-plan.md)
- [Canonical Schema 与字段规则](01-contract-and-schema.md)
- [结构化输出与 effect 通道拆分](02-tool-call-migration.md)
- [Provider 输出策略](03-provider-output-strategy.md)
- [XML、Markdown 适配](04-text-format-adapters.md)
- [TTS 与 speech 处理](05-tts-speech-pipeline.md)
- [迁移、验证与发布清单](06-migration-and-validation.md)

## Canonical Schema

```json
{
  "turn_action": "reply",
  "segments":[
    {
      "speech": "啊……怎么会这样？",
      "actions": ["lower_head"],
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

上例是内部聚合结果，不是单个 Provider payload。表达通道只包含 `turn_action`、`segments`；适用 effect 使用参数仅含 `effect_calls` 的 `persona_effect_batch` 独立 tool call，并与表达在同一模型响应中返回。无适用 effect 时不提供该工具，内部聚合结果以空数组表示。默认表达格式为 JSON + Prompt-only；Provider 页面 10 次稳定性测试由用户判断结果，不自动持久化或修改 Persona Response 配置。每个 `segments` 元素包含 `speech`、`actions` 和 `tendency`。`turn_action` 只表示 Personal 是否发出可见回复；是否进入 Core 由独立 Core Router 判断。文本平台使用按顺序拼接的 `segments[].speech`，TTS 使用原始分段；普通路径逐段合成，声明支持的 OLV 路径可并行准备并按序投递。

## 阶段状态

| 阶段 | 状态 | 代码边界 |
| --- | --- | --- |
| 准备阶段：冻结 Canonical Schema | 已完成 | 内部聚合字段、表达和 effect 分通道、segment 字段、情绪维度和值域已确定。 |
| 第一阶段：结构化输出与 effect 通道拆分 | 已实施，待真实 Provider 验收 | 默认表达使用 JSON + Prompt-only；表达格式可配置。适用插件 effect 使用同一响应中的独立 `persona_effect_batch`。缺失通道时只补缺失通道一次，Core 聚合后仍沿用现有下游接口。 |
| 第二阶段 2A：JSON Prompt 稳定性诊断 | 已完成 | Provider 页面支持编辑 JSON 示例并对指定对话模型请求 10 次，结果只用于 Prompt 遵循诊断，不改变 Persona 主路径。 |
| 第二阶段 2B：Provider 能力矩阵与 JSON mode | 已完成首轮 | 支持 JSON/XML/Markdown 的 Prompt-only 探测，以及 DeepSeek、OpenAI Chat Completions、OpenAI Responses、Gemini 的原生 JSON 探测；OpenAI Chat Completions 和 Responses 另支持 JSON Schema，MiniMax Token Plan 当前仅 Prompt-only；结果可复制但不持久化，Persona Response 可显式选择格式。 |
| 第二阶段 2C：原生 JSON Schema / structured output | 首轮已接入 | OpenAI Chat Completions/Responses 的 JSON Schema 请求参数已接入 Persona Response；仍需按模型和 endpoint 做真实组合验收。 |
| 第三阶段：XML、Markdown parser | 首轮已完成 | 语义 XML/Markdown parser 已接入 Persona Response；不接受把 JSON 嵌入 XML/Markdown 的方式。 |
| 第四阶段：TTS 标签适配 | 分段消费已实施，标签未实施 | 文本平台使用拼接文本；TTS 按 `segments[].speech` 分段消费。本协议尚未实现标签 Prompt 注入和清理。 |
| 文档、插件迁移和运行验收 | 文档已按当前代码更新；外部集成验收待完成 | Core 破坏性移除旧字段；依赖方需分别迁移并进行真实平台验收。 |

详细字段约束、阶段验收和未完成事项见各阶段文档。新功能读取运行时结构化结果时，应通过 Interaction Result Contributor 的 `view`；不要解析 provider 私有响应或从可见文本反推状态。
