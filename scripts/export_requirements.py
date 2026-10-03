"""Generate the pip-compatible requirements file from pyproject.toml."""

import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"
HEADER = (
    "# Generated from pyproject.toml; run "
    "scripts/export_requirements.py to refresh.\n"
)


def render_requirements() -> str:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    return HEADER + "\n".join(dependencies) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if requirements.txt is not up to date",
    )
    args = parser.parse_args()
    expected = render_requirements()

    if args.check:
        if REQUIREMENTS.read_text(encoding="utf-8") != expected:
            parser.error("requirements.txt is stale; run scripts/export_requirements.py")
        print("requirements.txt matches pyproject.toml")
        return 0

    REQUIREMENTS.write_text(expected, encoding="utf-8", newline="\n")
    print("Updated requirements.txt from pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
