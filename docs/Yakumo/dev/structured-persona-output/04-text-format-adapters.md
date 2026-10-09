# 第三阶段：XML、Markdown 等文本格式适配

**状态：未实施。** 当前 Persona 主路径不接受 XML 或 Markdown 格式的结构化表达。本阶段只有在 Provider 策略评估表明确有需要时才进入实现。

## 目标

为无法稳定提供协议级 tool call 或原生结构化输出的特定模型，设计明确的文本格式和解析器。文本格式只改变 Provider wire format；业务结果仍必须转换为同一个 Canonical Persona Schema，并经过与其他策略相同的校验。

本阶段不是通用自然语言抽取功能。普通聊天文本、随意排版的 Markdown 或近似 XML 都不能被猜测成成功的 Persona 结果。

## XML 适配要求

XML 方案需要定义固定根节点、字段节点、动作数组表示、八维 tendency 表示，以及动态 effect_calls 与 arguments 的编码方式。还必须规定：

- 必填节点、字段顺序是否无关、大小写规则和重复节点处理。
- 文本转义、空字符串和空数组的表示方法。
- effect_calls 的 name 与 arguments 如何匹配本轮动态 effect schema。
- 未知节点、缺字段、多余字段和格式错误时的失败行为。

解析后必须重新进行 Canonical Schema 校验。不能忽略未知节点、自动填充缺失情绪值或从其他文本片段推断缺失字段。

## Markdown 适配要求

Markdown 需要一个可机读的固定 grammar，例如固定标题或受控代码块；具体形式须通过样例和解析器测试确定。规范至少应说明：

- 标题、字段名及大小写是否固定。
- 多段 speech 如何解释。
- actions 列表和八维 tendency 的唯一合法表示。
- 动态 effect_calls 及嵌套参数的表示方法。
- 代码围栏、额外说明、重复字段和未知字段如何处理。

普通 Markdown 对话不能作为结构化输出。解析器不得依赖宽松的标题匹配或模糊文本提取来补全对象。

## 统一解析与失败策略

计划中的处理顺序是 Provider 原始响应、格式专用 parser、Canonical 字段与类型校验、请求场景与跨字段语义校验，最后生成 PersonaExpressionResult。

解析失败时记录明确原因，并按后续确定的受限纠正策略处理或失败。不能将错误文本部分解析后生成表面完整、含义不确定的结果。

## 启用条件

某一格式只有在 grammar、Prompt、parser、Schema 校验和 provider/model 实测均准备好后，才可按特定组合启用。验收须覆盖六个顶层字段、八维 tendency、silent 规则、动态 effect_calls、流式/非流式响应和格式错误。

XML、Markdown 不作为 JSON/tool-call 的隐式 fallback，也不因此改变 Canonical Schema 或字段消费者。

