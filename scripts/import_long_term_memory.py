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

from sqlalchemy.exc import OperationalError  # noqa: E402

from astrbot.core.memory import (  # noqa: E402
    get_memory_service,
    shutdown_memory_service,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import or update a long-term memory document.",
    )
    parser.add_argument(
        "doc_path",
        type=Path,
        help="Path to the long-term memory Markdown document.",
    )
    return parser.parse_args()


async def run(doc_path: Path) -> int:
    service = get_memory_service()
    try:
        persisted = await service.import_long_term_memory_document(doc_path.resolve())
    except OperationalError as exc:
        print(
            "[memory-import] failed: database schema is outdated for current memory tables.",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[memory-import] failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await shutdown_memory_service()

    print("[memory-import] success")
    print(f"memory_id: {persisted.memory_id}")
    print(f"doc_path: {persisted.doc_path}")
    print(f"title: {persisted.title}")
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(run(args.doc_path))


if __name__ == "__main__":
    raise SystemExit(main())
