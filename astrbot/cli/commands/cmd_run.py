import asyncio
import os
import sys
import traceback
from pathlib import Path

import click
from filelock import FileLock, Timeout

from ..utils import check_astrbot_root, check_dashboard, get_astrbot_root

DASHBOARD_RESET_PASSWORD_ENV = "ASTRBOT_RESET_DASHBOARD_PASSWORD"


def _sanitize_cli_error(text: str) -> str:
    return "".join(
        f"\\x{ord(char):02x}"
        if ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F
        else char
        for char in text
    )


def _sanitize_cli_traceback(formatted, seen=None) -> None:
    if seen is None:
        seen = set()
    if id(formatted) in seen:
        return
    seen.add(id(formatted))

    formatted._str = _sanitize_cli_error(formatted._str)
    for frame in formatted.stack:
        frame.filename = _sanitize_cli_error(frame.filename)
        frame.name = _sanitize_cli_error(frame.name)
        if frame.line is not None:
            frame._line = _sanitize_cli_error(frame.line)
    notes = getattr(formatted, "__notes__", None)
    if isinstance(notes, (list, tuple)):
        formatted.__notes__ = [_sanitize_cli_error(note) for note in notes]
    for attr in ("filename", "text", "msg"):
        value = getattr(formatted, attr, None)
        if isinstance(value, str):
            setattr(formatted, attr, _sanitize_cli_error(value))
    nested_exceptions = (
        getattr(formatted, "__cause__", None),
        getattr(formatted, "__context__", None),
        *(getattr(formatted, "exceptions", None) or ()),
    )
    for nested in nested_exceptions:
        if nested is not None:
            _sanitize_cli_traceback(nested, seen)


async def run_astrbot(astrbot_root: Path) -> None:
    """Run AstrBot"""
    from astrbot.core import LogBroker, LogManager, db_helper, logger
    from astrbot.core.initial_loader import InitialLoader

    await check_dashboard(astrbot_root / "data")

    log_broker = LogBroker()
    LogManager.set_queue_handler(logger, log_broker)
    db = db_helper

    core_lifecycle = InitialLoader(db, log_broker)

    await core_lifecycle.start()


@click.option("--reload", "-r", is_flag=True, help="Auto-reload plugins")
@click.option("--port", "-p", help="AstrBot Dashboard port", required=False, type=str)
@click.option(
    "--reset-password",
    is_flag=True,
    help="Reset dashboard initial password on startup",
)
@click.command()
def run(reload: bool, port: str | None, reset_password: bool) -> None:
    """Run AstrBot"""
    try:
        os.environ["ASTRBOT_CLI"] = "1"
        astrbot_root = get_astrbot_root()

        if not check_astrbot_root(astrbot_root):
            raise click.ClickException(
                f"{astrbot_root} is not a valid AstrBot root directory. Use 'astrbot init' to initialize",
            )

        os.environ["ASTRBOT_ROOT"] = str(astrbot_root)
        sys.path.insert(0, str(astrbot_root))

        if port:
            os.environ["DASHBOARD_PORT"] = port

        if reload:
            click.echo("Plugin auto-reload enabled")
            os.environ["ASTRBOT_RELOAD"] = "1"

        if reset_password:
            os.environ[DASHBOARD_RESET_PASSWORD_ENV] = "1"

        lock_file = astrbot_root / "astrbot.lock"
        lock = FileLock(lock_file, timeout=5)
        with lock.acquire():
            asyncio.run(run_astrbot(astrbot_root))
    except KeyboardInterrupt:
        click.echo("AstrBot has been shut down.")
    except Timeout:
        raise click.ClickException(
            "Cannot acquire lock file. Please check if another instance is running"
        )
    except Exception as e:
        formatted = traceback.TracebackException.from_exception(e)
        _sanitize_cli_traceback(formatted)
        message = f"Runtime error:\n{''.join(formatted.format())}"
        raise click.ClickException(message) from None
