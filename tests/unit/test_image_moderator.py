import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot.core.message.components import Image

_PLUGIN_PATH = (
    Path(__file__).parents[2]
    / "data"
    / "plugins"
    / "astrbot_plugin_image_moderator"
    / "main.py"
)
_SPEC = importlib.util.spec_from_file_location("test_image_moderator_plugin", _PLUGIN_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
ImageModeratorPlugin = _MODULE.ImageModeratorPlugin


class _FakeContext:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def llm_generate(self, **_kwargs):
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(completion_text='{"result":"PASS"}')


def _event(image: Image):
    return SimpleNamespace(
        get_group_id=lambda: "group",
        get_platform_name=lambda: "aiocqhttp",
        unified_msg_origin="aiocqhttp:GroupMessage:group",
        self_id="bot",
        message_obj=SimpleNamespace(
            message=[image],
            message_id="message",
            sender=SimpleNamespace(user_id="user"),
            self_id="bot",
        ),
    )


@pytest.mark.asyncio
async def test_animated_sticker_is_skipped_before_review_task_creation():
    context = _FakeContext()
    plugin = ImageModeratorPlugin(
        context,
        {"group_ids": ["group"], "provider_id": "vision"},
    )

    await plugin.moderate_group_images(
        _event(
            Image(
                file="https://example.com/sticker.jpg",
                delivery_metadata={
                    "onebot_sub_type": 1,
                    "onebot_summary": "[动画表情]",
                },
            )
        )
    )

    assert plugin._review_tasks == set()


@pytest.mark.asyncio
async def test_review_runs_in_background_and_is_cancelled_on_terminate():
    context = _FakeContext()
    plugin = ImageModeratorPlugin(
        context,
        {"group_ids": ["group"], "provider_id": "vision"},
    )

    await plugin.moderate_group_images(
        _event(Image(file="https://example.com/photo.jpg"))
    )
    await asyncio.wait_for(context.started.wait(), timeout=1)
    assert plugin._review_tasks

    await plugin.terminate()

    assert plugin._review_tasks == set()
    assert context.release.is_set() is False
