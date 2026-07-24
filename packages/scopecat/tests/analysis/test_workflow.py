from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.adapters.sqlite import SQLiteRunRepository
from scopecat.composition.embedded import (
    embedded_workspace_services,
)
from scopecat.config.resolution import (
    load_active_config,
    register_and_activate_candidate_config,
)
from scopecat.records.run import RunManifest
from scopecat.runs.refs import record_content_ref
from scopecat.runs.service import start_run
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.signal_testkit import (
    SUMMARY_STATS_RESULT_REF,
    SUMMARY_STATS_SUMMARY_REF,
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
)
from tests.testkit.workflow_fixtures import load_config, load_prepared_invocation


def test_workflow_analysis_review_activate_and_rerun_active_config(
    tmp_path: Path,
) -> None:
    services = embedded_workspace_services(tmp_path)
    run = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=services,
    )
    lab = in_process_lab(tmp_path, config=load_config())
    run_handle = lab.get_run(run.run_id)

    summary = run_handle.analyze(SummaryStatsAnalysisStep())
    summary.save()
    analysis = run_handle.analyze(BestSignalAnalysisStep())
    analysis.save()
    candidate = analysis.candidate_config()
    lab.review_parameter_proposal(run_handle, candidate.proposal_ids[0])
    activation = register_and_activate_candidate_config(
        candidate=candidate,
        services=services,
        entry_id="candidate-best-signal",
        registered_by="operator",
        operator="operator",
    )
    active_config = load_active_config(services=services)
    next_run = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=active_config.config,
        experiment=load_prepared_invocation(),
        services=services,
        config_source=active_config.config_source,
    )

    assert summary.outputs[1].kind == "artifact"
    assert candidate.parameter_proposals[0].deltas[0].parameter_id == "drive_frequency"
    assert activation.entry.id == "candidate-best-signal"
    assert active_config.config_source is not None
    assert next_run.status == "completed"
    assert next_run.config_source == active_config.config_source


def test_analysis_save_recovers_orphans_after_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = embedded_workspace_services(tmp_path)
    run = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=services,
    )
    analysis = (
        in_process_lab(tmp_path, config=load_config())
        .get_run(run.run_id)
        .analyze(SummaryStatsAnalysisStep())
    )
    analysis_record_id = "analysis-summary-stats"
    original_write_manifest = SQLiteRunRepository.write_manifest
    failed = False

    def fail_first_analysis_manifest(
        storage: SQLiteRunRepository,
        manifest: RunManifest,
    ) -> None:
        nonlocal failed
        if not failed and any(
            record.id == analysis_record_id for record in manifest.records
        ):
            failed = True
            raise OSError("injected analysis manifest failure")
        original_write_manifest(storage, manifest)

    monkeypatch.setattr(
        SQLiteRunRepository,
        "write_manifest",
        fail_first_analysis_manifest,
    )

    with pytest.raises(OSError, match="injected analysis manifest failure"):
        analysis.save()

    storage = services.runs
    analysis_ref = record_content_ref(
        record_id=analysis_record_id,
        kind="analysis",
    )
    assert storage.exists(run.run_id, analysis_ref)
    failed_manifest = storage.read_manifest(run.run_id)
    assert all(record.id != analysis_record_id for record in failed_manifest.records)
    assert all(
        artifact.id not in {"summary-stats-result", "summary-stats-summary"}
        for artifact in failed_manifest.artifacts
    )

    saved = analysis.save()

    recovered_manifest = storage.read_manifest(run.run_id)
    assert any(record.id == analysis_record_id for record in recovered_manifest.records)
    assert {artifact.id for artifact in saved.output_artifacts} <= {
        artifact.id for artifact in recovered_manifest.artifacts
    }


def test_analysis_save_recovers_after_output_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = embedded_workspace_services(tmp_path)
    run = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=services,
    )
    analysis = (
        in_process_lab(tmp_path, config=load_config())
        .get_run(run.run_id)
        .analyze(SummaryStatsAnalysisStep())
    )
    original_write_bytes = SQLiteRunRepository.write_bytes
    failed = False

    def fail_first_summary_write(
        storage: SQLiteRunRepository,
        run_id: str,
        ref: str,
        content: bytes,
    ) -> None:
        nonlocal failed
        if not failed and ref == SUMMARY_STATS_SUMMARY_REF:
            failed = True
            raise OSError("injected analysis output failure")
        original_write_bytes(storage, run_id, ref, content)

    monkeypatch.setattr(
        SQLiteRunRepository,
        "write_bytes",
        fail_first_summary_write,
    )

    with pytest.raises(OSError, match="injected analysis output failure"):
        analysis.save()

    storage = services.runs
    failed_manifest = storage.read_manifest(run.run_id)
    assert storage.exists(run.run_id, SUMMARY_STATS_RESULT_REF)
    assert not storage.exists(run.run_id, SUMMARY_STATS_SUMMARY_REF)
    assert all(
        record.id != "analysis-summary-stats" for record in failed_manifest.records
    )
    assert all(
        artifact.id not in {"summary-stats-result", "summary-stats-summary"}
        for artifact in failed_manifest.artifacts
    )

    saved = analysis.save()

    recovered_manifest = storage.read_manifest(run.run_id)
    assert storage.exists(run.run_id, SUMMARY_STATS_SUMMARY_REF)
    assert {artifact.id for artifact in saved.output_artifacts} <= {
        artifact.id for artifact in recovered_manifest.artifacts
    }
