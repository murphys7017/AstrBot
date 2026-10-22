from types import SimpleNamespace

import pytest

from astrbot.core.astr_main_agent import MainAgentBuildConfig
from astrbot.core.executors.session_registry import ExternalExecutorSessionRegistry
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.proactive_agent_turn import (
    ProactiveConfigurationSelection,
    run_proactive_agent_turn,
)
from astrbot.core.prompt.context_types import ContextPack
from astrbot.core.provider.manager import ProviderManager


@pytest.mark.asyncio
async def test_proactive_codex_receives_task_and_isolates_delivery_sessions(
    monkeypatch, tmp_path
):
    sessions, deliveries = [], []

    class _Session:
        unusable = False

        def __init__(self):
            self.prompts = []

        async def iter_turn(self, prompt):
            self.prompts.append(prompt)
            yield SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(
                    turn=SimpleNamespace(
                        status="completed",
                        items=[
                            SimpleNamespace(
                                type="agentMessage", phase="final_answer", text="done"
                            )
                        ],
                    )
                ),
            )

        async def aclose(self):
            self.unusable = True

    class _Runtime:
        async def create_session(self, **_kwargs):
            session = _Session()
            sessions.append(session)
            return session

    class _Controller:
        async def deliver_core_execution_result(self, message, event):
            await event.send(message)

    async def send_message(session, message):
        deliveries.append((str(session), message.get_plain_text()))
        return True

    async def prepare_context(*_args, **_kwargs):
        return ContextPack()

    async def get_conversation(*_args, **_kwargs):
        return SimpleNamespace(cid="conversation", history="[]")

    async def admit_plugins(**_kwargs):
        return None

    monkeypatch.setattr(
        "astrbot.core.astr_main_agent._get_session_conv", get_conversation
    )
    monkeypatch.setattr(
        "astrbot.core.astr_main_agent.PromptContextBuilder.build", prepare_context
    )
    monkeypatch.setattr(
        "astrbot.core.proactive_agent_turn.build_plugin_admission_snapshot",
        admit_plugins,
    )
    provider_manager = ProviderManager.__new__(ProviderManager)
    provider_manager.providers_config = [
        {
            "id": "codex-main",
            "type": "codex_cli",
            "provider_type": "agent_runner",
            "enable": True,
            "workspace_root": str(tmp_path),
        }
    ]
    registry = ExternalExecutorSessionRegistry(runtime=_Runtime())
    context = SimpleNamespace(
        provider_manager=provider_manager,
        external_executor_sessions=registry,
        interaction_output_controller=_Controller(),
        send_message=send_message,
    )
    origins = [
        MessageSession("qq", MessageType.FRIEND_MESSAGE, "42"),
        MessageSession("telegram", MessageType.FRIEND_MESSAGE, "42"),
        MessageSession("qq", MessageType.GROUP_MESSAGE, "42"),
    ]
    for index, origin in enumerate(origins):
        result = await run_proactive_agent_turn(
            context=context,
            session=origin,
            message=f"scheduled input {index}",
            extras={"cron_job": {"id": "job"}}
            if index == 0
            else {"background_task_result": {"result": "report"}},
            role="admin",
            config=MainAgentBuildConfig(tool_call_timeout=10),
            system_prompt=f"caller instruction {index}",
            prompt=f"requested work {index}",
            require_delivery_tool=True,
            include_history_fences=False,
            configuration_selection=ProactiveConfigurationSelection(
                config_id="bot-a",
                runtime_config={
                    "core_execution": {
                        "executor_id": "codex_cli",
                        "codex_cli": {"provider_id": "codex-main"},
                    }
                },
                adapter_binding_id=origin.platform_id,
                provider_references={},
            ),
        )
        assert result.response.completion_text == "done"
        assert result.delivery_confirmed is True

    assert len(registry) == 3
    assert deliveries == [(str(origin), "done") for origin in origins]
    for index, sdk_session in enumerate(sessions):
        request = sdk_session.prompts[0]
        assert f"scheduled input {index}" in request
        assert f"caller instruction {index}" in request
        assert f"requested work {index}" in request
    await registry.aclose()
