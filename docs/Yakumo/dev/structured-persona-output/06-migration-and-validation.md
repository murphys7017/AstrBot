# 第五阶段：迁移、验证与发布

**状态：第一阶段代码迁移已完成；后续 Provider、文本格式、TTS 和外部依赖验收仍未完成。**

本文把已落地工作和剩余验收分开记录。它不把未来 Provider/TTS 工作表述成已实现能力，也不代表本轮文档更新运行过代码测试。

## 已完成：Canonical Schema 与 tool-call 主路径

当前 Core 使用严格 persona_expression tool call，返回六个必填字段：

- turn_action：按调用场景限制的单值路由动作。
- speech：唯一用户可见表达及当前 TTS 文本来源。
- actions：简单动作意图数组。
- thought：角色简短心理想法。
- tendency：扮演角色当前的 Plutchik 八维情绪，每项为 -10..10 整数。
- effect_calls：按本轮注册和事件筛选结果动态约束的插件 effect 调用数组。

这是一次破坏性迁移。Core 不再接受 spoken_reply 或 speech_cues 等旧字段，也不把旧字段映射到新协议。旧版外部插件、adapter 和客户端若依赖这些私有数据，需自行按其发布流程迁移。

第一阶段代码已覆盖 Prompt、动态 Schema、tool-call 提取和结果校验、Personal 路由、即时/最终输出消费、结果 Contributor 快照，以及 Persona 模式插件输出。当前 Persona 不兼容 Provider 会在请求前排除；缺少 terminal tool call 不被当成成功的文本回复。

## 新功能如何消费结构化数据

新插件或输出功能不应读取 Provider 的原始 tool-call 响应，也不应解析用户可见 speech 来反推动作或情绪。应注册 Interaction Result Contributor，并从只读 InteractionResultView 中读取其负责的数据：

- actions、thought、tendency、turn_action：Persona 结构化状态快照。
- effect_calls：本轮有效的插件 effect 调用；解析器会跳过无效项并把问题记录在结果 metadata，必发 effect 不合规时整次校验会失败或进入一次纠正。在 Contributor 快照中，每一项是含 name、arguments、call_id、plugin_id 和 source 的只读 mapping，消费方只处理自己注册的 effect。
- purpose：区分 persona_reply、Persona 改写的 plugin_reply 和 core_reply。

Contributor 返回 InteractionResultContribution 后，Core 可合并其 platform_extras 或 client_objects。Core 不会自动把 actions、thought 或 tendency 转成平台数据。直接 plugin_direct 输出绕过 Persona 改写链路，因此不会有 Persona Expression 的这些字段。

实现代码示例与注册入口见 [Interaction 模块文档](../../modules/interaction.md) 的“Result Contributor”一节。跨插件输出边界见 [Interaction Output Plugin Contract](../interaction-output-plugin-contract.md)。

## 后续阶段验收清单

### Provider 输出策略

- 按 Provider、模型、endpoint 建立 tool call、JSON mode、原生 JSON Schema 的能力矩阵。
- 使用 Provider 页面 JSON 稳定性测试进行能力验收时，应一并记录所选 Provider/模型、测试模板、10 次字段结构与类型通过数、失败原因和单次延迟；该结果不作为原生 JSON mode / JSON Schema 支持证明。
- 明确 JSON 文本仍由 Core 解析和校验；Provider 的 JSON mode 不等同于 Schema 强制。
- 逐组合验证请求构造、响应提取、动态 effect schema、字段语义、失败行为、延迟和 token 成本。
- 只有测试通过的组合才显式启用；不满足约束时必须提供诊断失败。

### XML / Markdown 等文本格式

- 每种格式先定义完整 grammar、Prompt 适配和明确 parser。
- parser 输出必须通过与 tool-call 相同的 Canonical Schema 和语义校验。
- 覆盖未知字段、缺失字段、非法类型、动态 effect_calls、silent 和格式错误。
- 不允许通过自然语言猜测或模糊解析补全结构。

### TTS 标签

- 按目标 TTS Provider 注入标签规则到生成 speech 的模型请求。
- 确认标签直接嵌在 speech 中，并以原顺序进入 TTS 合成文本。
- 定义面向文本展示的清理边界，不引入平行的通用时序 cue 数组。
- 覆盖不支持标签、非法标签及标签清理失败。

### 插件与平台

- 检查依赖旧字段的外部插件，并按各自的安装/发布范围迁移；Core 不提供双轨兼容。
- 在真实平台确认 Contributor 的 platform_extras/client_objects 被目标 adapter 或客户端消费。
- 验证 Persona 改写插件输出 purpose 为 plugin_reply；direct 插件输出继续遵循 direct 路径。
- 分别确认平台发送、客户端展示、动作模型和 TTS 消费边界。

## 已有验证记录与限制

- 第一阶段曾有 Persona Schema 相关定向测试 58 项通过。
- 2026-10-09 的 plugin runtime 定向运行通过 44 项，覆盖 Persona 改写插件贡献、结构化字段快照和状态变化时的重复回复仲裁。
- 较宽的历史测试组合有未修改 fixture/assertion 失败；这些结果不证明全量测试通过。
- 实际 Provider 全矩阵、第三方插件迁移、真实平台投递以及 TTS 端到端验收仍未完成。

本次文档更新只进行文档审阅与静态一致性检查；没有编译、启动应用或运行代码测试。

