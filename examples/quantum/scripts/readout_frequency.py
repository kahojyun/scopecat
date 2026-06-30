"""Run the demo readout frequency workflow as a Python script."""

from __future__ import annotations

from pathlib import Path

from quantum_lab_demo import (
    DEFAULT_READOUT_FREQUENCY_WORKSPACE,
    ReadoutFrequencyWorkflowResult,
    format_readout_frequency_summary,
    run_readout_frequency_workflow,
)


def run(
    *,
    qubit: str = "q0",
    workspace: str | Path = DEFAULT_READOUT_FREQUENCY_WORKSPACE,
) -> ReadoutFrequencyWorkflowResult:
    return run_readout_frequency_workflow(
        qubit=qubit,
        workspace=workspace,
    )


def main() -> int:
    result = run()
    print(format_readout_frequency_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
