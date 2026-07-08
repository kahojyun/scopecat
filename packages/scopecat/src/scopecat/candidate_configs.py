"""Lazy candidate configuration resolution for parameter changes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scopecat._manifest_updates import write_manifest_records
from scopecat._storage.refs import record_content_ref
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.ids import artifact_slug
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import ParameterChangeSet
from scopecat.parameter_changes import (
    is_safe_parameter_change_id,
    parameter_change_set_record,
)
from scopecat.parameters import apply_parameter_patches
from scopecat.runs.access import open_run_store

type CandidateConfigInput = CandidateConfig | ResolvedCandidateConfig
type CandidateSelection = str | Sequence[str] | None


@dataclass(frozen=True)
class CandidateConfig:
    analysis_title: str
    analysis_key: str
    changes: tuple[ParameterChangeSet, ...]

    @property
    def source_run_id(self) -> str:
        run_ids = {change.source_run_id for change in self.changes}
        if len(run_ids) != 1:
            msg = "candidate config changes must all come from one source run"
            raise ValueError(msg)
        return next(iter(run_ids))

    @property
    def parameter_changes(self) -> tuple[ParameterChangeSet, ...]:
        return self.changes

    @property
    def change_set_ids(self) -> tuple[str, ...]:
        return tuple(change.id for change in self.changes)


@dataclass(frozen=True)
class ResolvedCandidateConfig:
    candidate: CandidateConfig
    config: ConfigProfileSnapshot
    change_set_records: tuple[RunRecordEntry, ...]
    candidate_config_record: RunRecordEntry

    @property
    def candidate_config_record_id(self) -> str:
        return self.candidate_config_record.id


def resolve_candidate_config(
    candidate: CandidateConfigInput,
    *,
    workspace: str | Path,
) -> ResolvedCandidateConfig:
    if isinstance(candidate, CandidateConfig):
        return _resolve_candidate_config(candidate, workspace=workspace)
    return candidate


def _build_candidate_config_snapshot(
    *,
    config: ConfigProfileSnapshot,
    changes: Sequence[ParameterChangeSet],
) -> ConfigProfileSnapshot:
    parameter_state = config.parameter_state
    for index, change in enumerate(changes):
        try:
            parameter_state = apply_parameter_patches(
                catalog=config.parameter_catalog,
                parameter_state=parameter_state,
                patches=change.patches,
                allow_table_row_changes=True,
            )
        except ValueError as error:
            raise ValidationFailed(
                [
                    Diagnostic(
                        severity="error",
                        code="parameter_change_candidate_patch_invalid",
                        message=f"parameter change candidate patch is invalid: {error}",
                        path=f"parameter_changes[{index}].patches",
                    )
                ]
            ) from error
    return ConfigProfileSnapshot.model_validate(
        config.model_dump(mode="python")
        | {
            "parameter_state": parameter_state,
        }
    )


def _resolve_candidate_config(
    candidate: CandidateConfig,
    *,
    workspace: str | Path,
) -> ResolvedCandidateConfig:
    _validate_candidate(candidate)
    storage = open_run_store(workspace)
    source_config = storage.read_config_profile_snapshot(candidate.source_run_id)
    candidate_id = _candidate_config_id(candidate)
    candidate_record_id = f"{candidate_id}-candidate-config"
    change_records = tuple(
        parameter_change_set_record(
            change=change,
        )
        for change in candidate.changes
    )
    candidate_config = _build_candidate_config_snapshot(
        config=source_config,
        changes=candidate.changes,
    )
    for change, record in zip(candidate.changes, change_records, strict=True):
        storage.write_model(
            candidate.source_run_id,
            record_content_ref(record_id=record.id, kind=record.kind),
            change,
        )
    candidate_record = RunRecordEntry(
        id=candidate_record_id,
        kind="candidate_config",
        media_type="application/json",
    )
    storage.write_model(
        candidate.source_run_id,
        record_content_ref(record_id=candidate_record.id, kind=candidate_record.kind),
        candidate_config,
    )
    manifest = storage.read_manifest(candidate.source_run_id)
    write_manifest_records(
        storage=storage,
        manifest=manifest,
        records=[*change_records, candidate_record],
    )
    return ResolvedCandidateConfig(
        candidate=candidate,
        config=candidate_config,
        change_set_records=change_records,
        candidate_config_record=candidate_record,
    )


def _validate_candidate(candidate: CandidateConfig) -> None:
    if not candidate.changes:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="candidate_config_empty",
                    message="candidate config requires at least one parameter change",
                    path="candidate",
                )
            ]
        )
    run_ids = {change.source_run_id for change in candidate.changes}
    if len(run_ids) != 1:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="candidate_config_source_run_mismatch",
                    message="candidate config changes must come from one source run",
                    path="candidate.parameter_changes",
                )
            ]
        )
    seen: set[str] = set()
    for change in candidate.changes:
        if not is_safe_parameter_change_id(change.id):
            raise ValidationFailed(
                [
                    Diagnostic(
                        severity="error",
                        code="parameter_change_invalid_id",
                        message=(
                            "parameter change id is not safe for record paths: "
                            f"{change.id}"
                        ),
                        path="parameter_change.id",
                    )
                ]
            )
        if change.id in seen:
            raise ValidationFailed(
                [
                    Diagnostic(
                        severity="error",
                        code="candidate_config_duplicate_parameter_change",
                        message=f"duplicate parameter change id: {change.id}",
                        path="candidate.parameter_changes",
                    )
                ]
            )
        seen.add(change.id)


def _candidate_config_id(candidate: CandidateConfig) -> str:
    selected = "-".join(artifact_slug(change.id) for change in candidate.changes)
    return f"candidate-{artifact_slug(candidate.analysis_key)}-{selected}"


__all__ = [
    "CandidateConfig",
    "CandidateConfigInput",
    "CandidateSelection",
    "ResolvedCandidateConfig",
    "resolve_candidate_config",
]
