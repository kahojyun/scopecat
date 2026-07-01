from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.workflows import (
    load_active_config,
    register_and_activate_candidate_review,
)
from scopecat.workflows.runs import start_run
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.signal_testkit import (
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
)
from tests.support.workflow_fixtures import load_config, load_experiment


def test_workflow_analysis_review_activate_and_rerun_active_config(
    tmp_path: Path,
) -> None:
    run = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    lab = sc.open(tmp_path, config=load_config(), mode="native_simulate")
    run_handle = lab.get_run(run.manifest.run_id)

    summary = run_handle.analyze(SummaryStatsAnalysisStep())
    summary.save()
    analysis = run_handle.analyze(BestSignalAnalysisStep())
    analysis.save()
    review = lab.review(
        analysis.candidate_config(reason=analysis.parameter_guesses[0].reason),
        note="looks good",
    )
    activation = register_and_activate_candidate_review(
        review=review,
        workspace=tmp_path,
        entry_id="accepted-best-signal",
        registered_by="operator",
        operator="operator",
    )
    active_config = load_active_config(workspace=tmp_path)
    next_run = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=active_config.config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    assert summary.outputs[1].kind == "artifact"
    assert review.candidate.guesses[0].parameter_id == "drive_frequency"
    assert activation.entry.id == "accepted-best-signal"
    assert active_config.provenance is not None
    assert next_run.manifest.status == "completed"
