# Interaction Turn State 与 Event Extra 边界

## 当前权威状态

一轮 Interaction 的状态由 `astrbot.core.interaction.turn_state.InteractionTurnState` 持有。核心代码应通过 `turn_state.py` 提供的读取和写入函数访问状态，不直接把 Event Extra 当作状态仓库。

当前终态只有三种：

- `completed`
- `failed`
- `cancelled`

终态由 `transition_interaction_turn_status()` 单点写入，并且具有单向性。重复写入同一终态是幂等的，已经结束的 Turn 不允许被另一个终态覆盖。

## Event Extra 的定位

Event Extra 只承担三类职责：

1. 平台和旧插件仍需要读取的兼容投影。
2. 跨 Pipeline 阶段传递的短期边界标记。
3. 无法放入 `InteractionTurnState` 的平台对象或外部句柄引用。

新的 Turn 状态字段不得只写入 Event Extra。需要兼容旧调用方时，先写入 `InteractionTurnState`，再由状态模块发布投影。

## 当前 Event Extra 分类

| 分类 | 示例 | 权威来源 |
|---|---|---|
| Turn 身份与配置 | `_turn_id`、`_astrbot_config_id` | `InteractionTurnState` |
| 路由与执行 | `_interaction_protocol_core_bypass`、`_interaction_core_execution_progress_text` | `InteractionTurnState` 或 Core Execution |
| 输出事务 | `_interaction_plugin_output_mode`、`_interaction_persona_segment_stream_status` | `InteractionTurnState` / Output Transaction |
| 主动行为 | `_personal_action_intent`、`_proactive_scene` | `PersonalRuntime` 的 ActionIntent |
| Pipeline 边界 | `_interaction_plugin_branch`、`_interaction_plugin_handler_name` | Pipeline 阶段上下文 |
| 外部句柄 | `provider_request`、`agent_stop_requested` | 当前执行边界或平台事件 |

## 本阶段完成内容

- `InteractionTurnState.completion_state` 成为 Turn 终态的唯一写入位置。
- `mark_interaction_turn_completed()`、`mark_interaction_turn_failed()` 和 `mark_interaction_turn_cancelled()` 统一经过状态转换函数。
- 终态转换具备幂等和单向保护，避免多个协调器互相覆盖结果。
- 保留现有 Event Extra 兼容投影，未改变插件公开读取方式。

## 后续清理顺序

1. 为 77 个已发现的 Interaction 相关 Extra 补充生产者、读取者和删除条件。
2. 将路由、输出事务和主动行为中仍由 Extra 独立保存的状态迁移到对应类型对象。
3. 保留平台对象、外部句柄和旧插件兼容字段作为投影。
4. 删除没有生产者或没有读取者的字段，并为每次删除补充运行验收。

