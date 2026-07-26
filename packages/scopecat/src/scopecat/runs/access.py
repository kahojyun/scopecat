"""Run content access helpers."""

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
    ProblemPhase,
)
from scopecat.records.artifact import RunContentEntry
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


def list_records(
    manifest: RunManifest,
    *,
    kind: str | None = None,
) -> tuple[RunContentEntry, ...]:
    return _list_entries(manifest, "record", kind=kind)


def artifact_storage_ref(artifact: RunContentEntry) -> str:
    return artifact_content_ref(artifact_id=artifact.id, kind=artifact.kind)


def dataset_storage_ref(dataset: RunContentEntry) -> str:
    return dataset_content_ref(
        dataset_id=dataset.id,
        kind=dataset.kind,
    )


def record_storage_ref(record: RunContentEntry) -> str:
    return record_content_ref(record_id=record.id, kind=record.kind)


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
                    message="run record is not valid JSON",
                    location=ModelLocation(
                        root="run_manifest",
                        path=("records", selector),
                    ),
                    details={"selector": selector},
                )
            ]
        ) from error


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
    relative = PurePosixPath(selector)
    if relative.is_absolute() or ".." in relative.parts:
        raise CheckFailed(
            [
                _access_problem(
                    code=f"run.{role}_selector_path_escape",
                    message=f"{role} selector must stay within the run namespace",
                    location=ModelLocation(root="run_access", path=(role,)),
                    details={"selector": selector},
                )
            ]
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


def _entry_metadata_matches(
    entry: RunPayloadEntry, expected: Mapping[str, object]
) -> bool:
    return all(entry.metadata.get(key) == value for key, value in expected.items())


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
