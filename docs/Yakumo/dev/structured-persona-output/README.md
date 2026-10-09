# Persona 结构化输出计划

这是 Yakumo Persona Expression 输出协议改造的计划目录。当前仅完成设计和源码审阅，尚未修改运行时代码、编译或运行测试。

## 文档索引

- [总计划](./00-overall-plan.md)
- [准备阶段：统一输出契约与 Schema](./01-contract-and-schema.md)
- [第一阶段：当前 tool call 迁移](./02-tool-call-migration.md)
- [第二阶段：Provider 输出策略协商](./03-provider-output-strategy.md)
- [第三阶段：XML、Markdown 等文本格式适配](./04-text-format-adapters.md)
- [第四阶段：TTS 与 speech 处理](./05-tts-speech-pipeline.md)
- [第五阶段：迁移、验证与发布](./06-migration-and-validation.md)

## 当前决定

- 这是一次破坏性更新，不保留 `spoken_reply`、`speech_cues` 等旧字段兼容别名。
- 第一批只修改现有 `persona_expression` tool call 的参数、Prompt、解析和运行时消费。
- 第二批再根据具体 provider 和模型能力，评估 tool call、原生 JSON Schema、JSON mode、prompt-only JSON 等方式。
- XML、Markdown 等格式通过独立 parser 和 Prompt 适配器逐步加入，不改变最终业务语义。
- 所有格式最终都必须解析为同一个 Persona Expression canonical schema。
- TTS 标签以后直接嵌入 `speech`，Core 不再维护独立的 `speech_cues` 时序数组。

