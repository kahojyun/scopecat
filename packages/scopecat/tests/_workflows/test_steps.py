from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat._workflows.config import (
    load_active_config,
    register_and_activate_candidate_config,
)
from scopecat._workflows.runs import start_run
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.signal_testkit import (
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
)
from tests.support.workflow_fixtures import load_config, load_experiment


def test_workflow_analysis_review_activate_and_rerun_active_config(
    tmp_path: Path,
) -> None:
    run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    lab = sc.open(tmp_path, config=load_config())
    run_handle = lab.get_run(run.run_id)

    summary = run_handle.analyze(SummaryStatsAnalysisStep())
    summary.save()
    analysis = run_handle.analyze(BestSignalAnalysisStep())
    analysis.save()
    candidate = analysis.candidate_config()
    activation = register_and_activate_candidate_config(
        candidate=candidate,
        workspace=tmp_path,
        entry_id="candidate-best-signal",
        registered_by="operator",
        operator="operator",
    )
    active_config = load_active_config(workspace=tmp_path)
    next_run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=active_config.config,
        experiment=load_experiment(),
        workspace=tmp_path,
        config_source=active_config.config_source,
    )

    assert summary.outputs[1].kind == "artifact"
    assert candidate.parameter_changes[0].patches[0].parameter_id == "drive_frequency"
    assert activation.entry.id == "candidate-best-signal"
    assert active_config.config_source is not None
    assert next_run.status == "completed"
    assert next_run.config_source == active_config.config_source
