# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

import pytest
from pydantic import ValidationError

import scopecat as sc
from scopecat.adapters.sqlite import SQLiteRunRepository
from scopecat.adapters.sqlite.run_repository import PreparedContentPublication
from scopecat.analysis.datasets import DERIVED_DATASET_CODEC, DerivedDataset
from scopecat.analysis.service import AnalysisDatasetOutput, AnalysisFactOutput
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


def _scaled_dataset_size(*, dataset: Dataset, scale: int) -> int:
    return len(dataset) * scale


def _derived_signal_frame(dataset: Dataset) -> DerivedDataset:
    frame = dataset.project(
        {"frequency": "drive_frequency", "response": "signal"},
        identity=False,
    ).to_pandas()
    frame["score"] = frame["response"] * 2.0
    return sc.derived_dataset(
        frame[["frequency", "response", "score"]],
        coordinates=("frequency",),
        labels={"score": "Doubled response"},
    )


def _derived_score_max(dataset: DerivedDataset) -> float:
    return float(cast("float", dataset.to_pandas()["score"].max()))


_COMPUTES = sc.ComputeRegistry()


@dataclass(frozen=True, slots=True)
class _PresentedObservation:
    bias: Annotated[
        sc.Quantity,
        sc.AnalysisField(id="bias_mv", label="Bias", unit="mV"),
    ]
    response: Annotated[float, sc.AnalysisField(label="Response")]


@_COMPUTES.implementation(
    "test.dataset-size-batches",
    "1",
    data_access="batches",
    batch_size=2,
)
def _batch_dataset_size(batches: Iterator[Dataset]) -> int:
    return sum(len(batch) for batch in batches)


def _encode_dataset_size(result: int) -> dict[str, int]:
    return {"points": result}


@_COMPUTES.implementation(
    "test.encoded-dataset-size",
    "1",
    input_codecs={"dataset": "scopecat.measurement-dataset.v8"},
    output_codec="test.dataset-size.v1",
    encode_output=_encode_dataset_size,
)
def _encoded_dataset_size(*, dataset: Dataset) -> int:
    return len(dataset)


class _DatasetComputeStep:
    id = "dataset-compute"

    def run(self, context: sc.AnalysisContext) -> sc.Analysis:
        measurements = context.measurements()
        count = context.compute(fn=_dataset_size, dataset=measurements)
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
            "implementation": "python:_dataset_size",
            "placement": "dataset",
            "deterministic": False,
            "inputs": ["dataset"],
            "outputs": ["_dataset_size"],
            "captures": [],
            "access": "full",
        },
        "binding": "dataset",
    }
    [data_output, table_output] = analysis.outputs
    assert isinstance(data_output, AnalysisFactOutput)
    assert data_output.content.value == 3
    execution = data_output.content.execution
    assert execution is not None
    assert execution.id == "_dataset_size"
    assert execution.placement == "dataset"
    assert execution.implementation == "python:_dataset_size"
    assert not execution.deterministic
    assert execution.inputs == ("dataset",)
    assert execution.outputs == ("_dataset_size",)
    assert execution.captures == ()
    [input_binding] = execution.input_bindings
    assert input_binding.name == "dataset"
    assert input_binding.target == "raw-measurements"
    assert input_binding.content_hash == handle.measurements().entry.content_hash
    assert input_binding.codec == "scopecat.measurement-dataset.v8"
    assert execution.output_content_hash.startswith("sha256:")
    assert table_output.kind == "table"
    stored = handle.record_json(
        "analysis-dataset-compute",
        expected_kind="analysis",
    )
    stored_outputs = stored.content["outputs"]
    assert isinstance(stored_outputs, list)
    [stored_output, _stored_table] = stored_outputs
    assert isinstance(stored_output, dict)
    assert stored_output["kind"] == "fact"
    assert stored_output["id"] == "_dataset_size"


def test_registered_dataset_compute_can_reduce_bounded_batches(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    context = sc.AnalysisContext(run=handle)

    count = context.compute(
        fn=_batch_dataset_size,
        batches=context.measurements(),
    )
    analysis = context.result("Batch compute")

    assert count == 3
    [output] = analysis.outputs
    assert isinstance(output, AnalysisFactOutput)
    execution = output.content.execution
    assert execution is not None
    assert execution.access == "batches"
    assert execution.implementation == ("registry:test.dataset-size-batches@1")


def test_native_dataframe_compute_returns_one_reusable_derived_dataset(
    tmp_path: Path,
) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    context = sc.AnalysisContext(run=handle)

    derived = context.compute(
        fn=_derived_signal_frame,
        dataset=context.measurements(),
    )
    maximum = context.compute(fn=_derived_score_max, dataset=derived)
    outcome = (
        context.result("Native derived data", key="native-derived-data")
        .table(
            dataset="_derived_signal_frame",
            columns=("frequency", "score"),
            title="Derived rows",
        )
        .figure(
            dataset="_derived_signal_frame",
            kind="line",
            x="frequency",
            y="score",
            title="Derived score",
        )
        .save()
    )

    assert isinstance(derived, DerivedDataset)
    assert derived.table.column_names == ["frequency", "response", "score"]
    assert maximum == 2.0
    data_output, maximum_output, table_output, figure_output = outcome.outputs
    assert isinstance(data_output, AnalysisDatasetOutput)
    assert data_output.execution is not None
    assert data_output.execution.output_content_hash.startswith("sha256:")
    dataset_id = "analysis-native-derived-data-_derived_signal_frame"
    restored = handle.derived_dataset(dataset_id)
    assert restored.table.equals(derived.table, check_metadata=True)
    assert isinstance(maximum_output, AnalysisFactOutput)
    assert maximum_output.content.value == 2.0
    execution = maximum_output.content.execution
    assert execution is not None
    [derived_input] = execution.input_bindings
    assert derived_input.kind == "derived_dataset"
    assert derived_input.target == "_derived_signal_frame"
    assert derived_input.codec == DERIVED_DATASET_CODEC
    assert derived_input.value is None
    assert table_output.kind == "table"
    assert figure_output.kind == "figure"

    stored = handle.record_json(
        "analysis-native-derived-data",
        expected_kind="analysis",
    )
    outputs = stored.content["outputs"]
    assert isinstance(outputs, list)
    persisted = outputs[0]
    assert isinstance(persisted, dict)
    content = persisted["content"]
    assert isinstance(content, dict)
    assert content["codec"] == DERIVED_DATASET_CODEC
    assert persisted["id"] == "_derived_signal_frame"
    assert content["dataset_id"] == dataset_id
    assert "value" not in content
    assert "arrow_ipc_base64" not in str(stored.content)
    manifest_entry = next(
        entry for entry in handle.manifest.datasets if entry.id == dataset_id
    )
    assert manifest_entry.kind == "analysis_dataset"
    assert manifest_entry.content_hash == content["content_hash"]


def test_analysis_dataset_publishes_a_native_frame_once(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    frame = (
        handle.measurements()
        .project(
            {"frequency": "drive_frequency", "response": "signal"},
            identity=False,
        )
        .to_pandas()
    )
    frame["score"] = frame["response"] * 2.0

    outcome = (
        handle.analysis("Native fits", key="native-fits")
        .dataset(
            "fits",
            frame[["frequency", "score"]],
            labels={"score": "Fit score"},
        )
        .save()
    )

    [output] = outcome.outputs
    assert isinstance(output, AnalysisDatasetOutput)
    restored = handle.derived_dataset("analysis-native-fits-fits")
    assert restored.table.to_pylist() == [
        {"frequency": frequency, "score": score}
        for frequency, score in zip(
            frame["frequency"],
            frame["score"],
            strict=True,
        )
    ]
    assert restored.schema.fields[0].role == "coordinate"
    assert restored.schema.fields[0].unit == "GHz"
    assert restored.schema.fields[1].label == "Fit score"


def test_analysis_publishes_typed_facts_and_owned_artifacts(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)

    outcome = (
        handle.analysis("Publication", key="publication")
        .fact(
            "resonance",
            sc.Quantity(5.1, "GHz"),
            title="Fitted resonance",
        )
        .artifact(
            "fit-report",
            text="# Fit report\n\nConverged.\n",
            filename="fit-report.md",
            media_type="text/markdown",
        )
        .save()
    )

    fact, artifact = outcome.outputs
    assert isinstance(fact, AnalysisFactOutput)
    assert fact.id == "resonance"
    assert fact.content.schema_id == "scopecat.quantity.v1"
    assert fact.content.value == {"value": 5.1, "unit": "GHz"}
    assert artifact.id == "fit-report"
    stored = handle.record_json("analysis-publication", expected_kind="analysis")
    stored_outputs = cast("list[object]", stored.content["outputs"])
    artifact_output = cast("dict[str, object]", stored_outputs[1])
    assert artifact_output["id"] == "fit-report"
    assert artifact_output["kind"] == "artifact"
    artifact_ref = cast("dict[str, object]", artifact_output["content"])
    artifact_id = "analysis-publication-fit-report"
    assert artifact_ref["artifact_id"] == artifact_id
    restored = handle.artifact_text(
        artifact_id,
        expected_kind="analysis_artifact",
    )
    assert restored.content == "# Fit report\n\nConverged.\n"
    entry = next(item for item in handle.manifest.artifacts if item.id == artifact_id)
    assert entry.filename == "fit-report.md"
    assert entry.produced_by == "analysis-publication"


def test_dataset_compute_records_named_inline_inputs(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    context = sc.AnalysisContext(run=handle)

    count = context.compute(
        fn=_scaled_dataset_size,
        dataset=context.measurements(),
        scale=2,
    )

    assert count == 6
    [output] = context.result().outputs
    assert isinstance(output, AnalysisFactOutput)
    execution = output.content.execution
    assert execution is not None
    assert execution.inputs == ("dataset", "scale")
    dataset_input, scale_input = execution.input_bindings
    assert dataset_input.kind == "measurement_dataset"
    assert scale_input.kind == "value"
    assert scale_input.codec == "scopecat.python-json.v1"
    assert scale_input.value == 2


def test_dataset_compute_uses_its_registered_output_encoder(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    handle = in_process_lab(tmp_path, config=load_config()).get_run(run.run_id)
    context = sc.AnalysisContext(run=handle)

    count = context.compute(
        fn=_encoded_dataset_size,
        dataset=context.measurements(),
    )

    assert count == 3
    [output] = context.result().outputs
    assert isinstance(output, AnalysisFactOutput)
    assert output.content.codec == "test.dataset-size.v1"
    assert output.content.value == {"points": 3}


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


def test_analysis_facade_projects_annotated_results_directly(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    observations = (
        _PresentedObservation(sc.Quantity(0.1, "V"), 0.2),
        _PresentedObservation(sc.Quantity(0.2, "V"), 0.4),
    )

    analysis = (
        in_process_lab(tmp_path, config=load_config())
        .get_run(run.run_id)
        .analysis("Direct presentation")
        .table(observations)
        .figure(
            observations,
            kind="line",
            x="bias_mv",
            y="response",
        )
    )

    table = analysis.outputs[0].content
    figure = analysis.outputs[1].content
    assert isinstance(table, sc.AnalysisTable)
    assert [row.cells for row in table.rows] == [[100.0, 0.2], [200.0, 0.4]]
    assert isinstance(figure, sc.AnalysisFigure)
    assert figure.series[0].x == [100.0, 200.0]
