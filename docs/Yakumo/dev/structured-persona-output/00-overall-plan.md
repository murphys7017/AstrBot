# Yakumo Persona 结构化输出总计划

**文档状态：** 设计审阅中  
**更新时间：** 2026-10-09  
**实施方式：** 分阶段破坏性更新  
**当前阶段：** 只读审阅，未修改代码

## 1. 目标

将 Persona Expression 从旧的 `spoken_reply + speech_cues + effect_calls` 输出，统一改造成一个可由多种 provider 输出方式承载的结构化协议。

协议只定义“模型最终表达的语义”，不把某一家 provider 的传输格式写入业务层。模型可以通过 tool call、原生 JSON Schema、JSON mode、prompt-only JSON，或后续的 XML、Markdown 适配器返回；Core 最终只接收一个统一的 `PersonaExpressionResult`。

## 2. 不在本计划内的内容

- 本阶段不重新设计 Persona 的人格规则或上下文材料。
- 本阶段不把 `actions` 直接解释成 Live2D、Motion 或平台动作参数。
- 本阶段不把 `effect_calls` 改造成 `actions`，也不改变现有插件 effect 执行机制。
- 本阶段不在 Core 中实现 TTS 专用标签；TTS 标签注入和清理放到独立阶段。
- 本阶段不为旧字段保留长期兼容别名。
- 本阶段不因为某个 provider 宣称支持某种格式，就默认启用该格式。

## 3. Canonical Persona Expression Schema

所有输出方式最终都要得到以下语义结构：

```json
{
  "turn_action": "reply",
  "speech": "啊……怎么会这样？",
  "actions": [
    "lower_head"
  ],
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

### 3.1 字段规则

| 字段 | 规则 | 主要消费者 |
| --- | --- | --- |
| `turn_action` | 必填单值，只能是 `reply`、`delegate`、`silent` | Personal Response Plan、路由控制 |
| `speech` | 用户可见文本；也是 TTS 的唯一文本来源 | Output Runtime、TTS、历史 |
| `actions` | 简单动作词数组，不携带参数 | 后续动作模型、表现插件 |
| `thought` | 简短心理状态摘要，不输出完整推理链 | 内部状态、诊断或训练标注 |
| `tendency` | 模型以角色身份输出的当前八维情绪状态 | 状态、训练数据、诊断 |
| `effect_calls` | 现有插件 effect 调用协议 | Effect 执行链、插件 |

`tendency` 使用 Plutchik 八种基本情绪作为统一标注词汇：

| 参数 | 含义 |
| --- | --- |
| `Joy` | 喜悦 |
| `Trust` | 信任 |
| `Fear` | 恐惧 |
| `Surprise` | 惊讶 |
| `Sadness` | 悲伤 |
| `Disgust` | 厌恶 |
| `Anger` | 愤怒 |
| `Anticipation` | 期待 |

除非后续另行决定，八个值继续使用 `-10` 到 `10` 的整数范围。`tendency` 是模型根据当前对话上下文和角色设定生成的输出字段，表示角色此刻的情绪状态。它不是用户情绪、模型自身情绪，也不是传入模型的情绪向量；这个体系只用于统一角色输出和训练数据标注，不要求模型内部形成固定的情绪轮结构。

### 3.2 输出目的地

```text
speech       -> 用户消息、TTS、可见输出历史
turn_action  -> 路由和本轮执行控制
actions      -> 简单动作意图，交给专门动作模型
thought      -> 内部结构化状态，不进入用户文本或 TTS
tendency     -> 角色当前情绪状态的结构化记录、训练/诊断数据
effect_calls -> 现有插件 effect 执行链
```

`silent` 时使用空的 `speech`、`actions` 和 `effect_calls`。`thought` 和 `tendency` 可以保留为内部状态。

## 4. 输入到输出的统一链路

```text
用户消息 / Core 结果 / 插件可见材料
        ↓
PersonaExpressionRequest
        ↓
Prompt Context Pack + Persona Prompt
        ↓
OutputContract
        ↓
Provider 能力协商与请求构造
        ↓
Provider 原始响应
        ↓
格式专用解析器
        ↓
Canonical Schema 类型与语义校验
        ↓
PersonaExpressionResult
        ↓
turn_action 路由、speech 输出、TTS、actions、effect_calls、内部状态
```

输入材料仍由现有 Prompt 系统组装；模型根据这些材料和角色设定生成 `tendency`，不需要为它增加独立的输入字段。新增内容主要集中在输出契约、格式策略和结果解析，不新增第二套对话或消息管线。

## 5. 分阶段实施顺序

| 阶段 | 目标 | 主要结果 |
| --- | --- | --- |
| 准备阶段 | 冻结 Canonical Schema | 字段、含义、范围、空值和失败规则确定 |
| 第一阶段 | 迁移当前 tool call | 当前主路径输出新 Schema，删除旧字段 |
| 第二阶段 | Provider 输出策略协商 | 支持并实测 tool call、原生 JSON Schema、JSON mode、prompt-only JSON |
| 第三阶段 | 文本格式适配 | 增加 XML、Markdown 等明确 grammar 的 parser |
| 第四阶段 | TTS 处理 | 将语音标签注入和清理集中到 `speech` |
| 第五阶段 | 迁移与验证 | 更新文档、测试、插件接口和运行指标，分批启用 |

每个阶段都需要先完成源码审阅和边界确认，再进入对应实现；不能用后续阶段的 fallback 掩盖前一阶段的协议错误。

## 6. 现有代码影响面

- [`expression_agent.py`](../../../../astrbot/core/interaction/expression_agent.py)：结果类型、Schema、Prompt、解析、校验和修正流程。
- [`output_contract.py`](../../../../astrbot/core/output_contract.py)：统一输出契约和策略类型。
- [`interfaces.py`](../../../../astrbot/core/prompt/render/interfaces.py)：契约编译、策略选择和 fallback Prompt。
- [`structured_json.py`](../../../../astrbot/core/prompt/structured_json.py)：JSON 提取和修复能力。
- [`middleware.py`](../../../../astrbot/core/interaction/middleware.py)、[`persona_runtime.py`](../../../../astrbot/core/interaction/persona_runtime.py)、[`output_controller.py`](../../../../astrbot/core/interaction/output_controller.py)：结果消费、路由、输出和 TTS 边界。
- [`capability_route_guard.py`](../../../../astrbot/core/interaction/capability_route_guard.py)：`turn_action` 和空输出约束。
- [`speech_cues.py`](../../../../astrbot/core/speech_cues.py)：本次破坏性更新中删除 Core 协议，后续由 TTS 专项替代。
- Provider renderer/source 和 [`output_contract_tools.py`](../../../../astrbot/core/provider/output_contract_tools.py)：后续输出策略协商和 provider 请求转换。
- Interaction、Persona、provider structured output 相关文档和测试。

## 7. 总体验收条件

1. 当前 tool-call provider 返回的新参数可以稳定解析为 Canonical Schema。
2. Core 不再接受或生成 `spoken_reply`、`speech_cues` 旧字段。
3. `speech` 是唯一进入用户输出和 TTS 的文本字段。
4. `turn_action` 始终是单值三选一，并能正确驱动 `reply / delegate / silent`。
5. `tendency` 始终包含八个固定维度，值域校验有效。
6. `actions` 和 `effect_calls` 在运行时职责上保持分离。
7. 不同 provider 输出格式最终得到相同的 `PersonaExpressionResult` 语义。
8. XML、Markdown 等后续格式不会改变业务层 Schema。
9. provider 策略切换有延迟、失败率、重试率和 fallback 诊断数据。

