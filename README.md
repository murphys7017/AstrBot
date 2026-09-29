# AG99

> 让人格成为对话的中心。

AG99 是由 YakumoAki 创建、基于 AstrBot 独立演进的 Persona-first 多平台对话 Runtime。
它不是把每一条消息交给模型后等待一次性回复的机器人，而是让一个持续存在的 Persona
理解关系、保持表达、管理有限状态，并在真正需要时调度复杂能力。

[开始使用](#快速开始) · [项目身份](./docs/Yakumo/project-identity.md) · [完整文档](./docs/README.md) · [问题反馈](https://github.com/murphys7017/AG99/issues)

## 对话应该有连续性

同一个 Persona 面对即时闲聊、复杂任务的进度反馈和最终结果，仍以一致的身份与语气交流。
它能记住当下对话的脉络，在合适的边界内主动关心，而不是把每一轮都当作孤立的问答。

当任务需要检索、工具调用、定时处理或更长的执行过程时，AG99 会把工作交给 Core；Core
只负责完成任务，结果仍回到 Persona 手中，再以适合这段对话的方式说出来。

## AG99 带来的体验

- **持续而一致的 Persona**：即时回复、插件输出和任务结果走同一条表达链路，减少口吻跳变与重复回答。
- **知道何时深入处理**：先判断是直接回应、委派复杂工作，还是在允许的场景保持安静；不让每条消息都触发重型执行。
- **把复杂留在幕后**：任务执行、工具与状态管理由 Core 承担，对话窗口保持自然、清晰和可控。
- **为多平台而生**：复用 AstrBot 的平台适配器、Provider、插件、Dashboard 和 CLI 基础设施，在熟悉的生态中运行。
- **受约束的主动性**：后台观察先经过明确的 Gate、Policy 和 ActionIntent，再决定是否表达；观察不会直接发送消息或调用工具。

## 快速开始

前提：Python `3.12+`，以及 [uv](https://docs.astral.sh/uv/getting-started/installation/)。

```bash
uv sync
uv run main.py
```

启动后打开 `http://localhost:6185` 进入 Dashboard。首次启动生成的账号和密码会输出到控制台；
随后配置 Provider 与消息平台适配器，即可开始建立自己的 Persona 对话体验。

- [源码部署指南](./docs/zh/deploy/astrbot/cli.md)
- [消息平台接入](./docs/zh/platform/start.md)
- [Provider、平台与 Dashboard 文档](./docs/README.md)

开发 Dashboard 时：

```bash
cd dashboard
pnpm install
pnpm dev
```

## 深入了解

- [Yakumo 架构索引](./docs/Yakumo/README.md)：当前运行时边界、模块说明与推荐阅读顺序。
- [当前状态](./docs/Yakumo/current-state.md)：已实现能力、仍在验证的边界和准确限制。
- [Interaction Runtime](./docs/Yakumo/modules/interaction.md)：Persona、Core、插件与输出的协作关系。
- [Structured Prompt](./docs/Yakumo/modules/prompt.md)：不同执行阶段如何看到所需的上下文。
- [Persona Effect](./docs/zh/dev/star/guides/persona-effects.md) 与 [Prompt Extension](./docs/zh/dev/star/guides/prompt-extensions.md)：扩展 Persona 表现与结构化上下文的插件协议。

## 开发状态

AG99 正在持续开发。Personal Runtime、Persona Expression、结构化 Prompt 和 Core 执行边界
已经接入实际链路，但不同 Provider 的结构化输出、外部执行器的流式投递，以及各平台的真实
取消和迟到结果场景仍在持续验证。

AG99 与上游 AstrBot 共用成熟的基础设施，但不是上游的稳定替代品。部署到真实平台前，请先
在自己的 Provider、平台适配器和插件组合上完成验证；运行时行为以本仓库源码与
[Yakumo 架构文档](./docs/Yakumo/) 为准。

## 许可证与来源

AG99 基于 AstrBot 独立演进，使用 `AGPL-3.0-or-later` 许可证，并继续遵守适用的 AstrBot
兼容说明。

- [LICENSE](./LICENSE)
- [EULA](./EULA.md)
- [AstrBot 上游仓库](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 官方文档](https://docs.astrbot.app/)
