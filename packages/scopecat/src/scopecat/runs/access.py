"""Run content access helpers."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import TypeAdapter, ValidationError

from scopecat.kernel.errors import DataIntegrityError
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
)
from scopecat.records.content import ContentEntry
from scopecat.runs.refs import (
    artifact_content_ref,
    dataset_content_ref,
    record_content_ref,
)
from scopecat.runs.repository import RunRepository

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


def artifact_storage_ref(artifact: ContentEntry) -> str:
    return artifact_content_ref(artifact_id=artifact.id, kind=artifact.kind)


def dataset_storage_ref(dataset: ContentEntry) -> str:
    return dataset_content_ref(
        dataset_id=dataset.id,
        kind=dataset.kind,
    )


def record_storage_ref(record: ContentEntry) -> str:
    return record_content_ref(record_id=record.id, kind=record.kind)


def read_artifact_bytes(
    *,
    storage: RunRepository,
    run_id: str,
    artifact: ContentEntry,
) -> bytes:
    return storage.read_bytes(run_id, artifact_storage_ref(artifact))


def read_dataset_bytes(
    *,
    storage: RunRepository,
    run_id: str,
    dataset: ContentEntry,
) -> bytes:
    return storage.read_bytes(run_id, dataset_storage_ref(dataset))


def read_artifact_text(
    *,
    storage: RunRepository,
    run_id: str,
    artifact: ContentEntry,
) -> str:
    return storage.read_text(run_id, artifact_storage_ref(artifact))


def read_artifact_json(
    *,
    storage: RunRepository,
    run_id: str,
    artifact: ContentEntry,
) -> Mapping[str, JsonValue]:
    selector = artifact.id
    try:
        return _JSON_OBJECT_ADAPTER.validate_json(
            read_artifact_text(
                storage=storage,
                run_id=run_id,
                artifact=artifact,
            )
        )
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _access_problem(
                    code="run.artifact_invalid_json",
                    message="run artifact is not valid JSON",
                    location=ModelLocation(
                        root="run_content",
                        path=("artifacts", selector),
                    ),
                    details={"selector": selector},
                )
            ]
        ) from error


def read_record_json(
    *,
    storage: RunRepository,
    run_id: str,
    record: ContentEntry,
) -> Mapping[str, JsonValue]:
    selector = record.id
    try:
        return _JSON_OBJECT_ADAPTER.validate_json(
            storage.read_text(run_id, record_storage_ref(record))
        )
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _access_problem(
                    code="run.record_invalid_json",
                    message="run record is not valid JSON",
                    location=ModelLocation(
                        root="run_content",
                        path=("records", selector),
                    ),
                    details={"selector": selector},
                )
            ]
        ) from error


def _access_problem(
    *,
    code: str,
    message: str,
    location: ModelLocation,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return Problem(
        code=code,
        phase=ProblemPhase.ANALYSIS,
        message=message,
        location=location,
        details={} if details is None else details,
    )
