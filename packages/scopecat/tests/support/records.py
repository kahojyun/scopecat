from __future__ import annotations

from pathlib import Path
from typing import cast

from pydantic import BaseModel

from scopecat.models.artifact import Artifact
from scopecat.results import MeasurementRecord


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
    schema_version: str | None = None,
    by_alias: bool = False,
) -> ModelT:
    restored = cast(
        ModelT,
        type(record).model_validate_json(record.model_dump_json(by_alias=by_alias)),
    )
    assert restored == record
    if schema_version is not None:
        assert restored.model_dump(mode="json")["schema_version"] == schema_version
    return restored


def read_measurement_records(path: Path) -> list[MeasurementRecord]:
    return read_jsonl_models(path, MeasurementRecord)


def artifact_refs_by_id(artifacts: list[Artifact]) -> dict[str, Artifact]:
    return {artifact.id: artifact for artifact in artifacts}


def require_artifact(artifacts: list[Artifact], artifact_id: str) -> Artifact:
    refs = artifact_refs_by_id(artifacts)
    return refs[artifact_id]


def require_artifact_by_kind(artifacts: list[Artifact], kind: str) -> Artifact:
    matches = [artifact for artifact in artifacts if artifact.kind == kind]
    assert len(matches) == 1
    return matches[0]


def assert_artifact_ref(
    artifacts: list[Artifact],
    artifact_id: str,
    *,
    kind: str | None = None,
    path: str | None = None,
) -> Artifact:
    artifact = require_artifact(artifacts, artifact_id)
    if kind is not None:
        assert artifact.kind == kind
    if path is not None:
        assert artifact.path == path
    return artifact
