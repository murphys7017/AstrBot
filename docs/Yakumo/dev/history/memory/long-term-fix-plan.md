# Long-Term Memory Fix Record

本文件用于保留 `LongTermMemory + Document Search V1` 第一轮稳定性修复的历史记录。

它的职责不是持续充当正式设计文档，而是记录：

- 当时确认过哪些问题
- 为什么这样修
- 修完后当前语义是什么

后续如果长期记忆本体设计继续推进，应优先把这里已经稳定下来的结论吸收到正式设计文档中；吸收完成后，这份文档可以降级为历史记录，甚至删除。

## 0. 文档定位

本文件对应的第一轮关键修复已经落地，当前文件主要作为：

- 已确认问题的历史记录
- 已修复行为的语义对齐说明
- 后续长期记忆继续演进时的边界参考

当前已经完成的修复包括：

- `DocumentLoader` 已收紧为同步接口
- `DocumentSearchResult.body_text` 已收紧为正文，不再暴露 front matter
- `long_term_promote` 已具备批次级全覆盖 / 不重复 / 重复 update target 校验
- 长期记忆 promotion 已改成“文档 staging + 数据库原子提交 + 向量刷新”
- 手动导入已改成严格模式，向量索引开启时会显式校验可用性
- 长期文档路径已改成稳定 hash 方案，避免路径碰撞
- `importance / confidence` 已收紧到 `0..1`

## 1. 当前结论

当前长期记忆第一版已经具备以下主链路：

- `Experience` 达阈值后触发长期记忆沉淀
- `long_term_promote` 决定 `create / update / ignore`
- `long_term_compose` 生成长期记忆内容
- `SQLite` 保存 `LongTermMemoryIndex / LongTermMemoryLink / Cursor`
- `Markdown` 保存长期记忆正文
- `VectorIndex` 提供长期记忆检索
- `DocumentSearchService` 可按 scope 检索长期记忆

当前问题不在“设计缺失”，而在“实现细节还不够稳”，尤其是：

- 数据提交原子性
- promote 动作约束
- 同批次更新一致性
- 文档 I/O 语义
- 搜索结果正文语义

## 2. 本轮只确认这些是真问题

### 2.1 P1: Markdown 在数据库批量提交前写入

涉及：

- `astrbot/core/memory/long_term_service.py`
- `astrbot/core/memory/document_loader.py`
- `astrbot/core/memory/store.py`

当前行为：

- `run_promotion(...)` 里先调用 `DocumentLoader.save_long_term_document(...)`
- 后面才调用 `MemoryStore.persist_long_term_promotion_batch(...)`

风险：

- 如果数据库批量写入失败，会留下孤儿 Markdown 文件
- `SQLite` 和 `Markdown` 会暂时失去一致性
- 后续审阅会看到并不存在于真源索引中的长期记忆文档

当前状态：

- 已修复

实际实现：

- 长期记忆 promotion 现在先准备文档 staging 文件
- 文档 staging 成功后才进入数据库原子提交
- 数据库失败时会回滚已应用的长期文档写入
- 向量索引刷新在数据库成功之后执行

### 2.2 P1: `long_term_promote` 动作校验没有保证候选 experiences 全覆盖且不重复

涉及：

- `astrbot/core/memory/long_term_service.py`

当前行为：

- `_validate_promote_payload(...)` 只校验单条 action 的字段形状
- 没有校验：
  - 每个候选 `experience_id` 是否都被 action 覆盖
  - 同一个 `experience_id` 是否出现在多个 action 中

风险：

- 某些 experience 可能完全没被处理
- 某些 experience 可能被重复处理到多个动作里
- 但 promotion cursor 仍会推进到本批次末尾
- 结果就是 experience 被“悄悄跳过”或“重复归并”

修复方向：

- 在 promote 结果校验阶段增加批次级约束
- 明确要求“本批次每个候选 experience 必须且只能被一个 action 消费”
- 如果不满足，直接按 strict 失败，不推进 cursor

### 2.3 P1: 同一批次多个 `update` 指向同一 `memory_id` 时，后一个更新看不到前一个更新结果

涉及：

- `astrbot/core/memory/long_term_service.py`

当前行为：

- `existing_memories` 和 `memory_map` 在循环前只加载一次
- 同一批次里如果出现多个 `update -> 同一个 memory_id`
- 后续 update 仍基于旧的 `existing_memory / existing_document` 继续 compose

风险：

- 后一个 update 可能覆盖前一个 update 的结果
- 同一批 promotion 内的语义不一致
- 长期记忆文档和 link 关系可能无法真实反映这批 experiences 的累计效果

修复方向：

- 第一轮先做严格限制
- 若同一批次出现多个 `update` 指向同一 `memory_id`，直接失败
- 后续若需要支持批内多次累积更新，再设计 working-set merge

### 2.4 P1/P2: `DocumentLoader` 是 async API，但内部做同步文件 I/O

涉及：

- `astrbot/core/memory/document_loader.py`

当前行为：

- `load_long_term_document(...)` / `save_long_term_document(...)` 是 `async def`
- 但内部直接使用 `Path.read_text()` / `Path.write_text()`

风险：

- API 语义和真实执行模型不一致
- 在事件循环里执行同步文件 I/O，会阻塞当前协程调度
- 后续如果大量长期记忆文档读写，会放大这个问题

当前状态：

- 已修复

实际实现：

- `DocumentLoader.load_long_term_document(...)` / `save_long_term_document(...)` 已改为同步接口
- 并额外补了 staging / rollback 所需的文档写入准备接口

### 2.5 P2: `DocumentSearchResult.body_text` 当前返回的是整份 Markdown 原文，不是正文

涉及：

- `astrbot/core/memory/document_search.py`

当前行为：

- `include_body=True` 时把 `document.raw_text` 直接塞进 `body_text`

风险：

- 调用方拿到的是带 front matter 的整份原始文档
- YAML 元数据、结构噪声、更新记录会混入“正文”
- 后续如果 collector 或 prompt 侧直接消费，会把结构噪声当正文输入

当前状态：

- 已修复

实际实现：

- `body_text` 保持字段名不变
- 返回值已收紧为去掉 YAML front matter 后的正文内容

## 3. 已确认这些不是问题

### 3.1 `vector_index.py` 使用 `doc_id` 作为 `memory_id` 是正确的

原因：

- 长期记忆入向量库时，写入的 `id` 本来就是 `memory_id`
- 检索结果里的 `doc_id` 就是当时写入的长期记忆主键

因此这里不是 bug，不需要按“metadata 里的 `memory_id` 才是正确值”的思路去改。

### 3.2 `_safe_path_component(...)` 不会把中文全部替换掉

原因：

- Python 的 `str.isalnum()` 对中文字符返回 `True`
- 所以“中文路径会全部变成 `_`”这个判断不成立

补充：

- 当前实现已经进一步收紧为“slug + hash”路径策略
- 所以后续真正需要关注的是路径长期稳定性，而不是中文是否被替换

## 4. 推荐修复顺序

### 4.1 第一组：先修数据正确性

顺序：

1. promotion 改成“文档 staging + 数据库原子提交 + 向量刷新”
2. promote 动作增加“全覆盖 + 不重复”校验
3. 同批次重复 `update memory_id` 直接失败

原因：

- 这三项都直接影响长期记忆真源是否正确
- 如果这层不稳，后面的搜索、投影、prompt 消费都没有基础

### 4.2 第二组：再修文档 I/O 和读取语义

顺序：

1. `DocumentLoader` 改成同步 API
2. `DocumentSearchResult.body_text` 改成只返回正文

原因：

- 这两项更多影响的是实现语义和后续可扩展性
- 重要，但不应先于数据正确性问题

## 5. 建议修复策略

### 5.1 Promotion 主链路

建议把 `run_promotion(...)` 收紧成：

1. 读取 pending experiences
2. 调用 `long_term_promote`
3. 对 promote actions 做批次级严格校验
4. 调用 `long_term_compose` 生成内存对象
5. 先把长期文档写入 staging / 应用到目标路径
6. 调用 store 原子落库：
   - `LongTermMemoryIndex`
   - `LongTermMemoryLink`
   - `LongTermPromotionCursor`
7. 数据库成功后，再刷新向量索引

其中：

- 文档准备失败：整体失败，不进入数据库提交
- 数据库失败：整体失败，回滚已应用的长期文档，不推进 cursor
- 向量索引失败：数据库和 Markdown 保留成功结果，显式失败暴露问题

说明：

- 这里和最初计划相比有一处收紧：当前实现没有把长期记忆 Markdown 视为“纯 projection”
- 原因是长期记忆 update 与正文检索都真实依赖该文档内容
- 因此第一轮更合理的策略是把长期文档纳入主一致性语义，而不是简单后置为可丢弃派生物

### 5.2 Promote 结果校验

建议增加批次级约束函数，至少校验：

- 候选 `experience_id` 集合
- actions 中声明的 `experience_id` 集合
- 是否存在缺失项
- 是否存在重复项
- 是否存在同一批次多个 `update` 指向同一 `memory_id`

开发阶段应保持 strict：

- 任何不满足契约的结果都直接失败
- 不做 fallback 自动修补

### 5.3 文档读取接口

建议把 `DocumentLoader` 调整为同步接口：

- `load_long_term_document(...)`
- `save_long_term_document(...)`

这样可以让接口语义和真实执行方式一致。

### 5.4 搜索正文接口

建议把 `DocumentSearchService` 的正文返回语义固定为：

- `body_text` 只包含正文内容
- 不包含 YAML front matter
- 不直接暴露整份 raw Markdown

## 6. 验收标准

### 6.1 数据正确性

- 数据库批量写入失败时，不留下“被认为已经生效”的长期记忆索引和 cursor
- 不会因为 promote 结果漏掉 experience 而推进 cursor
- 同一批次多个 `update -> 同一 memory_id` 会直接失败

### 6.2 文档一致性

- 数据库失败时，不留下已被视为成功的长期记忆文档
- 长期记忆索引与正文路径保持一致
- 文档路径对中文 / 特殊字符稳定

### 6.3 读取语义

- `DocumentLoader` 不再提供假异步接口
- `DocumentSearchResult.body_text` 为正文，而不是原始 Markdown 全文

## 7. 本轮不做什么

本修复计划不包括：

- 长期记忆 retrieval 扩张
- `MemorySnapshot` 接入长期记忆
- hybrid search / rerank
- 长期记忆与 `Experience` 的更强归并策略
- `working-set merge` 版的批内多次 update 支持

## 8. 后续处理建议

这三项关键问题在第一轮里已经完成。

接下来更合理的方向是：

- 继续设计长期记忆本体归并与更新策略
- 设计人工维护与系统自动沉淀的协作方式
- 再决定长期记忆何时进入 snapshot / retrieval / prompt 消费链路

当这些内容进入正式设计文档后，本文件应视为：

- 历史修复记录
- 不再持续扩写的新问题清单
- 不再承担长期记忆正式设计入口的角色
