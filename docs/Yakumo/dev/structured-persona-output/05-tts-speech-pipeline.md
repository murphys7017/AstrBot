# 第四阶段：TTS 与 speech 处理

**状态：未实施。** 当前结构化协议只定义 speech 为用户可见文本和输出层交给 TTS 的文本来源；Persona Prompt 尚未按 TTS 标签规范注入要求，Core 也没有 Persona speech cue 数组或统一的标签清理链路。

## 当前边界

- Persona 的 speech 是当前用户可见文本和 TTS 文本输入来源。
- 当前执行顺序是 Persona 先生成 speech，OutputController 再把 Plain 文本交给 synthesize_text；TTS 调用发生在 Persona Prompt 完成之后。
- actions、thought、tendency 和 effect_calls 不会自动拼接进 speech。
- speech_cues、phrase_index、before、after 等外置时序结构不是 Canonical Schema。
- 个别 TTS Provider 会格式化自己的合成请求。例如 [MiMo TTS adapter](../../../../astrbot/core/provider/sources/mimo_tts_api_source.py) 可将 style/dialect 包成 `<style>...` 前缀加到 TTS 请求文本；这是合成请求的 Provider-specific 处理，不会反向注入 Persona 生成 Prompt，也不提供通用 speech 标签解析或清理。

## 目标设计

需要标签的语音能力必须把其格式要求注入生成 speech 的模型请求 Prompt，再由模型将标签直接写进 speech 的正确位置。TTS 接收带内嵌标签的原始 speech 文本，才能保持标签与词句的时序关系。

后续实现应明确：

1. 如何从当前已配置的 TTS Provider 获取支持的标签、语法和限制。
2. 如何在发起 Persona 生成请求前，由对应的 TTS 适配层或 Prompt 适配层注入匹配的要求。
3. 如何把内嵌标签与普通文本一起传给 TTS，而不是从平行字段推断插入位置。
4. 哪些标签只供合成控制使用，以及文本展示或其他消费者应在哪个边界获得清理后的文本。
5. 标签非法、缺失或目标 TTS 不支持时的诊断与处理方式。

清理逻辑不得破坏送入 TTS 的标签和文本顺序。标签语法及清理范围须按目标 TTS Provider 分别定义，不能让 Persona Core 猜测厂商私有标记。

## 与其他字段的关系

- speech：唯一承载语音标签和文本时序的结构化输出字段。
- thought：角色心理想法，不进入用户文本或 TTS。
- tendency：角色当前情绪。是否以及如何影响语音生成，需由未来适配方案明确，当前不能当作已生效的 TTS cue。
- actions：动作意图数组，由独立动作模型或插件解释，不进入 TTS 文本。
- effect_calls：插件 effect 调用，保持现有独立消费链路。

本阶段不得重新引入与 speech 并行的通用 cue 数组。TTS 标签仍属于 speech 内容的一部分，字段之外的数据不能代替其时间位置。

## 验收要求

启用前按目标 TTS Provider 验证 Prompt 注入、标签生成、原始 speech 到 TTS 的顺序保真、文本侧清理边界以及失败诊断。没有针对某种 Provider 的注入和解析实现时，不应声称该 Provider 已支持 Persona 内嵌 TTS 标签。

