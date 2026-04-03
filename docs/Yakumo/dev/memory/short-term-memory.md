# Short-Term Memory Draft

本文件记录当前 AstrBot memory 系统中短期记忆层的第一版共识。

## 1. 第一版范围

当前短期层只做两个对象：

- `TopicState`
- `ShortTermMemory`

当前不做：

- 多层短期记忆树
- 短期向量检索
- 短期图谱
- 复杂短期状态集合

## 2. 数据来源

短期层的数据来源是：

- 当前回合输入输出
- AstrBot 现有历史对话系统中的最近若干轮对话

约束：

- 现有历史系统是原始材料源。
- 短期记忆不是整份历史对话副本。
- 短期层只保存抽象结果，不重复保存全部历史原文。

## 3. `TopicState`

### 3.1 定义

`TopicState` 表示当前会话正在围绕什么继续聊。

### 3.2 第一版字段

- `umo`
- `conversation_id`
- `current_topic`
- `topic_summary`
- `topic_confidence`
- `last_active_at`

### 3.3 用途

- 服务下一轮对话的主题连续性
- 告诉上层当前主要话题是什么
- 作为后续中期抽象的输入之一

### 3.4 第一版说明

- `current_topic` 是当前主话题名称
- `topic_summary` 是简短说明
- `topic_confidence` 是当前判断可信度
- `last_active_at` 用于判断该话题是否已经过期

## 4. `ShortTermMemory`

### 4.1 定义

`ShortTermMemory` 表示最近几轮对话中，下一轮仍值得保留的短期上下文抽象。

### 4.2 第一版字段

- `umo`
- `conversation_id`
- `short_summary`
- `active_focus`
- `updated_at`

### 4.3 用途

- 服务最近几轮连续对话
- 记录当前还在推进的问题或焦点
- 作为后续 `SessionInsight` 和 `Experience` 的原料

### 4.4 第一版说明

- `short_summary` 是对最近若干轮内容的压缩表达
- `active_focus` 是当前仍需继续推进的焦点
- `updated_at` 用于判断短期内容的新鲜度

## 5. 两个对象的边界

`TopicState` 关注：

- 当前在聊什么

`ShortTermMemory` 关注：

- 当前还有什么上下文需要下一轮继续带着

可以理解为：

- `TopicState` 更像主题标签与主题摘要
- `ShortTermMemory` 更像最近连续对话的短期抽象

## 6. 第一版更新时机

短期层更新时机：

- 在当前回合完成后触发
- 通过 `Post Process System` 驱动
- 作为 memory update 的最轻量第一步

当前链路：

- `after_message_sent`
- 读取最近若干轮历史材料
- 更新 `TopicState`
- 更新 `ShortTermMemory`

## 7. 与中长期层的关系

短期层不是最终记忆目标。

它的作用是：

- 给下一轮提供连续性
- 给后续 consolidation 提供原料

后续演化方向：

- `TopicState` 与 `ShortTermMemory`
- 累计后生成 `SessionInsight`
- 再进一步生成 `Experience`
- 再进一步补充 `LongTermMemory` 与 `PersonaState`

## 8. 当前结论

短期层第一版先只保留两个对象：

- `TopicState`
- `ShortTermMemory`

它们都以 `SQLite` 为主存储，并建立在现有 AstrBot 历史对话系统之上，但不等于历史对话本身。
