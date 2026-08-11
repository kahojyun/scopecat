from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from scopecat.records.artifact import RunContentEntry


def read_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    return model.model_validate_json(path.read_text())


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


def artifacts_by_id(artifacts: list[RunContentEntry]) -> dict[str, RunContentEntry]:
    return {artifact.id: artifact for artifact in artifacts}


def require_artifact(
    artifacts: list[RunContentEntry], artifact_id: str
) -> RunContentEntry:
    artifacts_by_key = artifacts_by_id(artifacts)
    return artifacts_by_key[artifact_id]
