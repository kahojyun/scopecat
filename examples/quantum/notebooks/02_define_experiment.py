"""Notebook-style example: define an experiment and customize its sweep."""

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
import scopecat.authoring as authoring
from quantum_lab_demo import DEFAULT_WORKSPACE_ROOT, readout_frequency_lab
from quantum_lab_demo.readout import frequency_calibration
from scopecat.models.parameter import Quantity

DEFAULT_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "notebooks" / "02-define-experiment"


@dataclass(frozen=True)
class DefineExperimentResult:
    experiment: sc.Experiment
    template_id: str | None
    qubit: str
    sweep_points: int
    sweep_span: Quantity


# %%
def open_lab(workspace: str | Path = DEFAULT_WORKSPACE) -> sc.Workspace:
    return readout_frequency_lab(workspace=workspace)


# %%
def define_experiment(
    *,
    lab: sc.Workspace,
    qubit: str = "q0",
    sweep_points: int = 41,
) -> DefineExperimentResult:
    sweep_span = Quantity(value=60.0, unit="MHz")
    source = frequency_calibration(
        qubit=qubit,
        sweep=authoring.around(
            "readout_frequency",
            span=sweep_span,
            points=sweep_points,
        ),
    )
    experiment = lab.experiment("readout frequency", source=source)
    return DefineExperimentResult(
        experiment=experiment,
        template_id=source.template_id,
        qubit=qubit,
        sweep_points=sweep_points,
        sweep_span=sweep_span,
    )


# %%
def run(workspace: str | Path = DEFAULT_WORKSPACE) -> DefineExperimentResult:
    return define_experiment(lab=open_lab(workspace))


# %%
def format_summary(result: DefineExperimentResult) -> str:
    sweep = (
        f"{result.sweep_points} points over "
        f"{result.sweep_span.value} {result.sweep_span.unit}"
    )
    return "\n".join(
        [
            f"Experiment: {result.experiment.name}",
            f"Template: {result.template_id}",
            f"Qubit: {result.qubit}",
            f"Sweep: {sweep}",
        ]
    )


if __name__ == "__main__":
    print(format_summary(run()))
