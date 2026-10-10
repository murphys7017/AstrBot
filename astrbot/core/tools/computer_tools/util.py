from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.config.default import get_local_permission_defaults
from astrbot.core.db import BaseDatabase
from astrbot.core.utils.astrbot_path import get_astrbot_workspaces_path
from astrbot.core.workspace import (
    normalize_umo_for_workspace,
    resolve_workspace_root_for_umo,
)


@dataclass(frozen=True)
class LocalPermissionPolicy:
    """Resolved Local Computer permissions for one caller."""

    allow_execution: bool
    allow_network: bool
    filesystem_scope: Literal["none", "workspace", "host"]

    @property
    def requires_sandbox(self) -> bool:
        """Whether execution requires an OS-isolated process."""
        return not self.allow_network or self.filesystem_scope != "host"


def workspace_root(umo: str) -> Path:
    """Root directory for relative paths in local runtime"""
    normalized_umo = normalize_umo_for_workspace(umo)
    return (Path(get_astrbot_workspaces_path()) / normalized_umo).resolve(strict=False)


async def workspace_root_for_context(
    context: ContextWrapper[AstrAgentContext],
) -> Path:
    umo = context.context.event.unified_msg_origin
    db = getattr(context.context.context, "_db", None)
    if not isinstance(db, BaseDatabase):
        return workspace_root(umo)
    try:
        return await resolve_workspace_root_for_umo(umo, db)
    except Exception:
        return workspace_root(umo)


def is_local_runtime(context: ContextWrapper[AstrAgentContext]) -> bool:
    cfg = context.context.context.get_config(
        umo=context.context.event.unified_msg_origin
    )
    provider_settings = cfg.get("provider_settings", {})
    runtime = str(provider_settings.get("computer_use_runtime", "none"))
    return runtime == "local"


def get_local_permission_policy(
    context: ContextWrapper[AstrAgentContext],
    *,
    role: Literal["admin", "member"] | None = None,
) -> LocalPermissionPolicy:
    """Resolve the Local permission policy for the caller's role."""
    cfg = context.context.context.get_config(
        umo=context.context.event.unified_msg_origin
    )
    provider_settings = cfg.get("provider_settings", {})
    if not isinstance(provider_settings, dict):
        provider_settings = {}

    role = role or ("admin" if context.context.event.role == "admin" else "member")
    defaults = get_local_permission_defaults()[role]
    permissions = provider_settings.get("computer_use_local_permissions")
    role_policy = permissions.get(role) if isinstance(permissions, dict) else None
    if not isinstance(role_policy, dict):
        role_policy = {}
        # Legacy configurations allowed members when the shared admin gate was
        # disabled. Preserve that intent only where the new default permits it.
        if role == "member" and not isinstance(permissions, dict):
            defaults["allow_execution"] = (
                defaults["filesystem_scope"] != "none"
                and provider_settings.get("computer_use_require_admin", True)
                is False
            )

    filesystem_scope = role_policy.get(
        "filesystem_scope", defaults["filesystem_scope"]
    )
    if filesystem_scope not in {"none", "workspace", "host"}:
        filesystem_scope = defaults["filesystem_scope"]
    allow_execution = (
        filesystem_scope != "none"
        and role_policy.get("allow_execution", defaults["allow_execution"]) is True
    )
    allow_network = (
        allow_execution
        and role_policy.get("allow_network", defaults["allow_network"]) is True
    )
    return LocalPermissionPolicy(
        allow_execution=allow_execution,
        allow_network=allow_network,
        filesystem_scope=filesystem_scope,
    )


def check_local_file_permission(
    context: ContextWrapper[AstrAgentContext],
) -> str | None:
    """Reject Local file tools when the caller's filesystem scope is disabled."""
    if (
        is_local_runtime(context)
        and get_local_permission_policy(context).filesystem_scope == "none"
    ):
        return (
            "error: Permission denied. Local computer tools are disabled for this "
            "user role. Enable Local computer access for this role in AstrBot "
            "WebUI -> Config -> Capabilities -> Agent Computer Use -> Local "
            "Permission Policies."
        )
    return None


def check_admin_permission(
    context: ContextWrapper[AstrAgentContext], operation_name: str
) -> str | None:
    cfg = context.context.context.get_config(
        umo=context.context.event.unified_msg_origin
    )
    provider_settings = cfg.get("provider_settings", {})
    require_admin = provider_settings.get("computer_use_require_admin", True)
    if require_admin and context.context.event.role != "admin":
        return (
            f"error: Permission denied. {operation_name} is only allowed for admin users. "
            "Computer Use access is configured in `AstrBot WebUI -> Config -> Capabilities -> Agent Computer Use`; add admin IDs in `Config -> Channels -> Platform Config -> General -> Administrator IDs`. "
            f"User's ID is: {context.context.event.get_sender_id()}. User's ID can be found by using /sid command."
        )
    return None


def check_local_execution_permission(
    context: ContextWrapper[AstrAgentContext],
    operation_name: str,
) -> tuple[LocalPermissionPolicy | None, str | None]:
    """Resolve permission for Local Python/Shell execution.

    The current checkout has no process sandbox implementation. Restricted
    policies therefore fail closed instead of accidentally executing on the
    host without their requested isolation.
    """
    if not is_local_runtime(context):
        return None, check_admin_permission(context, operation_name)

    policy = get_local_permission_policy(context)
    if not policy.allow_execution:
        return policy, (
            f"error: Permission denied. {operation_name} is disabled by the "
            "Local permission policy for this user role. Enable Local computer "
            "access and code execution for this role in AstrBot WebUI -> Config "
            "-> Capabilities -> Agent Computer Use -> Local Permission Policies."
        )
    if policy.requires_sandbox:
        return policy, (
            "error: Permission denied. Restricted Local execution is unavailable "
            "because this installation has no operating-system process sandbox. "
            "Use the Third-party sandbox runtime or grant the host/full-trust "
            "Local policy."
        )
    return policy, None
