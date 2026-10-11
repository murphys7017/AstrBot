# 第一阶段：Persona tool-call 迁移

**状态：表达与 effect 双通道已实施。** 首轮要求同响应返回所有启用通道；若首轮漏项，Core 只补缺失通道一次。Persona Response 也允许显式选择 JSON/XML/Markdown 表达格式；effect 始终走独立的协议级 tool call。

## 1. 实际契约

表达通道的 `persona_expression` 契约为：

```text
mode = tool_call
strict = true
preferred_tool_name = persona_expression
allow_text_fallback = false
```

`persona_expression` 只包含 `turn_action` 和 `segments`，并拒绝其他字段。`segments` 是按动作或状态变化排列的数组，每项包含 `speech`、`actions`、`thought` 和 `tendency`。当且仅当当前事件有已注册且适用的 effect 时，Provider 才会同时收到独立的 `persona_effect_batch` terminal tool；它的参数只包含 `effect_calls`，item schema 根据适用的 effect 注册动态生成。正常生成时，两路调用必须在同一模型响应中返回，不为 effect 单独发起模型请求；已解析的必发 effect 未通过校验时，现有校正流程会额外请求模型修复 effect batch。无适用 effect 时不提供该工具，聚合后的内部结果将 `effect_calls` 置为空数组。

正常路径要求每个启用通道在同一模型响应中恰好出现一次。运行器收到任一 terminal tool call 后就结束该轮，因此 Provider 可能只返回其中一个通道。双通道启用时，缺失的 `persona_expression` 或 `persona_effect_batch` 会触发一次隔离的定向补全请求；补全请求只开放缺失通道，不开放业务工具，也不重复请求生命周期 hooks。若首轮两路都缺失，则先补表达，再基于补全后的分段补 effect。补全后仍缺失时失败；重复通道或 effect batch 顶层结构无效仍直接拒绝。已解析 batch 中的必发 effect 不完整或参数无效时，也会沿用一次 effect-only 校正；校正输入包含原始分段及其索引，避免 per-segment effect 丢失对应关系。

调用场景会限制 `turn_action` 枚举。普通 visible-reply 和插件文本改写只允许 `reply`；Personal Response Plan 可选 `reply / delegate`，允许静默的群聊候选才会开放 `silent`。必发 effect 数量由注册 effect 元数据和当前是否允许 silent 共同决定。

## 2. Prompt 与解析校验

Persona system prompt 声明表达字段及 segment 内字段语义；存在适用 effect 时再声明 effect 通道要求。request prompt 按本轮任务说明 `reply / delegate / silent`、source text、progress 和 empty speech 等约束。`tendency` 明确表示角色当前八维情绪强度，固定为 Plutchik 八维，每项应为 `0..10` 整数；Core 对整数越界值执行边界裁剪。

解析流程分别读取表达 payload 和本轮要求的 effect batch。表达可来自指定的 `persona_expression` tool call，或由所选 JSON/XML/Markdown parser 读取；适用 effect 始终由 `persona_effect_batch` tool call 读取。首轮缺失通道时，定向补全后的 payload 会并入原响应结果；仍缺失或重复任一必需通道都会拒绝本次结果。两个 payload 校验后才合并为内部 `PersonaExpressionResult`。校验包括：

- 表达 payload 只包含 `turn_action`、`segments`；effect payload 只包含 `effect_calls`。
- `turn_action` 转成已知枚举并符合本次请求允许范围。
- `speech`、`thought` 类型有效，`actions` 为非空字符串组成的数组。
- `tendency` 恰好有八个规定键，值应是非 bool 的 `0..10` 整数；整数越界值在进入内部结果前裁剪到 `0` 或 `10`。
- effect 调用按本轮动态 schema 解析；无效或未注册调用会被丢弃并记录 parse issue。硬性 effect 缺失、无效或数量不符会失败或进入既有一次纠正流程。
- `silent` 仅在请求允许时有效，且表达的 `segments` 必须为空；若有适用 effect 通道，它仍需返回空 `effect_calls`。

Provider/renderer 能力在发请求前核对。选择 XML/Markdown/JSON 表达格式时，格式配置只适用于表达 payload；适用的 effect 仍要求同一响应能够返回独立 terminal tool call。候选 Provider 必须同时满足本轮所需的表达格式和 effect 通道能力；不满足时按现有候选策略筛除或明确失败。

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
