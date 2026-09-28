import asyncio

import pytest

from astrbot.core.agent_lifecycle import AgentRequestLifecycle
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.plugin_runtime import (
    PLUGIN_RUNTIME_TARGET_CORE,
    PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION,
)
from astrbot.core.provider.entities import ProviderRequest


@pytest.mark.asyncio
async def test_persona_and_core_lifecycle_state_isolated_while_hooks_overlap():
    event = AstrMessageEvent.__new__(AstrMessageEvent)
    event._extras = {}
    event._result = None
    event._force_stopped = False

    persona_request = ProviderRequest(prompt="persona")
    core_request = ProviderRequest(prompt="core")
    persona_entered = asyncio.Event()
    core_entered = asyncio.Event()
    persona_hook_finished = asyncio.Event()

    async def dispatch_hook(event, hook_type, request=None, **kwargs):
        del hook_type
        surface = kwargs["execution_surface"]
        if surface == PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION:
            persona_entered.set()
            await core_entered.wait()
            assert event.get_extra("provider_request") is persona_request
            assert event.get_extra("provider_request") is persona_request
            event.stop_event()
            assert event.is_stopped() is True
            persona_hook_finished.set()
            return True

        assert surface == PLUGIN_RUNTIME_TARGET_CORE
        assert request is core_request
        core_entered.set()
        await persona_entered.wait()
        await persona_hook_finished.wait()
        assert event.get_extra("provider_request") is core_request
        return event.is_stopped()

    persona = AgentRequestLifecycle(
        event,
        execution_surface=PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION,
        provider_request=persona_request,
        hook_dispatcher=dispatch_hook,
    )
    core = AgentRequestLifecycle(
        event,
        execution_surface=PLUGIN_RUNTIME_TARGET_CORE,
        provider_request=core_request,
        hook_dispatcher=dispatch_hook,
    )

    persona_stopped, core_stopped = await asyncio.gather(
        persona.dispatch_request(),
        core.dispatch_request(),
    )

    assert persona_stopped is True
    assert core_stopped is False
    assert event.get_extra("provider_request") is None
    assert event.is_stopped() is False


@pytest.mark.asyncio
async def test_lifecycle_restores_protected_prompt_fields_after_request_hook():
    event = AstrMessageEvent.__new__(AstrMessageEvent)
    event._extras = {}
    event._result = None
    event._force_stopped = False
    request = ProviderRequest(
        prompt="rendered request",
        contexts=[{"role": "user", "content": "rendered context"}],
        system_prompt="rendered system",
        extra_user_content_parts=[],
        image_urls=[],
        audio_urls=[],
    )

    async def dispatch_hook(_event, _hook_type, hooked_request, **_kwargs):
        hooked_request.prompt = "plugin prompt"
        hooked_request.contexts.append({"role": "system", "content": "plugin"})
        hooked_request.system_prompt = "plugin system"
        hooked_request.extra_user_content_parts.append({"type": "text", "text": "plugin"})
        hooked_request.image_urls.append("file:///plugin.png")
        hooked_request.audio_urls.append("file:///plugin.wav")
        return False

    lifecycle = AgentRequestLifecycle(
        event,
        execution_surface=PLUGIN_RUNTIME_TARGET_PERSONAL_EXPRESSION,
        provider_request=request,
        hook_dispatcher=dispatch_hook,
        protected_request_fields=frozenset(
            {
                "prompt",
                "contexts",
                "system_prompt",
                "extra_user_content_parts",
                "image_urls",
                "audio_urls",
            }
        ),
    )

    assert await lifecycle.dispatch_request() is False
    assert request.prompt == "rendered request"
    assert request.contexts == [{"role": "user", "content": "rendered context"}]
    assert request.system_prompt == "rendered system"
    assert request.extra_user_content_parts == []
    assert request.image_urls == []
    assert request.audio_urls == []
