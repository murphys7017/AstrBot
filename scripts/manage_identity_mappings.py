from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if PROJECT_ROOT.as_posix() not in sys.path:
    sys.path.insert(0, PROJECT_ROOT.as_posix())

import runtime_bootstrap  # noqa: E402

runtime_bootstrap.initialize_runtime_bootstrap()

from astrbot.core.memory import (
    get_memory_config,
    get_memory_service,
    shutdown_memory_service,
)  # noqa: E402
from astrbot.core.memory.identity import MemoryIdentityMappingService  # noqa: E402
from astrbot.core.memory.store import MemoryStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage memory identity mappings YAML and runtime reload.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List bindings from identity_mappings.yaml.")
    subparsers.add_parser("validate", help="Validate identity_mappings.yaml.")
    subparsers.add_parser(
        "reload",
        help="Reload identity_mappings.yaml into the runtime SQLite mapping table.",
    )

    bind_parser = subparsers.add_parser(
        "bind",
        help="Add or update a binding in identity_mappings.yaml.",
    )
    bind_parser.add_argument("--platform-id", required=True)
    bind_parser.add_argument("--sender-user-id", required=True)
    bind_parser.add_argument("--canonical-user-id", required=True)
    bind_parser.add_argument("--nickname-hint")

    unbind_parser = subparsers.add_parser(
        "unbind",
        help="Remove a binding from identity_mappings.yaml.",
    )
    unbind_parser.add_argument("--platform-id", required=True)
    unbind_parser.add_argument("--sender-user-id", required=True)

    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    config = get_memory_config()
    store = MemoryStore(config=config)
    mapping_service = MemoryIdentityMappingService(store, config=config)

    try:
        if args.command == "list":
            bindings = mapping_service.load_bindings_from_yaml()
            print(f"[identity-mappings] path: {mapping_service.mappings_path}")
            print(f"[identity-mappings] bindings: {len(bindings)}")
            for binding in bindings:
                print(
                    f"- {binding.platform_user_key} -> {binding.canonical_user_id}"
                    + (f" ({binding.nickname_hint})" if binding.nickname_hint else "")
                )
            return 0

        if args.command == "validate":
            bindings = mapping_service.validate_yaml()
            print(
                f"[identity-mappings] valid: {len(bindings)} binding(s) in {mapping_service.mappings_path}"
            )
            return 0

        if args.command == "bind":
            binding = mapping_service.upsert_binding_in_yaml(
                args.platform_id,
                args.sender_user_id,
                args.canonical_user_id,
                nickname_hint=args.nickname_hint,
            )
            print("[identity-mappings] binding written to YAML")
            print(f"platform_user_key: {binding.platform_user_key}")
            print(f"canonical_user_id: {binding.canonical_user_id}")
            print(
                "reload required: run `python scripts/manage_identity_mappings.py reload`"
            )
            return 0

        if args.command == "unbind":
            removed = mapping_service.remove_binding_from_yaml(
                f"{args.platform_id}:{args.sender_user_id}"
            )
            if not removed:
                print("[identity-mappings] binding not found", file=sys.stderr)
                return 1
            print("[identity-mappings] binding removed from YAML")
            print(
                "reload required: run `python scripts/manage_identity_mappings.py reload`"
            )
            return 0

        if args.command == "reload":
            service = get_memory_service()
            count = await service.reload_identity_mappings()
            print(f"[identity-mappings] reloaded: {count} binding(s)")
            return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[identity-mappings] failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await store.close()
        await shutdown_memory_service()

    return 1


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
