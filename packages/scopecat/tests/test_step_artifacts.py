from __future__ import annotations

from pathlib import Path

import pytest

from scopecat._steps import StepArtifactStore
from scopecat.errors import ValidationFailed
from scopecat.models.parameter import Quantity
from scopecat.results import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementRecord,
    MeasurementVariable,
)
from tests.support.steps import StepResult, artifact_diagnostics


def test_step_artifact_store_collects_existing_artifacts_only(tmp_path: Path) -> None:
    store = StepArtifactStore(
        root_dir=tmp_path,
        diagnostics=artifact_diagnostics(),
    )

    store.write_model(
        id="result",
        kind="result",
        model=StepResult(value=1),
    )
    unwritten = store.reserve_file(
        id="reserved",
        kind="log",
    )

    assert store.output_artifact_ids == ("result",)
    assert [artifact.id for artifact in store.artifacts] == ["result"]

    unwritten.path.write_text("reserved\n")

    assert store.output_artifact_ids == ("result", "reserved")
    assert [artifact.id for artifact in store.artifacts] == ["result", "reserved"]


def test_step_artifact_store_rejects_duplicate_id(
    tmp_path: Path,
) -> None:
    store = StepArtifactStore(
        root_dir=tmp_path,
        diagnostics=artifact_diagnostics(),
    )
    store.write_text(id="one", kind="log", content="one")

    with pytest.raises(ValidationFailed) as duplicate_id:
        store.write_text(id="one", kind="log", content="duplicate")

    assert duplicate_id.value.diagnostics[0].code == "test_duplicate_artifact"


def test_step_artifact_store_writes_measurement_dataset_metadata(
    tmp_path: Path,
) -> None:
    store = StepArtifactStore(
        root_dir=tmp_path,
        diagnostics=artifact_diagnostics(),
    )
    records = [
        MeasurementRecord(
            run_id="run-000001",
            point_index=0,
            coordinates={"drive_frequency": Quantity(value=5.0, unit="GHz")},
            observables={"signal": Quantity(value=0.5, unit="ratio")},
        )
    ]

    handle = store.write_measurement_dataset(
        id="derived-measurements",
        dataset_role="derived",
        records=records,
        source_step="test-step",
    )
    dataset = store.datasets[0]

    assert handle.kind == "measurement_dataset"
    assert handle.path.is_file()
    assert store.output_artifact_ids == ()
    assert store.output_dataset_ids == ("derived-measurements",)
    assert dataset.role == "derived"
    assert dataset.produced_by == "test-step"
    assert dataset.data_schema is not None
    assert dataset.data_schema["dataset_id"] == "derived-measurements"
    assert dataset.data_schema["primary_observables"] == ["signal"]


def test_step_artifact_store_validates_measurement_dataset_schema(
    tmp_path: Path,
) -> None:
    store = StepArtifactStore(
        root_dir=tmp_path,
        diagnostics=artifact_diagnostics(),
    )
    schema = MeasurementDatasetSchema(
        dataset_id="derived-measurements",
        dataset_role="derived",
        dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
        variables=[
            MeasurementVariable(
                id="drive_frequency",
                role="coordinate",
                dtype="float64",
                unit="GHz",
                dims=["point"],
                shape=[1],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
                shape=[1],
            ),
        ],
        primary_coordinates=["drive_frequency"],
        primary_observables=["signal"],
    )
    records = [
        MeasurementRecord(
            run_id="run-000001",
            point_index=0,
            coordinates={"drive_frequency": Quantity(value=5.0, unit="GHz")},
            observables={"bad_signal": Quantity(value=0.5, unit="ratio")},
        )
    ]

    with pytest.raises(ValidationFailed) as error:
        store.write_measurement_dataset(
            id="derived-measurements",
            dataset_role="derived",
            records=records,
            schema=schema,
        )

    assert [diagnostic.code for diagnostic in error.value.diagnostics] == [
        "measurement_record_missing_observable",
        "measurement_record_unexpected_observable",
    ]
    assert store.output_artifact_ids == ()
    assert store.output_dataset_ids == ()
