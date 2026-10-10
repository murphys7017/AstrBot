# 第一阶段：当前 tool-call 迁移

**状态：已完成，且作为默认路径保留。** Persona Response 现在也允许显式选择 JSON/XML/Markdown 文本格式；本阶段冻结的 tool-call 契约仍是默认和回退基线。

## 1. 实际契约

`build_persona_expression_output_contract_for_effects()` 生成以下契约：

```text
mode = tool_call
strict = true
preferred_tool_name = persona_expression
allow_text_fallback = false
```

Schema 顶层精确要求三个必填字段：`turn_action`、`segments`、`effect_calls`，并拒绝其他顶层字段。`segments` 是按动作或状态变化排列的数组，每项包含 `speech`、`actions`、`thought` 和 `tendency`。`effect_calls` 的 item schema 根据本轮启用并适用于当前事件的 effect 注册动态生成；没有 effect 时仍保留必填空数组字段。

调用场景会限制 `turn_action` 枚举。普通 visible-reply 和插件文本改写只允许 `reply`；Personal Response Plan 可选 `reply / delegate`，允许静默的群聊候选才会开放 `silent`。必发 effect 数量由注册 effect 元数据和当前是否允许 silent 共同决定。

## 2. Prompt 与解析校验

Persona system prompt 声明三个顶层字段及 segment 内字段语义；request prompt 再按本轮任务说明 `reply / delegate / silent`、source text、progress 和 empty speech 等约束。`tendency` 明确表示角色当前情绪，固定为 Plutchik 八维，每项 `-10..10` 整数。

解析流程优先读取指定的 `persona_expression` tool call。选择 `tool_call` 时，严格 Persona 契约缺少该 tool call 以 `missing_persona_expression_tool_call` 失败；选择文本格式时则由对应 parser 读取响应，再执行相同 Payload 校验。Payload 校验包括：

- 顶层字段精确匹配，不多不少。
- `turn_action` 转成已知枚举并符合本次请求允许范围。
- `speech`、`thought` 类型有效，`actions` 为非空字符串组成的数组。
- `tendency` 恰好有八个规定键，值是非 bool 的 `-10..10` 整数。
- `effect_calls` 按本轮动态 effect schema 解析；无效或未注册调用会被丢弃并记录 parse issue。硬性 effect 缺失、无效或数量不符会失败或进入既有一次纠正流程。
- `silent` 仅在请求允许时有效，且 `segments`、`effect_calls` 必须为空。

Provider/renderer 能力在发请求前核对。Persona 不接受编译为 `prompt_only` 的候选 Provider；若主 provider 不支持，可按现有候选策略查找支持协议级 tool call 的 provider，否则请求失败。

## 3. 运行时消费

- Middleware 根据 `turn_action` 决定完成回复、委派 Core 或静默。
- 用户可见文本使用 `segments[].speech` 按顺序拼接的整合文本。
- TTS 消费 `segments[].speech` 的原始分段，按顺序逐段合成；不把整合文本作为单个 TTS 请求。
- `thought` 和 `tendency` 不拼入用户文本或 TTS，也不进入普通对话历史。
- `actions` 是独立的简单动作意图数组；Schema 只校验非空字符串，简单意图且不带参数由 Prompt 要求；不会替代插件 effect 调用。
- `effect_calls` 保持插件所有权。Core 负责将当前结果放进 `InteractionResultView`，由有权消费该 effect 的插件解释和输出。
- Core 记录即时 Persona 的动作、心理想法和情绪快照。若 Core 最终文本与即时文本相同，只有在这三项状态也相同时才抑制重复发送。
- `capture_plugin_output(mode="persona")` 将模型改写结果交给 `plugin_reply` result contributors；`mode="direct"` 不进行 Persona 改写，保持原路径。

## 4. 旧输出字段

Core schema 和 `PersonaExpressionResult` 不再包含 `spoken_reply`、`speech_cues` 等别名。结构精确校验会拒绝旧字段混入新的 tool-call payload。任何仍依赖这些字段的外部插件或 adapter 都必须按其自身发布与部署流程迁移；Core 不提供兼容映射。

TTS 标签仍未在本阶段实现。当前已经保留 `segments[].speech` 的分段边界交给 TTS；注入 TTS provider 标签和按 TTS 要求清理输出属于第四阶段。

## 5. 实施与验证记录

- `007b6cb5d` 完成首轮 schema、Prompt、解析和运行时迁移；`964fbf9ad` 记录第一阶段事实。
- 后续修复 `eda87adb8` 让 Persona 改写的插件结果携带完整结构化字段进入 Contributor，并修正相同可见文本但 Persona 状态不同导致错误抑制的问题。
- 2026-10-09 对 `tests/unit/test_interaction_plugin_runtime.py` 的定向运行通过 44 项，覆盖 `plugin_reply` 字段与 extras 投递、即时字段快照和状态变化时不去重。Ruff check、Python 编译、`git diff --check` 通过。
- 既有第一阶段记录包含 Persona schema 相关定向测试 58 项通过。更宽的历史组合运行有 6 项未修改 fixture/assertion 失败；不能据此声称全量测试或真实平台验收通过。
- 本记录不声称已完成 Provider 全矩阵、外部插件迁移、应用启动或真实 Provider/TTS/平台端到端验收。
