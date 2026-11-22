# LivingMemory 长期记忆迁移计划

## 文档状态

- **状态**：设计/计划
- **所属总计划**：[人格中心化、统一身份与长期记忆架构调整总计划](00-overall-plan.md)
- **实施阶段**：Phase 3
- **风险等级**：高。涉及长期记忆召回、Prompt 注入和作用域兼容。

## 1. 目标

让 LivingMemory 成为 AG99 长期记忆的主要提供者，同时保持它自己的数据库、召回引擎、反思和管理页面所有权。

Prompt 只消费 LivingMemory 已经完成的只读快照。Prompt 不负责记忆写入，也不负责重新解释记忆作用域。

## 2. 责任边界

LivingMemory 负责：

- 用户消息和回合材料的长期记忆写入。
- 记忆索引、召回和反思。
- 记忆作用域解析。
- Prompt 召回快照缓存。
- 结构化 Prompt memory extension。
- 记忆管理、归档和作用域诊断。

AstrBot Core 负责：

- 提供统一身份字段。
- 调度 Prompt collector。
- 进行目标投影、敏感字段过滤和渲染。
- 维护官方 Conversation 和 Prompt ContextPack。

## 3. 当前路径迁移

当前 LivingMemory 通过 `collect_prompt_messages` 返回 `after_user` 临时消息。目标路径改为结构化 `PromptExtension`，挂载到 `memory`。

迁移期间需要保证：

- 单次事件只选择一条注入路径。
- 旧路径仍可通过配置回退。
- 结构化路径不触发额外 LLM 召回。
- 召回快照读取保持同步和快速返回。

当前 collector 见 [prompt_cache_collector.py](../../../../data/plugins/astrbot_plugin_livingmemory/core/prompt_cache_collector.py)。

## 4. 作用域迁移

LivingMemory 先读取 `memory_scope_mode` 和 `isolated_sessions`，再按用户作用域解析 Core canonical identity：

```text
isolated_sessions 命中
  -> 保留原始 session 作用域

memory_scope_mode=user 且有 canonical_user_id
  -> livingmemory:user:canonical:{id}

memory_scope_mode=user 且没有 canonical_user_id
  -> 保留现有 platform + identity 规则

memory_scope_mode=session / global / legacy
  -> 保留对应的现有作用域规则
```

写入、召回、缓存、反思和迁移命令必须调用同一个作用域解析函数，避免出现写入与读取不一致。

已有数据库不执行自动迁移。旧数据只有在显式执行后续迁移命令时才会改写。

当前作用域实现见 [memory_scope.py](../../../../data/plugins/astrbot_plugin_livingmemory/core/memory_scope.py)。

## 5. 配置建议

建议新增或整理以下配置组：

```text
prompt_injection:
  enabled: true
  target: persona
  context_views:
    - turn_plan
    - olv_stream
    - final_result
    - proactive
  max_items: 5
  max_chars: 6000
```

身份映射继续支持：

```text
access_control.identity_aliases
```

配置命名最终应以 LivingMemory 源仓库现有 schema 为准，AstrBot 生成部署目录不能作为源代码编辑位置。

## 6. 内置 Memory 的处理

内置 Memory 保留读取和兼容能力，直到 LivingMemory 结构化路径完成真实验收。

切换时执行以下步骤：

1. 关闭内置长期记忆的 Prompt 注入。
2. 检查 AG99live 或其他插件是否仍预热内置 Memory。
3. 保留短期 Conversation 和 Prompt 兼容插槽。
4. 确认 LivingMemory 成为长期记忆唯一注入来源。

这个过程不删除内置 Memory 数据，也不修改 LivingMemory 数据库。

## 7. 写入和召回时序

```text
消息事件
  -> Persona Runtime 解析 canonical identity
  -> LivingMemory 读取已完成 recall snapshot
  -> Prompt collector 发布 memory extension
  -> Persona / OLV / proactive 按 View 投影
  -> 模型请求
  -> 回合完成材料
  -> LivingMemory 后台写入和反思
  -> 更新下一轮 recall snapshot
```

当前请求不应等待本轮新记忆写入完成。新记忆在后续请求中可见。

## 8. 失败和回滚

- LivingMemory 未初始化时，collector 返回空扩展。
- 召回异常时，记录插件诊断并继续 Prompt 构建。
- 作用域解析异常时，使用旧身份回退并记录警告。
- 结构化注入出现问题时，切换回旧临时消息路径。
- 任何回滚都不删除已写入的 canonical scope 记录。

## 9. 验收

1. 普通 Persona 回合可以读取 LivingMemory 快照。
2. OLV 和主动 Persona 的注入范围按配置生效。
3. 记忆写入仍在回合完成后异步执行。
4. 用户作用域模式下，多渠道绑定身份共享新作用域。
5. 未绑定身份和其他作用域模式保持原行为。
6. 内置 Memory 不再重复注入长期记忆。
7. 召回失败不阻塞普通回复。
8. LivingMemory 管理页面和记忆操作不受 Prompt 改造影响。
