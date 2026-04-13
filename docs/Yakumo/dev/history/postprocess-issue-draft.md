# Post Process Issue Draft

## Suggested Title

`Proposal: expose a unified post-process abstraction over existing plugin hooks`

## Suggested Body

```markdown
### Background

While working on AstrBot plugin extensions, I noticed that AstrBot already has several useful lifecycle hooks and an internal Pipeline/Stage-based architecture.

For example, plugin developers can already hook into lifecycle points such as:

- `OnLLMRequestEvent`
- `OnLLMResponseEvent`
- `OnAfterMessageSentEvent`

So this issue is not about missing low-level capability.

Instead, the current issue is that these lifecycle points are still relatively scattered from a plugin developer's perspective, especially for cross-cutting concerns that should run after a response is generated or after a message is sent.

### Problem

For plugin developers, post-response logic such as the following is increasingly important:

- memory update
- trace / debug logging
- stats collection
- response audit
- conversation summarization

These can already be implemented through existing hooks, but there is no unified post-process abstraction to organize them consistently.

As a result:

- plugin authors need to reason about multiple scattered hook points
- cross-cutting logic is harder to compose and reuse
- observability of execution order is limited
- it is harder to build a clean "after response / after send" processing model

### Suggestion

Consider exposing a higher-level post-process abstraction on top of the existing hook system, for example:

```python
class PostProcessor:
    triggers = ["on_llm_response", "after_message_sent"]

    async def run(self, ctx):
        ...
```

Or a manager-style registration model that internally reuses the current hooks.

### Why this matters

This could make AstrBot more ergonomic for advanced plugin development without breaking compatibility:

- existing hooks could remain unchanged
- the new abstraction could be additive
- plugin developers would gain a more structured lifecycle model
- cross-cutting features such as memory / tracing / statistics would be easier to implement cleanly

### Notes

This proposal is mainly about exposing existing internal power in a more structured way, rather than replacing the current architecture.

The current hook system is already useful. The suggestion is to make post-response / after-send extension more composable and observable for plugin authors.
```

## Chinese Notes

这版 issue 的口径是：

- 承认 AstrBot 已经有 hook 和 pipeline
- 不说“缺少底层能力”
- 强调“插件层缺少统一的 post-process 抽象”
- 聚焦请求后阶段，而不是一次性要求完整 middleware 系统

这样更符合当前仓库现状，也更容易被作者接受。

## Suggested Bilingual Version

```markdown
### Background / 背景

While working on AstrBot plugin extensions, I noticed that AstrBot already has several useful lifecycle hooks and an internal Pipeline/Stage-based architecture.

在开发 AstrBot 插件扩展时，我注意到 AstrBot 内部其实已经具备比较完整的生命周期能力，例如 Pipeline/Stage 架构，以及多个请求前后相关的 hooks。

For example, plugin developers can already hook into lifecycle points such as:

例如，当前插件开发者已经可以接入这些生命周期节点：

- `OnLLMRequestEvent`
- `OnLLMResponseEvent`
- `OnAfterMessageSentEvent`

So this issue is not about missing low-level capability.

所以这个 issue 不是在说 AstrBot 缺少底层能力。

Instead, the issue is that these lifecycle points are still relatively scattered from a plugin developer's perspective, especially for cross-cutting concerns that should run after a response is generated or after a message is sent.

我想表达的问题是：从插件开发者视角来看，这些生命周期入口仍然比较分散，尤其是对于那些“在响应生成后 / 消息发送后”执行的横切逻辑来说，还缺少一个统一、结构化的抽象层。

---

### Problem / 问题

For plugin developers, post-response logic such as the following is increasingly important:

对于插件开发者来说，下面这类“请求后逻辑”会越来越重要：

- memory update  
  记忆更新
- trace / debug logging  
  调试与链路追踪日志
- stats collection  
  统计信息收集
- response audit  
  响应审计
- conversation summarization  
  对话总结

These can already be implemented through existing hooks, but there is no unified post-process abstraction to organize them consistently.

这些事情理论上已经可以通过现有 hooks 实现，但目前还没有一个统一的 post-process 抽象来一致地组织它们。

As a result:

因此现在会出现一些问题：

- plugin authors need to reason about multiple scattered hook points  
  插件作者需要自己理解和拼接多个分散的 hook 时机

- cross-cutting logic is harder to compose and reuse  
  横切逻辑不容易组合和复用

- observability of execution order is limited  
  执行顺序和执行链路的可观测性有限

- it is harder to build a clean "after response / after send" processing model  
  很难建立一个清晰的“响应后 / 发送后”处理模型

---

### Suggestion / 建议

Consider exposing a higher-level post-process abstraction on top of the existing hook system.

我想建议的是：在现有 hook 系统之上，暴露一个更高层的 post-process 抽象。

For example:

例如：

```python
class PostProcessor:
    triggers = ["on_llm_response", "after_message_sent"]

    async def run(self, ctx):
        ...
```

Or a manager-style registration model that internally reuses the current hooks.

或者提供一个 manager-style 的注册模型，在内部复用当前 hooks，但对插件开发者暴露更统一的使用方式。

---

### Why this matters / 为什么这很重要

This could make AstrBot more ergonomic for advanced plugin development without breaking compatibility:

这样做可以在不破坏兼容性的前提下，让 AstrBot 对高级插件开发更友好：

- existing hooks could remain unchanged  
  现有 hooks 可以保持不变

- the new abstraction could be additive  
  新抽象可以作为增量能力加入

- plugin developers would gain a more structured lifecycle model  
  插件开发者可以获得一个更结构化的生命周期模型

- cross-cutting features such as memory / tracing / statistics would be easier to implement cleanly  
  像 memory / tracing / statistics 这种横切功能会更容易被干净地实现

---

### Notes / 补充说明

This proposal is mainly about exposing existing internal power in a more structured way, rather than replacing the current architecture.

这个提议的重点，更像是“把已有能力以更结构化的方式暴露出来”，而不是替换当前架构。

The current hook system is already useful. The suggestion is to make post-response / after-send extension more composable and observable for plugin authors.

当前 hook 系统本身已经很有用。这里想讨论的是：能否让“响应后 / 发送后”的扩展方式，对插件开发者来说更加可组合、可观测、可维护。
```
