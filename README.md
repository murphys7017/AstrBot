<p align="center">
  <img src="./docs/public/logo_prod.png" width="112" alt="AG99 logo">
</p>

<h1 align="center">AG99</h1>

<p align="center"><strong>让 AI 不止会回答，而是以一个人格持续地理解、陪伴与行动。</strong></p>

<p align="center">
  由 YakumoAki 创建，基于 AstrBot 独立演进的 Persona-first 多平台对话 Runtime。
</p>

<p align="center">
  <code>Persona-first</code> · <code>Multi-platform</code> · <code>Bounded initiative</code>
</p>

<p align="center">
  <a href="#快速开始">开始使用</a> ·
  <a href="./docs/Yakumo/project-identity.md">认识 AG99</a> ·
  <a href="./docs/README.md">完整文档</a> ·
  <a href="https://github.com/murphys7017/AG99/issues">问题反馈</a>
</p>

---

## 从一条消息，到一段关系

多数 AI Bot 擅长给出答案，却很难让人感到正在和同一个对象说话。每条消息都是一次新的推理，
每个任务又像换了一个人：闲聊很自然，查资料时变成机械播报，工具跑完后口吻彻底断裂。

AG99 从一开始就把 **Persona** 放在中心。

它让一个持续存在的交互主体处理对话：理解这段关系正在发生什么，记住当下的脉络，维持自己的
表达方式，并在需要深入处理时，把复杂工作交给幕后能力。你看到的始终是同一个 Persona；它不必
把检索、工具、任务排程和执行过程原样摊在对话里。

> 不是“向模型发一条消息，得到一条回答”，而是“和一个知道何时回应、何时行动、何时安静的人格持续相处”。

<p align="center"><strong>能聊天，也能做事；更重要的是，它始终是它。</strong></p>

## 当对话需要真的去做事

你说一句“帮我查一下，整理好了告诉我”。AG99 不会把这句简单地扔给一个工具循环。

1. **Persona 先接住你。** 它判断此刻应该直接回应、委派复杂工作，还是在合适的群聊场景保持安静。
2. **复杂留在幕后。** 需要检索、工具调用、定时处理或更长执行过程时，Core 负责把任务真正完成。
3. **过程仍有温度。** 任务进行中，Persona 可以给出符合当前关系和语境的进度反馈，而不是一串生硬状态码。
4. **结果回到同一个人手里。** Core 的事实结果不会直接冲到平台上，而是回到 Persona，由它组织成自然、准确的最终表达。

这意味着轻量对话不必为复杂任务付出同样的等待；复杂任务也不必牺牲身份感和连续性。

## 你能感受到的不同

| 你在意的事 | AG99 的处理方式 |
| --- | --- |
| **它还是原来的它吗？** | 即时回复、插件输出、任务进度和最终结果都经过同一 Persona Expression，减少口吻跳变、重复回答和“工具人格”突然出现。 |
| **它知道什么时候该认真做事吗？** | Personal Response Plan 先选择 `reply`、`delegate` 或允许场景下的 `silent`；只有真正需要时才把任务交给 Core。 |
| **它会不会为了主动而打扰？** | 主动表达先经过 Observation、Gate、Policy 和 ActionIntent；后台事实不会直接发送消息，也不会直接调用工具。 |
| **我能把它放进现有环境吗？** | AG99 复用 AstrBot 的平台适配器、Provider、插件、Dashboard 与 CLI 基础设施，在熟悉的多平台生态中运行。 |
| **复杂能力会不会淹没对话？** | 工具、执行状态和结构化上下文在 Core 与 Prompt 边界内管理；对话窗口只保留真正应该被看见的内容。 |

## 与官方 AstrBot：同一生态，不同重心

AG99 不是把 AstrBot 推倒重来，也不把上游当作对立面。它继续使用 AstrBot 成熟的平台接入、
Provider、插件、Dashboard 和 CLI 基础设施；区别在于，AG99 选择把持续 Persona 作为运行时的
第一原则，并重写了围绕它的交互、表达、上下文和任务回流边界。

| 对比维度 | 官方 AstrBot | AG99 |
| --- | --- | --- |
| **公开定位** | 面向个人与群聊的 Agentic AI 助手，强调 IM 接入、插件扩展与通用 Agent 能力编排。 | Persona-first 多平台对话 Runtime，把“持续存在的交互主体”作为产品体验的起点。 |
| **AI 能力组织** | Chat Provider 负责模型回复，Agent Runner 负责多轮规划、工具调用与执行。 | 保留并复用这些能力，但由 Personal Response Plan 决定何时直接表达、何时委派 Core；Core 结果必须回到 Persona。 |
| **Persona 的位置** | 内置 Agent Runner 可以使用 Persona 功能。 | Persona 是所有用户可见表达的统一入口，并跨即时回复、任务进度、最终结果和受控主动表达维持连续性。 |
| **主动与状态** | 提供可扩展的 Bot、插件和 Agent 基础能力。 | 将 Observation、Gate、Policy 与 ActionIntent 作为显式边界，让主动性在可检查的约束下发生。 |
| **适合谁** | 想快速接入 IM、模型、插件和通用 Agent 能力的用户。 | 想在这些能力之上，打造有长期身份感、关系感和一致表达的 AI 的用户。 |

官方 AstrBot 仍是 AG99 的兼容基础与上游参考。若你的目标是接入一个成熟、可扩展的 AI Bot，
[AstrBot](https://docs.astrbot.app/) 已提供完整的平台、Provider、插件和 Agent 路径；若你更在意
“它是否始终像同一个人”，AG99 选择继续沿着 Persona Runtime 这条路深入。

## 为想要“角色感”的 AI 而生

AG99 适合那些不满足于“一个能调用工具的 Bot”的人。

- 想打造有稳定身份、长期语气和关系感的个人 AI。
- 想把聊天、检索、执行、定时任务与插件能力放进同一段自然对话。
- 想在多个消息平台上维持同一个 Persona，而不是维护一组彼此割裂的自动回复。
- 想让主动性有边界：它可以在适当的时候开口，但不会绕过规则、凭空行动或把观察事实当成用户指令。

AG99 的目标不是替你把每个流程自动化，而是给这些能力一个可信、可持续的对外人格。

## 快速开始

前提：Python `3.12+`，以及 [uv](https://docs.astral.sh/uv/getting-started/installation/)。

```bash
uv sync
uv run main.py
```

启动后打开 `http://localhost:6185` 进入 Dashboard。首次启动生成的账号和密码会输出到控制台；
配置 Provider 与消息平台适配器后，就可以开始建立自己的 Persona 对话体验。

- [源码部署指南](./docs/zh/deploy/astrbot/cli.md)
- [消息平台接入](./docs/zh/platform/start.md)
- [Provider、平台与 Dashboard 文档](./docs/README.md)

开发 Dashboard 时：

```bash
cd dashboard
pnpm install
pnpm dev
```

## 想了解得更深

- [AG99 项目身份](./docs/Yakumo/project-identity.md)：项目定位，以及与 AstrBot 的兼容边界。
- [Yakumo 架构索引](./docs/Yakumo/README.md)：当前运行时边界、模块说明与推荐阅读顺序。
- [当前状态](./docs/Yakumo/current-state.md)：已实现能力、仍在验证的边界和准确限制。
- [Interaction Runtime](./docs/Yakumo/modules/interaction.md)：Persona、Core、插件与输出如何协作。
- [Structured Prompt](./docs/Yakumo/modules/prompt.md)：不同阶段如何只看到自己真正需要的上下文。
- [Persona Effect](./docs/zh/dev/star/guides/persona-effects.md) 与 [Prompt Extension](./docs/zh/dev/star/guides/prompt-extensions.md)：扩展 Persona 表现与结构化上下文的插件协议。

## 开发状态

AG99 正在持续开发。Personal Runtime、Persona Expression、结构化 Prompt 和 Core 执行边界
已经接入实际链路；不同 Provider 的结构化输出、外部执行器的流式投递，以及各平台的真实取消
和迟到结果场景仍在持续验证。

AG99 与上游 AstrBot 共用成熟的基础设施，但不是上游的稳定替代品。部署到真实平台前，请先在
自己的 Provider、平台适配器和插件组合上完成验证；运行时行为以本仓库源码与
[Yakumo 架构文档](./docs/Yakumo/) 为准。

## 许可证与来源

AG99 基于 AstrBot 独立演进，使用 `AGPL-3.0-or-later` 许可证，并继续遵守适用的 AstrBot
兼容说明。

- [LICENSE](./LICENSE)
- [EULA](./EULA.md)
- [AstrBot 上游仓库](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 官方文档](https://docs.astrbot.app/)
