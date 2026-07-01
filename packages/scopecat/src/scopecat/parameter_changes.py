"""Parameter change set inspection and optional decision helpers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat._planning_parameter_patches import ParameterPatchSpec
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.ids import artifact_slug
from scopecat.models.artifact import Artifact
from scopecat.models.parameter import (
    ParameterChangeSet,
    ParameterPatch,
    ParameterPatchValue,
)
from scopecat.models.run import RunManifest, utc_now
from scopecat.relations import ScalarExpr
from scopecat.runs import RunStore, list_artifacts, open_run_store

ParameterChangeReviewState = Literal["approved", "rejected"]
ParameterChangeDecision = Literal["approved", "rejected", "invalidated"]
SAFE_PARAMETER_CHANGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

type AnalysisParameterPatch = ParameterPatch | ParameterPatchSpec


class ParameterChangeSetView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_run_id: str
    reason: str
    confidence: float | None = None
    patch_count: int
    patches: list[ParameterPatch] = Field(default_factory=list)
    path: str


class ParameterChangeDecisionRecord(BaseModel):
    """Durable optional decision record for a parameter change set."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.parameter_change_decision_record.v1"
    run_id: str
    change_set_id: str
    change_set_artifact_id: str
    decision: ParameterChangeDecision
    actor: str
    note: str = ""
    related_refs: list[str] = Field(default_factory=list)
    decided_at: datetime = Field(default_factory=utc_now)


def is_safe_parameter_change_id(value: str) -> bool:
    return SAFE_PARAMETER_CHANGE_ID_RE.fullmatch(value) is not None


def parameter_change_set_from_analysis_patches(
    *,
    source_run_id: str,
    analysis_title: str,
    change_id: str,
    patches: Sequence[AnalysisParameterPatch],
    reason: str,
    confidence: float | None,
) -> ParameterChangeSet:
    selected_id = artifact_slug(change_id, fallback="analysis")
    if not is_safe_parameter_change_id(selected_id):
        msg = f"parameter change id is not safe: {selected_id}"
        raise ValueError(msg)
    selected_reason = reason or (
        f"Parameter change {selected_id!r} from analysis {analysis_title!r}."
    )
    concrete_patches = [_concrete_patch(patch) for patch in patches]
    return ParameterChangeSet(
        id=selected_id,
        source_run_id=source_run_id,
        reason=selected_reason,
        patches=concrete_patches,
        confidence=confidence,
    )


def list_parameter_changes(
    *, run_id: str, workspace: str | Path
) -> list[ParameterChangeSetView]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    changes: list[ParameterChangeSetView] = []
    for change_artifact in _change_set_artifacts(manifest):
        change_set, resolved_ref = _load_ref(
            storage=storage,
            run_id=run_id,
            change_set_record_ref=change_artifact.path,
        )
        changes.append(
            ParameterChangeSetView(
                id=change_set.id,
                source_run_id=change_set.source_run_id,
                reason=change_set.reason,
                confidence=change_set.confidence,
                patch_count=len(change_set.patches),
                patches=list(change_set.patches),
                path=resolved_ref,
            )
        )
    return changes


def load_parameter_change(
    *, run_id: str, selector: str, workspace: str | Path
) -> ParameterChangeSet:
    storage = open_run_store(workspace)
    _change_set, change_artifact = _resolve_change_set_ref(
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    change_set, _resolved_ref = _load_ref(
        storage=storage,
        run_id=run_id,
        change_set_record_ref=change_artifact.path,
    )
    return change_set


def review_parameter_changes(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    state: ParameterChangeReviewState,
    reviewer: str,
    note: str = "",
) -> ParameterChangeDecisionRecord:
    return record_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        workspace=workspace,
        decision=state,
        actor=reviewer,
        note=note,
    )


def invalidate_parameter_change(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    reason: str,
    invalidated_by: str,
    invalidated_by_refs: list[str] | None = None,
) -> ParameterChangeDecisionRecord:
    related_refs = list(invalidated_by_refs or [])
    for ref in related_refs:
        _validate_selector_path(ref)
    return record_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        workspace=workspace,
        decision="invalidated",
        actor=invalidated_by,
        note=reason,
        related_refs=related_refs,
    )


def record_parameter_change_decision(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    decision: ParameterChangeDecision,
    actor: str,
    note: str = "",
    related_refs: list[str] | None = None,
) -> ParameterChangeDecisionRecord:
    storage = open_run_store(workspace)
    change_set, change_artifact = _resolve_change_set_ref(
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    record_ref = parameter_change_decision_ref(change_set.id)
    record_path = storage.ref_path(run_id, record_ref)
    if record_path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "parameter_change_decision_exists",
                    f"parameter change decision already exists: {change_set.id}",
                    "parameter_change",
                )
            ]
        )
    record = ParameterChangeDecisionRecord(
        run_id=run_id,
        change_set_id=change_set.id,
        change_set_artifact_id=change_artifact.id,
        decision=decision,
        actor=actor,
        note=note,
        related_refs=list(related_refs or []),
    )
    storage.write_model(run_id, record_ref, record)

    manifest = storage.read_manifest(run_id)
    write_manifest_artifacts(
        storage=storage,
        manifest=manifest,
        artifacts=[
            Artifact(
                id=f"{change_set.id}-decision",
                kind="parameter_change_decision_record",
                path=record_ref,
                media_type="application/json",
            )
        ],
    )
    return record


def parameter_change_decision_ref(change_set_id: str) -> str:
    return f"reviews/{change_set_id}.parameter-change-decision.json"


def parameter_change_record_ref(change_set_id: str) -> str:
    return f"parameter-changes/{change_set_id}.json"


def parameter_change_set_artifact(
    *,
    change: ParameterChangeSet,
    source: str,
    analysis_title: str | None = None,
    analysis_key: str | None = None,
) -> Artifact:
    metadata: dict[str, str] = {"source": source}
    if analysis_title is not None:
        metadata["analysis_title"] = analysis_title
    if analysis_key is not None:
        metadata["analysis_key"] = analysis_key
    return Artifact(
        id=change.id,
        kind="parameter_change_set",
        path=parameter_change_record_ref(change.id),
        media_type="application/json",
        metadata=metadata,
    )


def _concrete_patch(patch: AnalysisParameterPatch) -> ParameterPatch:
    if isinstance(patch, ParameterPatch):
        return patch
    if patch.kind == "set_scalar":
        return ParameterPatch(
            kind=patch.kind,
            parameter_id=_required(patch.parameter_id),
            value=_literal_expr_value(_required(patch.value)),
        )
    if patch.kind == "update_rows":
        return ParameterPatch(
            kind=patch.kind,
            table_id=_required(patch.table_id),
            key={
                name: _literal_expr_value(expr)
                for name, expr in _required(patch.key).items()
            },
            values={
                name: _literal_expr_value(expr)
                for name, expr in _required(patch.values).items()
            },
        )
    if patch.kind == "insert_rows":
        return ParameterPatch(
            kind=patch.kind,
            table_id=_required(patch.table_id),
            rows=[
                {name: _literal_expr_value(expr) for name, expr in row.items()}
                for row in _required(patch.rows)
            ],
        )
    if patch.kind == "delete_rows":
        return ParameterPatch(
            kind=patch.kind,
            table_id=_required(patch.table_id),
            key={
                name: _literal_expr_value(expr)
                for name, expr in _required(patch.key).items()
            },
        )
    msg = f"unsupported parameter patch kind: {patch.kind}"
    raise ValueError(msg)


def _literal_expr_value(expr: ScalarExpr) -> ParameterPatchValue:
    if expr.kind != "literal":
        msg = (
            "analysis parameter changes only accept literal patch values; "
            f"got {expr.kind!r}"
        )
        raise ValueError(msg)
    return expr.value


def _resolve_change_set_ref(
    *, storage: RunStore, run_id: str, selector: str
) -> tuple[ParameterChangeSet, Artifact]:
    manifest = storage.read_manifest(run_id)
    _validate_selector_path(selector)
    for change_artifact in _change_set_artifacts(manifest):
        change_set, _resolved_ref = _load_ref(
            storage=storage,
            run_id=run_id,
            change_set_record_ref=change_artifact.path,
        )
        if change_set.id == selector or change_artifact.id == selector:
            return change_set, change_artifact
    for change_artifact in _change_set_artifacts(manifest):
        if change_artifact.path == selector:
            change_set, _resolved_ref = _load_ref(
                storage=storage,
                run_id=run_id,
                change_set_record_ref=change_artifact.path,
            )
            return change_set, change_artifact
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "parameter_change_not_found",
                f"parameter change not found: {selector}",
                "parameter_change",
            )
        ]
    )


def _load_ref(
    *, storage: RunStore, run_id: str, change_set_record_ref: str
) -> tuple[ParameterChangeSet, str]:
    path = _change_set_path(
        storage=storage,
        run_id=run_id,
        change_set_record_ref=change_set_record_ref,
    )
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "parameter_change_not_found",
                    f"parameter change not found: {change_set_record_ref}",
                    "parameter_change",
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "parameter_change_is_directory",
                    f"parameter change is a directory: {change_set_record_ref}",
                    "parameter_change",
                )
            ]
        )
    try:
        change_set = ParameterChangeSet.model_validate_json(path.read_text())
        return change_set, change_set_record_ref
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_parameter_change",
                    (
                        "parameter change is not a valid parameter change set: "
                        f"{change_set_record_ref}"
                    ),
                    "parameter_change",
                )
            ]
        ) from error


def _change_set_artifacts(manifest: RunManifest) -> tuple[Artifact, ...]:
    return list_artifacts(manifest, kind="parameter_change_set")


def _change_set_path(
    *, storage: RunStore, run_id: str, change_set_record_ref: str
) -> Path:
    _validate_selector_path(change_set_record_ref)
    return storage.ref_path(run_id, change_set_record_ref)


def _validate_selector_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "parameter_change_path_escape",
                    f"parameter change path escapes run directory: {value}",
                    "parameter_change",
                )
            ]
        )


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value


__all__ = [
    "AnalysisParameterPatch",
    "ParameterChangeDecision",
    "ParameterChangeDecisionRecord",
    "ParameterChangeReviewState",
    "ParameterChangeSetView",
    "invalidate_parameter_change",
    "is_safe_parameter_change_id",
    "list_parameter_changes",
    "load_parameter_change",
    "parameter_change_decision_ref",
    "parameter_change_record_ref",
    "parameter_change_set_artifact",
    "parameter_change_set_from_analysis_patches",
    "record_parameter_change_decision",
    "review_parameter_changes",
]
