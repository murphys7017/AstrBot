# Memory Data Model

本文件定义 AstrBot memory 系统第一版核心数据类型设定。

目标：

- 定义第一版稳定数据对象
- 明确基础类型、枚举和值域约束
- 明确各对象的字段职责与层级归属
- 给后续 `astrbot/core/memory/types.py` 提供直接落地依据

## 1. 设计原则

第一版数据模型遵循以下原则：

- 先稳定对象边界，再逐步补复杂策略
- 持久化对象与运行期辅助对象分开定义
- `SQLite` 中保存结构化真源
- `Markdown` 只承载长期记忆正文，不承载高频状态
- 向量库只负责检索，不负责事实真源

## 2. 分层总览

第一版核心对象：

- `MemoryUpdateRequest`
- `TurnRecord`
- `TopicState`
- `ShortTermMemory`
- `SessionInsight`
- `Experience`
- `LongTermMemoryIndex`
- `PersonaState`
- `PersonaEvolutionLog`
- `MemorySnapshot`

分层关系：

- 回合后输入层：`MemoryUpdateRequest`
- 原始材料层：`TurnRecord`
- 短期层：`TopicState`、`ShortTermMemory`
- 中期层：`SessionInsight`
- 时间线层：`Experience`
- 长期层：`LongTermMemoryIndex`
- 人格层：`PersonaState`、`PersonaEvolutionLog`
- 请求前读取层：`MemorySnapshot`

## 3. 基础类型

本节定义第一版建议稳定下来的基础类型。

### 3.1 标识类型

第一版统一约定：

- `umo: str`
- `conversation_id: str | None`
- `platform_id: str | None`
- `session_id: str | None`

说明：

- `umo` 是 memory 系统的主归属标识，第一版所有核心对象都围绕它组织
- `conversation_id` 用于区分同一 `umo` 下的不同会话
- `platform_id` 用于保留平台来源信息
- `session_id` 用于承接运行期 session 语义

建议在 `types.py` 中用 type alias 表达：

```python
from typing import Any

JsonDict = dict[str, Any]
MessagePayload = dict[str, Any]
SourceRef = str
```

### 3.2 时间类型

第一版统一使用：

- 运行期对象：`datetime`
- `Markdown` front matter / 配置 / 导出：ISO 8601 字符串

约束：

- 所有持久化时间字段都应保存为可比较时间
- 第一版建议统一保存 UTC 时间

### 3.3 分数类型

第一版统一使用 `float`，取值区间为 `0.0 ~ 1.0`：

- `importance`
- `confidence`
- `topic_confidence`
- `familiarity`
- `trust`
- `warmth`
- `formality_preference`
- `directness_preference`

约束：

- 0.0 表示极低
- 1.0 表示极高
- 写入前应做 clamp，避免超界

### 3.4 `scope_type`

`scope_type` 用于表示对象绑定在哪个作用域。

第一版建议值：

- `user`
- `conversation`
- `session`
- `global`

说明：

- `Experience`、`LongTermMemoryIndex`、`PersonaState` 都会使用该字段
- 第一版最常用的是 `user` 和 `conversation`
- `global` 主要为未来公共人格或全局系统状态预留

### 3.5 `source_refs`

第一版暂不引入复杂 `SourceRef` 对象，统一使用 `list[str]`。

建议字符串格式：

- `turn:{turn_id}`
- `insight:{insight_id}`
- `exp:{experience_id}`
- `msg:{platform_id}:{message_id}`

说明：

- 第一版先保证可溯源
- 后续如果确实需要，再升级为结构化来源对象

### 3.6 `Experience.category`

第一版建议值：

- `user_fact`
- `user_preference`
- `project_progress`
- `interaction_pattern`
- `relationship_signal`
- `episodic_event`

说明：

- `user_fact`：相对稳定的用户事实
- `user_preference`：用户偏好
- `project_progress`：项目推进、计划、决策变化
- `interaction_pattern`：互动模式
- `relationship_signal`：亲近、信任、疏离等关系信号
- `episodic_event`：一次具体事件

## 4. 非持久化辅助类型

这些类型主要服务运行期拼装，不要求单独入库。

### 4.1 `ScopeRef`

建议结构：

```python
@dataclass(slots=True)
class ScopeRef:
    scope_type: str
    scope_id: str
```

用途：

- 统一表达 `Experience` / `LongTermMemoryIndex` / `PersonaState` 的作用域
- 避免到处散落 `scope_type` + `scope_id` 参数

### 4.2 `MemoryUpdateRequest`

定义：

`MemoryUpdateRequest` 表示一次回合后 memory 更新请求。

建议结构：

```python
@dataclass(slots=True)
class MemoryUpdateRequest:
    umo: str
    conversation_id: str | None
    platform_id: str | None
    session_id: str | None
    provider_request: JsonDict | None
    user_message: MessagePayload
    assistant_message: MessagePayload
    message_timestamp: datetime
    source_refs: list[SourceRef]
```

用途：

- 作为 `MemoryPostProcessor -> MemoryService` 的统一输入
- 给 `TurnRecordService` 提供原始材料

说明：

- 第一版不要求这里直接携带检索结果
- `user_message` 与 `assistant_message` 先保持统一 dict 结构

## 5. 持久化核心对象

### 5.1 `TurnRecord`

定义：

`TurnRecord` 表示一次回合完成后的标准化原始记录。

建议结构：

```python
@dataclass(slots=True)
class TurnRecord:
    turn_id: str
    umo: str
    conversation_id: str | None
    platform_id: str | None
    session_id: str | None
    user_message: MessagePayload
    assistant_message: MessagePayload
    message_timestamp: datetime
    source_refs: list[SourceRef]
    created_at: datetime
```

用途：

- 作为 memory 生命周期的统一原始材料
- 作为短期层与中期层的共同输入

存储位置：

- `SQLite`

### 5.2 `TopicState`

定义：

`TopicState` 表示当前会话正在围绕什么继续聊。

建议结构：

```python
@dataclass(slots=True)
class TopicState:
    umo: str
    conversation_id: str | None
    current_topic: str | None
    topic_summary: str | None
    topic_confidence: float
    last_active_at: datetime
```

用途：

- 维持当前对话的主题连续性
- 作为后续中期抽象的输入之一

存储位置：

- `SQLite`

### 5.3 `ShortTermMemory`

定义：

`ShortTermMemory` 表示最近若干轮对话中，下一轮仍值得保留的短期上下文抽象。

建议结构：

```python
@dataclass(slots=True)
class ShortTermMemory:
    umo: str
    conversation_id: str | None
    short_summary: str | None
    active_focus: str | None
    updated_at: datetime
```

用途：

- 服务最近几轮连续对话
- 记录当前仍需继续推进的焦点
- 为 `SessionInsight` 与 `Experience` 提供原料

存储位置：

- `SQLite`

### 5.4 `SessionInsight`

定义：

`SessionInsight` 表示一段对话阶段结束后形成的中期抽象。

建议结构：

```python
@dataclass(slots=True)
class SessionInsight:
    insight_id: str
    umo: str
    conversation_id: str | None
    window_start_at: datetime | None
    window_end_at: datetime | None
    topic_summary: str | None
    progress_summary: str | None
    summary_text: str | None
    created_at: datetime
```

用途：

- 作为短期层进入中长期层的桥
- 为 `Experience` 抽取提供输入
- 为长期记忆和人格状态更新提供阶段性理解

存储位置：

- `SQLite`

### 5.5 `Experience`

定义：

`Experience` 表示和时间线强关联的事件流对象。

建议结构：

```python
@dataclass(slots=True)
class Experience:
    experience_id: str
    umo: str
    conversation_id: str | None
    scope_type: str
    scope_id: str
    event_time: datetime
    category: str
    summary: str
    detail_summary: str | None
    importance: float
    confidence: float
    source_refs: list[SourceRef]
    created_at: datetime
    updated_at: datetime
```

用途：

- 作为强时间线事件流存在
- 参与长期记忆沉淀
- 参与人格状态更新
- 参与中长期记忆检索

存储位置：

- 主存储：`SQLite`
- 检索索引：向量库
- 审阅投影：`Markdown`

### 5.6 `LongTermMemoryIndex`

定义：

`LongTermMemoryIndex` 表示长期记忆对象的结构化索引与元数据。

建议结构：

```python
@dataclass(slots=True)
class LongTermMemoryIndex:
    memory_id: str
    umo: str
    scope_type: str
    scope_id: str
    summary: str
    doc_path: str
    importance: float
    confidence: float
    tags: list[str]
    source_refs: list[SourceRef]
    created_at: datetime
    updated_at: datetime
```

用途：

- 作为长期记忆对象的数据库索引
- 连接 `Markdown` 正文与检索系统
- 参与请求前 memory 召回

存储位置：

- 主存储：`SQLite`
- 正文内容：`Markdown`
- 检索索引：向量库

说明：

- `doc_path` 保存相对 `data/memory/long_term/` 的稳定路径更合适
- `summary` 是检索与快速预览入口，不等于正文全文

### 5.7 `PersonaState`

定义：

`PersonaState` 表示当前生效的动态人格状态。

建议结构：

```python
@dataclass(slots=True)
class PersonaState:
    state_id: str
    scope_type: str
    scope_id: str
    persona_id: str | None
    familiarity: float
    trust: float
    warmth: float
    formality_preference: float
    directness_preference: float
    updated_at: datetime
```

用途：

- 表示当前动态人格值
- 给请求前 snapshot 提供人格状态输入

存储位置：

- `SQLite`

说明：

- 第一版不改写静态 persona
- 这里只承载可演进的动态部分

### 5.8 `PersonaEvolutionLog`

定义：

`PersonaEvolutionLog` 表示一次人格状态变化的审计记录。

建议结构：

```python
@dataclass(slots=True)
class PersonaEvolutionLog:
    log_id: str
    scope_type: str
    scope_id: str
    before_state: JsonDict | None
    after_state: JsonDict
    reason: str | None
    source_refs: list[SourceRef]
    created_at: datetime
```

用途：

- 用于溯源人格状态变化
- 不直接作为日常对话主输入

存储位置：

- `SQLite`

## 6. 请求前只读对象

### 6.1 `MemorySnapshot`

定义：

`MemorySnapshot` 表示请求前给 Prompt System 消费的只读视图。

建议结构：

```python
@dataclass(slots=True)
class MemorySnapshot:
    umo: str
    conversation_id: str | None
    topic_state: TopicState | None
    short_term_memory: ShortTermMemory | None
    experiences: list[Experience]
    long_term_memories: list[LongTermMemoryIndex]
    persona_state: PersonaState | None
    debug_meta: JsonDict
```

用途：

- 给 Prompt System / MemoryCollector 提供统一只读输入
- 屏蔽底层 store / vector / docs 细节

说明：

- 第一版不强求复杂聚合 summary
- 先返回结构化对象，后续再根据 prompt 构建系统做裁剪

## 7. 对象关系

### 7.1 上游到下游

主链路：

- `MemoryUpdateRequest -> TurnRecord`
- `TurnRecord -> TopicState`
- `TurnRecord -> ShortTermMemory`
- `TurnRecord / ShortTermMemory -> SessionInsight`
- `SessionInsight -> Experience`
- `Experience -> LongTermMemoryIndex`
- `Experience / LongTermMemoryIndex -> PersonaState`

### 7.2 读取链路

请求前读取链路：

- `TopicState`
- `ShortTermMemory`
- `Experience`
- `LongTermMemoryIndex`
- `PersonaState`
- 聚合为 `MemorySnapshot`

### 7.3 溯源链路

第一版统一通过 `source_refs` 维持引用关系：

- `Experience.source_refs` 指向 `TurnRecord` 或 `SessionInsight`
- `LongTermMemoryIndex.source_refs` 指向 `Experience`
- `PersonaEvolutionLog.source_refs` 指向 `Experience` 或 `LongTermMemoryIndex`

## 8. 第一版最小必需对象

第一版必须优先实现：

- `MemoryUpdateRequest`
- `TurnRecord`
- `TopicState`
- `ShortTermMemory`
- `Experience`
- `LongTermMemoryIndex`
- `MemorySnapshot`

后续可逐步补齐：

- `SessionInsight`
- `PersonaState`
- `PersonaEvolutionLog`

## 9. 当前结论

第一版 memory 数据模型应遵循：

- 原始材料、短期状态、时间线事件、长期对象、人格状态分层定义
- `Experience` 与 `LongTermMemoryIndex` 是并列层，不是从属关系
- `MemorySnapshot` 是请求前唯一统一读取视图
- 第一版先保持类型稳定与边界清晰，不提前引入复杂策略对象
