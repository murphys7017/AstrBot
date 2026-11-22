# Prompt 记忆注入点计划

## 文档状态

- **状态**：设计/计划
- **所属总计划**：[人格中心化、统一身份与长期记忆架构调整总计划](00-overall-plan.md)
- **实施阶段**：Phase 2
- **风险等级**：中高。影响 Prompt 公共扩展点和多个 Persona Context View。

## 1. 目标

让长期记忆拥有一个明确、结构化、可按调用场景选择的 Prompt 注入点。

注入点应当表达“记忆是上下文事实”，不应表现为一条伪造的用户消息。

## 2. 现有能力

当前 Prompt 已经支持：

- `ContextSlot` 形式的命名事实。
- `memory` 分类。
- `PromptExtensionMount` 的 `memory` 挂载点。
- `PromptContextView` 视图投影。
- Persona 和 Core 的目标隔离。

当前 LivingMemory 使用临时消息路径，因此还需要完成结构化接入。

## 3. 目标接口

LivingMemory 应通过结构化扩展发布召回结果：

```text
plugin_id = livingmemory
mount = memory
value_kind = mapping 或 sequence
meta.targets = ["persona"]
meta.context_views = 选中的 Persona Context View
meta.source = livingmemory
meta.scope = 当前记忆作用域
```

具体 Python 类型以现有 `PromptExtension` 为准，计划不新增第二套扩展类型。

## 4. 注入位置

`memory` 扩展进入上下文区域，推荐顺序为：

```text
system / persona
conversation history
memory extensions
current user input
```

记忆内容应位于当前用户输入之前，让模型把它当作已知上下文处理。

## 5. Context View 选择

建议 LivingMemory 提供以下配置：

```text
prompt_injection.enabled
prompt_injection.context_views
prompt_injection.max_items
prompt_injection.max_chars
prompt_injection.target
```

默认视图：

- `turn_plan`
- `olv_stream`
- `final_result`
- `proactive`

默认不进入 `progress`，因为该视图承担轻量状态反馈职责。

Core 需要完成两项兼容改造：

1. 让 Persona 允许列表包含 `extension.memory`。
2. 让 `memory` 挂载点像 `context` 挂载点一样遵守 `meta.context_views`。

## 6. 目标隔离

长期记忆默认只进入 Persona：

- Persona 可以读取与人格表达有关的召回内容。
- Core 默认不接收 LivingMemory 的用户记忆扩展。
- Personal Policy 和进度请求只按明确配置决定是否接收。
- 插件不能通过记忆扩展获得工具能力。

如未来需要 Core 读取记忆，应单独增加 Core 目标配置和字段白名单，不复用 Persona 默认授权。

## 7. 数据形态

推荐将召回内容规范化为有限条目：

```text
count
items[]
  id
  summary
  category
  importance
  confidence（按目标投影决定是否暴露）
  source
  event_time（可选）
```

Prompt 只读取已完成的 recall snapshot。收集阶段不能触发新的长期记忆写入，也不应直接修改 LivingMemory 数据库。

## 8. 预算和失败策略

- `max_items` 默认保持现有 LivingMemory 召回上限。
- `max_chars` 用于限制 Prompt 体积，不能破坏条目结构。
- 召回失败时跳过记忆扩展，普通 Persona 请求继续执行。
- 召回超时只记录诊断，不成为普通回复的第二个 deadline owner。
- 记忆内容进入 Prompt 前进行敏感字段和调试字段过滤。

## 9. 迁移步骤

1. Core 支持 `extension.memory` 的 View 可见性。
2. LivingMemory 同时保留旧临时路径和新结构化路径，增加一次运行时去重标记。
3. 在测试和实机环境确认结构化路径的顺序、预算和失败行为。
4. 默认切换到结构化路径。
5. 删除或停用旧 `after_user` 临时消息路径。

## 10. 验收

- 选中的 View 可以看到记忆。
- 未选中的 View 看不到记忆。
- 记忆位于上下文区域，不出现在当前用户消息之后。
- 结构化路径不会与临时消息路径重复注入。
- Persona 可以看到记忆，Core 默认看不到。
- 记忆召回失败不阻塞普通回复。
- Prompt 日志能够显示注入来源、条数、字符预算和过滤结果。
