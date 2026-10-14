import asyncio
import base64
import json
import os
import shutil
from pathlib import PurePosixPath

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import File, Image, Json, Plain, Record
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.utils.datetime_utils import generate_timestamp_id
from astrbot.core.utils.media_utils import (
    MEDIA_MIME_EXTENSIONS,
    detect_image_mime_type_async,
)

from .webchat_queue_mgr import webchat_queue_mgr

attachments_dir = os.path.join(get_astrbot_data_path(), "attachments")


def _extract_conversation_id(session_id: str) -> str:
    """Extract raw webchat conversation id from event/session id."""
    if session_id.startswith("webchat!"):
        parts = session_id.split("!", 2)
        if len(parts) == 3:
            return parts[2]
    return session_id


def _snapshot_platform_extras(platform_extras: dict | None) -> dict:
    if not isinstance(platform_extras, dict):
        return {}
    snapshot = dict(platform_extras)
    persona_stream = snapshot.get("persona_stream")
    if isinstance(persona_stream, dict):
        snapshot["persona_stream"] = dict(persona_stream)
    return snapshot


def _attach_delivery_metadata(payload: dict, component) -> None:
    metadata = getattr(component, "delivery_metadata", None)
    if not isinstance(metadata, dict) or not metadata:
        return
    metadata = dict(metadata)
    payload["delivery_metadata"] = metadata
    for key in ("stream_event", "persona_result_id", "delta_index"):
        if key in metadata:
            payload[key] = metadata[key]
    segment_index = metadata.get(
        "segment_index",
        metadata.get("persona_segment_index"),
    )
    if segment_index is not None:
        payload["segment_index"] = segment_index


class WebChatMessageEvent(AstrMessageEvent):
    def __init__(self, message_str, message_obj, platform_meta, session_id) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        os.makedirs(attachments_dir, exist_ok=True)

    @staticmethod
    async def _send(
        message_id: str,
        message: MessageChain | None,
        session_id: str,
        streaming: bool = False,
        emit_complete: bool = False,
        platform_extras: dict | None = None,
    ) -> str | None:
        platform_extras = _snapshot_platform_extras(platform_extras)
        request_id = str(message_id)
        conversation_id = _extract_conversation_id(session_id)
        web_chat_back_queue = webchat_queue_mgr.get_or_create_back_queue(
            request_id,
            conversation_id,
        )
        if not message:
            await web_chat_back_queue.put(
                {
                    "type": "end",
                    "data": "",
                    "streaming": False,
                    "message_id": message_id,
                    "platform_extras": platform_extras,
                },  # end means this request is finished
            )
            return

        data = ""
        for comp in message.chain:
            if isinstance(comp, Plain):
                data = comp.text
                payload = {
                    "type": "plain",
                    "data": data,
                    "streaming": streaming,
                    "chain_type": message.type,
                    "message_id": message_id,
                    "platform_extras": platform_extras,
                }
                _attach_delivery_metadata(payload, comp)
                await web_chat_back_queue.put(payload)
            elif isinstance(comp, Json):
                await web_chat_back_queue.put(
                    {
                        "type": "plain",
                        "data": json.dumps(comp.data, ensure_ascii=False),
                        "streaming": streaming,
                        "chain_type": message.type,
                        "message_id": message_id,
                        "platform_extras": platform_extras,
                    },
                )
            elif isinstance(comp, Image):
                # save image to local
                image_base64 = await comp.convert_to_base64()
                image_bytes = base64.b64decode(image_base64)
                mime_type = await detect_image_mime_type_async(image_bytes)
                ext = MEDIA_MIME_EXTENSIONS.get(mime_type or "", ".jpg")
                filename = f"{generate_timestamp_id()}{ext}"
                path = os.path.join(attachments_dir, filename)
                with open(path, "wb") as f:
                    f.write(image_bytes)
                data = f"[IMAGE]{filename}"
                await web_chat_back_queue.put(
                    {
                        "type": "image",
                        "data": data,
                        "streaming": streaming,
                        "message_id": message_id,
                        "platform_extras": platform_extras,
                    },
                )
            elif isinstance(comp, Record):
                # save record to local
                filename = f"{generate_timestamp_id()}.wav"
                path = os.path.join(attachments_dir, filename)
                record_base64 = await comp.convert_to_base64()
                with open(path, "wb") as f:
                    f.write(base64.b64decode(record_base64))
                data = f"[RECORD]{filename}"
                payload = {
                    "type": "record",
                    "data": data,
                    "streaming": streaming,
                    "chain_type": message.type,
                    "message_id": message_id,
                    "platform_extras": platform_extras,
                }
                _attach_delivery_metadata(payload, comp)
                await web_chat_back_queue.put(payload)
            elif isinstance(comp, File):
                # save file to local
                file_path = await comp.get_file()
                raw_original_name = comp.name or os.path.basename(file_path)
                original_name = (
                    PurePosixPath(str(raw_original_name).replace("\\", "/"))
                    .name.replace("\x00", "")
                    .strip()
                )
                if original_name in {"", ".", ".."}:
                    original_name = os.path.basename(file_path) or "file"
                ext = os.path.splitext(original_name)[1] or ""
                filename = f"{generate_timestamp_id()}{ext}"
                dest_path = os.path.join(attachments_dir, filename)
                shutil.copy2(file_path, dest_path)
                data = f"[FILE]{filename}|{original_name}"
                await web_chat_back_queue.put(
                    {
                        "type": "file",
                        "data": data,
                        "streaming": streaming,
                        "message_id": message_id,
                        "platform_extras": platform_extras,
                    },
                )
            else:
                logger.debug(f"webchat 忽略: {comp.type}")

        if emit_complete:
            await web_chat_back_queue.put(
                {
                    "type": "complete",
                    "data": data,
                    "streaming": streaming,
                    "chain_type": message.type,
                    "message_id": message_id,
                        "platform_extras": platform_extras,
                },
            )

        return data

    async def send(self, message: MessageChain | None) -> None:
        logger.debug(
            "WebChat send falling back to legacy path: session_id=%s message_id=%s",
            self.session_id,
            self.message_obj.message_id,
        )
        message_id = self.message_obj.message_id
        await WebChatMessageEvent._send(message_id, message, session_id=self.session_id)
        await super().send(MessageChain([]))

    async def send_message_with_extras(
        self,
        message: MessageChain,
        *,
        platform_extras: dict | None = None,
        record_send_operation: bool = True,
    ) -> None:
        await WebChatMessageEvent._send(
            self.message_obj.message_id,
            message,
            session_id=self.session_id,
            platform_extras=platform_extras,
        )
        if record_send_operation:
            await super().send(MessageChain([]))

    async def complete_visible_turn(self) -> None:
        if self.get_extra("_visible_turn_completion_sent", False):
            return
        await WebChatMessageEvent._send(
            self.message_obj.message_id,
            None,
            session_id=self.session_id,
        )
        self.set_extra("_visible_turn_completion_sent", True)
        self.set_extra("_platform_completion_signal_sent", True)

    def requires_visible_turn_completion(self) -> bool:
        return True

    async def send_interaction_streaming(
        self,
        generator,
        *,
        platform_extras: dict | None = None,
        use_fallback: bool = False,
    ) -> None:
        await WebChatMessageEvent._send_streaming_via_back_queue(
            message_id=self.message_obj.message_id,
            session_id=self.session_id,
            generator=generator,
            platform_extras=platform_extras,
        )

    @staticmethod
    async def _send_streaming_via_back_queue(
        message_id: str,
        session_id: str,
        generator,
        platform_extras: dict | None = None,
    ) -> None:
        stream_state = {"final_data": "", "reasoning_content": ""}
        stream_metadata = (
            platform_extras.get("persona_stream")
            if isinstance(platform_extras, dict)
            else None
        )
        request_id = str(message_id)
        conversation_id = _extract_conversation_id(session_id)
        web_chat_back_queue = webchat_queue_mgr.get_or_create_back_queue(
            request_id,
            conversation_id,
        )

        async def enqueue_complete(
            status: str | None = None,
            *,
            best_effort: bool = False,
        ) -> None:
            if isinstance(stream_metadata, dict) and status is not None:
                stream_metadata["status"] = status
                if status == "incomplete":
                    stream_metadata.setdefault(
                        "failure_reason",
                        "webchat_delivery_failed",
                    )
            extras_snapshot = _snapshot_platform_extras(platform_extras)
            complete_payload = {
                "type": "complete",  # complete means we return the final result
                "data": stream_state["final_data"],
                "reasoning": stream_state["reasoning_content"],
                "streaming": True,
                "message_id": message_id,
                "platform_extras": extras_snapshot,
            }
            persona_stream = extras_snapshot.get("persona_stream")
            if isinstance(persona_stream, dict):
                complete_payload["persona_stream"] = dict(persona_stream)
            if best_effort:
                try:
                    web_chat_back_queue.put_nowait(complete_payload)
                except asyncio.QueueFull:
                    logger.debug(
                        "Dropping WebChat stream terminal event because the back queue is full: "
                        "message_id=%s status=%s",
                        message_id,
                        status,
                    )
            else:
                await web_chat_back_queue.put(complete_payload)

        async def send_chunks() -> None:
            async for chain in generator:
                # 处理音频流（Live Mode）
                if chain.type == "audio_chunk":
                    # 音频流数据，直接发送
                    audio_b64 = ""
                    text = None

                    if chain.chain and isinstance(chain.chain[0], Plain):
                        audio_b64 = chain.chain[0].text

                    if len(chain.chain) > 1 and isinstance(chain.chain[1], Json):
                        text = chain.chain[1].data.get("text")

                    payload = {
                        "type": "audio_chunk",
                        "data": audio_b64,
                        "streaming": True,
                        "message_id": message_id,
                        "platform_extras": _snapshot_platform_extras(
                            platform_extras
                        ),
                    }
                    if text:
                        payload["text"] = text

                    await web_chat_back_queue.put(payload)
                    continue

                result = await WebChatMessageEvent._send(
                    message_id=message_id,
                    message=chain,
                    session_id=session_id,
                    streaming=True,
                    platform_extras=platform_extras,
                )
                if not result or chain.type == "persona_stream_tts":
                    continue
                if chain.type == "reasoning":
                    stream_state["reasoning_content"] += chain.get_plain_text()
                else:
                    stream_state["final_data"] += result

        try:
            await send_chunks()
        except asyncio.CancelledError:
            if isinstance(stream_metadata, dict):
                await asyncio.shield(
                    enqueue_complete("cancelled", best_effort=True)
                )
            raise
        except Exception:
            if isinstance(stream_metadata, dict):
                await enqueue_complete("incomplete")
            raise
        else:
            await enqueue_complete()

    async def send_streaming(self, generator, use_fallback: bool = False) -> None:
        logger.debug(
            "WebChat streaming falling back to legacy path: session_id=%s message_id=%s use_fallback=%s",
            self.session_id,
            self.message_obj.message_id,
            use_fallback,
        )
        await WebChatMessageEvent._send_streaming_via_back_queue(
            message_id=self.message_obj.message_id,
            session_id=self.session_id,
            generator=generator,
        )
        await super().send_streaming(generator, use_fallback)
