"""Run access helpers for feature modules and tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ValidationError

from scopecat._storage.local import LocalRunStore
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.experiments import PlanSnapshot
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.models.run import RunManifest

RunStore = LocalRunStore


def open_run_store(workspace: str | Path) -> LocalRunStore:
    return LocalRunStore(workspace)


def load_config_profile_snapshot(
    *, storage: LocalRunStore, run_id: str
) -> ConfigProfileSnapshot:
    return storage.read_config_profile_snapshot(run_id)


def load_plan_snapshot(*, storage: LocalRunStore, run_id: str) -> PlanSnapshot:
    return storage.read_plan_snapshot(run_id)


def append_unique(values: list[str], value: str) -> list[str]:
    if value in values:
        return values
    return [*values, value]


def upsert_artifacts(
    existing: list[Artifact], additions: list[Artifact]
) -> list[Artifact]:
    additions_by_id = {artifact.id: artifact for artifact in additions}
    kept = [artifact for artifact in existing if artifact.id not in additions_by_id]
    return [*kept, *additions]


def list_artifacts(
    manifest: RunManifest,
    *,
    kind: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> tuple[Artifact, ...]:
    """Return manifest artifacts matching simple typed index filters."""
    artifacts = manifest.artifact_refs
    if kind is not None:
        artifacts = list_artifacts_by_kind(manifest, kind)
    if metadata:
        artifacts = [
            artifact
            for artifact in artifacts
            if _artifact_metadata_matches(artifact, metadata)
        ]
    return tuple(artifacts)


def list_artifacts_by_kind(manifest: RunManifest, kind: str) -> list[Artifact]:
    return [artifact for artifact in manifest.artifact_refs if artifact.kind == kind]


def list_artifacts_by_metadata(
    manifest: RunManifest, metadata: Mapping[str, object]
) -> list[Artifact]:
    return [
        artifact
        for artifact in manifest.artifact_refs
        if _artifact_metadata_matches(artifact, metadata)
    ]


def get_artifact_by_id(manifest: RunManifest, artifact_id: str) -> Artifact | None:
    for artifact in manifest.artifact_refs:
        if artifact.id == artifact_id:
            return artifact
    return None


def validate_run_ref_selector(
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
) -> Artifact:
    validate_run_ref_selector(
        selector,
        code=path_escape_code,
        message_prefix=path_escape_message,
        path=diagnostic_path,
    )
    for artifact in manifest.artifact_refs:
        if artifact.id == selector:
            return ensure_artifact_kind(
                artifact,
                expected_kind=expected_kind,
                code=invalid_kind_code,
                message=invalid_kind_message,
                path=diagnostic_path,
            )
    for artifact in manifest.artifact_refs:
        if artifact.path == selector:
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


def find_artifact(manifest: RunManifest, selector: str) -> Artifact | None:
    validate_run_ref_selector(
        selector,
        code="artifact_selector_path_escape",
        message_prefix="artifact selector escapes run directory",
        path="artifact",
    )
    artifact = get_artifact_by_id(manifest, selector)
    if artifact is not None:
        return artifact
    for artifact in manifest.artifact_refs:
        if artifact.path == selector:
            return artifact
    return None


def require_artifact(
    *,
    manifest: RunManifest,
    selector: str,
    expected_kind: str | None = None,
) -> Artifact:
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
    return storage.ref_path(run_id, artifact.path).read_bytes()


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
    return storage.ref_path(run_id, artifact.path).read_text()


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


def read_data_table_artifact(
    *, storage: LocalRunStore, run_id: str, selector: str
) -> DataTableArtifact:
    return read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=selector,
        model_type=DataTableArtifact,
        expected_kind="data_table",
    )


def read_data_array_artifact(
    *, storage: LocalRunStore, run_id: str, selector: str
) -> DataArrayArtifact:
    return read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=selector,
        model_type=DataArrayArtifact,
        expected_kind="data_array",
    )


def ensure_artifact_kind(
    artifact: Artifact,
    *,
    expected_kind: str,
    code: str,
    message: str,
    path: str,
) -> Artifact:
    if artifact.kind != expected_kind:
        raise ValidationFailed([_diagnostic("error", code, message, path)])
    return artifact


def _artifact_metadata_matches(
    artifact: Artifact, expected: Mapping[str, object]
) -> bool:
    return all(artifact.metadata.get(key) == value for key, value in expected.items())


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
