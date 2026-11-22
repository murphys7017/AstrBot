# 人格中心化、统一身份与长期记忆架构调整总计划

## 文档状态

- **状态**：代码已实现，待真实运行验收
- **计划版本**：v1
- **编写时间**：2026-11-22
- **适用项目**：AG99、AstrBot Core、LivingMemory
- **风险等级**：高。计划会触及 Prompt 公共扩展点、身份作用域和插件兼容边界。
- **当前实现**：Phase 1–3 已落地，Phase 4 的运行时验收和旧内置长期记忆开关仍需在重启后确认

## 1. 目标

本计划把当前以适配器入口为中心的部分结构，收口为以 Persona Runtime 为核心的结构。

目标包括：

1. 让适配器只负责平台输入、路由字段、平台能力和消息输出。
2. 让 Persona Runtime 维护统一的人格实例、交互上下文和身份绑定。
3. 为跨渠道用户提供一个可选的统一身份字段。
4. 为记忆提供一个稳定、可选择的 Prompt 注入点。
5. 让 LivingMemory 成为长期记忆的主要提供者。
6. 让配置绑定的身份使用统一作用域。
7. 用配置和运行时映射解决身份切换，不做数据库回填。

## 2. 非目标

本阶段不包含以下内容：

- 多人格实例调度和人格路由平台化。
- 现有记忆数据库的迁移、合并或批量重写。
- C++ Runtime 的架构调整。
- AG99live TypeScript 或 C++ 表现链路重写。
- 重新设计 Adapter 协议或删除平台原始身份字段。
- 新建一套独立于 Prompt ContextPack 的记忆总线。
- 让 Prompt 收集阶段写入长期记忆。

## 3. 当前基线

### 3.1 Prompt 已有记忆能力

Prompt 系统已经存在内置记忆插槽和插件扩展挂载点：

- 内置插槽包括 `memory.topic_state`、`memory.short_term`、`memory.experiences`、`memory.long_term_memories` 和 `memory.persona_state`。
- 插件扩展挂载点已经包含 `memory`。
- 记忆扩展会进入上下文区域，由目标投影和渲染器处理。
- Context View 已经区分 `turn_plan`、`olv_stream`、`final_result`、`progress` 和 `proactive`。

实现位置见 [Prompt 扩展类型](../../../../astrbot/core/prompt/extensions/types.py)、[Context View](../../../../astrbot/core/prompt/context_views.py) 和 [Prompt 模块说明](../../modules/prompt.md)。

### 3.2 LivingMemory 的当前接入方式

LivingMemory 已通过结构化 `PromptExtension` 使用 `memory` 扩展挂载点。旧的 `collect_prompt_messages` 注入实现已退出，当前 collector 只读取已完成的本地召回快照。

结构化扩展由 Core 统一做目标投影、Context View 过滤和上下文区域渲染。

### 3.3 当前身份作用域问题

LivingMemory 已有 `identity_aliases` 配置。用户作用域当前包含平台前缀，因此同一个人通过多个平台进入时，仍可能得到不同作用域。

canonical identity 只参与用户作用域的身份键解析，不覆盖 `memory_scope_mode` 和 `isolated_sessions` 的既有规则。session、global 和 legacy 模式继续保持原语义。

## 4. 目标架构

```text
平台适配器
  -> 标准事件与平台原始字段
  -> Persona Runtime 身份解析
       -> canonical_user_id（仅绑定身份有值）
       -> Persona 实例与交互生命周期
       -> Prompt ContextBuilder
            -> Conversation History
            -> LivingMemory Recall Snapshot
            -> Desktop / Plugin / Capability Context
            -> Target Projection
            -> Provider Renderer
       -> Persona Expression
       -> Output / Delivery Receipt

LivingMemory
  -> 按身份和人格读取长期记忆
  -> 发布只读 Prompt memory extension
  -> 按交互完成事件写入长期记忆

```

## 5. 所有权边界

| 对象 | 唯一责任方 | 允许其他组件读取的内容 |
| --- | --- | --- |
| 平台原始身份 | Adapter / Event | sender、platform、session、group 等原始字段 |
| 统一身份 | Persona Runtime / Identity Resolver | `canonical_user_id` 和绑定来源 |
| 人格定义 | Persona 配置与 Persona Runtime | 静态人格快照 |
| 长期记忆 | LivingMemory | 召回快照、记忆注入内容、作用域诊断 |
| Prompt 事实 | Prompt ContextBuilder | 只读 ContextPack 和目标投影视图 |
| 平台输出 | Adapter / Output Runtime | 输出意图、媒体和投递回执 |

任何组件都不应通过读取另一组件的私有数据库来建立第二条事实链。

## 6. 实施阶段

### Phase 0：文档与观测准备

冻结当前行为描述，记录 Prompt、LivingMemory 和身份作用域的现状。

交付物：

- 本计划文档集。
- 现有注入路径、作用域和插件入口清单。
- 不修改数据的观测日志字段。

完成条件：能够区分当前路径、目标路径和兼容路径。

### Phase 1：统一身份契约

建立可选的 canonical identity 字段和绑定解析规则。

交付物：

- 身份字段契约。
- 适配器原始字段与统一身份的映射规则。
- 身份绑定集合的配置示例。
- 未绑定身份的兼容回退规则。

完成条件：在用户作用域模式下，同一绑定身份在两个渠道产生相同的长期记忆作用域，其他作用域模式和未绑定身份行为不变。

### Phase 2：Prompt 记忆注入点

将 `memory` 扩展挂载点变成可按 Context View 选择的结构化注入点。

交付物：

- `extension.memory` 的 Persona 视图可见性规则。
- LivingMemory 记忆注入配置契约。
- 记忆顺序、预算、目标和失败策略。

完成条件：记忆出现在上下文区域的稳定位置，未选中的 View 不包含记忆，且不会重复注入。

### Phase 3：LivingMemory 迁移

让 LivingMemory 成为长期记忆的实际提供者，使用结构化 Prompt 扩展发布召回快照。

交付物：

- 结构化 Prompt collector。
- canonical identity 到作用域的解析。
- 内置长期记忆重复注入的关闭方案。
- 旧临时消息路径的退出条件。

完成条件：普通对话、OLV、主动 Persona 和最终表达都能按配置读取 LivingMemory，数据写入仍只由 LivingMemory 负责。

### Phase 4：切换与旧路径退出

关闭重复的内置长期记忆注入和 LivingMemory 临时消息路径，保留必要兼容读取。

交付物：

- 配置切换说明。
- 运行时诊断和回滚开关。
- 真实运行验收结果。
- 当前实现文档同步。

完成条件：单一长期记忆来源、单一结构化 Prompt 注入路径和可回滚的配置边界成立。

## 7. 数据策略

本计划采用 add-only 迁移策略：

- 不删除已有记忆。
- 不改写已有记忆的 scope 字段。
- 不改变普通用户已有的作用域规则。
- 用户作用域模式下的新绑定身份使用新的 canonical scope。
- 旧作用域数据保留在原位置，是否迁移留到后续独立计划。

这意味着指定用户的旧平台记忆不会自动合并到新作用域。需要旧数据时，再使用 LivingMemory 已有的作用域迁移能力进行显式操作。

## 8. 兼容与回滚

每个阶段都保留以下回滚点：

- 关闭 LivingMemory Prompt 注入配置，恢复无长期记忆注入。
- 回滚 LivingMemory 插件版本，恢复包含旧临时消息路径的版本，直到结构化路径完成真实验收。
- 未提供 canonical identity 时继续使用平台和 session 组合。
- 内置 Memory 只读兼容服务暂不删除。

回滚只能恢复运行路径，不能自动撤销已经写入的新 canonical scope 数据。

## 9. 总验收标准

1. 用户作用域模式下，同一绑定用户通过两个渠道发送消息时，LivingMemory 使用同一个 canonical scope。
2. 未绑定用户和其他作用域模式继续使用当前配置的作用域规则。
3. Prompt 只在配置选中的 Context View 注入 LivingMemory 内容。
4. 记忆位于上下文区域，顺序稳定，且不追加到当前用户消息之后。
5. 内置 Memory 和 LivingMemory 不产生重复长期记忆注入。
6. Persona、Core、Progress 和 Proactive 的目标隔离保持有效。
7. LivingMemory 召回失败时不阻塞普通对话，且有可追踪诊断。
8. 现有 Adapter、AG99live 和平台输出链无需改变外部消息协议。
9. 文档、配置、日志和实际运行结果与源码一致。
