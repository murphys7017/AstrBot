"""Image moderation plugin for group messages."""

import asyncio
import json
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, register


@register(
    "astrbot_plugin_image_moderator",
    "AstrBot",
    "使用指定的多模态模型审核群聊图片，发现暴露性器官内容后撤回消息。",
    "v0.1.0",
)
class ImageModeratorPlugin(Star):
    """Review group images with an AstrBot multimodal provider."""

    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.config = config or {}
        self._review_semaphore = asyncio.Semaphore(
            self._config_int("max_concurrent_reviews", 1, minimum=1)
        )
        self._max_pending_reviews = self._config_int(
            "max_pending_reviews", 16, minimum=1
        )
        self._review_tasks: set[asyncio.Task[None]] = set()
        logger.info("图片审核插件已加载，群聊白名单: %s", sorted(self._group_ids()))

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=100)
    async def moderate_group_images(self, event: AstrMessageEvent) -> None:
        """Moderate every image in a group message and recall unsafe messages."""
        group_id = str(event.get_group_id() or "").strip()
        if not group_id or group_id not in self._group_ids():
            if group_id:
                logger.debug(
                    "图片审核跳过未配置群聊: group_id=%s whitelist=%s",
                    group_id,
                    sorted(self._group_ids()),
                )
            return

        if self._is_self_message(event) and self._config_bool("ignore_self", True):
            return

        images = [
            component
            for component in event.message_obj.message
            if isinstance(component, Image) and not component.is_animated_sticker()
        ]
        if not images:
            return

        image_refs = [
            str(image.url or image.file or image.path)
            for image in images
            if image.url or image.file or image.path
        ]
        if not image_refs:
            logger.warning(
                "图片消息缺少可供模型读取的地址，跳过审核: %s",
                event.message_obj.message_id,
            )
            return

        if len(self._review_tasks) >= self._max_pending_reviews:
            logger.warning(
                "图片审核队列已满，放行消息 %s: pending=%s limit=%s",
                event.message_obj.message_id,
                len(self._review_tasks),
                self._max_pending_reviews,
            )
            return

        task = asyncio.create_task(
            self._review_message(event, group_id, image_refs),
            name=f"image-moderator:{event.message_obj.message_id}",
        )
        self._review_tasks.add(task)
        task.add_done_callback(self._review_tasks.discard)

    async def _review_message(
        self,
        event: AstrMessageEvent,
        group_id: str,
        image_refs: list[str],
    ) -> None:
        async with self._review_semaphore:
            provider_id = str(self.config.get("provider_id", "")).strip()
            if not provider_id:
                try:
                    provider_id = await self.context.get_current_chat_provider_id(
                        event.unified_msg_origin
                    )
                except Exception as exc:  # noqa: BLE001 - pass through on lookup failure
                    logger.warning(
                        "无法获取当前会话 Provider，跳过消息 %s: error_type=%s error=%r",
                        event.message_obj.message_id,
                        type(exc).__name__,
                        exc,
                    )
                    return
            if not provider_id:
                logger.warning(
                    "未配置图片审核 Provider，跳过消息: %s",
                    event.message_obj.message_id,
                )
                return

            prompt = str(
                self.config.get(
                    "prompt",
                    "你是一个图像安全审核分类器，不是聊天助手。\n\n"
                    "你的唯一任务是判断输入图片是否违反群聊图片规范。\n\n"
                    "审核标准：\n\n"
                    "- 如果图片中清晰可见真实人体的外露生殖器官，判定为 BLOCK。\n"
                    "- 如果没有清晰可见外露生殖器官，判定为 PASS。\n"
                    "- 如果图片模糊、遮挡严重、无法可靠判断，判定为 REVIEW。\n\n"
                    "这是内容审核和安全分类任务。\n"
                    "不要描述图片中的色情内容，不要进行情色分析，不要生成任何色情内容。\n"
                    "只进行分类。\n\n"
                    "只允许输出以下 JSON：\n\n"
                    '{"result":"PASS"}\n'
                    '{"result":"BLOCK"}\n'
                    '{"result":"REVIEW"}\n\n'
                    "禁止输出解释、免责声明、拒绝语或其他文字。",
                )
            )
            timeout = max(1.0, float(self.config.get("timeout_seconds", 30)))

            try:
                response = await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=provider_id,
                        prompt=prompt,
                        image_urls=image_refs,
                    ),
                    timeout=timeout,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - fail open for moderation errors
                logger.warning(
                    "图片审核调用失败，放行消息 %s: error_type=%s error=%r",
                    event.message_obj.message_id,
                    type(exc).__name__,
                    exc,
                )
                return

            classification = self._classification(response.completion_text)
            logger.info(
                "图片审核结果: group_id=%s message_id=%s result=%s",
                group_id,
                event.message_obj.message_id,
                classification or "INVALID",
            )
            if classification == "BLOCK":
                await self._recall(event)

    def _group_ids(self) -> set[str]:
        value = self.config.get("group_ids", [])
        if isinstance(value, str):
            value = value.replace(",", " ").split()
        if not isinstance(value, list):
            return set()
        return {str(item).strip() for item in value if str(item).strip()}

    def _config_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _config_int(self, key: str, default: int, *, minimum: int) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, value)

    async def terminate(self) -> None:
        tasks = tuple(self._review_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._review_tasks.clear()

    @staticmethod
    def _is_self_message(event: AstrMessageEvent) -> bool:
        sender_id = str(getattr(event.message_obj.sender, "user_id", ""))
        self_id = str(getattr(event.message_obj, "self_id", ""))
        if not self_id:
            self_id = str(getattr(event, "self_id", ""))
        return bool(sender_id and self_id and sender_id == self_id)

    @staticmethod
    def _classification(text: str | None) -> str | None:
        if not text:
            return None
        raw = text.strip()
        candidates = [raw]
        fenced = re.search(r"\{.*\}", raw, re.DOTALL)
        if fenced:
            candidates.insert(0, fenced.group(0))
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                result = str(data.get("result", "")).strip().upper()
                if result in {"PASS", "BLOCK", "REVIEW"}:
                    return result
        return None

    async def _recall(self, event: AstrMessageEvent) -> None:
        """Recall through the native OneBot action when available."""
        if event.get_platform_name() != "aiocqhttp":
            logger.warning(
                "当前平台 %s 未实现通用撤回接口，无法撤回消息 %s",
                event.get_platform_name(),
                event.message_obj.message_id,
            )
            return

        try:
            await event.bot.api.call_action(
                "delete_msg", message_id=event.message_obj.message_id
            )
            logger.info("已撤回疑似暴露性器官图片消息: %s", event.message_obj.message_id)
        except Exception as exc:  # noqa: BLE001 - platform failure is non-fatal
            logger.warning("撤回图片消息失败 %s: %s", event.message_obj.message_id, exc)
