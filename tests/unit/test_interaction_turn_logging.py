from types import SimpleNamespace

from astrbot.core.interaction.personal_runtime import PersonalRuntimeManager


class _Trace:
    def __init__(self):
        self.records = []

    def record(self, name, **fields):
        self.records.append((name, fields))


def test_deadline_diagnostics_emits_one_summary_and_keeps_full_trace(monkeypatch):
    trace = _Trace()
    state = SimpleNamespace(
        route_decision=SimpleNamespace(route_mode=SimpleNamespace(value="persona")),
        completion_state=SimpleNamespace(status=SimpleNamespace(value="completed")),
        failures=[],
        personal_emitted_monotonic=10.0,
        output_delivery_receipts=[
            {"message_kind": "immediate_reply", "status": "delivered"}
        ],
    )
    event = SimpleNamespace(trace=trace, _interaction_turn_state=state)
    deadline = SimpleNamespace(
        started_at=0.0,
        snapshot=lambda: {
            "total_seconds": 120.0,
            "elapsed_seconds": 12.5,
            "remaining_seconds": 107.5,
            "expired": False,
            "stages": [
                {"name": "persona_expression", "elapsed_seconds": 10.0},
                {"name": "provider_request", "elapsed_seconds": 9.2},
                {"name": "provider_request", "elapsed_seconds": 0.3},
                {"name": "plugin_enrichment", "elapsed_seconds": 0.4},
            ],
        }
    )
    turn = SimpleNamespace(
        state=SimpleNamespace(deadline=deadline),
        event=event,
        turn_id="turn-1",
        session=SimpleNamespace(session_id="session-1"),
    )
    reservation = SimpleNamespace(turn=turn)
    debug_calls = []
    monkeypatch.setattr(
        "astrbot.core.interaction.personal_runtime.logger.debug",
        lambda *args: debug_calls.append(args),
    )

    PersonalRuntimeManager._record_deadline_diagnostics(reservation)

    assert len(trace.records) == 1
    assert trace.records[0][0] == "interaction_deadline"
    assert len(debug_calls) == 1
    message, *values = debug_calls[0]
    assert message.startswith("DIAG interaction.turn: phase=settled")
    assert "stages=%s" not in message
    assert values[2:6] == ["completed", "persona", "10000", 12_500.0]
    assert values[6:9] == [10_000.0, 9_500.0, 400.0]
    assert values[-4:] == ["107500", False, "delivered", "none"]
