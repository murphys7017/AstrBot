# Memory Docs Index

本文件记录 `docs/Yakumo/dev/memory/` 的当前文档结构与后续补充顺序。

## 0. 当前实现进度

当前 memory 线已经完成到：

- `Post Process -> MemoryService` 回合后写入链路已接通
- `TurnRecord`、`TopicState`、`ShortTermMemory` 已稳定写入 `SQLite`
- `MemorySnapshot` 读取链路已接通
- 短期层已具备配置驱动的 analyzer 基础设施
- `SessionInsight` 与 `Experience` 已具备模型驱动的 consolidation 链路
- consolidation 当前按“回合后阈值触发”执行，不走独立 scheduler

当前仍未进入：

- `LongTermMemory` 沉淀
- `PersonaState` / `PersonaEvolutionLog` 更新
- `VectorIndex` / `Retriever`
- `MemorySnapshot` 的中长期结果扩张
- prompt render / prompt 注入

当前真实闭环：

1. `AFTER_MESSAGE_SENT`
2. `MemoryPostProcessor`
3. `MemoryService.update_from_postprocess(...)`
4. `TurnRecordService.ingest_turn(...)`
5. `ShortTermMemoryService.update_after_turn(...)`
6. 达阈值时 `MemoryService.run_consolidation(...)`
7. `ConsolidationService.run_for_scope(...)`
8. `ExperienceService.persist_experiences(...)`
9. 请求前通过 `MemoryService.get_snapshot(...)` 读取短期层只读视图

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
- 需要按当前代码状态继续维护阶段完成度说明

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

如果是先看当前代码已做到哪里，建议先读：

1. `index.md`
2. `mvp-plan.md`
3. `architecture.md`
4. `lifecycle.md`

## 5. 推荐编写顺序

当前推荐补充顺序：

1. `jobs-and-scheduling.md`
2. `snapshot-and-read-path.md`

说明：

- 目前模块结构、配置、数据对象与 MVP 范围已经基本收口
- 当前更需要补的是“已实现状态”和“下一阶段边界”同步

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

当前代码进度已经超过最初短期 MVP，正在进入中期抽象阶段：

- 已落地 `TurnRecord -> TopicState -> ShortTermMemory -> MemorySnapshot`
- 已落地 `SessionInsight -> Experience` 的 memory 内部闭环
- `MemorySnapshot` 仍停在短期层，只作为统一只读出口

下一步应继续补：

- `jobs-and-scheduling.md`
- `snapshot-and-read-path.md`
