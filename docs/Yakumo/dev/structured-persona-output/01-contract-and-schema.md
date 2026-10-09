# 准备阶段：统一输出契约与 Schema

## 目标

先冻结输出语义，避免在 provider 适配之前反复改变字段含义。此阶段只做设计和协议定义，第一阶段再进入当前 tool call 的代码迁移。

## 1. Canonical Schema

`persona_expression` 的规范参数包含：

```text
turn_action
speech
actions
thought
tendency
effect_calls
```

建议在严格结构化路径中所有字段都存在；没有内容时使用空字符串、空数组或全零情绪向量。`effect_calls` 继续使用现有动态 effect Schema。

## 2. 字段语义

### `turn_action`

这是一个字符串枚举，不是数组：

```text
reply | delegate | silent
```

它表示本轮是否直接回答、是否交给 Core/外部能力继续处理，或是否保持安静。普通对话和群聊候选可以由调用场景进一步限制允许的枚举子集，但最终字段形态不变。

### `speech`

这是唯一用户可见的表达文本，也是 TTS 的输入文本。当前阶段不要在 Core 中额外生成语音 cue；后续 TTS 适配器需要的标签直接放在这个字段内部。

### `actions`

使用简单、稳定的动作词，例如 `lower_head`、`look_away`。不包含方向、时长、强度、模型参数或平台私有数据。具体动作解释由单独动作模型或表现插件完成。

### `thought`

表示简短的心理状态摘要，用于内部状态、训练数据或诊断。Prompt 必须明确它不是完整推理链，也不会进入用户消息、TTS、对话历史或 memory。

### `tendency`

使用 Plutchik 八维情绪词汇：`Joy`、`Trust`、`Fear`、`Surprise`、`Sadness`、`Disgust`、`Anger`、`Anticipation`。它表示模型以角色身份判断的当前情绪状态，由模型作为输出生成。它不是用户情绪、模型自身情绪或传入模型的情绪向量，也不要求模型内部遵循固定情绪轮结构。

### `effect_calls`

保持现有插件 effect 调用机制。它是插件执行协议，不与 `actions` 合并，也不因为输出格式改成 JSON/XML/Markdown 就改变执行语义。

## 3. 校验规则

- `turn_action` 必须是允许枚举值。
- `speech` 必须是字符串。
- `actions` 必须是字符串数组，数组元素不能为空且不得携带参数对象。
- `thought` 必须是字符串。
- `tendency` 必须包含且只包含八个约定维度。
- 八个情绪值必须是 `-10` 到 `10` 的整数，除非后续协议明确修改。
- `effect_calls` 使用现有 effect 名称和参数校验。
- `silent` 时 `speech`、`actions`、`effect_calls` 必须为空。

## 4. 破坏性变更

删除以下旧字段及其 Core 兼容读取：

```text
spoken_reply
speech_cues
```

旧字段不在结果规范化阶段自动映射。旧插件或 adapter 的迁移单独记录，不把兼容壳保留在新的主协议中。

## 5. 文档和训练数据约束

所有 Schema 示例、Prompt 示例、训练数据标注和测试 fixture 都必须使用同一组八维角色情绪字段和相同解释。字段顺序建议固定为：

```text
Joy, Trust, Fear, Surprise, Sadness, Disgust, Anger, Anticipation
```

字段顺序不影响 JSON 语义，但固定顺序有利于 Prompt、一致性检查和人工审阅。

