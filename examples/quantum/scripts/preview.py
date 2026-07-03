"""Preview a plan as a Python script."""

from __future__ import annotations

from pathlib import Path

from quantum_lab_demo import (
    DEFAULT_PREVIEW_WORKSPACE,
    format_preview_summary,
    preview_drive_scan,
)


def run(
    *,
    workspace: str | Path = DEFAULT_PREVIEW_WORKSPACE,
):
    return preview_drive_scan(workspace=workspace)


def main() -> int:
    result = run()
    print(format_preview_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
