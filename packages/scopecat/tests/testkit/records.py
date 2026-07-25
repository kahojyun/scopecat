from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from scopecat.measurements.results import MeasurementRecord
from scopecat.records.artifact import RunContentEntry


def read_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text())


def read_jsonl_models[ModelT: BaseModel](
    path: Path,
    model: type[ModelT],
) -> list[ModelT]:
    return [model.model_validate_json(line) for line in path.read_text().splitlines()]


def assert_model_round_trip[ModelT: BaseModel](
    record: ModelT,
    *,
    by_alias: bool = False,
) -> ModelT:
    restored = type(record).model_validate_json(
        record.model_dump_json(by_alias=by_alias)
    )
    assert restored == record
    return restored


def read_measurement_records(path: Path) -> list[MeasurementRecord]:
    return read_jsonl_models(path, MeasurementRecord)


def artifacts_by_id(artifacts: list[RunContentEntry]) -> dict[str, RunContentEntry]:
    return {artifact.id: artifact for artifact in artifacts}


def require_artifact(
    artifacts: list[RunContentEntry], artifact_id: str
) -> RunContentEntry:
    artifacts_by_key = artifacts_by_id(artifacts)
    return artifacts_by_key[artifact_id]


def require_artifact_by_kind(
    artifacts: list[RunContentEntry], kind: str
) -> RunContentEntry:
    matches = [artifact for artifact in artifacts if artifact.kind == kind]
    assert len(matches) == 1
    return matches[0]


def assert_artifact_ref(
    artifacts: list[RunContentEntry],
    artifact_id: str,
    *,
    kind: str | None = None,
) -> RunContentEntry:
    artifact = require_artifact(artifacts, artifact_id)
    if kind is not None:
        assert artifact.kind == kind
    return artifact
