# Memory Docs Index

本文件记录 `docs/Yakumo/dev/memory/` 的当前文档结构与后续补充顺序。

## 1. 当前目录目标

当前目录用于收口 AstrBot memory 系统的：

- 数据分层
- 存储模型
- 生命周期
- 模块结构
- MVP 实现顺序

当前目录只讨论 memory 系统本身，不替代：

- `Prompt System`
- `Post Process System`

## 2. 当前已存在文档

### 2.1 `storage-model.md`

内容：

- 各类 memory 数据使用什么存储载体
- `SQLite`、`Markdown`、向量库、图数据库的职责边界
- 哪些对象是主存储，哪些只是投影或索引

当前状态：

- 已完成第一版共识整理

### 2.2 `short-term-memory.md`

内容：

- 短期层第一版对象
- `TopicState`
- `ShortTermMemory`
- 两者边界、用途、更新时机

当前状态：

- 已完成第一版共识整理

### 2.3 `lifecycle.md`

内容：

- `TurnRecord -> TopicState -> ShortTermMemory -> SessionInsight -> Experience -> LongTermMemory -> PersonaState`
- 各阶段触发时机
- 各阶段输入输出
- 第一版实现顺序

当前状态：

- 已完成第一版链路整理

### 2.4 `architecture.md`

内容：

- memory 系统的模块结构
- 推荐代码目录
- service / store / postprocessor / job / retriever / vector index 的函数级接口
- 各模块之间的调用链

当前状态：

- 已完成第一版实现导向结构整理

### 2.5 `config.md`

内容：

- `data/memory/config.yaml` 的第一版配置结构
- 默认目录结构
- 哪些配置在第一版开放
- 后续如何迁移到 AstrBot 统一配置

当前状态：

- 已完成第一版配置整理

### 2.6 `data-model.md`

内容：

- 基础类型与枚举约定
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

当前状态：

- 已完成第一版数据类型设定

### 2.7 `mvp-plan.md`

内容：

- 第一版实现范围
- 不做什么
- 实现顺序
- 需要补哪些代码目录与接口

当前状态：

- 已完成第一版最小实现规划

## 3. 建议补充文档

### 3.1 `jobs-and-scheduling.md`

内容：

- 哪些更新走回合后即时执行
- 哪些更新走定时任务
- 定时任务如何和长期记忆 / 人格状态对齐

优先级：

- 中

### 3.2 `snapshot-and-read-path.md`

内容：

- 请求前如何读取 memory
- `MemorySnapshot` 如何构建
- 后续如何被 Prompt System 消费

优先级：

- 中

## 4. 推荐阅读顺序

当前推荐顺序：

1. `storage-model.md`
2. `short-term-memory.md`
3. `lifecycle.md`
4. `architecture.md`
5. `config.md`
6. `data-model.md`
7. `mvp-plan.md`

## 5. 推荐编写顺序

当前推荐补充顺序：

1. `jobs-and-scheduling.md`
2. `snapshot-and-read-path.md`

说明：

- 目前模块结构、配置、数据对象与 MVP 范围已经基本收口
- 下一步应该把调度和读取链路继续收紧

## 6. 当前目录边界

本目录负责：

- memory 系统设计本身
- memory 的存储、生命周期、结构、配置与实现计划

本目录暂不负责：

- prompt selector 设计
- intent router 设计
- chat state / context selector 设计
- postprocess 自身设计

## 7. 当前结论

当前 `docs/Yakumo/dev/memory/` 已经形成第一版主骨架：

- 存储模型
- 短期对象
- 生命周期
- 模块结构
- 配置结构
- 数据类型设定
- MVP 范围

下一步应继续补：

- `jobs-and-scheduling.md`
- `snapshot-and-read-path.md`
