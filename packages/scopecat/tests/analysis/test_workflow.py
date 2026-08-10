from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

import scopecat as sc
from scopecat.adapters.sqlite import SQLiteRunRepository
from scopecat.adapters.sqlite.run_repository import PreparedContentPublication
from scopecat.analysis.service import AnalysisDataOutput
from scopecat.config.registry import service as config_registry_service
from scopecat.measurements.results import Dataset
from scopecat.records.run import RunManifest
from scopecat.runs.refs import record_content_ref
from tests.testkit.config_registry import activate_candidate_config
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.runtime import (
    sqlite_project_services,
)
from tests.testkit.signal_testkit import (
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
    execute_signal_run,
)
from tests.testkit.workflow_fixtures import load_config, load_invocation


def _dataset_size(dataset: Dataset) -> int:
    return len(dataset)


_COMPUTES = sc.ComputeRegistry()


@_COMPUTES.implementation(
    "test.dataset-size-batches",
    "1",
    data_access="batches",
    batch_size=2,
)
def _batch_dataset_size(batches: Iterator[Dataset]) -> int:
    return sum(len(batch) for batch in batches)


class _DatasetComputeStep:
    id = "dataset-compute"

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        measurements = context.measurements()
        count = context.compute(measurements, fn=_dataset_size)
        return context.result("Dataset compute").table(
            sc.AnalysisTable.from_rows([{"points": count}])
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
    analysis = run_handle.analyze(BestSignalAnalysisStep())
    candidate = analysis.candidate_config()
    lab.review_parameter_proposal(run_handle, candidate.proposal_id)
    activation = activate_candidate_config(
        candidate=candidate,
        services=services,
        entry_id="candidate-best-signal",
        actor="operator",
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

    assert isinstance(summary, sc.AnalysisOutcome)
    assert summary.outputs[0].kind == "table"
    assert candidate.parameter_proposal.deltas[0].parameter_id == "drive_frequency"
    assert activation.entry.id == "candidate-best-signal"
    assert next_run.status == "completed"
    assert next_run.config_source == active_source


def test_dataset_compute_records_its_analysis_dependency(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    analysis = handle.analyze(_DatasetComputeStep())

    [dependency] = analysis.inputs
    assert dependency.target == "raw-measurements"
    assert dependency.role == "compute-input"
    assert dependency.metadata == {
        "compute": {
            "id": "_dataset_size",
            "implementation": "local:_dataset_size",
            "placement": "dataset",
            "access": "full",
        }
    }
    [data_output, table_output] = analysis.outputs
    assert isinstance(data_output, AnalysisDataOutput)
    assert data_output.content.value == 3
    assert data_output.content.execution.id == "_dataset_size"
    assert data_output.content.execution.input_content_hash == (
        handle.measurements().entry.content_hash
    )
    assert data_output.content.execution.output_content_hash.startswith("sha256:")
    assert table_output.kind == "table"
    stored = handle.record_json(
        "analysis-dataset-compute",
        expected_kind="analysis",
    )
    stored_outputs = stored.content["outputs"]
    assert isinstance(stored_outputs, list)
    [stored_output, _stored_table] = stored_outputs
    assert isinstance(stored_output, dict)
    assert stored_output["kind"] == "data"


def test_registered_dataset_compute_can_reduce_bounded_batches(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    context = sc.AnalysisContext(run=handle)

    count = context.compute(context.measurements(), fn=_batch_dataset_size)
    analysis = context.result("Batch compute")

    assert count == 3
    [output] = analysis.outputs
    assert isinstance(output, AnalysisDataOutput)
    assert output.content.execution.access == "batches"
    assert output.content.execution.implementation == (
        "registry:test.dataset-size-batches@1"
    )


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
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    analysis = SummaryStatsAnalysisStep().run(
        sc.AnalysisContext(run=handle),
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
    failed_manifest = storage.read_manifest(run.run_id)
    assert all(record.id != analysis_record_id for record in failed_manifest.records)

    saved = analysis.save()

    recovered_manifest = storage.read_manifest(run.run_id)
    assert any(record.id == analysis_record_id for record in recovered_manifest.records)
    assert saved.record.id == analysis_record_id


def test_local_analysis_rejects_metadata_outside_the_remote_json_contract(
    tmp_path: Path,
) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    analysis = (
        in_process_lab(tmp_path, config=load_config())
        .get_run(run.run_id)
        .analysis("Strict metadata")
        .table(
            sc.AnalysisTable.from_rows([{"value": 1}]),
            metadata={"opaque": object()},
        )
    )

    with pytest.raises(ValidationError):
        analysis.save()
