# 人格、身份与长期记忆架构调整计划

本目录是 AG99 人格中心化架构调整的计划文档集合，适用范围是 AstrBot Core、Prompt 构建系统和 LivingMemory 长期记忆插件。

本文档集属于**设计/计划**，不能作为当前实现说明。当前行为仍以源码和 [Yakumo 架构文档](../../README.md) 为准。

## 阅读顺序

1. [总体计划](00-overall-plan.md)
2. [统一身份契约计划](01-unified-identity-contract.md)
3. [Prompt 记忆注入点计划](02-prompt-memory-injection.md)
4. [LivingMemory 长期记忆迁移计划](03-livingmemory-migration.md)
5. [切换、验收与旧路径退出计划](04-cutover-validation-and-retirement.md)

## 计划边界

- AG99live 继续作为消息、桌面状态和表现能力的适配来源，本计划不重写 AG99live 的运行时。
- 适配器负责接入和传输，Persona Runtime 负责统一身份、人格和交互生命周期。
- 当前只运行一个 Persona 实例，不引入多人格调度。
- LivingMemory 作为长期记忆提供者，AstrBot 内置 Memory 保留兼容能力并逐步停止长期记忆注入。
- 不修改已有记忆数据库，不回填历史作用域。

## 文档维护规则

- 代码完成后，先把对应分计划中的“当前状态”改成已完成，再同步当前实现文档。
- 计划中的接口名属于设计名称，落地时以源码现有命名和兼容约束为准。
- 生成部署目录不作为源代码编辑位置。LivingMemory 与 AG99live 的源代码必须在各自源仓库维护，再执行部署脚本。
