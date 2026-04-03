# Memory MVP Plan

本文件定义 AstrBot memory 系统第一版最小实现范围。

## 1. MVP 目标

第一版只要求打通以下闭环：

- 回合结束后能够写入标准化 `TurnRecord`
- 能够基于最近对话更新 `TopicState` 与 `ShortTermMemory`
- 能够在请求前读取 `MemorySnapshot`
- 能够提供最小的中长期记忆骨架
- 不改动现有 Prompt System，只提供可消费数据

第一版不要求：

- 完整人格演进
- 复杂记忆选择策略
- 图数据库
- 自动多阶段反思链
- 大规模历史迁移

## 2. MVP 范围

### 2.1 本次必须实现

- `config.py`
- `types.py`
- `store.py`
- `service.py`
- `history_source.py`
- `turn_record_service.py`
- `short_term_service.py`
- `snapshot_builder.py`
- `postprocessor.py`
- `__init__.py`

### 2.2 本次建议一起实现

- `consolidation_service.py`
- `experience_service.py`
- `vector_index.py`
- `retriever.py`

说明：

- 这部分建议和 MVP 一起做，是因为你已经明确希望前期就引入简单向量检索
- 但它们可以在工程节奏上晚于短期链路落地

### 2.3 本次明确后置

- `long_term_service.py`
- `persona_state_service.py`
- `jobs.py`
- `graph_store.py`

说明：

- 第一版先把短期闭环和中长期骨架跑通
- 长期沉淀与人格更新放到下一阶段

## 3. MVP 分阶段

### 3.1 Phase 1: 回合后短期闭环

目标：

- 先让 memory 能在每轮结束后稳定更新短期状态

需要实现：

- `MemoryConfig`
- `MemoryUpdateRequest`
- `TurnRecord`
- `TopicState`
- `ShortTermMemory`
- `MemoryStore`
- `RecentConversationSource`
- `TurnRecordService`
- `ShortTermMemoryService`
- `MemoryService.update_from_postprocess(...)`
- `MemoryPostProcessor`

完成标准：

- `AFTER_MESSAGE_SENT` 能调用 `MemoryPostProcessor`
- 当前回合可写入 `TurnRecord`
- 当前会话可更新 `TopicState`
- 当前会话可更新 `ShortTermMemory`
- 没有 memory 时不影响现有消息链路

### 3.2 Phase 2: 请求前读取闭环

目标：

- 让 Prompt System 后续可以读取 memory，但不在本次里改 prompt 构建

需要实现：

- `MemorySnapshot`
- `MemorySnapshotBuilder`
- `MemoryService.get_snapshot(...)`

完成标准：

- 能按 `umo + conversation_id` 读取 `TopicState`
- 能按 `umo + conversation_id` 读取 `ShortTermMemory`
- 返回统一 `MemorySnapshot`
- 现有 prompt 构建系统不需要立刻修改

### 3.3 Phase 3: 中长期骨架

目标：

- 把 `Experience` 和简单检索骨架接上，为后续长期记忆沉淀做准备

需要实现：

- `SessionInsight`
- `Experience`
- `ConsolidationService`
- `ExperienceService`
- `VectorIndex`
- `MemoryRetriever`

完成标准：

- 能从短期材料批量产出 `Experience`
- 能把 `Experience` 写入 `SQLite`
- 能把高价值 `Experience.summary` 写入简单向量索引
- 请求前可按 query 召回相关 `Experience`

说明：

- 这一阶段只做 `Experience`，不要求真正生成 `LongTermMemory`

## 4. MVP 数据对象

### 4.1 Phase 1 必需对象

- `MemoryUpdateRequest`
- `TurnRecord`
- `TopicState`
- `ShortTermMemory`

### 4.2 Phase 2 必需对象

- `MemorySnapshot`

### 4.3 Phase 3 必需对象

- `SessionInsight`
- `Experience`

### 4.4 本次不落地对象

- `LongTermMemoryIndex`
- `PersonaState`
- `PersonaEvolutionLog`

说明：

- 这些对象在数据模型中先定义好
- 但不作为本次最小实现的落地目标

## 5. MVP 代码目录

第一版建议最小目录：

- `astrbot/core/memory/__init__.py`
- `astrbot/core/memory/config.py`
- `astrbot/core/memory/types.py`
- `astrbot/core/memory/store.py`
- `astrbot/core/memory/service.py`
- `astrbot/core/memory/history_source.py`
- `astrbot/core/memory/turn_record_service.py`
- `astrbot/core/memory/short_term_service.py`
- `astrbot/core/memory/snapshot_builder.py`
- `astrbot/core/memory/postprocessor.py`

中长期骨架目录：

- `astrbot/core/memory/consolidation_service.py`
- `astrbot/core/memory/experience_service.py`
- `astrbot/core/memory/vector_index.py`
- `astrbot/core/memory/retriever.py`

## 6. MVP 公共接口

第一版必须尽早稳定的接口：

```python
def load_memory_config(path: Path | None = None) -> MemoryConfig: ...
def get_memory_config() -> MemoryConfig: ...
```

```python
async def MemoryService.update_from_postprocess(req: MemoryUpdateRequest) -> TurnRecord: ...
async def MemoryService.get_snapshot(umo: str, conversation_id: str | None, query: str | None = None) -> MemorySnapshot: ...
```

```python
async def MemoryPostProcessor.build_update_request(ctx: PostProcessContext) -> MemoryUpdateRequest | None: ...
async def MemoryPostProcessor.run(ctx: PostProcessContext) -> None: ...
```

```python
async def MemoryStore.save_turn_record(record: TurnRecord) -> None: ...
async def MemoryStore.get_recent_turn_records(umo: str, limit: int) -> list[TurnRecord]: ...
async def MemoryStore.upsert_topic_state(state: TopicState) -> None: ...
async def MemoryStore.get_topic_state(umo: str, conversation_id: str | None) -> TopicState | None: ...
async def MemoryStore.upsert_short_term_memory(memory: ShortTermMemory) -> None: ...
async def MemoryStore.get_short_term_memory(umo: str, conversation_id: str | None) -> ShortTermMemory | None: ...
```

Phase 3 补充接口：

```python
async def ConsolidationService.run_for_scope(umo: str, conversation_id: str | None) -> tuple[SessionInsight | None, list[Experience]]: ...
async def ExperienceService.persist_experiences(experiences: list[Experience]) -> list[Experience]: ...
async def MemoryRetriever.retrieve_for_snapshot(umo: str, conversation_id: str | None, query: str) -> tuple[list[Experience], list[LongTermMemoryIndex]]: ...
```

## 7. MVP 触发链路

### 7.1 回合后写入链路

调用顺序：

1. `PostProcessManager`
2. `MemoryPostProcessor.run(ctx)`
3. `MemoryPostProcessor.build_update_request(ctx)`
4. `MemoryService.update_from_postprocess(req)`
5. `TurnRecordService.ingest_turn(req)`
6. `ShortTermMemoryService.update_after_turn(turn)`

输出：

- `TurnRecord`
- `TopicState`
- `ShortTermMemory`

### 7.2 请求前读取链路

调用顺序：

1. `MemoryService.get_snapshot(...)`
2. `MemorySnapshotBuilder.build_snapshot(...)`
3. `MemoryStore.get_topic_state(...)`
4. `MemoryStore.get_short_term_memory(...)`
5. Phase 3 后再接入 `MemoryRetriever`

输出：

- `MemorySnapshot`

### 7.3 中长期骨架链路

调用顺序：

1. `ConsolidationService.run_for_scope(...)`
2. `ExperienceService.persist_experiences(...)`
3. `VectorIndex.upsert_experience(...)`
4. `MemorySnapshotBuilder.build_snapshot(...)`
5. `MemoryRetriever.retrieve_for_snapshot(...)`

输出：

- `Experience`
- 中长期召回结果

## 8. MVP 存储范围

第一版实际需要落的存储：

- `data/memory/config.yaml`
- `data/memory/memory.db`

第一版建议先创建但可暂不深用的目录：

- `data/memory/long_term/`
- `data/memory/projections/`

说明：

- `long_term/` 先作为后续长期记忆正文目录预留
- `projections/` 先作为后续 `Experience` 审阅投影目录预留

## 9. MVP 数据表建议

第一版最少需要：

- `memory_turn_records`
- `memory_topic_states`
- `memory_short_term_memories`

Phase 3 追加：

- `memory_session_insights`
- `memory_experiences`

当前不需要：

- `memory_long_term_memories`
- `memory_persona_states`
- `memory_persona_evolution_logs`

## 10. MVP 配置范围

第一版实际生效配置建议只启用：

- `enabled`
- `storage.sqlite_path`
- `storage.docs_root`
- `storage.projections_root`
- `short_term.enabled`
- `short_term.recent_turns_window`
- `consolidation.enabled`
- `consolidation.min_short_term_updates`
- `vector_index.enabled`
- `vector_index.experience_top_k`

当前可先忽略：

- `long_term.*`
- `persona.*`
- `jobs.*`

说明：

- 文档中可以先保留这些配置
- 代码里本阶段不必全部消费

## 11. MVP 不做什么

本次明确不做：

- 长期记忆 `Markdown` 正文写入
- 长期记忆对象合并与更新
- 人格状态更新
- 图谱构建
- 复杂 rerank
- 配置化策略选择器
- prompt 构建系统改造

## 12. MVP 验收标准

### 12.1 Phase 1 验收

- 回合结束后 memory 可安全触发
- `TurnRecord` 能成功写库
- `TopicState` 能按会话更新
- `ShortTermMemory` 能按会话更新
- 任意 memory 异常不会打断主消息链路

### 12.2 Phase 2 验收

- 能构建 `MemorySnapshot`
- snapshot 至少包含短期层对象
- 未命中数据时返回空对象而不是抛错

### 12.3 Phase 3 验收

- 能生成 `Experience`
- 能做最小 query 检索
- 检索结果能进入 `MemorySnapshot`

## 13. 实现顺序

建议实际编码顺序：

1. `config.py`
2. `types.py`
3. `store.py`
4. `history_source.py`
5. `turn_record_service.py`
6. `short_term_service.py`
7. `service.py`
8. `postprocessor.py`
9. `snapshot_builder.py`
10. `consolidation_service.py`
11. `experience_service.py`
12. `vector_index.py`
13. `retriever.py`

说明：

- 前 9 步完成后，短期闭环和读取闭环就已经成立
- 后 4 步用于补中长期骨架

## 14. 当前结论

memory 第一版最小实现应理解为：

- 先打通 `TurnRecord -> TopicState -> ShortTermMemory -> MemorySnapshot`
- 再补 `SessionInsight -> Experience -> Vector Retrieval`
- `LongTermMemory` 与 `PersonaState` 先只保留设计，不进入本次实现范围
