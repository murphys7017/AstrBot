# Canonical Schema 与字段规则

**状态：** 已冻结并由第一阶段代码实现
**代码位置：** `astrbot/core/interaction/expression_agent.py`

本文说明业务语义和实际校验边界。Provider wire format 不属于 Canonical Schema；当前生产 Persona 请求通过严格的 `persona_expression` tool call 承载。

## Canonical 参数

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

Schema 对象 `additionalProperties=false`，并要求且只接受这六个顶层字段。缺字段、多余字段、错误类型或不满足语义限制时不构造成功的 Persona 结果。

## 字段定义

### `turn_action`

必填的单个字符串枚举：`reply`、`delegate` 或 `silent`。每次调用按请求目的收窄 Schema：

- 普通结果表达、Core 最终表达和 Persona 改写插件文本只允许 `reply`。
- Personal Response Plan 要求输出动作；不可静默的私聊/续接允许 `reply`、`delegate`。
- 仅允许静默的群聊候选可以额外选择 `silent`。

`delegate` 表示 Personal 将工作委派给 Core；它不是另一个工具调用数组，也不携带 Core task specification。`silent` 只能用于允许静默的群聊候选。

### `speech`

必填字符串，是唯一用户可见的表达文本，也是当前输出层交给 TTS 的文本来源。正常可见回复要求它非空；仅明确允许为空的特定请求（例如流式 interjection）可以返回空字符串。TTS 标签嵌入、Prompt 注入及清理尚未实现。

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

必填数组。schema 按当前事件中已启用且适用的 `PersonaEffectSpec` 动态构造，每项包含注册 effect 的 `name` 和符合注册参数 schema 的 `arguments`。无可用 effect 时使用空数组。Core 负责限制、解析和校验；具体 effect 由注册插件消费和解释。

若有必发 effect，Schema 和语义校验会按注册元数据要求数量；允许 `silent` 的请求可返回空 effect 数组。`actions` 不替代任何必发 effect。

## 跨字段约束

- `silent` 时 `speech`、`actions`、`effect_calls` 必须为空；`thought` 仍是必填字符串，`tendency` 仍须提供完整八维对象。
- `delegate` 时由 Persona Request Prompt 限定 `speech` 为简短处理中确认；后续 task 由 Core Planner 生成。
- 所有表达字段均来自同一次结构化结果，不能从自由文本或 provider 私有日志补猜缺值。

## 旧字段

Core 不再接受 `spoken_reply` 或 `speech_cues`，也不映射到新字段。`speech_cues` 时序信息不得作为并行结果数组使用；未来 TTS 控制标签应由 TTS 适配器注入 `speech`，并在 TTS 边界清理。外部插件的私有字段迁移由插件维护者单独完成。
