"""Run access helpers for feature modules and tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from scopecat.kernel.errors import CheckFailed, DataIntegrityError, NotFound
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    StorageLocation,
    model_location,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.records.run import RunManifest
from scopecat.runs.refs import (
    artifact_content_ref,
    dataset_content_ref,
    record_content_ref,
)
from scopecat.runs.repository import RunRepository

type RunPayloadEntry = RunContentEntry
type _ContentRole = Literal["artifact", "dataset", "record"]

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


def upsert_contents(
    existing: Sequence[RunContentEntry], additions: Sequence[RunContentEntry]
) -> tuple[RunContentEntry, ...]:
    additions_by_id = {(entry.role, entry.id): entry for entry in additions}
    kept = [
        entry for entry in existing if (entry.role, entry.id) not in additions_by_id
    ]
    return (*kept, *additions)


def list_payload_entries(
    manifest: RunManifest,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunPayloadEntry, ...]:
    """Return user-facing datasets and artifacts matching simple filters."""
    return _filter_entries(
        (*manifest.datasets, *manifest.artifacts),
        kind=kind,
        metadata=metadata,
    )


def list_artifacts(
    manifest: RunManifest,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunContentEntry, ...]:
    """Return run artifact payloads matching simple typed index filters."""
    return _list_entries(manifest, "artifact", kind=kind, metadata=metadata)


def list_artifacts_by_kind(manifest: RunManifest, kind: str) -> list[RunContentEntry]:
    return list(_list_entries(manifest, "artifact", kind=kind))


def list_datasets(
    manifest: RunManifest,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunContentEntry, ...]:
    return _list_entries(manifest, "dataset", kind=kind, metadata=metadata)


def list_datasets_by_kind(manifest: RunManifest, kind: str) -> list[RunContentEntry]:
    return list(_list_entries(manifest, "dataset", kind=kind))


def list_records(
    manifest: RunManifest,
    *,
    kind: str | None = None,
) -> tuple[RunContentEntry, ...]:
    return _list_entries(manifest, "record", kind=kind)


def list_records_by_kind(manifest: RunManifest, kind: str) -> list[RunContentEntry]:
    return list(_list_entries(manifest, "record", kind=kind))


def list_artifacts_by_metadata(
    manifest: RunManifest, metadata: Mapping[str, object]
) -> list[RunContentEntry]:
    return list(_list_entries(manifest, "artifact", metadata=metadata))


def get_artifact_by_id(
    manifest: RunManifest, artifact_id: str
) -> RunContentEntry | None:
    return _get_entry(manifest, "artifact", artifact_id)


def get_dataset_by_id(manifest: RunManifest, dataset_id: str) -> RunContentEntry | None:
    return _get_entry(manifest, "dataset", dataset_id)


def get_record_by_id(manifest: RunManifest, record_id: str) -> RunContentEntry | None:
    return _get_entry(manifest, "record", record_id)


def artifact_storage_ref(artifact: RunContentEntry) -> str:
    return artifact_content_ref(artifact_id=artifact.id, kind=artifact.kind)


def dataset_storage_ref(dataset: RunContentEntry) -> str:
    return dataset_content_ref(
        dataset_id=dataset.id,
        kind=dataset.kind,
    )


def record_storage_ref(record: RunContentEntry) -> str:
    return record_content_ref(record_id=record.id, kind=record.kind)


def validate_run_entry_selector(
    value: str,
    *,
    code: str,
    message_prefix: str,
    location: ModelLocation,
) -> None:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise CheckFailed(
            [
                _access_problem(
                    code=code,
                    category=ProblemCategory.INVALID_INPUT,
                    message=message_prefix,
                    location=location,
                    details={"selector": value},
                )
            ]
        )


def resolve_artifact(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str,
    not_found_code: str,
    invalid_kind_code: str,
    path_escape_code: str,
    not_found_message: str,
    invalid_kind_message: str,
    path_escape_message: str,
    location: ModelLocation,
) -> RunContentEntry:
    return _resolve_entry(
        manifest=manifest,
        role="artifact",
        selector=selector,
        expected_kind=expected_kind,
        not_found_code=not_found_code,
        invalid_kind_code=invalid_kind_code,
        path_escape_code=path_escape_code,
        not_found_message=not_found_message,
        invalid_kind_message=invalid_kind_message,
        path_escape_message=path_escape_message,
        location=location,
    )


def resolve_dataset(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str,
    not_found_code: str,
    invalid_kind_code: str,
    path_escape_code: str,
    not_found_message: str,
    invalid_kind_message: str,
    path_escape_message: str,
    location: ModelLocation,
) -> RunContentEntry:
    return _resolve_entry(
        manifest=manifest,
        role="dataset",
        selector=selector,
        expected_kind=expected_kind,
        not_found_code=not_found_code,
        invalid_kind_code=invalid_kind_code,
        path_escape_code=path_escape_code,
        not_found_message=not_found_message,
        invalid_kind_message=invalid_kind_message,
        path_escape_message=path_escape_message,
        location=location,
    )


def find_artifact(manifest: RunManifest, selector: str) -> RunContentEntry | None:
    return _find_entry(manifest, "artifact", selector)


def find_dataset(manifest: RunManifest, selector: str) -> RunContentEntry | None:
    return _find_entry(manifest, "dataset", selector)


def find_record(manifest: RunManifest, selector: str) -> RunContentEntry | None:
    return _find_entry(manifest, "record", selector)


def require_artifact(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str | None = None,
) -> RunContentEntry:
    return _require_entry(manifest, "artifact", selector, expected_kind=expected_kind)


def require_dataset(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str | None = None,
) -> RunContentEntry:
    return _require_entry(manifest, "dataset", selector, expected_kind=expected_kind)


def require_record(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str | None = None,
) -> RunContentEntry:
    return _require_entry(manifest, "record", selector, expected_kind=expected_kind)


def read_artifact_bytes(
    *,
    storage: RunRepository,
    run_id: str,
    artifact: RunContentEntry,
) -> bytes:
    return storage.read_bytes(run_id, artifact_storage_ref(artifact))


def read_artifact_text(
    *,
    storage: RunRepository,
    run_id: str,
    artifact: RunContentEntry,
) -> str:
    return storage.read_text(run_id, artifact_storage_ref(artifact))


def read_artifact_json(
    *,
    storage: RunRepository,
    run_id: str,
    artifact: RunContentEntry,
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
                    category=ProblemCategory.DATA_INTEGRITY,
                    message="run artifact is not valid JSON",
                    location=ModelLocation(
                        root="run_manifest",
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
    record: RunContentEntry,
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
                    category=ProblemCategory.DATA_INTEGRITY,
                    message="run record is not valid JSON",
                    location=ModelLocation(
                        root="run_manifest",
                        path=("records", selector),
                    ),
                    details={"selector": selector},
                )
            ]
        ) from error


def read_data_table_artifact(
    *,
    storage: RunRepository,
    run_id: str,
    dataset: RunContentEntry,
) -> DataTableArtifact:
    selector = dataset.id
    ref = dataset_storage_ref(dataset)
    try:
        return DataTableArtifact.model_validate_json(storage.read_text(run_id, ref))
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _access_problem(
                    code="run.dataset_invalid_model",
                    category=ProblemCategory.DATA_INTEGRITY,
                    message="run dataset does not match the data-table schema",
                    location=StorageLocation(run_id=run_id, ref=ref),
                    details={"selector": selector, "model": "DataTableArtifact"},
                )
            ]
        ) from error


def read_data_array_artifact(
    *,
    storage: RunRepository,
    run_id: str,
    dataset: RunContentEntry,
) -> DataArrayArtifact:
    selector = dataset.id
    ref = dataset_storage_ref(dataset)
    try:
        return DataArrayArtifact.model_validate_json(storage.read_text(run_id, ref))
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _access_problem(
                    code="run.dataset_invalid_model",
                    category=ProblemCategory.DATA_INTEGRITY,
                    message="run dataset does not match the data-array schema",
                    location=StorageLocation(run_id=run_id, ref=ref),
                    details={"selector": selector, "model": "DataArrayArtifact"},
                )
            ]
        ) from error


def ensure_artifact_kind(
    artifact: RunContentEntry,
    *,
    expected_kind: str,
    code: str,
    message: str,
    location: ModelLocation,
) -> RunContentEntry:
    return _ensure_entry_kind(
        artifact,
        role="artifact",
        expected_kind=expected_kind,
        code=code,
        message=message,
        location=location,
    )


def ensure_dataset_kind(
    dataset: RunContentEntry,
    *,
    expected_kind: str,
    code: str,
    message: str,
    location: ModelLocation,
) -> RunContentEntry:
    return _ensure_entry_kind(
        dataset,
        role="dataset",
        expected_kind=expected_kind,
        code=code,
        message=message,
        location=location,
    )


def _role_plural(role: _ContentRole) -> str:
    return f"{role}s"


def _role_entries(
    manifest: RunManifest,
    role: _ContentRole,
) -> tuple[RunContentEntry, ...]:
    return tuple(entry for entry in manifest.contents if entry.role == role)


def _filter_entries(
    entries: Sequence[RunContentEntry],
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunContentEntry, ...]:
    return tuple(
        entry
        for entry in entries
        if (kind is None or entry.kind == kind)
        and (not metadata or _entry_metadata_matches(entry, metadata))
    )


def _list_entries(
    manifest: RunManifest,
    role: _ContentRole,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunContentEntry, ...]:
    return _filter_entries(
        _role_entries(manifest, role),
        kind=kind,
        metadata=metadata,
    )


def _get_entry(
    manifest: RunManifest,
    role: _ContentRole,
    entry_id: str,
) -> RunContentEntry | None:
    return next(
        (
            entry
            for entry in manifest.contents
            if entry.role == role and entry.id == entry_id
        ),
        None,
    )


def _find_entry(
    manifest: RunManifest,
    role: _ContentRole,
    selector: str,
) -> RunContentEntry | None:
    validate_run_entry_selector(
        selector,
        code=f"run.{role}_selector_path_escape",
        message_prefix=f"{role} selector must stay within the run namespace",
        location=model_location("run_access", role),
    )
    return _get_entry(manifest, role, selector)


def _require_entry(
    manifest: RunManifest,
    role: _ContentRole,
    selector: str,
    *,
    expected_kind: str | None,
) -> RunContentEntry:
    entry = _find_entry(manifest, role, selector)
    path = (_role_plural(role), selector)
    if entry is None:
        raise NotFound(
            [
                _access_problem(
                    code=f"run.{role}_not_found",
                    category=ProblemCategory.NOT_FOUND,
                    message=f"run {role} was not found",
                    location=ModelLocation(root="run_manifest", path=path),
                    details={"selector": selector},
                )
            ]
        )
    if expected_kind is not None and entry.kind != expected_kind:
        raise CheckFailed(
            [
                _access_problem(
                    code=f"run.{role}_kind_mismatch",
                    category=ProblemCategory.INVALID_INPUT,
                    message=f"run {role} does not have the requested kind",
                    location=ModelLocation(
                        root="run_manifest",
                        path=(*path, "kind"),
                    ),
                    details={
                        "selector": selector,
                        "actual_kind": entry.kind,
                        "expected_kind": expected_kind,
                    },
                )
            ]
        )
    return entry


def _resolve_entry(
    *,
    manifest: RunManifest,
    role: _ContentRole,
    selector: str,
    expected_kind: str,
    not_found_code: str,
    invalid_kind_code: str,
    path_escape_code: str,
    not_found_message: str,
    invalid_kind_message: str,
    path_escape_message: str,
    location: ModelLocation,
) -> RunContentEntry:
    validate_run_entry_selector(
        selector,
        code=path_escape_code,
        message_prefix=path_escape_message,
        location=location,
    )
    entry = _get_entry(manifest, role, selector)
    if entry is not None:
        return _ensure_entry_kind(
            entry,
            role=role,
            expected_kind=expected_kind,
            code=invalid_kind_code,
            message=invalid_kind_message,
            location=location,
        )
    raise NotFound(
        [
            _access_problem(
                code=not_found_code,
                category=ProblemCategory.NOT_FOUND,
                message=not_found_message,
                location=ModelLocation(
                    root="run_manifest",
                    path=(_role_plural(role), selector),
                ),
                details={"selector": selector, "expected_kind": expected_kind},
            )
        ]
    )


def _ensure_entry_kind(
    entry: RunContentEntry,
    *,
    role: _ContentRole,
    expected_kind: str,
    code: str,
    message: str,
    location: ModelLocation,
) -> RunContentEntry:
    if entry.kind != expected_kind:
        raise CheckFailed(
            [
                _access_problem(
                    code=code,
                    category=ProblemCategory.INVALID_INPUT,
                    message=message,
                    location=model_location(location.root, *location.path, "kind"),
                    details={
                        f"{role}_id": entry.id,
                        "actual_kind": entry.kind,
                        "expected_kind": expected_kind,
                    },
                )
            ]
        )
    return entry


def _entry_metadata_matches(
    entry: RunPayloadEntry, expected: Mapping[str, object]
) -> bool:
    return all(entry.metadata.get(key) == value for key, value in expected.items())


def _access_problem(
    *,
    code: str,
    category: ProblemCategory,
    message: str,
    location: ModelLocation | StorageLocation,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return Problem(
        code=code,
        impact=ProblemImpact.BLOCKING,
        category=category,
        phase=ProblemPhase.ANALYSIS,
        message=message,
        location=location,
        details={} if details is None else details,
    )
