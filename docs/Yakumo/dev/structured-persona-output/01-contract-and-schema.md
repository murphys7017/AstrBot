# Canonical Schema 与字段规则

**状态：** 已冻结并由第一阶段代码实现
**代码位置：** `astrbot/core/interaction/expression_agent.py`

本文说明业务语义和实际校验边界。Provider wire format 不属于 Canonical Schema；当前生产 Persona 请求通过严格的 `persona_expression` tool call 承载。

## Canonical 参数

```json
{
  "turn_action": "reply",
  "segments": [
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

Schema 对象 `additionalProperties=false`，并要求且只接受三个顶层字段：`turn_action`、`segments`、`effect_calls`。缺字段、多余字段、错误类型或不满足语义限制时不构造成功的 Persona 结果。

## 字段定义

### `turn_action`

必填的单个字符串枚举：`reply`、`delegate` 或 `silent`。每次调用按请求目的收窄 Schema：

- 普通结果表达、Core 最终表达和 Persona 改写插件文本只允许 `reply`。
- Personal Response Plan 要求输出动作；不可静默的私聊/续接允许 `reply`、`delegate`。
- 仅允许静默的群聊候选可以额外选择 `silent`。

`delegate` 表示 Personal 将工作委派给 Core；它不是另一个工具调用数组，也不携带 Core task specification。`silent` 只能用于允许静默的群聊候选。

### `segments[].speech`

必填字符串，表示这一段的用户可见表达。平台文本发送时按 `segments` 顺序拼接为一个整合文本；TTS 消费时逐段读取这些字符串并保持原顺序，不先把它们合并成一个 TTS 请求。正常可见回复要求至少有一个非空 speech；仅明确允许为空的特定请求可以返回空字符串。TTS 标签嵌入、Prompt 注入及清理尚未实现。

### `actions`

必填数组，每个元素是非空字符串，例如 `lower_head`、`look_away`。Prompt 要求元素表达简单动作意图，不放动作参数、方向、时长、平台 ID 或插件 effect 数据；Schema 本身不校验字符串是否符合某种动作词语法。空动作使用 `[]`。执行和具体动作解释不属于 Core schema。

### `thought`

必填字符串，表示角色当前的简短心理想法，不是完整推理链。它不得拼接到用户消息、TTS 文本或普通对话历史。无心理描述时使用空字符串。

### `tendency`

必填对象，必须恰好包含以下八个大小写敏感的键；值必须是整数（布尔值不算整数值），范围 `-10..10`：

| Key | 角色当前情绪 |
| --- | --- |
| `Joy` | 喜悦 |
| `Trust` | 信任 |
| `Fear` | 恐惧 |
| `Surprise` | 惊讶 |
| `Sadness` | 悲伤 |
| `Disgust` | 厌恶 |
| `Anger` | 愤怒 |
| `Anticipation` | 期待 |

该字段表示模型以当前角色身份判断的情绪，不是用户情绪或模型内部状态；八维分类用于统一输入输出含义及训练标注，不约束神经网络内部形成情绪轮。

### `effect_calls`

必填数组。tool-call Schema 按当前事件中已启用且适用的 `PersonaEffectSpec` 动态构造，每项包含注册 effect 的 `name` 和符合注册参数 schema 的 `arguments`。无可用 effect 时使用空数组。Core 解析时只保留已注册且 arguments 通过 schema 校验的调用，并将无效项的解析问题记录在结果 metadata；对于必发 effect，缺失或无效会使本次结果校验失败并进入现有纠正流程（至多一次）。非必发的无效项会被丢弃，不一定使整次表达失败。具体 effect 由注册插件消费和解释。

若有必发 effect，Schema 和语义校验会按注册元数据要求数量；允许 `silent` 的请求可返回空 effect 数组。`actions` 不替代任何必发 effect。

## 跨字段约束

- `silent` 时 `segments`、`effect_calls` 必须为空；`thought` 和 `tendency` 约束只适用于存在的 segment。
- `delegate` 时由 Persona Request Prompt 限定 `speech` 为简短处理中确认；后续 task 由 Core Planner 生成。
- 所有表达字段均来自同一次结构化结果，不能从自由文本或 provider 私有日志补猜缺值。

## 旧字段

Core 不再接受 `spoken_reply` 或 `speech_cues`，也不映射到新字段。TTS 的时序边界直接来自 `segments[].speech`；不要另建并行 cue 数组。未来 TTS 控制标签应由 TTS 适配器注入各段 `speech`，并在 TTS 边界清理。外部插件的私有字段迁移由插件维护者单独完成。
