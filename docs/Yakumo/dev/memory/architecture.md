# Memory Architecture

本文件定义 AstrBot memory 系统的实现导向结构设计。

目标：

- 定义第一版 memory 模块划分
- 定义每个模块的核心职责
- 定义模块之间的调用顺序
- 定义第一版建议稳定下来的函数接口
- 定义推荐代码目录

## 1. 总体分层

第一版 memory 系统推荐拆成 9 层：

1. `Config Layer`
2. `Store Layer`
3. `Turn Ingest Layer`
4. `Short-Term Layer`
5. `Consolidation Layer`
6. `Experience Layer`
7. `Long-Term Layer`
8. `Retrieval Layer`
9. `Read / Snapshot Layer`

触发关系：

- 回合后：`Post Process -> Turn Ingest -> Short-Term Update`
- 当前实现：`Post Process -> Turn Ingest -> Short-Term Update -> Threshold Check -> Consolidation -> Experience Persist`
- 后续批量任务：`Scheduler -> Consolidation -> Experience Persist`
- 定时任务：`Scheduler -> Long-Term / Persona Update`
- 请求前：`Prompt / Collector -> Retrieval -> Snapshot Builder`

## 2. 推荐代码目录

推荐目录：

- `astrbot/core/memory/__init__.py`
- `astrbot/core/memory/config.py`
- `astrbot/core/memory/types.py`
- `astrbot/core/memory/store.py`
- `astrbot/core/memory/service.py`
- `astrbot/core/memory/turn_record_service.py`
- `astrbot/core/memory/short_term_service.py`
- `astrbot/core/memory/consolidation_service.py`
- `astrbot/core/memory/experience_service.py`
- `astrbot/core/memory/long_term_service.py`
- `astrbot/core/memory/persona_state_service.py`
- `astrbot/core/memory/vector_index.py`
- `astrbot/core/memory/retriever.py`
- `astrbot/core/memory/snapshot_builder.py`
- `astrbot/core/memory/postprocessor.py`
- `astrbot/core/memory/jobs.py`
- `astrbot/core/memory/history_source.py`

后续可选：

- `astrbot/core/memory/graph_store.py`
- `astrbot/core/memory/projection.py`

当前实现状态：

- 已实现：`__init__.py`、`config.py`、`types.py`、`store.py`、`service.py`、`turn_record_service.py`、`short_term_service.py`、`consolidation_service.py`、`experience_service.py`、`snapshot_builder.py`、`postprocessor.py`、`history_source.py`
- 未实现：`long_term_service.py`、`persona_state_service.py`、`vector_index.py`、`retriever.py`、`jobs.py`
- 预留：`graph_store.py`、`projection.py`

## 3. 核心模块

### 3.1 `config.py`

职责：

- 读取 `data/memory/config.yaml`
- 提供默认值
- 对外暴露结构化配置对象

第一版核心对象：

- `MemoryConfig`
- `load_memory_config() -> MemoryConfig`
- `get_memory_config() -> MemoryConfig`

建议函数：

```python
def load_memory_config(path: Path | None = None) -> MemoryConfig: ...
def get_memory_config() -> MemoryConfig: ...
```

模块协作：

- `service.py` 初始化时读取配置
- `jobs.py` 读取调度相关配置
- `store.py` 读取 sqlite 路径与 docs 根目录
- `vector_index.py` 读取向量索引配置

### 3.2 `types.py`

职责：

- 定义 memory 系统核心数据对象
- 给 service / store / postprocessor / retriever 提供统一类型

第一版建议类型：

- `TurnRecord`
- `TopicState`
- `ShortTermMemory`
- `SessionInsight`
- `Experience`
- `LongTermMemoryIndex`
- `PersonaState`
- `PersonaEvolutionLog`
- `MemorySnapshot`
- `MemoryUpdateRequest`

建议函数：

- 本文件只定义 dataclass / typed model，不承载业务逻辑

### 3.3 `store.py`

职责：

- 对 `SQLite` 的读写做统一封装
- 管理 memory 相关表
- 屏蔽上层对 SQL 细节的直接依赖

第一版核心对象：

- `MemoryStore`

建议函数：

```python
async def save_turn_record(self, record: TurnRecord) -> None: ...
async def get_recent_turn_records(self, umo: str, limit: int) -> list[TurnRecord]: ...
async def upsert_topic_state(self, state: TopicState) -> None: ...
async def get_topic_state(self, umo: str, conversation_id: str | None) -> TopicState | None: ...
async def upsert_short_term_memory(self, memory: ShortTermMemory) -> None: ...
async def get_short_term_memory(self, umo: str, conversation_id: str | None) -> ShortTermMemory | None: ...
async def save_session_insight(self, insight: SessionInsight) -> None: ...
async def save_experience(self, experience: Experience) -> None: ...
async def list_recent_experiences(self, umo: str, limit: int) -> list[Experience]: ...
async def list_experiences_by_time_range(self, umo: str, start_at, end_at) -> list[Experience]: ...
async def upsert_long_term_memory_index(self, memory: LongTermMemoryIndex) -> None: ...
async def list_long_term_memory_indexes(self, umo: str, limit: int) -> list[LongTermMemoryIndex]: ...
async def upsert_persona_state(self, state: PersonaState) -> None: ...
async def get_persona_state(self, scope_type: str, scope_id: str) -> PersonaState | None: ...
async def save_persona_evolution_log(self, log: PersonaEvolutionLog) -> None: ...
```

模块协作：

- 所有 service 都依赖 `MemoryStore`
- `retriever.py` 通过 store 回表读取对象
- `snapshot_builder.py` 通过 store 读取短期层与人格层

### 3.4 `history_source.py`

职责：

- 从 AstrBot 现有历史系统读取最近若干轮原始材料
- 统一转换为 memory 可消费的输入

第一版核心对象：

- `RecentConversationSource`

建议函数：

```python
async def get_recent_turn_payloads(self, event, limit: int) -> list[dict]: ...
```

模块协作：

- `turn_record_service.py` 生成 `TurnRecord` 时使用
- `short_term_service.py` 更新短期状态时使用

说明：

- 第一版不直接重写 AstrBot 历史系统
- 只增加一层读取适配器

### 3.5 `turn_record_service.py`

职责：

- 把当前回合结果转换成 `TurnRecord`
- 作为 memory 生命周期的入口层

第一版核心对象：

- `TurnRecordService`

建议函数：

```python
async def build_turn_record(self, req: MemoryUpdateRequest) -> TurnRecord: ...
async def ingest_turn(self, req: MemoryUpdateRequest) -> TurnRecord: ...
```

模块协作：

- `MemoryPostProcessor` 调用 `MemoryService.update_from_postprocess(...)`
- `MemoryService` 内部调用 `TurnRecordService.ingest_turn(...)`
- `TurnRecordService` 最终调用 `MemoryStore.save_turn_record(...)`

### 3.6 `short_term_service.py`

职责：

- 基于当前 `TurnRecord` 和最近若干轮材料更新短期层
- 生成 `TopicState`
- 生成 `ShortTermMemory`

第一版核心对象：

- `ShortTermMemoryService`

建议函数：

```python
async def update_topic_state(self, turn: TurnRecord) -> TopicState: ...
async def update_short_term_memory(self, turn: TurnRecord) -> ShortTermMemory: ...
async def update_after_turn(self, turn: TurnRecord) -> tuple[TopicState, ShortTermMemory]: ...
```

模块协作：

- `MemoryService.update_from_postprocess(...)` 调用
- 依赖 `RecentConversationSource`
- 依赖 `MemoryStore`

### 3.7 `consolidation_service.py`

职责：

- 把多个短期片段批量整理成中期结果
- 生成 `SessionInsight`
- 生成 `Experience`

第一版核心对象：

- `ConsolidationService`

建议函数：

```python
async def should_run_consolidation(self, umo: str) -> bool: ...
async def build_session_insight(self, umo: str, conversation_id: str | None) -> SessionInsight | None: ...
async def extract_experiences(self, insight: SessionInsight) -> list[Experience]: ...
async def run_for_scope(self, umo: str, conversation_id: str | None) -> tuple[SessionInsight | None, list[Experience]]: ...
```

模块协作：

- 当前由 `MemoryService.update_from_postprocess(...)` 在短期更新后按阈值触发
- 后续可再接 `jobs.py` 的批量任务调用
- 依赖 `MemoryStore`
- 为 `ExperienceService`、`LongTermMemoryService` 和 `PersonaStateService` 提供输入

### 3.8 `experience_service.py`

职责：

- 维护强时间线关联的 `Experience`
- 把中期抽象结果转成事件流对象
- 提供时间范围检索能力
- 后续再补审阅投影导出能力
- 后续再补 `Experience` 的简单向量索引

第一版核心对象：

- `ExperienceService`

建议函数：

```python
async def persist_experiences(self, experiences: list[Experience]) -> list[Experience]: ...
async def list_recent(self, umo: str, limit: int) -> list[Experience]: ...
async def list_by_time_range(self, umo: str, start_at, end_at) -> list[Experience]: ...
```

模块协作：

- `ConsolidationService.run_for_scope(...)` 产出 `Experience`
- `MemoryService.run_consolidation(...)` 调用 `ExperienceService.persist_experiences(...)`
- `VectorIndex.upsert_experience(...)` 由本模块触发
- `LongTermMemoryService` 与 `PersonaStateService` 把 `Experience` 作为独立输入消费

说明：

- `Experience` 与 `LongTermMemory` 同级，不是其附属字段。
- `Experience` 是时间线事件流，长期记忆是高价值认知对象。

### 3.9 `long_term_service.py`

职责：

- 将 `Experience` / `SessionInsight` 沉淀为长期记忆对象
- 维护长期记忆索引
- 负责长期记忆正文文档写入
- 同步维护长期记忆的简单向量索引

第一版核心对象：

- `LongTermMemoryService`

建议函数：

```python
async def should_promote_experience(self, exp: Experience) -> bool: ...
async def create_long_term_memory(self, exp: Experience) -> LongTermMemoryIndex: ...
async def update_long_term_memory(self, memory_id: str, exp: Experience) -> LongTermMemoryIndex: ...
async def write_memory_document(self, index: LongTermMemoryIndex, body: str) -> Path: ...
async def run_promotion(self, umo: str) -> list[LongTermMemoryIndex]: ...
```

模块协作：

- `jobs.py` 的长期沉淀任务调用
- 依赖 `MemoryStore`
- 依赖 `VectorIndex`

说明：

- 第一版落 `SQLite` 索引 + `Markdown` 正文 + 简单向量索引

### 3.10 `vector_index.py`

职责：

- 为 `Experience` 与 `LongTermMemory` 维护简单语义索引
- 提供第一版中长期记忆检索能力

第一版核心对象：

- `VectorIndex`

建议函数：

```python
async def upsert_experience(self, exp: Experience) -> None: ...
async def upsert_long_term_memory(self, memory: LongTermMemoryIndex, content: str | None = None) -> None: ...
async def search_experiences(self, query: str, limit: int = 5, filters: dict | None = None) -> list[str]: ...
async def search_long_term_memories(self, query: str, limit: int = 5, filters: dict | None = None) -> list[str]: ...
```

模块协作：

- `ExperienceService` 保存事件流后写入向量索引
- `LongTermMemoryService` 更新长期记忆后写入向量索引
- `retriever.py` 通过该模块做中长期候选召回

说明：

- 第一版只需要简单实现，不要求复杂 rerank
- 向量库仍不是事实真源，只负责检索

### 3.11 `persona_state_service.py`

职责：

- 维护当前动态人格状态
- 根据 `Experience`、`LongTermMemory` 等中长期材料缓慢更新 `PersonaState`
- 写入 `PersonaEvolutionLog`

第一版核心对象：

- `PersonaStateService`

建议函数：

```python
async def get_state(self, scope_type: str, scope_id: str) -> PersonaState | None: ...
async def compute_next_state(self, current: PersonaState | None, experiences: list[Experience], memories: list[LongTermMemoryIndex]) -> PersonaState: ...
async def save_evolution_log(self, before: PersonaState | None, after: PersonaState, reason: str, source_refs: list[str]) -> None: ...
async def run_reflection(self, scope_type: str, scope_id: str) -> PersonaState | None: ...
```

模块协作：

- `jobs.py` 的人格状态更新任务调用
- 依赖 `MemoryStore`

说明：

- 第一版不改写静态 persona
- 只维护动态人格状态

### 3.12 `retriever.py`

职责：

- 基于查询文本从 `Experience` 和 `LongTermMemory` 中召回中长期候选
- 为 `MemorySnapshotBuilder` 提供统一读取结果

第一版核心对象：

- `MemoryRetriever`

建议函数：

```python
async def retrieve_experiences(self, umo: str, query: str, limit: int = 5) -> list[Experience]: ...
async def retrieve_long_term_memories(self, umo: str, query: str, limit: int = 5) -> list[LongTermMemoryIndex]: ...
async def retrieve_for_snapshot(self, umo: str, conversation_id: str | None, query: str) -> tuple[list[Experience], list[LongTermMemoryIndex]]: ...
```

模块协作：

- 依赖 `VectorIndex`
- 依赖 `MemoryStore`
- `MemorySnapshotBuilder` 调用

### 3.13 `snapshot_builder.py`

职责：

- 把当前 memory 各层读取结果聚合成请求前只读视图
- 向 Prompt System 暴露统一读取接口
- 组合短期层、经历层与长期记忆层

第一版核心对象：

- `MemorySnapshotBuilder`

建议函数：

```python
async def build_snapshot(self, umo: str, conversation_id: str | None, query: str | None = None) -> MemorySnapshot: ...
```

模块协作：

- `MemoryService.get_snapshot(...)` 调用
- `MemoryCollector` 后续通过该接口读取
- 依赖 `MemoryStore`
- 依赖 `MemoryRetriever`

### 3.14 `service.py`

职责：

- 作为 memory 子系统统一门面
- 协调各个 service 的调用顺序

第一版核心对象：

- `MemoryService`

建议函数：

```python
async def update_from_postprocess(self, req: MemoryUpdateRequest) -> TurnRecord: ...
async def get_snapshot(self, umo: str, conversation_id: str | None, query: str | None = None) -> MemorySnapshot: ...
async def run_consolidation(self, umo: str, conversation_id: str | None) -> tuple[SessionInsight | None, list[Experience]]: ...
async def run_long_term_promotion(self, umo: str) -> list[LongTermMemoryIndex]: ...
async def run_persona_reflection(self, scope_type: str, scope_id: str) -> PersonaState | None: ...
```

模块协作：

- `postprocessor.py` 调用 `update_from_postprocess(...)`
- `jobs.py` 调用批量接口
- `MemoryCollector` 后续调用 `get_snapshot(...)`

### 3.15 `postprocessor.py`

职责：

- 把 `PostProcessContext` 转成 `MemoryUpdateRequest`
- 桥接 `Post Process System` 和 `MemoryService`

第一版核心对象：

- `MemoryPostProcessor`

建议函数：

```python
async def build_update_request(self, ctx: PostProcessContext) -> MemoryUpdateRequest | None: ...
async def run(self, ctx: PostProcessContext) -> None: ...
```

模块协作：

- 由 `PostProcessManager` 调度
- 内部调用 `MemoryService.update_from_postprocess(...)`

说明：

- 第一版建议挂在 `AFTER_MESSAGE_SENT`
- 它不直接写数据库，只调 `MemoryService`

### 3.16 `jobs.py`

职责：

- 运行 memory 批量任务和定时任务

第一版核心对象：

- `MemoryJobRunner`

建议函数：

```python
async def run_consolidation_job(self) -> None: ...
async def run_long_term_job(self) -> None: ...
async def run_persona_reflection_job(self) -> None: ...
```

模块协作：

- 依赖 `MemoryService`
- 由 AstrBot 现有 cron / scheduler 能力触发

## 4. 核心调用链

### 4.1 回合后即时链路

调用顺序：

1. `PostProcessManager`
2. `MemoryPostProcessor.run(ctx)`
3. `MemoryPostProcessor.build_update_request(ctx)`
4. `MemoryService.update_from_postprocess(req)`
5. `TurnRecordService.ingest_turn(req)`
6. `ShortTermMemoryService.update_after_turn(turn)`

结果：

- 写入 `TurnRecord`
- 更新 `TopicState`
- 更新 `ShortTermMemory`

### 4.2 中期抽象链路

调用顺序：

1. `MemoryService.update_from_postprocess(...)`
2. `ShortTermMemoryService.update_after_turn(...)`
3. `ConsolidationService.should_run_consolidation(...)`
4. 达阈值时 `MemoryService.run_consolidation(...)`
5. `ConsolidationService.run_for_scope(...)`
6. `MemoryStore.save_session_insight(...)`
7. `ExperienceService.persist_experiences(...)`
8. 后续再接 `VectorIndex.upsert_experience(...)`

结果：

- 生成 `SessionInsight`
- 生成 `Experience`

### 4.3 经历检索链路

调用顺序：

1. `MemoryService.get_snapshot(...)`
2. `MemorySnapshotBuilder.build_snapshot(...)`
3. `MemoryRetriever.retrieve_for_snapshot(...)`
4. `VectorIndex.search_experiences(...)`
5. `VectorIndex.search_long_term_memories(...)`
6. `MemoryStore` 回表读取对象

结果：

- 召回中长期 `Experience`
- 召回相关 `LongTermMemory`

### 4.4 长期沉淀链路

调用顺序：

1. `MemoryJobRunner.run_long_term_job()`
2. `MemoryService.run_long_term_promotion(...)`
3. `LongTermMemoryService.run_promotion(...)`
4. `LongTermMemoryService.write_memory_document(...)`
5. `MemoryStore.upsert_long_term_memory_index(...)`
6. `VectorIndex.upsert_long_term_memory(...)`

结果：

- 更新长期记忆索引
- 更新长期记忆 `Markdown` 正文

### 4.5 人格状态更新链路

调用顺序：

1. `MemoryJobRunner.run_persona_reflection_job()`
2. `MemoryService.run_persona_reflection(...)`
3. `PersonaStateService.run_reflection(...)`
4. `MemoryStore.upsert_persona_state(...)`
5. `MemoryStore.save_persona_evolution_log(...)`

结果：

- 更新 `PersonaState`
- 记录 `PersonaEvolutionLog`

### 4.6 请求前读取链路

调用顺序：

1. `MemoryService.get_snapshot(...)`
2. `MemorySnapshotBuilder.build_snapshot(...)`
3. 当前直接由 `MemoryStore` 读取短期层
4. 后续再接 `MemoryRetriever.retrieve_for_snapshot(...)`
5. 返回 `MemorySnapshot`

结果：

- 给 Prompt System / MemoryCollector 提供只读输入

## 5. 第一版需要稳定下来的公共接口

建议第一版稳定以下接口：

```python
async def MemoryService.update_from_postprocess(req: MemoryUpdateRequest) -> TurnRecord: ...
async def MemoryService.get_snapshot(umo: str, conversation_id: str | None, query: str | None = None) -> MemorySnapshot: ...
async def MemoryPostProcessor.run(ctx: PostProcessContext) -> None: ...
async def MemoryStore.save_turn_record(record: TurnRecord) -> None: ...
async def MemoryStore.upsert_topic_state(state: TopicState) -> None: ...
async def MemoryStore.upsert_short_term_memory(memory: ShortTermMemory) -> None: ...
async def ExperienceService.persist_experiences(experiences: list[Experience]) -> list[Experience]: ...
async def VectorIndex.search_experiences(query: str, limit: int = 5, filters: dict | None = None) -> list[str]: ...
async def VectorIndex.search_long_term_memories(query: str, limit: int = 5, filters: dict | None = None) -> list[str]: ...
```

原因：

- 这些接口构成第一版最小闭环
- 后续就算中长期层扩展，上面这些也不应频繁变化

## 6. 第一版不建议先做的模块

当前建议后置：

- `graph_store.py`
- 复杂 `selector` 逻辑
- 人格深度反思策略
- 自动大规模长期回写

## 7. 目录与数据根路径

当前建议默认根路径：

- `data/memory/config.yaml`
- `data/memory/memory.db`
- `data/memory/long_term/`
- `data/memory/projections/`

说明：

- `memory.db`：结构化真源
- `long_term/`：长期记忆正文文档
- `projections/`：经历等审阅投影

## 8. 当前结论

当前 memory 系统第一版应理解为：

- `MemoryPostProcessor` 负责回合后入口
- `MemoryService` 负责统一编排
- `TurnRecordService` 与 `ShortTermMemoryService` 负责即时更新
- `ConsolidationService` 负责中期抽象
- `ExperienceService` 负责独立的时间线事件流
- `MemorySnapshotBuilder` 当前只负责短期层只读视图
- `LongTermMemoryService`、`VectorIndex`、`MemoryRetriever`、`PersonaStateService` 仍处于后续阶段
