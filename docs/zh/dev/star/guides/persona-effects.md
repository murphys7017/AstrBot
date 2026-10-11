---
outline: deep
---

# Persona Effect

Persona Effect 是 AG99（作者 YakumoAki）的拟人输出扩展协议。插件可以让 Persona Runtime 在生成分段用户可见文本 `segments[].speech` 的同时生成结构化表现意图，例如 Live2D 动作、灯光或客户端表情。

Persona Effect 不是可执行的业务 Agent Tool：它不会交给 Core Tool Loop 执行，也不会提供给 Core Planner。表达由严格 `persona_expression` 契约返回，字段为 `turn_action` 和 `segments`；当前事件有已注册且适用的 Persona Effect 时，首轮响应还要求调用独立的 `persona_effect_batch` terminal tool，参数只包含 `effect_calls`。正常生成时两路数据在 Core 内聚合，不会为 effect 单独发起请求。若双通道首轮漏掉一侧，Core 会用隔离请求只补缺失通道一次；已解析的必发 effect 未通过校验时，也可额外请求模型修复 effect batch。`actions` 是简单动作词意图，与插件拥有的 `effect_calls` 分开。没有适用 effect 时不向模型提供 effect 工具，聚合结果中的 `effect_calls` 为空数组。

## 注册 Effect

```python
from astrbot.api.star import Context, Star
from astrbot.core.interaction import PersonaEffectSpec


def supports_current_event(event) -> bool:
    return event.get_platform_name() == "my_platform"


class Main(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        context.register_persona_effect(
            PersonaEffectSpec(
                plugin_id="my_plugin",
                name="my_plugin.expression",
                description="Select a client expression for the visible reply.",
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {"type": "string"},
                    },
                    "required": ["label"],
                },
            ),
            event_filter=supports_current_event,
        )
```

`event_filter` 是同步、无副作用的判断函数。Core 在每次构建 Persona 输出契约时传入当前事件：

- 返回 `True`：effect schema 进入本轮独立的 `persona_effect_batch` tool-call 契约，不会加入 `persona_expression`。
- 返回 `False`：本轮不向模型暴露该 effect，不消耗对应 schema token。
- 抛出异常：Core 记录告警并按 `False` 处理。

平台专用插件不应只在启动时全局注册 schema，而应同时检查当前平台、adapter、设备能力和所需 runtime 是否真实可用。合成环境事件也可以在过滤器中排除。

## 查询与注销

```python
active = context.list_persona_effects(event=event)
all_enabled = context.list_persona_effects()
context.unregister_persona_effects(plugin_id="my_plugin")
```

带 `event` 的查询用于构建当前 Persona 契约。不带 `event` 的查询用于注册表管理和诊断，会返回所有已启用注册项，不代表它们对任意事件都可用。

## 输出与消费

表达通道 `persona_expression` 的参数结构为：

```json
{
  "turn_action": "reply",
  "segments": [
    {
      "speech": "用户可见回复",
      "actions": [],
      "thought": "角色当前的简短心理想法",
      "tendency": {
        "Joy": 0,
        "Trust": 0,
        "Fear": 0,
        "Surprise": 0,
        "Sadness": 0,
        "Disgust": 0,
        "Anger": 0,
        "Anticipation": 0
      }
    }
  ]
}
```

存在适用 effect 时，同一模型响应还需调用独立 `persona_effect_batch`，参数结构为：

```json
{
  "effect_calls": [
    {
      "name": "my_plugin.expression",
      "arguments": {"label": "happy"}
    }
  ]
}
```

有适用的可选 effect 时，即使本轮没有需要执行的调用，effect batch 仍通过该通道返回空数组；必发 effect 则必须满足注册的数量约束（允许静默时可为空）。Core 根据注册 schema 校验调用并补充插件所有权；插件从当前阶段的 `InteractionResultView.effect_calls` 消费属于自己的调用，再通过 `client_objects`、`platform_extras` 或自己的传输链路执行。没有适用 effect 时不发起 effect tool call，Core 聚合结果仍提供空数组。

插件必须自行负责设备约束、资源映射和降级策略。Core 不理解具体动作、Live2D 参数或客户端协议。
