"""Notebook-style example: review a candidate config and rerun."""

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
from quantum_lab_demo import DEFAULT_WORKSPACE_ROOT, readout_frequency_lab
from quantum_lab_demo.readout import (
    ReadoutFrequencyAnalysisStep,
    frequency_calibration,
)

DEFAULT_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "notebooks" / "06-review-and-rerun"


@dataclass(frozen=True)
class ReviewCandidateAndRerunResult:
    baseline: sc.Run
    analysis: sc.Analysis
    review: sc.CandidateConfigReview
    follow_up: sc.Run
    comparison: sc.ComparisonHandle


# %%
def open_lab(workspace: str | Path = DEFAULT_WORKSPACE) -> sc.Workspace:
    return readout_frequency_lab(workspace=workspace)


# %%
def run(workspace: str | Path = DEFAULT_WORKSPACE) -> ReviewCandidateAndRerunResult:
    lab = open_lab(workspace)
    experiment = lab.experiment(
        "readout frequency",
        source=frequency_calibration(qubit="q0"),
    )

    baseline = lab.run(experiment)
    analysis = baseline.analyze(ReadoutFrequencyAnalysisStep())
    analysis.save()
    candidate = analysis.candidate_config(reason=analysis.parameter_guesses[0].reason)
    review = lab.review(candidate, note="accept promoted readout analysis")
    follow_up = lab.run(experiment, config=review)
    comparison = lab.compare(baseline, follow_up, observable="raw_i")

    return ReviewCandidateAndRerunResult(
        baseline=baseline,
        analysis=analysis,
        review=review,
        follow_up=follow_up,
        comparison=comparison,
    )


# %%
def format_summary(result: ReviewCandidateAndRerunResult) -> str:
    guess = result.analysis.parameter_guesses[0]
    return "\n".join(
        [
            f"Baseline run: {result.baseline.id}",
            f"Accepted guess: {guess.parameter_id}",
            f"Candidate artifact: {result.review.candidate_config_artifact.id}",
            f"Follow-up run: {result.follow_up.id}",
            f"Comparison: {result.comparison.id}",
        ]
    )


if __name__ == "__main__":
    print(format_summary(run()))
