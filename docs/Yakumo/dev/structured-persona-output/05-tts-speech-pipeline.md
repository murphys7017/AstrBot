# 第四阶段：TTS 与 speech 处理

**状态：分段消费已实施；TTS 标签适配未实施。** 当前文本平台收到的是按 `segments[].speech` 顺序整合的一条普通文本；TTS 消费保留每个 speech 分段并按顺序逐段调用。Persona Prompt 尚未按 TTS 标签规范注入要求，Core 也没有通用的标签清理链路。

## 当前边界

- Persona 的 `segments[].speech` 是分段用户可见文本和 TTS 输入来源。
- 文本平台路径先按 `segments[].speech` 顺序整合成一个 Plain 文本，便于一次发送；TTS 路径保留分段，OutputController 按顺序把每个非空 speech 段交给 `synthesize_text`。
- 一个 Persona 结果对应一个文本消息，但可以对应多个有序 TTS Record；每个音频 Record 带有 `parent_message_id`、`persona_result_id`、`persona_segment_index`、`persona_segment_count`、`message_id` 和 `tts_request_id`，用于在并发、取消和插件回调场景下保持消费顺序和关联。
- actions、thought、tendency 和 effect_calls 不会自动拼接进 speech。
- 已存在 Persona 分段时，只允许保持原文或按原边界进行前缀截断。响应 hook 或
  `final_text_override` 任意改写整合文本时，Core 忽略该次改写并记录
  `persona_text_rewrite_requires_segment_boundaries`，保留原始回复；不按旧段长度比例
  猜测新边界，也不把旧动作绑定到改变后的语义。单段也适用；普通非 Persona 文本不受此限制。
  贡献者可以通过 `platform_extras.persona_speech_segments` 提交与最终整合文本完全一致、
  数量相同的逐段文本；贡献者须确保各段语义和原动作仍匹配，语义改变时应先重新生成动作。
  AG99live 的隐藏标记清理按原段逐段处理，使用该路径保持 TTS 文本与动作索引一致。
- speech_cues、phrase_index、before、after 等外置时序结构不是 Canonical Schema；分段本身就是 TTS 的时序边界。
- 个别 TTS Provider 会格式化自己的合成请求。例如 [MiMo TTS adapter](../../../../astrbot/core/provider/sources/mimo_tts_api_source.py) 可将 style/dialect 包成 `<style>...` 前缀加到 TTS 请求文本；这是合成请求的 Provider-specific 处理，不会反向注入 Persona 生成 Prompt，也不提供通用 speech 标签解析或清理。

## 目标设计

需要标签的语音能力必须把其格式要求注入生成各段 speech 的模型请求 Prompt，再由模型将标签直接写进对应 speech 的正确位置。TTS 接收带内嵌标签的原始 speech 分段，才能保持标签与词句的时序关系。

后续实现应明确：

1. 如何从当前已配置的 TTS Provider 获取支持的标签、语法和限制。
2. 如何在发起 Persona 生成请求前，由对应的 TTS 适配层或 Prompt 适配层注入匹配的要求。
3. 如何把内嵌标签与普通文本一起传给 TTS，而不是从平行字段推断插入位置。
4. 哪些标签只供合成控制使用，以及文本展示或其他消费者应在哪个边界获得清理后的文本。
5. 标签非法、缺失或目标 TTS 不支持时的诊断与处理方式。

清理逻辑不得破坏送入 TTS 的标签和文本顺序。标签语法及清理范围须按目标 TTS Provider 分别定义，不能让 Persona Core 猜测厂商私有标记。

## 与其他字段的关系

- segments[].speech：承载语音标签和文本时序的结构化输出字段；平台文本消费使用其拼接结果，TTS 消费其原始分段。
- thought：角色心理想法，不进入用户文本或 TTS。
- tendency：角色当前情绪强度。是否以及如何影响语音生成，需由未来适配方案明确，当前不能当作已生效的 TTS cue。
- actions：动作意图数组，由独立动作模型或插件解释，不进入 TTS 文本。
- effect_calls：插件 effect 调用，保持现有独立消费链路。

本阶段不得重新引入与 `segments[].speech` 并行的通用 cue 数组。TTS 标签仍属于 speech 内容的一部分，字段之外的数据不能代替其时间位置。

## 验收要求

### 逐段就绪、按序投递

普通 `_apply_interaction_tts` 仍逐段合成后返回整条 MessageChain。声明支持段级 finalizer
与提前 flush 的 OLV 独立动作分支，新增最大并发 2 的 TTS 准备和按段汇合、按序投递。
源码与边界检查已完成，尚未现场验收，具体条件见
[低延迟分段投递方案](07-low-latency-segment-delivery.md)。以下为实施与验收边界。

- Core 保留装饰和插件文本修改流程，先确定最终分段，再将 TTS 物化拆为逐段就绪产物。
  每段保留原 segment_index/count 与 parent_message_id、persona_result_id、message_id、
  tts_request_id；空段不改变其他段的原始索引。
- AG99live 分段任务提供按索引读取的结果；每段只等待自己的动作。当前整批 finalizer
  不应被简单重复调用，否则会重复合并 client_objects 和绑定状态。
- 输出协调器只投递连续就绪前缀，后段先完成也必须等待前段；既有中断、断连、重复投递
  检查和 frontend/AstrBot turn ID 映射继续生效。TTS 失败与动作超时分别保留明确状态。
- 文本平台仍只发送一次拼接文本。双输出的 Plain 是文本回显，不是再次生成动作的段。
  附件、effect、普通贡献者与最终历史/after-message 生命周期不得因分段发送重复执行。
- 首批范围建议限定具备分段音频投递能力的平台；普通插件现有整条消息贡献接口不改为
  默认逐段调用。投递超时需沿用明确的整轮预算，不因每段重新计时而无限延长。

现场验收需覆盖两段/三段乱序就绪、动作超时、TTS 失败、首段后中断、断连重置、
文本回显与重复消息。日志分别测首段就绪、首段投递、末段投递；播放时长不计为模型延迟。

已完成的分段链路验证应覆盖：多段 speech 按原顺序合成、文本平台仍收到拼接文本、空 speech 段不生成音频、Record 的分段元数据连续。TTS 标签能力启用前还需按目标 Provider 验证 Prompt 注入、标签生成、原始 speech 到 TTS 的顺序保真、文本侧清理边界以及失败诊断。没有针对某种 Provider 的注入和解析实现时，不应声称该 Provider 已支持 Persona 内嵌 TTS 标签。

