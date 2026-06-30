"""Run a dry-run plan as a Python script."""

from __future__ import annotations

from pathlib import Path

from quantum_lab_demo import (
    DEFAULT_DRY_RUN_WORKSPACE,
    format_dry_run_summary,
    run_dry_run_plan,
)


def run(
    *,
    workspace: str | Path = DEFAULT_DRY_RUN_WORKSPACE,
):
    return run_dry_run_plan(workspace=workspace)


def main() -> int:
    result = run()
    print(format_dry_run_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
