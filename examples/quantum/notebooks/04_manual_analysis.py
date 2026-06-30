"""Notebook-style example: save manual analysis from notebook data."""

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

DEFAULT_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "notebooks" / "04-manual-analysis"


@dataclass(frozen=True)
class ManualAnalysisCandidateResult:
    baseline: sc.Run
    follow_up: sc.Run
    analysis: sc.Analysis
    saved_analysis: sc.SavedAnalysis
    review: sc.CandidateConfigReview
    raw_measurement_count: int


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
def run(workspace: str | Path = DEFAULT_WORKSPACE) -> ManualAnalysisCandidateResult:
    lab = open_lab(workspace)
    experiment = lab.experiment(
        "readout frequency",
        source=frequency_calibration(qubit="q0"),
    )

    baseline = lab.run(experiment)
    raw = baseline.data().measurements()

    rows = [
        {
            "point": record.point_index,
            "observables": sorted(record.observables),
        }
        for record in raw.dataset.records
    ]
    analysis = (
        baseline.analysis("manual notebook review")
        .note("Inspected the readout sweep in a notebook.")
        .table(rows, title="raw measurement index")
        .artifact_ref("raw-measurements", expected_kind="measurement_dataset")
        .guess(
            "readout_frequency",
            5.953,
            unit="GHz",
            reason="manual notebook pick from the lowest S21 point",
            confidence=0.8,
        )
    )
    saved = analysis.save()

    candidate = analysis.candidate_config(reason="manual notebook review")
    review = lab.review(candidate, note="approved from notebook example")
    follow_up = lab.run(experiment, config=review)

    return ManualAnalysisCandidateResult(
        baseline=baseline,
        follow_up=follow_up,
        analysis=analysis,
        saved_analysis=saved,
        review=review,
        raw_measurement_count=len(raw.dataset.records),
    )


# %%
def format_summary(result: ManualAnalysisCandidateResult) -> str:
    guess = result.analysis.parameter_guesses[0]
    return "\n".join(
        [
            f"Baseline run: {result.baseline.id}",
            f"Follow-up run: {result.follow_up.id}",
            f"Raw measurements: {result.raw_measurement_count}",
            f"Saved analysis: {result.saved_analysis.artifact.id}",
            f"Candidate artifact: {result.review.candidate_config_artifact.id}",
            f"Guess: {guess.parameter_id} = {guess.value} {guess.unit}",
        ]
    )


if __name__ == "__main__":
    print(format_summary(run()))
