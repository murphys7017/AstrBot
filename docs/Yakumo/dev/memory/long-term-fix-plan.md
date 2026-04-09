# Long-Term Memory Fix Plan

本文件用于收口当前 `LongTermMemory + Document Search V1` 实现中的已确认问题。

目标不是重写设计，而是在继续做长期记忆本体之前，先修掉会影响数据正确性、生命周期稳定性和读取语义的关键问题。

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

修复方向：

- 把 `SQLite` 作为长期记忆第一真源
- 长期记忆 promotion 改成“数据库先原子提交，Markdown 后置刷新”
- `Markdown` 视为派生产物，不参与主事务成败判定

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

修复方向：

- 第一轮优先收紧为同步 API
- 不制造“假异步”接口
- 如果未来确实需要异步文件 I/O，再统一引入真实异步实现

### 2.5 P2: `DocumentSearchResult.body_text` 当前返回的是整份 Markdown 原文，不是正文

涉及：

- `astrbot/core/memory/document_search.py`

当前行为：

- `include_body=True` 时把 `document.raw_text` 直接塞进 `body_text`

风险：

- 调用方拿到的是带 front matter 的整份原始文档
- YAML 元数据、结构噪声、更新记录会混入“正文”
- 后续如果 collector 或 prompt 侧直接消费，会把结构噪声当正文输入

修复方向：

- 保留字段名 `body_text`
- 但语义收紧为“正文内容”，不包含 front matter
- 如果需要原始文档全文，后续另开专门字段或接口

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

当前真正需要关注的不是“中文被抹掉”，而是路径可读性和特殊字符处理是否要继续优化。这个问题目前优先级不高，不作为本轮修复项。

## 4. 推荐修复顺序

### 4.1 第一组：先修数据正确性

顺序：

1. promotion 改成“数据库原子提交优先，Markdown 后置刷新”
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
5. 调用 store 原子落库：
   - `LongTermMemoryIndex`
   - `LongTermMemoryLink`
   - `LongTermPromotionCursor`
6. 数据库成功后，再刷新 Markdown 文档
7. Markdown 成功后，再刷新向量索引

其中：

- 数据库失败：整体失败，不推进 cursor
- Markdown 失败：数据库保留成功结果，记录错误，允许后续重建
- 向量索引失败：数据库和 Markdown 保留成功结果，记录错误，允许后续重建

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

- 数据库成功后才能刷新长期记忆 Markdown
- Markdown 失败不会破坏已提交数据库结果
- 后续可以按 scope 或 memory_id 重建文档

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

## 8. 当前结论

当前长期记忆第一版已经够进入“修实现细节”的阶段，而不是继续堆新设计。

真正需要优先修的是：

- 真源提交顺序
- promote 批次契约
- 同批次更新一致性

这三项修完之后，再继续往长期记忆增强和读取接入走，会更稳。
