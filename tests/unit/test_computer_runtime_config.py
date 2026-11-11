from types import SimpleNamespace

from astrbot.core.tools.computer_tools import util


def _context(live_config: dict):
    event = SimpleNamespace(
        unified_msg_origin="test:private:user",
        role="member",
        get_sender_id=lambda: "member-1",
        get_extra=lambda *_args, **_kwargs: None,
    )
    context = SimpleNamespace(
        event=event,
        context=SimpleNamespace(get_config=lambda **_: live_config),
    )
    return SimpleNamespace(context=context)


def test_computer_permissions_use_admitted_turn_config(monkeypatch):
    wrapper = _context(
        {
            "provider_settings": {
                "computer_use_runtime": "none",
                "computer_use_require_admin": True,
            }
        }
    )
    admitted = {
        "provider_settings": {
            "computer_use_runtime": "local",
            "computer_use_require_admin": False,
            "computer_use_local_permissions": {
                "member": {
                    "allow_execution": True,
                    "allow_network": True,
                    "filesystem_scope": "host",
                }
            },
        }
    }
    monkeypatch.setattr(
        util,
        "resolve_event_runtime_configuration",
        lambda _event: (admitted, "profile-a"),
    )

    assert util.is_local_runtime(wrapper) is True
    policy = util.get_local_permission_policy(wrapper)
    assert policy.allow_execution is True
    assert policy.allow_network is True
    assert policy.filesystem_scope == "host"
    assert util.check_admin_permission(wrapper, "Python execution") is None
