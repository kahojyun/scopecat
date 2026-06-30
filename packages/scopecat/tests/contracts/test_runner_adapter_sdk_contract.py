from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, PlanSnapshot
from scopecat.models.config import (
    ConfigProfileSnapshot,
    load_config_profile,
)
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementDatasetSchema
from scopecat.runner import (
    MeasurementSink,
    RunnerAdapterResult,
    RunnerAdapterRunSnapshot,
    RunnerContext,
    execute_runner_adapter,
)
from scopecat.runs import open_run_store
from tests.support.records import (
    artifact_refs_by_id,
    assert_artifact_ref,
    read_measurement_records,
    read_model,
)

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"


class BoundaryAdapter:
    adapter_id = "contract.boundary_adapter"
    adapter_version = "v0"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        _assert_storage_layout_is_hidden(context)
        assert isinstance(context.plan, PlanSnapshot)
        context.artifacts.write_text(
            id="adapter-log",
            kind="adapter_log",
            filename="adapter-log.txt",
            content="adapter log\n",
            media_type="text/plain",
        )
        for point in context.plan.points:
            sink.record(
                point_index=point.point_id,
                coordinates={
                    name: value
                    for name, value in point.row.items()
                    if isinstance(value, Quantity)
                },
                observables={
                    "signal": Quantity(
                        value=round(0.5 + point.point_id * 0.25, 12),
                        unit="ratio",
                    )
                },
                metadata={"adapter": self.adapter_id},
            )
        return RunnerAdapterResult(metadata={"boundary": "runner_adapter_sdk"})


class FailingAfterArtifactAdapter(BoundaryAdapter):
    adapter_id = "contract.failing_after_artifact_adapter"

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        _assert_storage_layout_is_hidden(context)
        assert isinstance(context.plan, PlanSnapshot)
        context.artifacts.write_text(
            id="pre-failure-log",
            kind="adapter_log",
            filename="pre-failure-log.txt",
            content="written before failure\n",
            media_type="text/plain",
        )
        point = context.plan.points[0]
        sink.record(
            point_index=point.point_id,
            coordinates={
                name: value
                for name, value in point.row.items()
                if isinstance(value, Quantity)
            },
            observables={"signal": Quantity(value=1.0, unit="ratio")},
        )
        raise RuntimeError("contract failure")


def test_runner_adapter_sdk_boundary_hides_storage_layout_and_writes_runner_data(
    tmp_path: Path,
) -> None:
    manifest, snapshot = execute_runner_adapter(
        config=_load_config(),
        experiment=_load_experiment(),
        adapter=BoundaryAdapter(),
        workspace=tmp_path,
    )

    run_dir = open_run_store(tmp_path).display_run_path(manifest.run_id)
    artifact_refs = artifact_refs_by_id(manifest.artifact_refs)
    measurements = read_measurement_records(
        run_dir / "artifacts" / "raw-measurements.jsonl"
    )

    assert manifest.status == "completed"
    assert manifest.runner_versions == {"contract.boundary_adapter": "v0"}
    assert_artifact_ref(
        manifest.artifact_refs,
        "raw-measurements",
        kind="measurement_dataset",
    )
    raw_metadata = artifact_refs["raw-measurements"].metadata
    assert raw_metadata["dataset_role"] == "raw"
    assert raw_metadata["record_schema"] == "scopecat.measurement_record.v0"
    raw_schema = MeasurementDatasetSchema.model_validate(raw_metadata["dataset_schema"])
    assert raw_schema.schema_version == "scopecat.measurement_dataset_schema.v0"
    assert raw_schema.dataset_id == "raw-measurements"
    assert raw_schema.dataset_role == "raw"
    assert raw_schema.primary_coordinates == ["drive_frequency"]
    assert raw_schema.primary_observables == ["signal"]
    raw_variables = {variable.id: variable for variable in raw_schema.variables}
    assert raw_variables["drive_frequency"].unit == "GHz"
    assert raw_variables["signal"].unit == "ratio"
    assert_artifact_ref(
        manifest.artifact_refs,
        "adapter-log",
        path="artifacts/adapter-log.txt",
    )
    assert (run_dir / artifact_refs["adapter-log"].path).read_text() == "adapter log\n"
    assert snapshot.metadata == {"boundary": "runner_adapter_sdk"}
    assert snapshot.measurement_count == 3
    assert {record.schema_version for record in measurements} == {
        "scopecat.measurement_record.v0"
    }
    assert [record.point_index for record in measurements] == [0, 1, 2]
    assert [record.observables["signal"].value for record in measurements] == [
        0.5,
        0.75,
        1.0,
    ]


def test_runner_adapter_sdk_boundary_keeps_failed_run_and_written_artifacts(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_runner_adapter(
            config=_load_config(),
            experiment=_load_experiment(),
            adapter=FailingAfterArtifactAdapter(),
            workspace=tmp_path,
        )

    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    manifest = manifests[0]
    run_dir = open_run_store(tmp_path).display_run_path(manifest.run_id)
    artifact_refs = artifact_refs_by_id(manifest.artifact_refs)

    assert error.value.diagnostics[-1].code == "runner_adapter_failed"
    assert manifest.status == "failed"
    assert_artifact_ref(
        manifest.artifact_refs,
        "pre-failure-log",
        path="artifacts/pre-failure-log.txt",
    )
    assert (run_dir / artifact_refs["pre-failure-log"].path).read_text() == (
        "written before failure\n"
    )
    assert (run_dir / "artifacts" / "raw-measurements.jsonl").is_file()
    snapshot = read_model(
        run_dir / "artifacts" / "runner-adapter.snapshot.json",
        RunnerAdapterRunSnapshot,
    )
    assert snapshot.status == "failed"
    assert snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert snapshot.diagnostics[-1].code == "runner_adapter_failed"


def _assert_storage_layout_is_hidden(context: RunnerContext) -> None:
    assert not hasattr(context, "workspace")
    assert not hasattr(context, "run_dir")
    assert not hasattr(context, "artifacts_dir")
    assert hasattr(context, "artifacts")


def _load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def _load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)
