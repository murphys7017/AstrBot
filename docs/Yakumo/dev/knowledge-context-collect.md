# Knowledge Context Collect

记录本次 `KnowledgeCollector` v1 的实现范围、数据结构和边界。

## 范围

- 新增 `KnowledgeCollector`
- 收集知识库非 agentic 模式下的检索结果
- 写入 `ContextPack` 供日志调试和后续 renderer 使用
- 不改原有知识库主链路逻辑
- 不处理 agentic KB tool 注入

## 本次实现

### 新增类

#### `astrbot/core/prompt/collectors/knowledge_collector.py`

新增 `KnowledgeCollector`。

职责：

- 收集 `knowledge.snippets`

主要函数：

- `collect(...)`
- `_resolve_query(...)`
- `_build_knowledge_slot(...)`

实现要点：

- 只在 `kb_agentic_mode == false` 时尝试收集
- query 优先使用 `provider_request.prompt`
- 没有 `provider_request.prompt` 时回退 `event.message_str`
- 调用 `retrieve_knowledge_base(...)` 获取结果
- 只有检索结果非空时才产出 slot
- slot 采用薄包装结构，不直接模拟最终 prompt 拼接
- fail-open，检索异常只打 warning，不中断 collect

## 当前 slot 结构

### `knowledge.snippets`

value:

- `format`
- `query`
- `text`

meta:

- `format=kb_text_block_v1`
- `query_source=provider_request.prompt|event.message_str`
- `kb_agentic_mode=<bool>`

## 设计思路

- 这次 collector 明确对齐原版 `_apply_kb()` 的非 agentic 路径
- 原版主链路在这一路径上，本质上只是拿到一段知识库结果文本并注入 prompt
- 所以 collect 阶段没有必要提前拆成复杂 snippet list
- 先保留为单文本块，更贴近原版，也更利于后续 renderer 复用

## 本次实现边界

- 不修改 `astrbot/core/astr_main_agent.py`
- 不修改 `_apply_kb()`
- 不处理 `kb_agentic_mode=true` 时的 KB query tool
- 不做 renderer
- 不做 selector
- 不改 `ProviderRequest`

## 验证

验证项包括：

- `kb_agentic_mode=false` 且检索到结果时，产出 `knowledge.snippets`
- `provider_request.prompt` 优先于 `event.message_str`
- 无 query 或检索无结果时，不产出 slot
- KB 检索异常时 fail-open

结果以实际测试输出为准。
