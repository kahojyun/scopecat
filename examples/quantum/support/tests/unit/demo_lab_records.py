from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from scopecat.models.artifact import Artifact
from scopecat.results import MeasurementDatasetSchema, MeasurementRecord

type MeasurementRecordMutation = Callable[[MeasurementRecord], MeasurementRecord | None]
type MeasurementRecordPredicate = Callable[[MeasurementRecord], bool]


def read_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text())


def read_measurement_records(path: Path) -> list[MeasurementRecord]:
    return [
        MeasurementRecord.model_validate_json(line)
        for line in path.read_text().splitlines()
    ]


def write_measurement_records(
    path: Path, measurements: list[MeasurementRecord]
) -> None:
    path.write_text(
        "\n".join(json.dumps(record.model_dump(mode="json")) for record in measurements)
        + "\n"
    )


def mutate_measurement_records(
    path: Path,
    mutation: MeasurementRecordMutation,
) -> None:
    measurements = []
    for record in read_measurement_records(path):
        mutated = mutation(record)
        measurements.append(record if mutated is None else mutated)
    write_measurement_records(path, measurements)


def mutate_first_measurement_record(
    path: Path,
    mutation: MeasurementRecordMutation,
) -> None:
    measurements = read_measurement_records(path)
    first, *rest = measurements
    mutated = mutation(first)
    write_measurement_records(path, [first if mutated is None else mutated, *rest])


def mutate_matching_measurement_records(
    path: Path,
    predicate: MeasurementRecordPredicate,
    mutation: MeasurementRecordMutation,
) -> None:
    mutate_measurement_records(
        path,
        lambda record: mutation(record) if predicate(record) else record,
    )


def without_observable(
    record: MeasurementRecord,
    observable_id: str,
) -> MeasurementRecord:
    observables = dict(record.observables)
    observables.pop(observable_id)
    return record.model_copy(update={"observables": observables}, deep=True)


def without_coordinate(
    record: MeasurementRecord,
    coordinate_id: str,
) -> MeasurementRecord:
    coordinates = dict(record.coordinates)
    coordinates.pop(coordinate_id)
    return record.model_copy(update={"coordinates": coordinates}, deep=True)


def with_observable_unit(
    record: MeasurementRecord,
    observable_id: str,
    unit: str,
) -> MeasurementRecord:
    observables = dict(record.observables)
    observables[observable_id] = observables[observable_id].model_copy(
        update={"unit": unit},
    )
    return record.model_copy(update={"observables": observables}, deep=True)


def with_observable_copied_from(
    record: MeasurementRecord,
    *,
    target_observable_id: str,
    source_observable_id: str,
) -> MeasurementRecord:
    observables = dict(record.observables)
    observables[target_observable_id] = observables[source_observable_id]
    return record.model_copy(update={"observables": observables}, deep=True)


def assert_measurement_dataset_schema(
    metadata: dict[str, Any],
    *,
    dataset_id: str,
    dataset_role: str,
    size: int,
    coordinates: dict[str, str],
    observables: dict[str, str],
    dimension_id: str = "point",
    dimension_kind: str = "point",
    dimension_label: str | None = "Point",
    dimension_unit: str | None = None,
    source_step: str | None = None,
    source_artifact_ids: list[str] | None = None,
) -> None:
    assert metadata["dataset_role"] == dataset_role
    assert metadata["record_schema"] == "scopecat.measurement_record.v0"
    if source_step is not None:
        assert metadata["source_step"] == source_step
    if source_artifact_ids is not None:
        assert metadata["source_artifact_ids"] == source_artifact_ids

    schema = MeasurementDatasetSchema.model_validate(metadata["dataset_schema"])
    assert schema.schema_version == "scopecat.measurement_dataset_schema.v0"
    assert schema.dataset_id == dataset_id
    assert schema.dataset_role == dataset_role
    assert schema.record_schema == "scopecat.measurement_record.v0"
    assert len(schema.dimensions) == 1
    dimension = schema.dimensions[0]
    assert dimension.id == dimension_id
    assert dimension.kind == dimension_kind
    assert dimension.label == dimension_label
    assert dimension.size == size
    assert dimension.unit == dimension_unit
    assert dimension.metadata == {}
    assert schema.primary_coordinates == list(coordinates)
    assert schema.primary_observables == list(observables)

    variables = {variable.id: variable for variable in schema.variables}
    assert set(variables) == set(coordinates) | set(observables)
    for variable_id, unit in coordinates.items():
        assert variables[variable_id].role == "coordinate"
        assert variables[variable_id].unit == unit
        assert variables[variable_id].dims == [dimension_id]
        assert variables[variable_id].shape == [size]
    for variable_id, unit in observables.items():
        assert variables[variable_id].role == "observable"
        assert variables[variable_id].unit == unit
        assert variables[variable_id].dims == [dimension_id]
        assert variables[variable_id].shape == [size]


def assert_artifact_ref(
    artifacts: list[Artifact],
    artifact_id: str,
    *,
    kind: str | None = None,
    path: str | None = None,
) -> Artifact:
    refs = {artifact.id: artifact for artifact in artifacts}
    artifact = refs[artifact_id]
    if kind is not None:
        assert artifact.kind == kind
    if path is not None:
        assert artifact.path == path
    return artifact
