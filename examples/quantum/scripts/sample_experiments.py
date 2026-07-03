"""Run the demo sample-backed experiments as a Python script."""

from __future__ import annotations

from pathlib import Path

from quantum_lab_demo import (
    DEFAULT_SAMPLE_TEMPLATES_WORKSPACE,
    SampleExperimentsResult,
    format_sample_experiments_summary,
    run_sample_experiments,
)


def run(
    *,
    qubit: str = "q0",
    coupled_qubit: str = "q1",
    workspace: str | Path = DEFAULT_SAMPLE_TEMPLATES_WORKSPACE,
) -> SampleExperimentsResult:
    return run_sample_experiments(
        qubit=qubit,
        coupled_qubit=coupled_qubit,
        workspace=workspace,
    )


def main() -> int:
    result = run()
    print(format_sample_experiments_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
