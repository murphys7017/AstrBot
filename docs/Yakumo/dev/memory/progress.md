# Memory Progress

本文件只记录当前 memory 子系统的实现完成度，不重复展开完整设计。

## 1. 当前阶段

当前 memory 处于：

- 已完成短期闭环
- 已完成 snapshot 只读出口
- 已完成中期 consolidation 第一版
- 已完成 `Experience` 的 snapshot 暴露
- 已完成 `Experience` 的 Markdown 投影
- 未进入长期记忆、人格演进、检索召回

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
3. `MemoryStore` 读取短期层与当前会话 `Experience`

当前 snapshot 返回：

- `topic_state`
- `short_term_memory`
- `experiences`
- `long_term_memories=[]`
- `persona_state=None`

说明：

- `Experience` 当前是直接读取当前 scope 最近结果，不代表 retrieval 已实现
- `long_term_memories` 与 `persona_state` 仍然是占位

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

- 按 `umo + conversation_id` 判断
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

## 3. 已完成模块

当前已实现模块：

- `astrbot/core/memory/config.py`
- `astrbot/core/memory/types.py`
- `astrbot/core/memory/store.py`
- `astrbot/core/memory/service.py`
- `astrbot/core/memory/history_source.py`
- `astrbot/core/memory/turn_record_service.py`
- `astrbot/core/memory/short_term_service.py`
- `astrbot/core/memory/snapshot_builder.py`
- `astrbot/core/memory/postprocessor.py`
- `astrbot/core/memory/consolidation_service.py`
- `astrbot/core/memory/experience_service.py`
- `astrbot/core/memory/projection.py`

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

## 4. 当前未完成部分

当前明确未做：

- `vector_index.py`
- `retriever.py`
- `long_term_service.py`
- `persona_state_service.py`
- `jobs.py`
- `graph_store.py`

当前能力边界：

- memory 只负责内部写入、内部 consolidation、内部 snapshot
- prompt system 只消费 snapshot
- memory 还不负责 prompt render
- memory 还不负责 selector / router / chat state
- memory 还不负责长期记忆 markdown 正文落盘
- memory 还不负责人格演进更新

## 5. 当前完成度判断

如果按当前规划分层看：

- Phase 1 短期写入闭环：已完成
- Phase 2 snapshot 读取闭环：已完成
- Phase 3 中期抽象链路：已部分完成
- 长期记忆层：未开始
- 人格演进层：未开始
- retrieval 层：未开始

如果按“能不能给后续 prompt system 提供稳定 memory 输入”来看：

- 短期层：可以
- 中期层：`Experience` 已可直接通过 snapshot 读取
- 长期层：还不可以

## 6. 当前主要限制

当前最大的限制不是写入，而是读取范围还刻意收窄：

- `SessionInsight` 已写入，但不进入 snapshot
- 还没有 query 驱动的 retrieval
- 还没有向量召回

所以当前对外稳定开放的 memory 结果现在是：

- `TopicState`
- `ShortTermMemory`
- `Experience`

## 7. 下一步建议顺序

建议后续顺序：

1. `snapshot-and-read-path.md`
2. `jobs-and-scheduling.md`
3. `vector_index.py`
4. `retriever.py`
5. 将 `SessionInsight` / `LongTermMemory` 以受控方式接入 snapshot
6. `long_term_service.py`
7. `persona_state_service.py`

如果继续坚持“memory 先独立收口，再让 prompt 使用”，那当前最合理的下一步是：

1. 完成中长期 read path 设计
2. 明确 snapshot 什么时候开始暴露 `SessionInsight` / `LongTermMemory`
3. 再决定 retrieval 和长期沉淀的先后

## 8. 当前结论

当前 memory 已经不是“只有设计”，而是已经完成了第一条真实工作链路：

`Post Process -> TurnRecord -> ShortTermMemory -> Consolidation -> SessionInsight / Experience -> Snapshot`

当前这个链路里，对外已经开放到了短期层加 `Experience`。

所以当前最准确的判断是：

- memory 基础设施已成立
- 中期抽象已落地到 store
- `Experience` 已进入 snapshot，projection 已可审阅
- 系统整体正处于“短期完成，中期内部打通，长期未开始”的阶段
