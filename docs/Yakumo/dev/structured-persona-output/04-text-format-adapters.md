# 第三阶段：XML、Markdown 等文本格式适配

**状态：已实现首版生产适配。** Provider 页面和 Persona Response 共用语义 XML grammar、语义 Markdown 标题 grammar；Persona Response 只有在配置明确选择 XML/Markdown 时才启用对应 parser，默认仍为 tool call。

## 目标

为无法稳定提供协议级 tool call 或原生结构化输出的特定模型，设计明确的文本格式和解析器。文本格式只改变 Provider wire format；业务结果仍必须转换为同一个 Canonical Persona Schema，并经过与其他策略相同的校验。

本阶段不是通用自然语言抽取功能。普通聊天文本、随意排版的 Markdown 或近似 XML 都不能被猜测成成功的 Persona 结果。

## XML 适配要求

生产 XML grammar 固定根节点为 `<output>`，直接使用语义字段节点，例如 `<turn_action>reply</turn_action>`、`<segments><segment>…</segment></segments>`、`<actions><action>lower_head</action></actions>` 和 `<tendency><Joy>8</Joy></tendency>`。字符串直接使用节点文本，数值使用十进制文本，布尔使用 `true/false`，`null` 使用空节点；XML 中不嵌入 JSON 字面量。解析器会先恢复统一对象，再执行 Canonical Schema 校验，并拒绝未知、重复或带属性的字段：

- 必填节点、字段顺序无关、字段名大小写固定，重复节点直接失败。
- 文本转义、空字符串和空数组的表示方法。
- effect_calls 的 name 与 arguments 如何匹配本轮动态 effect schema。
- 未知节点、缺字段、多余字段和格式错误时的失败行为。

解析后必须重新进行 Canonical Schema 校验。不能忽略未知节点、自动填充缺失情绪值或从其他文本片段推断缺失字段。

## Markdown 适配要求

生产和诊断使用同一语义 Markdown grammar：首行为 `# output`，字段使用标题表示，数组使用 `segment`、`action`、`effect_call` 等重复的单数标题，标量值写在标题下一行。解析结果会恢复为统一对象后再校验；不能把 JSON 作为 Markdown 的载荷。标题层级、重复字段和字符串行格式均按 parser 的固定规则处理：

- 标题、字段名及大小写固定；多段 speech 按 segment 顺序解释。
- actions 列表和八维 tendency 采用唯一合法的重复标题表示。
- 动态 effect_calls 及嵌套参数使用语义标题表示。
- 标题级别、额外说明、重复字段和未知字段按 parser 规则拒绝。

普通 Markdown 对话不能作为结构化输出。解析器不得依赖宽松的标题匹配或模糊文本提取来补全对象。

## 统一解析与失败策略

计划中的处理顺序是 Provider 原始响应、格式专用 parser、Canonical 字段与类型校验、请求场景与跨字段语义校验，最后生成 PersonaExpressionResult。

解析失败时记录明确原因，并按后续确定的受限纠正策略处理或失败。不能将错误文本部分解析后生成表面完整、含义不确定的结果。

## 启用条件

某一格式只有在 grammar、Prompt、parser、Schema 校验和 provider/model 实测均准备好后，才可按特定组合启用。验收须覆盖三个顶层字段、segments 内的八维 tendency、silent 规则、动态 effect_calls、流式/非流式响应和格式错误。

XML、Markdown 不作为 JSON/tool-call 的隐式 fallback，也不因此改变 Canonical Schema 或字段消费者。
