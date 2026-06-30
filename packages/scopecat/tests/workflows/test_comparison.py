from __future__ import annotations

from pathlib import Path

from scopecat.workflows import (
    compare_runs,
    list_run_comparisons,
    review_run_comparison,
)
from scopecat.workflows._types import CalibrationRoutine, CandidateReviewPolicy
from scopecat.workflows.routines import run_calibration_routine
from scopecat.workflows.runs import (
    run_mode_executor,
    start_run,
)
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.signal_testkit import (
    TestSignalAnalysisStep,
)
from tests.support.workflow_fixtures import (
    load_config,
    load_experiment,
)


def test_workflow_compare_list_and_review_runs(tmp_path: Path) -> None:
    baseline = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    candidate = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    comparison = compare_runs(
        baseline_run_id=baseline.manifest.run_id,
        candidate_run_id=candidate.manifest.run_id,
        workspace=tmp_path,
    )

    comparison_id = f"run-comparison-{candidate.manifest.run_id}-signal"
    assert comparison.job.id == comparison_id
    assert comparison.result.comparison_id == comparison_id
    assert comparison.result.outcome == "unchanged"
    views_before = list_run_comparisons(
        run_id=baseline.manifest.run_id,
        workspace=tmp_path,
    )
    assert len(views_before) == 1
    assert views_before[0].id == comparison_id
    assert views_before[0].review_status == "not_reviewed"

    review = review_run_comparison(
        run_id=baseline.manifest.run_id,
        selector=comparison_id,
        workspace=tmp_path,
        state="accepted",
        reviewer="operator",
        note="candidate is equivalent",
    )

    assert review.result.comparison_id == comparison_id
    assert review.review.decision == "accepted"
    views_after = list_run_comparisons(
        run_id=baseline.manifest.run_id,
        workspace=tmp_path,
    )
    assert views_after[0].review_status == "reviewed"


def test_calibration_routine_follow_up_can_be_compared_and_reviewed(
    tmp_path: Path,
) -> None:
    routine = CalibrationRoutine(
        id="demo-best-signal-follow-up",
        experiment=load_experiment(),
        run_executor=run_mode_executor(
            "native_simulate", native_instrument_provider=TestSignalInstrumentProvider()
        ),
        analysis_steps=(TestSignalAnalysisStep(),),
        review_candidate=CandidateReviewPolicy(
            reviewer="operator",
        ),
    )

    baseline = run_calibration_routine(
        routine=routine,
        config=load_config(),
        workspace=tmp_path,
    )
    assert baseline.active_config is not None
    candidate = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=baseline.active_config.config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    comparison = compare_runs(
        baseline_run_id=baseline.run.manifest.run_id,
        candidate_run_id=candidate.manifest.run_id,
        workspace=tmp_path,
    )
    review = review_run_comparison(
        run_id=baseline.run.manifest.run_id,
        selector=comparison.result.comparison_id,
        workspace=tmp_path,
        state="accepted",
        reviewer="operator",
        note="follow-up accepted",
    )

    assert comparison.result.comparison_id.startswith("run-comparison-")
    assert review.review.decision == "accepted"
