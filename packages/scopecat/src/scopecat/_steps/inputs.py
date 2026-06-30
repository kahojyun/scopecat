"""Internal input resolution helpers for persisted steps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scopecat._storage.local import LocalRunStore
from scopecat.models.artifact import Artifact
from scopecat.models.run import RunManifest
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementRecord,
)
from scopecat.runs.access import resolve_artifact, validate_run_ref_selector
from scopecat.runs.measurements import (
    read_measurement_dataset_path,
    read_measurement_records_path,
)


@dataclass(frozen=True)
class StepInputArtifact:
    """Resolved step input artifact."""

    artifact_id: str
    ref: str
    path: Path
    artifact: Artifact | None = None


@dataclass(frozen=True)
class ArtifactInputDiagnostics:
    not_found_code: str
    invalid_kind_code: str
    path_escape_code: str
    not_found_message: str
    invalid_kind_message: str
    path_escape_message: str
    diagnostic_path: str = "input"


@dataclass(frozen=True)
class MeasurementInputDiagnostics:
    missing_code: str
    empty_code: str
    invalid_code: str
    noun: str
    diagnostic_path: str | None = None


class StepInputResolver:
    """Resolves step inputs and records job input provenance."""

    def __init__(
        self, *, storage: LocalRunStore, run_id: str, manifest: RunManifest
    ) -> None:
        self._storage = storage
        self._run_id = run_id
        self._manifest = manifest
        self._input_artifact_ids: list[str] = []
        self._input_record_refs: list[str] = []

    @property
    def input_artifact_ids(self) -> tuple[str, ...]:
        return tuple(self._input_artifact_ids)

    @property
    def input_record_refs(self) -> tuple[str, ...]:
        return tuple(self._input_record_refs)

    def record_ref(
        self,
        ref: str,
        *,
        path_escape_code: str,
        path_escape_message: str,
        diagnostic_path: str,
    ) -> None:
        validate_run_ref_selector(
            ref,
            code=path_escape_code,
            message_prefix=path_escape_message,
            path=diagnostic_path,
        )
        self._append_input_record_ref(ref)

    def artifact_ref(
        self,
        *,
        artifact_id: str,
        ref: str,
        path_escape_code: str,
        path_escape_message: str,
        diagnostic_path: str,
    ) -> StepInputArtifact:
        validate_run_ref_selector(
            ref,
            code=path_escape_code,
            message_prefix=path_escape_message,
            path=diagnostic_path,
        )
        self._append_input_artifact_id(artifact_id)
        return StepInputArtifact(
            artifact_id=artifact_id,
            ref=ref,
            path=self._storage.ref_path(self._run_id, ref),
        )

    def resolve_artifact(
        self,
        *,
        selector: str,
        expected_kind: str,
        diagnostics: ArtifactInputDiagnostics,
    ) -> StepInputArtifact:
        artifact = resolve_artifact(
            manifest=self._manifest,
            selector=selector,
            expected_kind=expected_kind,
            not_found_code=diagnostics.not_found_code,
            invalid_kind_code=diagnostics.invalid_kind_code,
            path_escape_code=diagnostics.path_escape_code,
            not_found_message=diagnostics.not_found_message,
            invalid_kind_message=diagnostics.invalid_kind_message,
            path_escape_message=diagnostics.path_escape_message,
            diagnostic_path=diagnostics.diagnostic_path,
        )
        self._append_input_artifact_id(artifact.id)
        return StepInputArtifact(
            artifact_id=artifact.id,
            ref=artifact.path,
            path=self._storage.ref_path(self._run_id, artifact.path),
            artifact=artifact,
        )

    def read_measurement_records(
        self,
        input_artifact: StepInputArtifact,
        *,
        diagnostics: MeasurementInputDiagnostics,
    ) -> list[MeasurementRecord]:
        self._append_input_artifact_id(input_artifact.artifact_id)
        return read_measurement_records_path(
            path=input_artifact.path,
            ref=input_artifact.ref,
            missing_code=diagnostics.missing_code,
            empty_code=diagnostics.empty_code,
            invalid_code=diagnostics.invalid_code,
            noun=diagnostics.noun,
            diagnostic_path=diagnostics.diagnostic_path or input_artifact.ref,
        )

    def read_measurement_dataset(
        self,
        input_artifact: StepInputArtifact,
        *,
        diagnostics: MeasurementDatasetInputDiagnostics,
    ) -> MeasurementDataset:
        self._append_input_artifact_id(input_artifact.artifact_id)
        return read_measurement_dataset_path(
            path=input_artifact.path,
            artifact_id=input_artifact.artifact_id,
            ref=input_artifact.ref,
            metadata=(
                input_artifact.artifact.metadata
                if input_artifact.artifact is not None
                else {}
            ),
            diagnostics=diagnostics,
        )

    def _append_input_artifact_id(self, artifact_id: str) -> None:
        if artifact_id not in self._input_artifact_ids:
            self._input_artifact_ids.append(artifact_id)

    def _append_input_record_ref(self, ref: str) -> None:
        if ref not in self._input_record_refs:
            self._input_record_refs.append(ref)
