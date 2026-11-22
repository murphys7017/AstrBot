# 统一身份契约计划

## 文档状态

- **状态**：设计/计划
- **所属总计划**：[人格中心化、统一身份与长期记忆架构调整总计划](00-overall-plan.md)
- **实施阶段**：Phase 1
- **风险等级**：高。身份字段会影响记忆作用域和部分插件行为。

## 1. 目标

在保留平台原始字段的前提下，为明确绑定的用户增加一个可选的统一身份标识。

统一身份只回答“这是哪个稳定用户”，不承担平台路由、会话隔离、群组权限或消息发送目标的职责。

## 2. 字段模型

建议使用一个可选字段：

```text
canonical_user_id: string | null
```

事件继续保留：

- `platform`
- `sender_id`
- `sender_name`
- `unified_msg_origin`
- `group_id`
- `conversation_id`

这些字段仍然用于路由、权限、会话和平台回复。

## 3. 解析优先级

身份解析按以下顺序进行：

1. Core 或 Persona Runtime 已明确提供的 canonical identity。
2. 当前配置中针对平台和 sender 的绑定。
3. 当前配置中针对 sender 的绑定。
4. 未绑定时返回空值，让下游继续使用旧身份规则。

sender name 只用于配置匹配和展示，不作为长期稳定身份的首选键。

## 4. 绑定范围

本阶段支持按配置绑定身份，具体绑定集合由部署配置决定。例如：

```text
qq:10001=aki
webchat:user-abc=aki
```

相同的右侧值代表同一个 canonical identity。配置字段可以继续复用 LivingMemory 现有的 `identity_aliases`，后续再迁移到 Core 统一配置。

## 5. 作用域规则

在 `memory_scope_mode=user` 且事件不属于 `isolated_sessions` 时，对已解析 canonical identity 的用户：

```text
livingmemory:user:canonical:{canonical_user_id}
```

在 `memory_scope_mode=user` 且事件不属于 `isolated_sessions` 时，对未绑定用户：

```text
livingmemory:user:{platform}:{identity}
```

当 `memory_scope_mode` 为 `session`、`global` 或 `legacy` 时，继续使用现有作用域规则。`isolated_sessions` 继续优先使用原始 session 作用域。

这条规则只改变新绑定身份的用户作用域读写键。已有平台作用域记录不被改写，也不在本阶段自动合并。

## 6. 兼容约束

- Adapter 不需要删除或重命名原始身份字段。
- 旧插件读取 sender、platform 和 UMO 的代码继续可用。
- 没有 canonical identity 时，调用方得到 `None` 或现有身份回退值。
- 群聊是否共享继续由 `memory_scope_mode`、`isolated_sessions` 和现有会话规则决定，canonical identity 不改变这套策略。
- Persona 实例当前固定为一个，身份绑定不会引入多人格路由。

## 7. 实施步骤

### 7.1 Core 侧

- 明确事件或 Persona Runtime 中 canonical identity 的只读承载位置。
- 提供统一读取函数，避免 Adapter 和 LivingMemory 各自解析。
- 在诊断中记录来源类型，不记录不必要的原始隐私字段。

### 7.2 LivingMemory 侧

- 优先读取 Core canonical identity。
- 在用户作用域模式下，对已解析身份使用 canonical scope。
- 保留现有 alias 配置作为过渡回退。
- 让写入、召回、缓存和迁移命令使用同一作用域函数。

## 8. 验收

| 场景 | 预期结果 |
| --- | --- |
| 用户作用域模式下的 QQ 绑定用户 | 使用 canonical scope |
| 用户作用域模式下的 WebChat 同一绑定用户 | 与 QQ 使用相同 canonical scope |
| 未绑定用户 | 使用当前配置的作用域规则 |
| session、global 或 legacy 模式 | 保持对应的现有作用域语义 |
| 绑定用户的旧记忆 | 保留在旧作用域，不自动合并 |
| sender name 改变 | 不影响已绑定 canonical identity |
| 群聊中的绑定用户 | 仍遵守当前 `memory_scope_mode` 和 `isolated_sessions` 规则 |

## 9. 回滚

关闭 canonical identity 解析后，LivingMemory 恢复切换前的 `memory_scope_mode` 和身份作用域规则。已写入的 canonical scope 记录保留，不执行自动反向迁移。
