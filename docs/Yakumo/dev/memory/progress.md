# Memory Progress

本文件只记录当前 memory 子系统的实现完成度，不重复展开完整设计。

## 1. 当前阶段

当前 memory 处于：

- 已完成短期闭环
- 已完成 snapshot 只读出口
- 已完成中期 consolidation 第一版
- 已完成 `Experience` 的 Markdown 投影
- 已完成 `LongTermMemory + Document Search V1`
- 已完成长期记忆一致性修复第一轮
- 已完成 identity 三层拆分第一版
- 未进入人格演进与完整 retrieval 接入

当前可以认为已经完成了：

1. `TurnRecord`
2. `TopicState`
3. `ShortTermMemory`
4. `MemorySnapshot`
5. `SessionInsight`
6. `Experience`

## 2. 已完成链路

### 2.1 回合后写入链路

当前已落地：

1. `AFTER_MESSAGE_SENT`
2. `MemoryPostProcessor`
3. `MemoryService.update_from_postprocess(...)`
4. `TurnRecordService.ingest_turn(...)`
5. `ShortTermMemoryService.update_after_turn(...)`

结果：

- 写入 `TurnRecord`
- 更新 `TopicState`
- 更新 `ShortTermMemory`

当前身份解析已固定为只看事件对象：

- `umo = event.unified_msg_origin`
- `platform_user_key = event.get_platform_id() + ":" + event.get_sender_id()`
- `canonical_user_id` 只通过 SQLite 显式映射表解析

当前行为约束：

- 短期层继续按 `umo + conversation_id` 工作
- `canonical_user_id` 缺失时，不阻断短期写入
- `canonical_user_id` 缺失时，中长期链路直接停止，不做 fallback

### 2.2 短期分析链路

当前已落地：

- memory analyzer 基础设施
- `analysis.enabled`
- `analysis.strict`
- `analysis.prompts_root`
- `analysis.analyzers.*`
- `analysis.stages.short_term_update`

当前短期层支持两种运行模式：

- `analysis.enabled=false`
  - 使用当前确定性最小逻辑
- `analysis.enabled=true`
  - 使用配置驱动 analyzer

当前短期 analyzer 契约已经固定为：

- `topic_v1`
  - `current_topic`
  - `topic_summary`
  - `topic_confidence`
- `focus_v1`
  - `active_focus`
- `summary_v1`
  - `short_summary`

### 2.3 Snapshot 读取链路

当前已落地：

1. `MemoryService.get_snapshot(...)`
2. `MemorySnapshotBuilder.build_snapshot(...)`
3. `MemoryStore` 读取短期层

当前 snapshot 返回：

- `topic_state`
- `short_term_memory`
- `experiences=[]`
- `long_term_memories=[]`
- `persona_state=None`

说明：

- `experiences` 当前仍未进入 snapshot，保持空列表占位
- `long_term_memories` 与 `persona_state` 仍然是占位
- 这里的空中长期字段不代表 retrieval / prompt 接入已实现

### 2.4 中期 consolidation 链路

当前已落地：

1. `MemoryService.update_from_postprocess(...)`
2. 短期更新完成后检查 consolidation 阈值
3. `MemoryService.run_consolidation(...)`
4. `ConsolidationService.run_for_scope(...)`
5. `MemoryStore.save_session_insight(...)`
6. `ExperienceService.persist_experiences(...)`

当前已补齐：

- `ExperienceProjectionService`
- `data/memory/projections/experiences/...` Markdown 投影写入

当前触发方式：

- 不是 scheduler
- 不是 jobs
- 是回合后阈值触发

当前阈值语义：

- 按 `canonical_user_id + conversation_id` 判断
- 统计最新 `SessionInsight.window_end_at` 之后的新 turn 数
- 达到 `consolidation.min_short_term_updates` 才触发

当前中期 analyzer 契约已经固定为：

- `session_insight_update`
  - `topic_summary`
  - `progress_summary`
  - `summary_text`
- `experience_extract`
  - `experiences`
  - 每项包含：
    - `category`
    - `summary`
    - `detail_summary`
    - `importance`
    - `confidence`

### 2.5 长期记忆与文档搜索链路

当前已落地：

1. `LongTermMemoryService.run_promotion(...)`
2. `MemoryStore.upsert_long_term_memory_index(...)`
3. `DocumentSerializer`
4. `DocumentLoader`
5. `DocumentSearchService`
6. `MemoryVectorIndex` 接口第一版

当前状态：

- 长期记忆文档与索引第一版已存在
- 文档搜索第一版已存在
- 手动导入 / 更新入口已存在
- 长期归属已切到 `canonical_user_id`
- 长期文档写入已改成 staging + 原子替换
- 向量索引开启时，长期导入 / promotion 会先校验 provider 绑定与索引可用性
- `importance / confidence / topic_confidence` 已收紧到 `0..1`
- 仍未完整接入 `MemorySnapshot.long_term_memories`
- 仍未接入 prompt collector / renderer 消费链路

## 3. 已完成模块

当前已实现模块：

- `astrbot/core/memory/config.py`
- `astrbot/core/memory/types.py`
- `astrbot/core/memory/store.py`
- `astrbot/core/memory/service.py`
- `astrbot/core/memory/history_source.py`
- `astrbot/core/memory/identity.py`
- `astrbot/core/memory/turn_record_service.py`
- `astrbot/core/memory/short_term_service.py`
- `astrbot/core/memory/snapshot_builder.py`
- `astrbot/core/memory/postprocessor.py`
- `astrbot/core/memory/consolidation_service.py`
- `astrbot/core/memory/experience_service.py`
- `astrbot/core/memory/projection.py`
- `astrbot/core/memory/long_term_service.py`
- `astrbot/core/memory/document_serializer.py`
- `astrbot/core/memory/document_loader.py`
- `astrbot/core/memory/document_search.py`
- `astrbot/core/memory/vector_index.py`

当前已补齐的 store 能力：

- `save_turn_record(...)`
- `get_recent_turn_records(...)`
- `upsert_topic_state(...)`
- `get_topic_state(...)`
- `upsert_short_term_memory(...)`
- `get_short_term_memory(...)`
- `save_session_insight(...)`
- `get_latest_session_insight(...)`
- `save_experience(...)`
- `list_recent_experiences(...)`
- `list_experiences_for_scope(...)`
- `list_experiences_by_time_range(...)`
- `list_turn_records_by_time_range(...)`
- `list_turn_records_by_canonical_user(...)`
- `upsert_long_term_memory_index(...)`
- `list_long_term_memory_indexes(...)`
- `get_long_term_memory_index(...)`
- `save_long_term_memory_link(...)`
- `list_long_term_memory_links(...)`
- `upsert_long_term_promotion_cursor(...)`
- `get_long_term_promotion_cursor(...)`
- `save_identity_mapping(...)`
- `get_identity_mapping(...)`
- `delete_identity_mapping(...)`
- `list_identity_mappings_for_canonical_user(...)`

## 4. 当前未完成部分

当前明确未做：

- `retriever.py`
- `persona_state_service.py`
- `jobs.py`
- `graph_store.py`

当前能力边界：

- memory 已负责短期写入、中期 consolidation、长期文档与索引第一版
- prompt system 只消费 snapshot
- memory 还不负责 prompt render
- memory 还不负责 selector / router / chat state
- memory 还未把长期记忆稳定暴露到 snapshot
- memory 还不负责人格演进更新

## 5. 当前完成度判断

如果按当前规划分层看：

- Phase 1 短期写入闭环：已完成
- Phase 2 snapshot 读取闭环：已完成
- Phase 3 中期抽象链路：已部分完成
- 长期记忆层：已完成第一版基础服务，但未完成对外读取闭环
- 人格演进层：未开始
- retrieval 层：仅完成文档搜索基础，未完成统一召回链路

如果按“能不能给后续 prompt system 提供稳定 memory 输入”来看：

- 短期层：可以
- 中期层：内部已可用，但 `experiences` 仍未进入 snapshot
- 长期层：内部基础已存在，但还未形成稳定 prompt 消费入口

## 6. 当前主要限制

当前最大的限制不是写入，而是读取范围还刻意收窄：

- `SessionInsight` 已写入，但不进入 snapshot
- `LongTermMemory` 尚未进入 snapshot
- 还没有统一 query 驱动的 retrieval
- 向量索引已可服务长期记忆文档搜索，但仍未进入统一 retrieval

所以当前对外稳定开放的 memory 结果现在是：

- `TopicState`
- `ShortTermMemory`

## 7. 下一步建议顺序

建议后续顺序：

1. `snapshot-and-read-path.md`
2. `jobs-and-scheduling.md`
3. `retriever.py`
4. 将 `SessionInsight` / `Experience` / `LongTermMemory` 以受控方式接入 snapshot
5. 将长期层接入 prompt collector / renderer
6. `persona_state_service.py`

如果继续坚持“memory 先独立收口，再让 prompt 使用”，那当前最合理的下一步是：

1. 完成中长期 read path 设计
2. 明确 snapshot 什么时候开始暴露 `SessionInsight` / `LongTermMemory`
3. 再决定 retrieval 和长期沉淀的先后

## 8. 当前结论

当前 memory 已经不是“只有设计”，而是已经完成了第一条真实工作链路：

`Post Process -> TurnRecord -> ShortTermMemory -> Consolidation -> SessionInsight / Experience -> LongTermPromotion -> Snapshot`

当前这个链路里，对外稳定开放的仍然是短期层。
当前这个链路里，长期层仍主要停留在 memory 内部服务能力。

所以当前最准确的判断是：

- memory 基础设施已成立
- 中期抽象已落地到 store
- 长期层基础服务与文档搜索第一版已落地，并完成第一轮一致性修复
- `Experience` 已完成 projection，可供内部审阅
- 系统整体正处于“短期完成，中期可读，长期第一版已落地但尚未完整接入”的阶段
