from __future__ import annotations

from pathlib import Path

import pytest

from scopecat._steps import MeasurementInputDiagnostics, StepInputResolver
from scopecat.errors import ValidationFailed
from scopecat.results import MeasurementDatasetInputDiagnostics
from scopecat.runs import dataset_storage_ref, get_dataset_by_id, open_run_store
from tests.support.steps import input_diagnostics, make_signal_run


def test_step_input_resolver_reads_measurement_records(tmp_path: Path) -> None:
    run_id = make_signal_run(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    resolver = StepInputResolver(
        storage=storage,
        run_id=run_id,
        manifest=manifest,
    )
    raw_dataset = get_dataset_by_id(manifest, "raw-measurements")
    assert raw_dataset is not None
    source = resolver.dataset_ref(
        dataset_id="raw-measurements",
        ref=dataset_storage_ref(raw_dataset),
        path_escape_code="test_input_escape",
        path_escape_message="test input escaped",
        diagnostic_path="input",
    )

    measurements = resolver.read_measurement_records(
        source,
        diagnostics=MeasurementInputDiagnostics(
            missing_code="missing",
            empty_code="empty",
            invalid_code="invalid",
            noun="measurement input",
        ),
    )

    assert resolver.input_artifact_ids == ()
    assert resolver.input_dataset_ids == ("raw-measurements",)
    assert resolver.input_records == ()
    assert [measurement.point_index for measurement in measurements] == [0, 1, 2]


def test_step_input_resolver_reads_measurement_dataset(tmp_path: Path) -> None:
    run_id = make_signal_run(tmp_path)
    storage = open_run_store(tmp_path)
    resolver = StepInputResolver(
        storage=storage,
        run_id=run_id,
        manifest=storage.read_manifest(run_id),
    )
    source = resolver.resolve_dataset(
        selector="raw-measurements",
        expected_kind="measurement_dataset",
        diagnostics=input_diagnostics(),
    )

    dataset = resolver.read_measurement_dataset(
        source,
        diagnostics=MeasurementDatasetInputDiagnostics(
            missing_code="missing",
            empty_code="empty",
            invalid_code="invalid",
            missing_schema_code="missing_schema",
            invalid_schema_code="invalid_schema",
            noun="measurement dataset input",
        ),
    )

    assert resolver.input_artifact_ids == ()
    assert resolver.input_dataset_ids == ("raw-measurements",)
    assert resolver.input_records == ()
    assert dataset.dataset_id == "raw-measurements"
    assert dataset.dataset_schema.dataset_id == "raw-measurements"
    assert dataset.dataset_schema.primary_coordinates == ["drive_frequency"]
    assert dataset.dataset_schema.primary_observables == ["signal"]
    assert [measurement.point_index for measurement in dataset.records] == [0, 1, 2]


def test_step_input_resolver_requires_measurement_dataset_schema(
    tmp_path: Path,
) -> None:
    run_id = make_signal_run(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    raw_dataset = manifest.datasets[0]
    raw_dataset.data_schema = None
    storage.write_manifest(manifest)
    resolver = StepInputResolver(
        storage=storage,
        run_id=run_id,
        manifest=storage.read_manifest(run_id),
    )
    source = resolver.resolve_dataset(
        selector="raw-measurements",
        expected_kind="measurement_dataset",
        diagnostics=input_diagnostics(),
    )

    with pytest.raises(ValidationFailed) as error:
        resolver.read_measurement_dataset(
            source,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="missing",
                empty_code="empty",
                invalid_code="invalid",
                missing_schema_code="missing_schema",
                invalid_schema_code="invalid_schema",
                noun="measurement dataset input",
            ),
        )

    assert error.value.diagnostics[0].code == "missing_schema"


def test_step_input_resolver_rejects_invalid_measurement_dataset_schema(
    tmp_path: Path,
) -> None:
    run_id = make_signal_run(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    raw_dataset = manifest.datasets[0]
    assert raw_dataset.data_schema is not None
    raw_dataset.data_schema["dataset_id"] = "other-measurements"
    storage.write_manifest(manifest)
    resolver = StepInputResolver(
        storage=storage,
        run_id=run_id,
        manifest=storage.read_manifest(run_id),
    )
    source = resolver.resolve_dataset(
        selector="raw-measurements",
        expected_kind="measurement_dataset",
        diagnostics=input_diagnostics(),
    )

    with pytest.raises(ValidationFailed) as error:
        resolver.read_measurement_dataset(
            source,
            diagnostics=MeasurementDatasetInputDiagnostics(
                missing_code="missing",
                empty_code="empty",
                invalid_code="invalid",
                missing_schema_code="missing_schema",
                invalid_schema_code="invalid_schema",
                noun="measurement dataset input",
            ),
        )

    assert error.value.diagnostics[0].code == "invalid_schema"
