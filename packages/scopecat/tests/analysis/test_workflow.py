from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scopecat.adapters.sqlite import SQLiteRunRepository
from scopecat.adapters.sqlite.run_repository import PreparedContentPublication
from scopecat.analysis.service import prepare_analysis_artifact
from scopecat.config.registry import service as config_registry_service
from scopecat.records.run import RunManifest
from scopecat.runs.refs import record_content_ref
from tests.testkit.config_registry import activate_candidate_config
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.runtime import (
    sqlite_project_services,
)
from tests.testkit.signal_testkit import (
    SUMMARY_STATS_RESULT_REF,
    SUMMARY_STATS_SUMMARY_REF,
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
    execute_signal_run,
)
from tests.testkit.workflow_fixtures import load_config, load_invocation


def test_analysis_artifact_path_is_snapshotted(tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_bytes(b"first")

    spec = prepare_analysis_artifact(
        title="report",
        kind="report",
        artifact_id="report",
        filename=None,
        model=None,
        json_content=None,
        text=None,
        content=None,
        path=source,
        media_type=None,
        metadata=None,
    )
    source.write_bytes(b"second")

    assert (spec.content, spec.filename, spec.media_type) == (
        b"first",
        "report.txt",
        "text/plain",
    )


def test_workflow_analysis_review_activate_and_rerun_active_config(
    tmp_path: Path,
) -> None:
    services = sqlite_project_services(tmp_path)
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    lab = in_process_lab(tmp_path, config=load_config())
    run_handle = lab.get_run(run.run_id)

    summary = run_handle.analyze(SummaryStatsAnalysisStep())
    summary.save()
    analysis = run_handle.analyze(BestSignalAnalysisStep())
    analysis.save()
    candidate = analysis.candidate_config()
    lab.review_parameter_proposal(run_handle, candidate.proposal_id)
    activation = activate_candidate_config(
        candidate=candidate,
        services=services,
        entry_id="candidate-best-signal",
        registered_by="operator",
        operator="operator",
    )
    active_config, active_source = (
        config_registry_service.resolve_config_registry_config_source(
            selector="active",
            unit_of_work=services.config_registry,
        )
    )
    next_run = execute_signal_run(
        config=active_config,
        experiment=load_invocation(),
        project_root=tmp_path,
        config_source=active_source,
    )

    assert summary.outputs[1].kind == "artifact"
    assert candidate.parameter_proposal.deltas[0].parameter_id == "drive_frequency"
    assert activation.entry.id == "candidate-best-signal"
    assert next_run.status == "completed"
    assert next_run.config_source == active_source


def test_analysis_save_rolls_back_refs_after_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = sqlite_project_services(tmp_path)
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    analysis = (
        in_process_lab(tmp_path, config=load_config())
        .get_run(run.run_id)
        .analyze(SummaryStatsAnalysisStep())
    )
    analysis_record_id = "analysis-summary-stats"
    original_publish = SQLiteRunRepository.publish_prepared_content_in_transaction
    failed = False

    def fail_first_analysis_publication(
        storage: SQLiteRunRepository,
        connection: sqlite3.Connection,
        prepared: PreparedContentPublication,
    ) -> RunManifest:
        nonlocal failed
        manifest = original_publish(storage, connection, prepared)
        if not failed and any(
            record.id == analysis_record_id for record in manifest.records
        ):
            failed = True
            raise OSError("injected analysis manifest failure")
        return manifest

    monkeypatch.setattr(
        SQLiteRunRepository,
        "publish_prepared_content_in_transaction",
        fail_first_analysis_publication,
    )

    with pytest.raises(OSError, match="injected analysis manifest failure"):
        analysis.save()

    storage = services.runs
    analysis_ref = record_content_ref(
        record_id=analysis_record_id,
        kind="analysis",
    )
    assert not storage.exists(run.run_id, analysis_ref)
    assert not storage.exists(run.run_id, SUMMARY_STATS_RESULT_REF)
    assert not storage.exists(run.run_id, SUMMARY_STATS_SUMMARY_REF)
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
