"""Run the demo readout IQ quality workflow as a Python script."""

from __future__ import annotations

from pathlib import Path

from quantum_lab_demo import (
    DEFAULT_READOUT_IQ_WORKSPACE,
    ReadoutIQWorkflowResult,
    format_readout_iq_summary,
    run_readout_iq_workflow,
)


def run(
    *,
    qubit: str = "q0",
    workspace: str | Path = DEFAULT_READOUT_IQ_WORKSPACE,
) -> ReadoutIQWorkflowResult:
    return run_readout_iq_workflow(
        qubit=qubit,
        workspace=workspace,
    )


def main() -> int:
    result = run()
    print(format_readout_iq_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
