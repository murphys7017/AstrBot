from types import SimpleNamespace

import pytest

from astrbot.core.agent.runners.dashscope import dashscope_agent_runner as module


@pytest.mark.asyncio
async def test_dashscope_request_passes_configured_timeout(monkeypatch):
    captured = {}

    def fake_application_call(**kwargs):
        captured.update(kwargs)
        return object()

    async def fake_build_payload(*_args):
        return {"app_id": "app-1", "prompt": "hello"}

    async def fake_handle_response(_response, _session_id):
        if False:
            yield None

    runner = object.__new__(module.DashscopeAgentRunner)
    runner.req = SimpleNamespace(
        prompt="hello",
        session_id="session-1",
        image_urls=[],
        contexts=[],
        system_prompt="system",
    )
    runner.streaming = False
    runner.timeout = 37
    runner._build_request_payload = fake_build_payload
    runner._handle_streaming_response = fake_handle_response

    monkeypatch.setattr(module.Application, "call", fake_application_call)

    responses = [response async for response in runner._execute_dashscope_request()]

    assert responses == []
    assert captured["request_timeout"] == 37
    assert captured["incremental_output"] is False
