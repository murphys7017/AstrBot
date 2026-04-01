# Prompt Progress And Memory Reference

记录当前 AstrBot prompt/context 优化进度、`mk1` 项目的参考价值，以及 `MemoryOS` 的接入方向决策。

## 当前阶段定位

当前阶段仍然属于 prompt/context 系统的第一阶段：

- 先收集
- 先准备结构化数据
- 先把链路打通
- 先保证日志可见
- 不急着进入 render
- 不急着替换现有 `ProviderRequest` 注入行为

当前的核心原则没有变化：

- `Collect -> Select -> Render -> Execute`
- 现在只做 `Collect`

## 当前已完成进度

### 1. Persona collect 已完成基础收口

当前已具备：

- `persona.prompt`
- `persona.segments`
- `persona.begin_dialogs`
- `persona.tools_whitelist`
- `persona.skills_whitelist`

当前状态：

- `PersonaCollector` 已接入 `ContextPack`
- 支持 legacy persona prompt 解析为 `persona.segments`
- 支持完整 persona 日志输出
- 仍然保留旧的 persona 注入行为作为真实运行路径

对应文档：

- `docs/Yakumo/dev/persona-context-collect.md`
- `docs/Yakumo/dev/persona-segments-prepare.md`
- `docs/Yakumo/dev/persona-format-current.md`

### 2. Input collect 已完成基础收口

当前已具备：

- `input.text`
- `input.images`
- `input.quoted_text`
- `input.quoted_images`
- `input.files`

当前状态：

- `InputCollector` 已接入默认 collect 链路
- 已完成当前输入、引用输入、附件输入的结构化整理
- 已具备最小测试覆盖
- 当前输入日志已经可用于调试后续 renderer

对应文档：

- `docs/Yakumo/dev/input-context-collect.md`

### 3. 当前默认 collect 链路

当前默认 collectors 为：

- `PersonaCollector`
- `InputCollector`

当前链路只负责：

- 读取数据
- 标准化结构
- 记录日志
- 写入 `ContextPack`

当前没有做：

- selector
- renderer
- 用 collect 结果反向改写 `req.system_prompt`
- 用 collect 结果替换旧的 `astr_main_agent.py` prompt 注入逻辑

## 当前 prompt 优化还没完成的部分

### collect 层仍然缺失的重要部分

当前 catalog 中，仍然未落地或未独立设计的部分主要有：

- `conversation.history`
- `knowledge.snippets`
- `capability.skills_prompt`
- `capability.tools_schema`
- `capability.subagent_handoff_tools`
- `capability.subagent_router_prompt`
- `policy.safety_prompt`
- `policy.sandbox_prompt`
- `session.datetime`
- `session.user_info`

但经过当前讨论，`conversation.history` 不再建议直接做成一个简单 collector。

### 关于 `conversation.history` 的新判断

原先的直觉是补一个 `ConversationHistoryCollector`，直接收集历史消息。

现在新的判断是：

- 不建议把这一块只做成“历史消息收集器”
- 更合理的是把它升级为“记忆模块 + collector 读取”

目标不再只是：

- 最近历史

而是拆成：

- 长期记忆总结
- 短期记忆总结
- 当前话题
- 可选对话状态

也就是说，这一块更接近：

- `ConversationMemoryService`
- `ConversationMemoryCollector`

而不是单纯的：

- `ConversationHistoryCollector`

## `mk1` 对当前 AstrBot 的参考价值

当前参考项目：

- `D:\\BaiduSyncdisk\\Code\\mk1`

这个项目对 AstrBot 的价值，不是照搬它的全部实现，而是提供了几条很清晰的设计原则。

### 1. 同步回复与异步记忆更新分离

`mk1` 的核心思路之一是：

- 同步链路负责快速回复
- 回合后链路负责反思、摘要、状态更新、记忆写入

参考文档：

- `D:\\BaiduSyncdisk\\Code\\mk1\\docs\\gpt-整体流程.md`

对 AstrBot 的启发：

- 后续记忆系统不应直接塞进当前主请求同步链路
- collector 不应该一边 collect 一边生成摘要
- 更适合新增 post-turn memory update 入口

### 2. Assembler 与 MemorySystem 职责分离

`mk1` 中：

- `MemorySystem` 负责存储与更新
- `GlobalContextAssembler` 只负责读取并组装

参考位置：

- `D:\\BaiduSyncdisk\\Code\\mk1\\src\\ContextAssembler\\DefaultGlobalContextAssembler.py`
- `D:\\BaiduSyncdisk\\Code\\mk1\\docs\\gpt-整体流程.md`

对 AstrBot 的启发：

- Prompt collect / render 模块不应承担记忆生成责任
- 记忆生成和 prompt 组装应是两个边界清晰的系统

### 3. 当前话题 / 对话状态不应混进摘要

`mk1` 将 chat state 单独建模，而不是把它粗暴塞进 summary。

参考位置：

- `D:\\BaiduSyncdisk\\Code\\mk1\\src\\ChatStateSystem\\DefaultChatStateSystem.py`
- `D:\\BaiduSyncdisk\\Code\\mk1\\config\\system_prompt.yaml`

对 AstrBot 的启发：

- `current_topic`
- `chat_state`

更适合单独建模，不应该简单附着在 `conversation.history` 上。

### 4. 摘要先裁决，再生成

`mk1` 不会机械地每 N 轮总结，而是先判断：

- `merge`
- `new`
- `none`

参考位置：

- `D:\\BaiduSyncdisk\\Code\\mk1\\src\\MemorySystem\\MemoryStore\\DialogueStorage.py`
- `D:\\BaiduSyncdisk\\Code\\mk1\\config\\system_prompt.yaml`

对 AstrBot 的启发：

- 记忆更新策略最好是策略驱动
- 后续如果做记忆更新，不应只是简单轮数阈值

### 5. PromptBuilder / PromptNode 结构很适合 renderer

`mk1` 的另一个高价值参考是：

- `PromptBuilder`
- `PromptNode`

参考位置：

- `D:\\BaiduSyncdisk\\Code\\mk1\\src\\tools\\PromptBuilder.py`
- `D:\\BaiduSyncdisk\\Code\\mk1\\src\\DataClass\\PromptNode.py`

对 AstrBot 的启发：

- 后续 renderer 很适合走树状节点模型
- 这和当前 persona segment 想要的 tag/XML 风格天然匹配
- 后面如果实现：
  - `<persona>`
  - `<identity>`
  - `<memory>`
  - `<current_topic>`

  这类结构化输出，可以直接参考这种设计思路

### 6. 配置驱动的路由与来源控制值得在 selector 阶段参考

`mk1` 的 `template_input.yaml` 将：

- intent
- source
- retrieve
- token_budget

这类策略显式配置化。

参考位置：

- `D:\\BaiduSyncdisk\\Code\\mk1\\config\\template_input.yaml`

对 AstrBot 的启发：

- 后续 selector 阶段可以考虑引入策略 YAML
- 用配置明确控制：
  - 什么情况下读取 memory
  - 什么情况下读取 KB
  - 什么情况下只保留短期上下文

## 当前对 `mk1` 的实际采纳结论

当前决定采纳的是“设计思想”和“模块边界”，不是直接合并代码。

当前明确要借鉴的点：

- post-turn update 思路
- memory service 与 assembler 分离
- current topic / chat state 单独建模
- PromptBuilder 风格的 renderer 设计
- selector 阶段的配置驱动思路

当前不直接照搬的点：

- 不直接把 `mk1` 的总结逻辑塞进主链路
- 不直接引入它的完整单体 memory runtime
- 不直接把其 MemorySystem 实现整体复制到 AstrBot

## 对 MemoryOS 的新决策

经过比较后，当前对 `MemoryOS` 的决策发生了变化。

早期备选方向包括：

- 作为外部服务
- 作为 MCP
- 直接在 AstrBot 中复用其思路

当前新的决定是：

- 直接将 `MemoryOS` 源码加入 AstrBot
- 单独为其配置 LLM / embedding / memory backend
- 不走 MCP
- 不依赖 HTTP 网关调用

这样做的原因：

- 集成边界更直接
- 便于后续直接代码调用
- 更容易与 AstrBot 的 session / conversation / prompt collect 链路对齐
- 可以在代码层更细粒度控制 memory update 与 memory retrieval

### 当前对 MemoryOS 的定位

当前希望 `MemoryOS` 承担的职责是：

- 记忆存储
- 记忆更新
- 记忆检索
- 用户画像或长期记忆管理

当前不希望由它直接主导的部分：

- 当前输入 collect
- persona collect
- prompt renderer
- 当前话题的渲染结构

也就是说，当前目标更像：

- `MemoryOS = memory backend / memory engine`
- `AstrBot prompt collect = 读取和组织层`

## 当前对 Memory 模块的建议边界

如果后续在 AstrBot 内落 Memory 模块，推荐边界如下：

### Memory 模块负责

- 长期记忆
- 中期记忆
- 用户画像
- 相关记忆检索
- 回合后记忆更新

### Prompt collect 负责

- 读取当前会话需要的 memory snapshot
- 放入 `ContextPack`
- 记录调试日志

### Renderer 负责

- 把 memory 相关 slot 渲染成目标结构
- 决定：
  - 放入 system
  - 放入 history
  - 放入独立 `<memory>` 段

## 当前文档结论

到当前为止，AstrBot prompt 优化路线可以总结为：

- `PersonaCollector` 已经完成基础收口
- `InputCollector` 已经完成基础收口
- `conversation.history` 已经不建议按普通 collector 继续推进
- 下一阶段更合理的方向是：
  - 先设计 memory 模块边界
  - 再做 memory collector
  - 最后在 renderer 阶段统一消费

当前 `mk1` 的价值已经明确：

- 它提供了很好的 memory / context / renderer 设计参考
- 尤其适合指导 AstrBot 的下一阶段 prompt 优化

当前 `MemoryOS` 的新方向也已经明确：

- 不是 MCP
- 不是外部 HTTP 服务
- 而是作为源码集成到 AstrBot 内部，作为独立 memory engine 使用
