"""Notebook-style example: open a workspace, run an experiment, read data."""

# ruff: noqa: E402

from __future__ import annotations

# %%
import sys
from dataclasses import dataclass
from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_ROOT))

# %%
import scopecat as sc
from quantum_lab_demo.fixtures import (
    DEFAULT_WORKSPACE_ROOT,
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
)
from quantum_lab_demo.readout import frequency_calibration
from quantum_lab_demo.virtual_lab.provider import ReadoutFrequencyVirtualProvider

DEFAULT_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "notebooks" / "03-run-and-read-data"


@dataclass(frozen=True)
class RunAndReadDataResult:
    run: sc.Run
    measurement_count: int
    artifact_ids: tuple[str, ...]


# %%
def open_lab(workspace: str | Path = DEFAULT_WORKSPACE) -> sc.Workspace:
    return sc.open(
        workspace,
        config_profile=READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=ReadoutFrequencyVirtualProvider(
            profile=READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
        ),
    )


# %%
def run(workspace: str | Path = DEFAULT_WORKSPACE) -> RunAndReadDataResult:
    lab = open_lab(workspace)
    experiment = lab.experiment(
        "readout frequency",
        source=frequency_calibration(qubit="q0"),
    )

    completed_run = lab.run(experiment)
    data = completed_run.data()
    raw = data.measurements()

    return RunAndReadDataResult(
        run=completed_run,
        measurement_count=len(raw.dataset.records),
        artifact_ids=tuple(artifact.id for artifact in data.list()),
    )


# %%
def format_summary(result: RunAndReadDataResult) -> str:
    return "\n".join(
        [
            f"Run: {result.run.id}",
            f"Status: {result.run.manifest.status}",
            f"Measurements: {result.measurement_count}",
            f"Artifacts: {', '.join(result.artifact_ids)}",
        ]
    )


if __name__ == "__main__":
    print(format_summary(run()))
