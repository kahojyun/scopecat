"""Run access helpers for feature modules and tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError

from scopecat._storage.local import LocalRunStore
from scopecat._storage.refs import (
    artifact_content_ref,
    dataset_content_ref,
    record_content_ref,
)
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.models.run import RunManifest

RunStore = LocalRunStore
type RunPayloadEntry = RunArtifactEntry | RunDatasetEntry
type RunManifestEntry = RunArtifactEntry | RunDatasetEntry | RunRecordEntry


def open_run_store(workspace: str | Path) -> LocalRunStore:
    return LocalRunStore(workspace)


def load_config_profile_snapshot(
    *, storage: LocalRunStore, run_id: str
) -> ConfigProfileSnapshot:
    return storage.read_config_profile_snapshot(run_id)


def append_unique(values: list[str], value: str) -> list[str]:
    if value in values:
        return values
    return [*values, value]


def _upsert_entries[TRef: RunManifestEntry](
    existing: list[TRef], additions: list[TRef]
) -> list[TRef]:
    additions_by_id = {entry.id: entry for entry in additions}
    kept = [entry for entry in existing if entry.id not in additions_by_id]
    return [*kept, *additions]


def upsert_artifacts(
    existing: list[RunArtifactEntry], additions: list[RunArtifactEntry]
) -> list[RunArtifactEntry]:
    return _upsert_entries(existing, additions)


def upsert_datasets(
    existing: list[RunDatasetEntry], additions: list[RunDatasetEntry]
) -> list[RunDatasetEntry]:
    return _upsert_entries(existing, additions)


def upsert_records(
    existing: list[RunRecordEntry], additions: list[RunRecordEntry]
) -> list[RunRecordEntry]:
    return _upsert_entries(existing, additions)


def list_payload_entries(
    manifest: RunManifest,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunPayloadEntry, ...]:
    """Return user-facing datasets and artifacts matching simple filters."""
    entries: list[RunPayloadEntry] = [*manifest.datasets, *manifest.artifacts]
    if kind is not None:
        entries = [entry for entry in entries if entry.kind == kind]
    if metadata:
        entries = [
            entry for entry in entries if _entry_metadata_matches(entry, metadata)
        ]
    return tuple(entries)


def list_artifacts(
    manifest: RunManifest,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunArtifactEntry, ...]:
    """Return run artifact payloads matching simple typed index filters."""
    artifacts = manifest.artifacts
    if kind is not None:
        artifacts = list_artifacts_by_kind(manifest, kind)
    if metadata:
        artifacts = [
            artifact
            for artifact in artifacts
            if _entry_metadata_matches(artifact, metadata)
        ]
    return tuple(artifacts)


def list_artifacts_by_kind(manifest: RunManifest, kind: str) -> list[RunArtifactEntry]:
    return [artifact for artifact in manifest.artifacts if artifact.kind == kind]


def list_datasets(
    manifest: RunManifest,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[RunDatasetEntry, ...]:
    datasets = manifest.datasets
    if kind is not None:
        datasets = list_datasets_by_kind(manifest, kind)
    if metadata:
        datasets = [
            dataset
            for dataset in datasets
            if _entry_metadata_matches(dataset, metadata)
        ]
    return tuple(datasets)


def list_datasets_by_kind(manifest: RunManifest, kind: str) -> list[RunDatasetEntry]:
    return [dataset for dataset in manifest.datasets if dataset.kind == kind]


def list_records(
    manifest: RunManifest,
    *,
    kind: str | None = None,
) -> tuple[RunRecordEntry, ...]:
    records = manifest.records
    if kind is not None:
        records = list_records_by_kind(manifest, kind)
    return tuple(records)


def list_records_by_kind(manifest: RunManifest, kind: str) -> list[RunRecordEntry]:
    return [record for record in manifest.records if record.kind == kind]


def list_artifacts_by_metadata(
    manifest: RunManifest, metadata: Mapping[str, object]
) -> list[RunArtifactEntry]:
    return [
        artifact
        for artifact in manifest.artifacts
        if _entry_metadata_matches(artifact, metadata)
    ]


def get_artifact_by_id(
    manifest: RunManifest, artifact_id: str
) -> RunArtifactEntry | None:
    for artifact in manifest.artifacts:
        if artifact.id == artifact_id:
            return artifact
    return None


def get_dataset_by_id(manifest: RunManifest, dataset_id: str) -> RunDatasetEntry | None:
    for dataset in manifest.datasets:
        if dataset.id == dataset_id:
            return dataset
    return None


def get_record_by_id(manifest: RunManifest, record_id: str) -> RunRecordEntry | None:
    for record in manifest.records:
        if record.id == record_id:
            return record
    return None


def storage_ref(ref: RunManifestEntry) -> str:
    if isinstance(ref, RunArtifactEntry):
        return artifact_storage_ref(ref)
    if isinstance(ref, RunDatasetEntry):
        return dataset_storage_ref(ref)
    return record_storage_ref(ref)


def artifact_storage_ref(artifact: RunArtifactEntry) -> str:
    return artifact_content_ref(artifact_id=artifact.id, kind=artifact.kind)


def dataset_storage_ref(dataset: RunDatasetEntry) -> str:
    return dataset_content_ref(
        dataset_id=dataset.id,
        kind=dataset.kind,
    )


def record_storage_ref(record: RunRecordEntry) -> str:
    return record_content_ref(record_id=record.id, kind=record.kind)


def validate_run_entry_selector(
    value: str,
    *,
    code: str,
    message_prefix: str,
    path: str,
) -> None:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    code,
                    f"{message_prefix}: {value}",
                    path,
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
    diagnostic_path: str,
) -> RunArtifactEntry:
    validate_run_entry_selector(
        selector,
        code=path_escape_code,
        message_prefix=path_escape_message,
        path=diagnostic_path,
    )
    for artifact in manifest.artifacts:
        if artifact.id == selector:
            return ensure_artifact_kind(
                artifact,
                expected_kind=expected_kind,
                code=invalid_kind_code,
                message=invalid_kind_message,
                path=diagnostic_path,
            )
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                not_found_code,
                f"{not_found_message}: {selector}",
                diagnostic_path,
            )
        ]
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
    diagnostic_path: str,
) -> RunDatasetEntry:
    validate_run_entry_selector(
        selector,
        code=path_escape_code,
        message_prefix=path_escape_message,
        path=diagnostic_path,
    )
    for dataset in manifest.datasets:
        if dataset.id == selector:
            return ensure_dataset_kind(
                dataset,
                expected_kind=expected_kind,
                code=invalid_kind_code,
                message=invalid_kind_message,
                path=diagnostic_path,
            )
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                not_found_code,
                f"{not_found_message}: {selector}",
                diagnostic_path,
            )
        ]
    )


def find_artifact(manifest: RunManifest, selector: str) -> RunArtifactEntry | None:
    validate_run_entry_selector(
        selector,
        code="artifact_selector_path_escape",
        message_prefix="artifact selector escapes run directory",
        path="artifact",
    )
    artifact = get_artifact_by_id(manifest, selector)
    if artifact is not None:
        return artifact
    return None


def find_dataset(manifest: RunManifest, selector: str) -> RunDatasetEntry | None:
    validate_run_entry_selector(
        selector,
        code="dataset_selector_path_escape",
        message_prefix="dataset selector escapes run directory",
        path="dataset",
    )
    dataset = get_dataset_by_id(manifest, selector)
    if dataset is not None:
        return dataset
    return None


def find_record(manifest: RunManifest, selector: str) -> RunRecordEntry | None:
    validate_run_entry_selector(
        selector,
        code="record_selector_path_escape",
        message_prefix="record selector escapes run directory",
        path="record",
    )
    record = get_record_by_id(manifest, selector)
    if record is not None:
        return record
    return None


def require_artifact(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str | None = None,
) -> RunArtifactEntry:
    artifact = find_artifact(manifest, selector)
    if artifact is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "artifact_not_found",
                    f"artifact not found: {selector}",
                    "artifact",
                )
            ]
        )
    if expected_kind is not None and artifact.kind != expected_kind:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "artifact_kind_mismatch",
                    f"artifact {selector} has kind {artifact.kind}, "
                    f"expected {expected_kind}",
                    "artifact",
                )
            ]
        )
    return artifact


def require_dataset(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str | None = None,
) -> RunDatasetEntry:
    dataset = find_dataset(manifest, selector)
    if dataset is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "dataset_not_found",
                    f"dataset not found: {selector}",
                    "dataset",
                )
            ]
        )
    if expected_kind is not None and dataset.kind != expected_kind:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "dataset_kind_mismatch",
                    f"dataset {selector} has kind {dataset.kind}, "
                    f"expected {expected_kind}",
                    "dataset",
                )
            ]
        )
    return dataset


def require_record(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str | None = None,
) -> RunRecordEntry:
    record = find_record(manifest, selector)
    if record is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "record_not_found",
                    f"record not found: {selector}",
                    "record",
                )
            ]
        )
    if expected_kind is not None and record.kind != expected_kind:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "record_kind_mismatch",
                    f"record {selector} has kind {record.kind}, "
                    f"expected {expected_kind}",
                    "record",
                )
            ]
        )
    return record


def read_artifact_bytes(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str,
    expected_kind: str | None = None,
) -> bytes:
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return storage.ref_path(run_id, artifact_storage_ref(artifact)).read_bytes()


def read_artifact_text(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str,
    expected_kind: str | None = None,
) -> str:
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return storage.ref_path(run_id, artifact_storage_ref(artifact)).read_text()


def read_artifact_json(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str,
    expected_kind: str | None = None,
) -> Any:
    try:
        return json.loads(
            read_artifact_text(
                storage=storage,
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
            )
        )
    except json.JSONDecodeError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "artifact_invalid_json",
                    f"artifact is not valid JSON: {selector}",
                    "artifact",
                )
            ]
        ) from error


def read_record_text(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str,
    expected_kind: str | None = None,
) -> str:
    record = require_record(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return storage.ref_path(run_id, record_storage_ref(record)).read_text()


def read_record_json(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str,
    expected_kind: str | None = None,
) -> Any:
    try:
        return json.loads(
            read_record_text(
                storage=storage,
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
            )
        )
    except json.JSONDecodeError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "record_invalid_json",
                    f"record is not valid JSON: {selector}",
                    "record",
                )
            ]
        ) from error


def read_model_artifact[TModel: BaseModel](
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str,
    model_type: type[TModel],
    expected_kind: str | None = None,
) -> TModel:
    try:
        return model_type.model_validate(
            read_artifact_json(
                storage=storage,
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
            )
        )
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "artifact_invalid_model",
                    f"artifact does not match {model_type.__name__}: {selector}",
                    "artifact",
                )
            ]
        ) from error


def read_model_record[TModel: BaseModel](
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str,
    model_type: type[TModel],
    expected_kind: str | None = None,
) -> TModel:
    try:
        return model_type.model_validate(
            read_record_json(
                storage=storage,
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
            )
        )
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "record_invalid_model",
                    f"record does not match {model_type.__name__}: {selector}",
                    "record",
                )
            ]
        ) from error


def read_data_table_artifact(
    *, storage: LocalRunStore, run_id: str, selector: str
) -> DataTableArtifact:
    dataset = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="data_table",
    )
    try:
        return DataTableArtifact.model_validate_json(
            storage.ref_path(run_id, dataset_storage_ref(dataset)).read_text()
        )
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "dataset_invalid_model",
                    f"dataset does not match DataTableArtifact: {selector}",
                    "dataset",
                )
            ]
        ) from error


def read_data_array_artifact(
    *, storage: LocalRunStore, run_id: str, selector: str
) -> DataArrayArtifact:
    dataset = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="data_array",
    )
    try:
        return DataArrayArtifact.model_validate_json(
            storage.ref_path(run_id, dataset_storage_ref(dataset)).read_text()
        )
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "dataset_invalid_model",
                    f"dataset does not match DataArrayArtifact: {selector}",
                    "dataset",
                )
            ]
        ) from error


def ensure_artifact_kind(
    artifact: RunArtifactEntry,
    *,
    expected_kind: str,
    code: str,
    message: str,
    path: str,
) -> RunArtifactEntry:
    if artifact.kind != expected_kind:
        raise ValidationFailed([_diagnostic("error", code, message, path)])
    return artifact


def ensure_dataset_kind(
    dataset: RunDatasetEntry,
    *,
    expected_kind: str,
    code: str,
    message: str,
    path: str,
) -> RunDatasetEntry:
    if dataset.kind != expected_kind:
        raise ValidationFailed([_diagnostic("error", code, message, path)])
    return dataset


def _entry_metadata_matches(
    entry: RunPayloadEntry, expected: Mapping[str, object]
) -> bool:
    return all(entry.metadata.get(key) == value for key, value in expected.items())


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
