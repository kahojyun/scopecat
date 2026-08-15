"""Generate the committed Python-to-TypeScript measurement Arrow fixture."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from scopecat_testkit.measurement_arrow_fixture import ui_measurement_arrow_fixture

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    REPOSITORY_ROOT
    / "apps"
    / "scopecat-ui"
    / "src"
    / "features"
    / "runs"
    / "test-fixtures"
    / "measurement-append-v9.arrow"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = ui_measurement_arrow_fixture()
    if cast("bool", args.check):
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != content:
            raise SystemExit(
                "UI measurement Arrow fixture is stale; run "
                "uv run python scripts/generate_ui_measurement_arrow_fixture.py"
            )
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(content)


if __name__ == "__main__":
    main()
