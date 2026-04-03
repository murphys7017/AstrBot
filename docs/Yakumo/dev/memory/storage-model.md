# Memory Storage Model

本文件记录当前 AstrBot memory 系统对数据类型、存储载体与索引方式的共识。

## 1. 总体原则

- `SQLite` 是结构化真源。
- `Markdown` 用于保存高价值、低频更新、需要人工审阅的长期对象正文。
- 第一版即引入简单向量库用于语义检索索引，但不作为真源。
- 图数据库暂时只作为后续关系增强方向预留，不进入第一版主链路。

## 2. 当前确定的数据分层

### 2.1 短期层

存储方式：

- 主存储：`SQLite`
- 不使用 `Markdown` 作为主载体

当前包含：

- `TopicState`
- `ShortTermMemory`

说明：

- 短期层更新频率高。
- 短期层主要服务最近几轮连续对话。
- 短期层不应被设计成文档对象。

### 2.2 经历层

存储方式：

- 主存储：`SQLite`
- 审阅投影：`Markdown`（可选）
- 语义检索索引：向量库

对象：

- `Experience`

说明：

- `Experience` 强时间线、强来源、强聚合。
- 它更适合作为事件流保存在数据库中。
- 如后续需要人工审阅，可导出时间线型 `Markdown` 视图。
- 第一版即建议把高价值 `Experience` 摘要写入简单向量索引。

### 2.3 长期记忆层

存储方式：

- 索引与元数据：`SQLite`
- 正文内容：`Markdown`
- 语义检索索引：向量库

对象：

- `LongTermMemory`

说明：

- 一个长期记忆对象对应一个 `Markdown` 文件。
- 文件头使用 YAML front matter 保存概要信息。
- 数据库保存文档索引、摘要、标签、重要性、置信度、文件路径。
- 向量库只保存需要被语义召回的长期对象摘要，不保存为真源。

### 2.4 人格层

存储方式：

- 当前动态状态：`SQLite`
- 演进日志：`SQLite`

对象：

- `PersonaState`
- `PersonaEvolutionLog`

说明：

- `PersonaState` 表示当前生效的人格动态值。
- `PersonaEvolutionLog` 用于溯源，不直接作为日常对话读取输入。
- 当前共识是不使用 `Markdown` 存人格演进日志。

## 3. 各类数据的存储决定

### 3.1 `TopicState`

- 主存储：`SQLite`
- 不进入向量库
- 不单独写 `Markdown`

### 3.2 `ShortTermMemory`

- 主存储：`SQLite`
- 不进入向量库
- 不单独写 `Markdown`

### 3.3 `Experience`

- 主存储：`SQLite`
- 进入向量库
- 可选导出 `Markdown` 时间线投影

### 3.4 `LongTermMemory`

- 正文：`Markdown`
- 索引：`SQLite`
- 检索：向量库

### 3.5 `PersonaState`

- 主存储：`SQLite`
- 不单独写 `Markdown`

### 3.6 `PersonaEvolutionLog`

- 主存储：`SQLite`
- 不单独写 `Markdown`

## 4. `Markdown` 文档对象规则

当前仅明确适用于：

- `LongTermMemory`

建议结构：

```md
---
id: ltm_xxx
type: long_term_memory
scope_type: user
scope_id: xxx
summary: 用户偏好先完成基础设施再做路由层
importance: 0.82
confidence: 0.76
tags:
  - architecture
  - planning
source_refs:
  - exp_001
  - exp_002
created_at: 2026-04-03T00:00:00Z
updated_at: 2026-04-03T00:00:00Z
---

## Current Understanding
...

## Evidence
...

## Updates
- 2026-04-03: created
```

约束：

- 数据库中的索引必须能定位到唯一文档路径。
- 文档是长期对象正文，不是高频状态缓存。
- 一次更新优先更新数据库索引与文档正文，再按需刷新向量索引。

## 5. 数据库职责

`SQLite` 负责：

- 结构化真源
- 时间线查询
- 按会话、用户、scope 聚合
- 当前状态读取
- 文档索引管理
- 演进日志溯源

推荐由数据库主存储的对象：

- `TurnRecord`
- `TopicState`
- `ShortTermMemory`
- `Experience`
- `PersonaState`
- `PersonaEvolutionLog`
- `MemoryDocumentIndex`

## 6. 向量库职责

向量库负责：

- 语义召回候选
- 长期记忆相关检索增强

第一版建议索引：

- `LongTermMemory.summary`
- 高价值 `Experience.summary`

当前不建议：

- 把所有原始对话写入向量库
- 把短期状态写入向量库

## 7. 图数据库职责

图数据库当前只作为预留方向：

- 用户关系图谱
- 主题关系图谱
- 偏好与事实关系
- 项目与经历之间的引用关系

当前不进入第一版 MVP 主链路。

## 8. 当前结论

- 短期层：`SQLite`
- 经历层：`SQLite` 为主，`Markdown` 只做投影，并进入简单向量索引
- 长期记忆层：`SQLite` 索引 + `Markdown` 正文 + 向量检索
- 人格层：`SQLite` 状态 + `SQLite` 演进日志
