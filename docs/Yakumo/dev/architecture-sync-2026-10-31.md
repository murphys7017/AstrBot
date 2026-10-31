# 2026-10-31 架构同步基线

本文记录当前源码已经落地的结构边界。历史计划和实施记录继续保留原文；阅读当前行为时，以本文、[Yakumo 架构入口](../README.md)、[Interaction 模块](../modules/interaction.md)和[Prompt 模块](../modules/prompt.md)为准。

当前同步基线对应以下本地提交：

- `3fb9ad681`：Runtime-owned PersonaContext 基础结构。
- `0fc88e7c8`：Persona Expression 类型、schema、contract、校验、codec 和流式协议分层。
- `c89df36bb`：Tencent SILK 头部识别和前缀剥离统一。
- `04b6aba49`：Heartbeat、NVIDIA endpoint、pip 安全边界及对应记录更新。

## 当前 Persona 主链

```text
PersonalRuntime / InteractionTurnState
  -> PersonaContextSeed（Runtime-owned 静态人格快照）
  -> Persona Collector / Persona Policy / Persona Expression
  -> ContextPack target projection
  -> PromptRenderProfile / Provider Renderer
  -> Persona Expression protocol adapter
  -> PersonaExpressionResult
  -> Output Controller / History / TTS / Effect delivery
```

`PersonaContextSeed` 是普通 Interaction、主动 Policy 和主动 Expression 共用的人格快照来源。它只承载本轮需要的静态人格事实；动态输入、历史、Memory、插件扩展和能力工具仍由各自的 Context Collector 与 target projection 提供。

人格事实的中性边界由 `astrbot.core.persona_context` 和 `astrbot.core.interaction.persona_domain` 提供。Prompt 层只在 `persona_collector.py` 中把人格领域槽投影为 Prompt `ContextSlot`，Policy 和 Expression 不再各自重建一套人格上下文。

## Persona Expression 分层

`expression_agent.py` 负责运行编排、Provider 调用、生命周期和输出交接。协议数据和解析规则位于独立模块：

| 层 | 当前模块 | 职责 |
|---|---|---|
| 类型 | `interaction/persona_expression_types.py` | `PersonaExpressionRequest`、`PersonaExpressionSegment`、`PersonaExpressionResult`、`InteractionExpressionError` 和协议类型别名 |
| Schema | `interaction/persona_expression_schema.py` | 表达和 Effect 的 JSON Schema 以及共享字段说明 |
| Contract | `interaction/persona_expression_contract.py` | 输出契约、工具名称、Effect terminal tool 集合 |
| 校验 | `interaction/persona_expression_validation.py` | segment、tendency、turn action 和 Effect 语义校验；流式校验契约 |
| Codec | `interaction/persona_expression_codec.py` | 工具参数、JSON/XML/Markdown 结果和 Effect 回执的归一化 |
| 流式状态机 | `interaction/persona_stream_parser.py` | `segment_stream_v1` JSONL 记录解析、恢复、状态迁移和事件生成 |
| 流式协议辅助 | `interaction/persona_stream_protocol.py` | 流式 Prompt 和响应形状诊断 |
| JSON 基础能力 | `core/json_parsing.py`、`prompt/json_recovery.py` | 中性 JSON 文本规范化、宽松值解析和完整记录恢复 |

这些模块不改变 Provider 的调用方式。默认 Persona 表达仍是 JSON 文本加 Prompt-only；严格 `persona_expression` tool call 由配置显式启用。适用的 Persona Effect 仍通过同一响应中的独立 `persona_effect_batch` tool call 返回。

## 流式协议边界

`PersonaSegmentStreamParser` 维护 `segment_stream_v1` 的记录顺序、重复字段拒绝、记录和字符上限、空行处理、完整记录恢复以及 `header -> segment -> finish` 状态迁移。`feed_async()` 对完整行只进行一次严格 JSON 解码；恢复只作用于当前完整记录，不改变原始 wire text 诊断。

流式校验通过 `PersonaStreamValidationContract` 注入默认 turn action、segment 和 result 校验。默认契约与非流式 Persona 结果共用同一套语义校验，Provider、Prompt 和下游输出协议不依赖具体 Agent 类的位置。

## JSON 边界

JSON 处理分为三层：

1. `core/json_parsing.py` 处理代码围栏、对象提取和宽松 JSON-like 值归一化。
2. `prompt/json_recovery.py` 处理完整记录的严格解析、既有 repair fallback 和一次配置的恢复请求。
3. `interaction/structured_output.py` 负责 JSON/XML/Markdown 的结构 grammar；Persona codec 再把结果交给 Canonical 校验。

`prompt/structured_json.py` 保留兼容导出，业务代码不应重新实现 `repair_json`、代码围栏剥离或工具参数宽松解析。

## 实时性约束

- 抽取模块只移动职责，不新增 Provider 请求、Prompt 重建或同步等待。
- 流式解析仍按完整行增量消费，恢复请求仍受原有生命周期和预算控制。
- Persona ContextSeed 只在 Runtime 内共享静态人格快照；历史、Memory 和插件 enrichment 不被跨回合冻结。
- Prompt target projection 仍决定模型可见字段，协议层不绕过 Prompt 白名单。

## 兼容和维护边界

- `expression_agent.py` 保留旧入口导出，兼容已有内部调用方；新代码应直接依赖对应的中性模块。
- `prompt/structured_json.py` 是兼容层，不是新的实现位置。
- AG99live 的源码仍位于独立仓库；本仓库的部署目录不是插件源文件。
- 旧计划中的目标态、历史性能样本和未完成的真实 Provider/Live2D 验收不能写成当前已完成能力。
