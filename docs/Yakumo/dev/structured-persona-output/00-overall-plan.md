# Persona 结构化输出总计划

**文档状态：** 2026-10-09 按当前代码复核
**更新时间：** 2026-10-09  
**代码基线：** `149dd0485`（当前 HEAD；包含 `d4f9f69d3` 的 Provider JSON 稳定性诊断）
**实施方式：** 分阶段破坏性协议迁移

## 1. 目标与边界

为 Persona Expression 建立稳定的语义结果协议，使用户可见文本、角色动作意图、角色心理状态、角色情绪和插件 effect 调用各有明确字段。Provider 的传输格式属于适配层；无论未来采用何种输出方式，都必须解析为同一业务结果类型 `PersonaExpressionResult`。

本协议描述**扮演角色的输出状态**。`tendency` 由模型依据角色设定和当前对话生成，采用 Plutchik 八种基本情绪作为统一含义及训练标注词汇；它不是用户情绪、模型内部情绪向量或对神经网络内部状态的轮结构约束。

本计划不把 `actions` 解释为平台或 Live2D 参数，不把 `effect_calls` 合并进 `actions`，也不在 Core 实现 TTS 标签注入和清理。插件私有动作和 effect 仍由插件负责解释。

## 2. 当前 Canonical Schema

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

顶层必须且只能包含 `turn_action`、`segments`、`effect_calls`。三个字段都是必填项；额外顶层字段会被拒绝。`segments` 按说话时动作或状态变化分段，每段都包含 `speech`、`actions`、`thought` 和 `tendency`。

| 字段 | 当前代码约束 | 当前消费者 |
| --- | --- | --- |
| `turn_action` | 单个字符串；Schema 按请求限制可选值。 | Personal 路由和本轮执行控制。 |
| `speech` | 字符串；正常回复不能为空。 | 所在分段的用户可见文本；平台文本发送时按 `segments` 顺序整合，TTS 消费时保留分段边界。 |
| `actions` | Schema 校验为非空字符串数组；Prompt 要求其表达简单动作意图，不承载参数、方向、时长或平台数据。 | Result Contributor 可读取；需要投递动作数据时由插件构造自己的 contribution。 |
| `thought` | 字符串；角色简短心理想法，不是完整推理链。 | Result Contributor 可读取；不进入普通对话历史或用户文本。 |
| `tendency` | 必须恰好包含以下八个 key；值为不含 bool 的 `-10..10` 整数。 | Result Contributor 可读取；不作为用户文本或普通对话历史。 |
| `effect_calls` | 固定必填数组；tool-call Schema 按本轮有效 effect 生成 item schema。Core 解析时只保留已注册且参数通过校验的调用，并将解析问题写入结果 metadata；缺失或无效的必发 effect 会失败或进入既有纠正流程。无有效 effect 时使用空数组。 | Result Contributor / effect 插件；由插件解释执行。 |

情绪维度为 `Joy`（喜悦）、`Trust`（信任）、`Fear`（恐惧）、`Surprise`（惊讶）、`Sadness`（悲伤）、`Disgust`（厌恶）、`Anger`（愤怒）、`Anticipation`（期待）。

`silent` 仅对允许静默的群聊候选开放，并要求 `segments`、`effect_calls` 为空。即时私聊/直接续接不开放 `silent`；不要求 Personal Response Plan 的表达请求仅允许 `reply`。

### 字段流向

```text
turn_action  -> Personal 路由与 reply / delegate / silent 仲裁
segments[].speech -> 按顺序拼接为文本平台使用的整合文本；TTS 按段顺序消费每个 speech
actions      -> InteractionResultView；需要外部动作输出时由插件生成 contribution
thought      -> InteractionResultView；不自动投递、不进入普通对话历史
tendency     -> InteractionResultView；不自动投递、不进入普通对话历史
effect_calls -> InteractionResultView；effect 插件读取并解释
```

Core 不会自动把 `actions`、`thought` 或 `tendency` 序列化成平台 payload。插件应注册 Interaction Result Contributor，根据 `view.purpose` 及字段产生 `platform_extras` 或 `client_objects`。`plugin_direct` 输出不经过 Persona 改写，也不会收到这些 Persona 字段；Persona 改写的插件输出以 `plugin_reply` purpose 进入贡献阶段。

## 3. 当前运行链路

```text
用户输入 / Core 结果 / Persona 模式插件文本
        ↓
PersonaExpressionRequest + Prompt Context Pack
        ↓
Persona Prompt + 动态 effect schema + persona_expression OutputContract
        ↓
Prompt renderer 编译 tool_call contract
        ↓
Provider 能力检查：必须支持协议级 tool call
        ↓
Provider 原始响应中的 persona_expression tool call
        ↓
严格解析：精确字段集合、类型、枚举、情绪范围、effect schema
        ↓
PersonaExpressionResult
        ↓
turn_action 路由 / segments 文本与 TTS / InteractionResultView 插件贡献
```

当前 Persona 契约为 `mode="tool_call"`、`strict=True`、`preferred_tool_name="persona_expression"`、`allow_text_fallback=False`。Persona 主路径不会因 Provider 不支持强制 tool call 而降级成 JSON 文本或自由文本；候选会在请求前筛除，缺少 terminal tool call 时解析失败。通用 `OutputContract` 中的 JSON 模式或 Provider 通用解析能力不等于 Persona 已切换到该输出模式。

输入上下文仍由现有 Prompt 系统和 `PersonaExpressionRequest` 组装。`tendency` 是模型输出，不需要添加平行的输入情绪字段或新的对话管线。

## 4. 阶段状态

| 阶段 | 状态 | 结果或剩余工作 |
| --- | --- | --- |
| 准备：Canonical Schema | 完成 | 固定字段、角色情绪含义、范围和破坏性兼容决策。 |
| 第一阶段：当前 tool-call 路径 | 完成 | Schema、Prompt、解析校验、Personal/Core 消费和 Contributor 快照已迁移；插件 Persona 输出及文本相同但状态不同的 Core 去重也已修复。 |
| 第二阶段 2A：JSON Prompt 稳定性诊断 | 完成 | Provider 页面支持编辑 JSON 示例并对指定对话模型独立请求 10 次，检查 JSON 语法、对象字段和示例推断出的类型；该诊断不调用原生 JSON mode / JSON Schema，也不改变 Persona 主路径。 |
| 第二阶段 2B：Provider 能力矩阵与 JSON mode | 进行中（诊断记录已扩展） | 稳定性弹窗可区分 JSON/XML/Markdown 的 Prompt-only 与 JSON 的 Provider 原生模式；DeepSeek、OpenAI Chat Completions 和 OpenAI Responses 发送各自原生 JSON 参数，OpenAI Chat Completions 与 Responses 另支持 JSON Schema，Gemini 发送 `response_mime_type=application/json`，MiniMax Token Plan 当前仅 Prompt-only。结果可复制为单次探测记录，包含 Provider/模型、脱敏 endpoint 标识、UTC 时间、延迟汇总和能力判定；记录不持久化，也不等于完整矩阵。原生模式首个请求失败后停止，只有明确拒绝参数时标记 endpoint/model 不支持。Persona 生产路径接入尚未完成。 |
| 第二阶段 2C：原生 JSON Schema / structured output | 未开始（生产路径） | 诊断层已能把示例投影为 JSON Schema，并探测 OpenAI Chat Completions / Responses 的请求接受情况；尚未实现 Persona 生产路径的 Schema 选择、Provider-specific 响应提取和端到端验收。 |
| 第三阶段：文本格式解析 | 未开始 | 为 XML/Markdown 等定义明确 grammar 和 parser；示例仅为设计草案。 |
| 第四阶段：TTS 分段与标签 | 分段消费已实施；标签未开始 | 文本平台使用拼接文本，TTS 按 `segments[].speech` 分段消费；后续由 TTS 适配器负责 Prompt 注入、标签清理和 Provider-specific 验收。 |
| 文档与集成验收 | Core 文档已同步；外部验收未完成 | 外部插件依赖、Provider 实例、平台投递和 TTS 端到端仍需分别验收。 |

阶段 2–4 不得仅凭接口声明启用；每种策略都需经过实际请求构造、解析语义校验和 Provider/模型数据验证。

## 5. 代码所有权与影响面

- [`expression_agent.py`](../../../../astrbot/core/interaction/expression_agent.py)：结果类型、动态 schema、Prompt、tool-call 提取、字段校验及 effect 纠正流程。
- [`output_contract.py`](../../../../astrbot/core/output_contract.py)、[`interfaces.py`](../../../../astrbot/core/prompt/render/interfaces.py)：通用契约与 renderer 编译；其中有些策略类型是通用基础设施，不表示 Persona 已使用。
- [`middleware.py`](../../../../astrbot/core/interaction/middleware.py)：Personal Response Plan 请求、`turn_action` 路由与 silent 限制。
- [`output_controller.py`](../../../../astrbot/core/interaction/output_controller.py)、[`turn_state.py`](../../../../astrbot/core/interaction/turn_state.py)：即时/最终/插件输出，结果贡献、可见文本和重复回复仲裁状态。
- [`contributors.py`](../../../../astrbot/core/interaction/contributors.py)：只读 `InteractionResultView` 和 `persona_reply | plugin_reply | core_reply` purpose。
- [`interaction.md`](../../modules/interaction.md) 与 [`output-contract.md`](../output-contract.md)：当前运行和扩展接口说明。

## 6. 验收与发布边界

当前代码验收要求：

1. Persona 成功响应必须带 `persona_expression` tool call；纯文本不得被误认为成功。
2. Canonical 顶层字段必须精确匹配，`tendency` 八维和值域有效。
3. `segments[].speech` 按顺序拼接成文本平台使用的整合文本；TTS 不使用拼接结果，而是按原分段顺序逐段合成。
4. `reply / delegate / silent` 由调用场景限制并驱动 Personal 路由。
5. `actions` 和 `effect_calls` 维持不同含义与消费者。
6. 同文本但动作、心理想法或情绪状态变化的 Core 最终回复不能被错误去重。
7. Persona 改写的插件输出把结构化状态传给 `plugin_reply` contributors；直接插件输出保持 direct 路径。

阶段 2–4 还需补上各自的 Provider/格式/TTS 验收。当前已有定向测试覆盖上述部分运行时边界；完整 Provider 矩阵、真实平台交付和外部插件兼容不应据此标记完成。
