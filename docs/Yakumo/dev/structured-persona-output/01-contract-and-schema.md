# Canonical Schema 与字段规则

**状态：** 双通道运行时与缺失通道恢复已实现；自动化定向验证通过；真实 Provider 和插件验收待完成
**代码位置：** `astrbot/core/interaction/expression_agent.py`

本文说明业务语义和实际校验边界。Provider wire format 不属于 Canonical Schema。表达通道默认使用 JSON 文本 + Prompt-only 约束，也可配置为原生 JSON、XML、Markdown 或严格 `persona_expression` tool call；适用的插件 effect 始终由独立 `persona_effect_batch` tool call 承载。Provider 页的 10 次诊断只检查所选文本格式的稳定性，不自动切换生产配置，也不覆盖 effect tool-call 能力。

## Canonical 参数

```json
{
  "turn_action": "reply",
  "segments": [
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

上例是内部聚合后的 `PersonaExpressionResult`，不是单个 Provider payload。`persona_expression` 只包含 `turn_action` 和 `segments`；当前事件存在已注册且适用的 Persona Effect 时，同一模型响应还必须调用 `persona_effect_batch`，其参数只包含 `effect_calls`。这是同一响应中的两个独立通道；正常生成不为 effect 单独发起请求，已解析的必发 effect 未通过校验时沿用现有 effect batch 校正请求。没有适用 effect 时不向模型提供 effect 工具，内部聚合结果的 `effect_calls` 为空数组。

每个通道分别执行精确字段和语义校验：表达 payload 只接受 `turn_action`、`segments`；effect payload 只接受 `effect_calls`。重复或缺少本轮要求的调用、额外字段、错误类型或不满足语义限制时，不构造成功结果。

## 字段定义

### `turn_action`

必填的单个字符串枚举：`reply` 或 `silent`。每次调用按请求目的收窄 Schema：

- 普通结果表达、Core 最终表达和 Persona 改写插件文本只允许 `reply`。
- Personal 表达调用仅允许 `reply`；允许静默的群聊候选才额外开放 `silent`。

`turn_action` 只决定 Personal 是否发出可见回复，不决定是否进入 Core。独立 Core Router 判断是否路由到 Core；Core Planner 随后生成任务规格。`silent` 只能用于允许静默的群聊候选。

### `segments[].speech`

必填字符串，表示这一段的用户可见表达。平台文本发送时按 `segments` 顺序拼接为一个整合文本；TTS 消费时逐段读取这些字符串并保持原顺序，不先把它们合并成一个 TTS 请求。正常可见回复要求至少有一个非空 speech；仅明确允许为空的特定请求可以返回空字符串。TTS 标签嵌入、Prompt 注入及清理尚未实现。

### `actions`

必填数组，每个元素是非空字符串，例如 `lower_head`、`look_away`、`turn_head_left`。Prompt 要求元素表达简单动作意图，允许自然方向，不放角度、坐标、速度、时长等执行参数、平台 ID 或插件 effect 数据；Schema 本身不校验字符串是否符合某种动作词语法。空动作使用 `[]`。执行和具体动作解释不属于 Core schema。

同段 `actions` 表示可同时发生的动作，不表示依次执行的时间序列。需要先后配合不同话语的动作必须拆为不同 `segments`，例如“左……”配左转头、“右……”配右转头，各段填写 `tendency`。没有动作或状态变化时不必拆段，不添加重复文本或无意义动作。该语义由 Prompt 与 Schema 描述要求模型遵守，结构校验不能保证模型按意图正确分段。

### `tendency`

必填对象，必须恰好包含以下八个大小写敏感的键；模型应输出整数（布尔值不算整数值），范围 `0..10`。Core 对整数越界值执行边界裁剪：负数归零，大于 `10` 的值归 `10`；缺失、未知键或非整数仍然是结构错误：

| Key | 角色当前情绪强度 |
| --- | --- |
| `Joy` | 喜悦 |
| `Trust` | 信任 |
| `Fear` | 恐惧 |
| `Surprise` | 惊讶 |
| `Sadness` | 悲伤 |
| `Disgust` | 厌恶 |
| `Anger` | 愤怒 |
| `Anticipation` | 期待 |

该字段表示模型以当前角色身份判断的情绪强度，不是用户情绪或模型内部状态；八维分类用于统一输入输出含义及训练标注，不约束神经网络内部形成情绪轮。

### `effect_calls`

内部聚合结果中的数组字段。仅当当前事件存在已启用且适用的 `PersonaEffectSpec` 时，Provider 才会收到独立的 `persona_effect_batch` tool schema；其参数精确包含 `effect_calls`，每项包含注册 effect 的 `name` 和符合注册参数 schema 的 `arguments`。首轮响应要求每个启用通道恰好出现一次；没有适用 effect 时省略 effect tool call，内部结果仍以空数组表示。若双通道首轮漏掉表达或 effect batch，Core 会用隔离请求只补缺失通道一次；两个通道都缺失时依次补齐。重复通道、无效的 batch 顶层结构仍直接拒绝。Core 解析时只保留已注册且 arguments 通过 schema 校验的调用，并将无效项的解析问题记录在结果 metadata；已解析 batch 中必发 effect 缺失或无效时，也会进入至多一次 effect-only 校正。非必发的无效项会被丢弃，不一定使整次表达失败。最终聚合结果由插件消费和解释。

若有必发 effect，Schema 和语义校验会按注册元数据要求数量；允许 `silent` 的请求仍会调用 effect 工具，但必须传入空 `effect_calls`。`actions` 不替代任何必发 effect。

## 跨字段约束

- `silent` 时表达 payload 的 `segments` 必须为空；如果本轮启用了 effect 通道，该通道的 `effect_calls` 也必须为空。无适用 effect 时不提供 effect 工具。
- Core 路由结果不包含在 Persona payload 中；路由到 Core 后由 Core Planner 生成任务规格。
- 正常路径中表达 payload 与适用的 effect payload 来自同一模型响应；若双通道首轮漏项，Core 只请求缺失通道并在校验后合并。不能从自由文本或 provider 私有日志补猜缺值。

## 旧字段

Core 不再接受 `spoken_reply` 或 `speech_cues`，也不映射到新字段。TTS 的时序边界直接来自 `segments[].speech`；不要另建并行 cue 数组。未来 TTS 控制标签应由 TTS 适配器注入各段 `speech`，并在 TTS 边界清理。外部插件的私有字段迁移由插件维护者单独完成。
