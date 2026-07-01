from __future__ import annotations

from pathlib import Path

from scopecat.workflows import accept_proposal, load_active_config
from scopecat.workflows.runs import start_run
from scopecat.workflows.steps import evaluate_run, process_run
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.signal_testkit import (
    BestSignalEvaluationStep,
    SummaryStatsProcessingStep,
)
from tests.support.workflow_fixtures import load_config, load_experiment


def test_workflow_process_evaluate_accept_and_rerun_active_config(
    tmp_path: Path,
) -> None:
    run = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    processing = process_run(
        run_id=run.manifest.run_id,
        workspace=tmp_path,
        step=SummaryStatsProcessingStep(),
    )
    evaluation = evaluate_run(
        run_id=run.manifest.run_id,
        workspace=tmp_path,
        step=BestSignalEvaluationStep(),
    )
    acceptance = accept_proposal(
        run_id=run.manifest.run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
        entry_id="accepted-best-signal",
    )
    active_config = load_active_config(workspace=tmp_path)
    next_run = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=active_config.config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    assert processing.result.measurement_count == 3
    assert evaluation.proposals[0].patches[0].parameter_id == "drive_frequency"
    assert acceptance.review is not None
    assert active_config.provenance is not None
    assert next_run.manifest.status == "completed"
