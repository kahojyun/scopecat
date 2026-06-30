"""Notebook-style example: replace manual analysis with a reusable AnalysisStep."""

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
from quantum_lab_demo.readout import (
    ReadoutFrequencyAnalysisStep,
    frequency_calibration,
)
from quantum_lab_demo.virtual_lab.provider import ReadoutFrequencyVirtualProvider

DEFAULT_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "notebooks" / "05-promoted-analysis"


@dataclass(frozen=True)
class PromotedAnalysisStepResult:
    run: sc.Run
    analysis: sc.Analysis
    saved_analysis: sc.SavedAnalysis
    candidate: sc.CandidateConfig
    overview: sc.OverviewHandle


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
def run(workspace: str | Path = DEFAULT_WORKSPACE) -> PromotedAnalysisStepResult:
    lab = open_lab(workspace)
    experiment = lab.experiment(
        "readout frequency",
        source=frequency_calibration(qubit="q0"),
    )

    completed_run = lab.run(experiment)
    analysis = completed_run.analyze(ReadoutFrequencyAnalysisStep())
    saved = analysis.save()
    candidate = analysis.candidate_config(reason=analysis.parameter_guesses[0].reason)
    overview = completed_run.overview()

    return PromotedAnalysisStepResult(
        run=completed_run,
        analysis=analysis,
        saved_analysis=saved,
        candidate=candidate,
        overview=overview,
    )


# %%
def format_summary(result: PromotedAnalysisStepResult) -> str:
    guess = result.candidate.guesses[0]
    return "\n".join(
        [
            f"Run: {result.run.id}",
            f"Analysis: {result.saved_analysis.artifact.id}",
            f"Overview lines: {len(result.overview.markdown.splitlines())}",
            f"Candidate guess: {guess.parameter_id}",
        ]
    )


if __name__ == "__main__":
    print(format_summary(run()))
