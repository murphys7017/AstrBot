# Memory Current Status

本文只记录当前源码已经具备的能力和仍存在的边界，不保留历史实施步骤。

## 已完成

- Memory Service 在 Core Lifecycle 初始化，并按有效配置隔离实例。
- `AFTER_TURN_COMPLETED` Postprocessor 已成为自动写入入口。
- Interaction finalized material 与普通 Conversation 回合都可形成 `MemoryUpdateRequest`。
- 所有可接受回合保留 `TurnRecord`；assistant-only 主动表达保留精确历史，但不会更新
  TopicState、ShortTermMemory、PersonaState 或触发 consolidation / promotion。
- 真实用户回合（包括附件或媒体输入）形成 TopicState、ShortTermMemory 的短期闭环。
- canonical identity 映射、SessionInsight、Experience 和长期记忆 promotion 已接入。
- 长期记忆 Markdown、结构化索引、证据链接、向量同步状态和文档搜索已实现。
- `MemorySnapshotBuilder` 可读取 topic、short-term、experience、long-term 和 persona state。
- Prompt 使用异步 Recall Snapshot：当前回合只同步读取 topic、short-term 和 persona state，长期记忆由 short-term revision/fingerprint 驱动后台刷新，首次无缓存时不等待。
- Recall 可按 `USER`、`GROUP`、`GLOBAL` 合并；USER 绑定当前 canonical user，GROUP/GLOBAL 按稳定 scope key 共享，并按配置的作用域优先级、最终 top-k 和冲突去重策略收口。
- 群聊用户回合可同时贡献 `USER` 与 `GROUP`；GROUP consolidation 会聚合同一群组的不同成员回合，使用稳定群组 owner key 运行 Experience/Long-Term promotion，贡献者身份仍保留在回合 provenance 中。
- Memory Phase 5 第一批已接入 `MemoryJobScheduler`：后台 Postprocessor 先持久化 `TurnRecord`，再按会话串行提交短期更新；短期更新完成后继续按 scope 串行提交 consolidation/promotion。后台任务只携带 `turn_id` 并从存储重读，旧时间戳回合不会覆盖较新的短期状态；直接调用 `MemoryService.update_from_postprocess()` 仍保持同步执行和异常传播。
- Memory Phase 5 第二批已将 Recall refresh 和 dirty vector sync 接入同一 scheduler；Recall 继续保持 stale-while-revalidate，向量修复增加显式 `schedule_dirty_long_term_vector_indexes()` 非等待入口，并按任务类型和 dedupe key 合并。
- 变更型后台任务已接入 SQLite pending-job journal：短期更新、scope consolidation/promotion、dirty vector sync 与 Persona reflection 在入队前持久化，启动时恢复未结算项。每条目使用 delivery token，旧 worker 完成不会误删已被合并任务替换的新条目；Recall refresh 保持可丢弃的缓存刷新任务，不写入 journal。
- `assistant_only` 已作为 `TurnRecord` 持久化字段保存，后台更新按该明确事实跳过抽象状态写入，不再以空 `user_message` 推断。
- Persona reflection analyzer 与 `persona_reflection` 后台 Job 已接入 consolidation 成功后的 USER scope 链路；两个开关仍默认关闭，失败只影响 PersonaState，不影响已完成的 Memory consolidation/promotion。
- `MemoryService` 已提供 PersonaState 只读状态、演进日志、显式 rollback 和 scheduler/reflection 诊断入口；真实运行观察与开关启用仍未执行。
- `MemoryCollector` 已进入统一 Prompt ContextPack，并由 target projection 控制 Personal
  Response Plan、Planner、Persona 和 Core 的可见范围。
- `MemorySnapshot` 已通过 `snapshot_bridge.py` 发布到 Core `SnapshotHub`，使用配置档、UMO
  和 conversation 组成的稳定哈希作用域以及短 TTL；读取仍以 MemoryService 和事件级缓存
  为主，Hub 只提供跨插件只读投影。
- Core 已提供统一身份绑定解析。配置位于当前 AstrBot 配置档的
  `memory.identity.bindings`，每条绑定使用 `platform_id`、`sender_user_id` 和
  `canonical_user_id`。绑定只改变跨平台用户作用域的解析，不重写原始适配器字段，也不修改
  已有记忆数据。
- LivingMemory 作为外部长期记忆插件通过 `PromptExtension` 的 `memory` 挂载点向 Persona
  发布已完成的召回快照。它读取自己的缓存和数据库，Prompt 构建阶段不重新检索、不写入记忆，
  旧的临时消息注入路径已经退出。LivingMemory 在 `memory_scope_mode=user` 下优先使用 Core
  解析出的 canonical user scope。
- Interaction 私有 Memory Store 和 `memory.interaction` slot 已删除。

## 当前限制

- consolidation、长期 promotion、Recall 刷新和 dirty vector sync 已由后台 scheduler 承担；变更型任务可在下次服务初始化时恢复，但当前不会在同一进程内自动重试持续失败的 analyzer 任务。PersonaState 真实运行验收尚未完成，默认注入与自动演进仍默认关闭。
- canonical identity 缺失的用户回合只跳过 USER 中长期沉淀；若回合带有稳定 GROUP scope，GROUP 中长期沉淀仍可执行。
- Memory analyzer 依赖配置的 Provider；分析失败按 Postprocessor 失败语义记录并跳过该次更新。
- 向量检索、文档回表和 analyzer 调用仍需要持续关注延迟、超时和可观测性。
- Context Catalog 的生命周期与脱敏字段尚未全部成为运行时强约束。

## 下一步

1. 完善 Memory read/write latency、降级组件和后台任务诊断。
2. 固化 finalized material 到 MemoryUpdateRequest 的版本化契约，并进行真实运行验收。

## 配置入口

身份绑定位于 AstrBot Dashboard 的「智能」→「智能配置」→「统一身份」。统一身份配置使用
`memory.identity.enabled` 和 `memory.identity.bindings`，运行时读取当前配置档，修改后需要让 AstrBot 重新加载配置。
绑定列表支持搜索已有账号。使用「从已知账号选择」可以按平台、对话、用户 ID 和昵称筛选近期观察到的账号，选择后仍需填写统一身份 ID 并保存。
候选数据来自当前运行期间收到的消息和已保存的平台消息历史，未观察到的账号仍可手动添加。

具体模块关系见 `architecture.md`；配置事实以 `astrbot/core/memory/config.py`、
`astrbot/core/memory_config_defaults.py` 和统一配置 schema 为准。
