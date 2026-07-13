"""Internal input resolution helpers for persisted steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scopecat.adapters.filesystem.measurement_files import (
    read_measurement_dataset_path,
    read_measurement_records_path,
)
from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.kernel.problems import ModelLocation, model_location
from scopecat.measurements.results import (
    MeasurementDataset,
    MeasurementDatasetReadContract,
    MeasurementRecord,
)
from scopecat.records.artifact import RunArtifactEntry, RunDatasetEntry
from scopecat.records.run import RunManifest
from scopecat.runs.access import (
    artifact_storage_ref,
    dataset_storage_ref,
    get_dataset_by_id,
    resolve_artifact,
    resolve_dataset,
    validate_run_entry_selector,
)


@dataclass(frozen=True)
class StepInputArtifact:
    """Resolved step input artifact."""

    artifact_id: str
    ref: str
    path: Path
    artifact: RunArtifactEntry | None = None
    dataset: RunDatasetEntry | None = None
    is_dataset: bool = False


@dataclass(frozen=True)
class ArtifactInputContract:
    not_found_code: str
    invalid_kind_code: str
    path_escape_code: str
    not_found_message: str
    invalid_kind_message: str
    path_escape_message: str
    location: ModelLocation = field(
        default_factory=lambda: model_location("run_access", "input")
    )


@dataclass(frozen=True)
class MeasurementInputContract:
    missing_code: str
    empty_code: str
    invalid_code: str
    noun: str


class StepInputResolver:
    """Resolves step inputs and records job input provenance."""

    def __init__(
        self, *, storage: FilesystemRunRepository, run_id: str, manifest: RunManifest
    ) -> None:
        self._storage = storage
        self._run_id = run_id
        self._manifest = manifest
        self._input_artifact_ids: list[str] = []
        self._input_dataset_ids: list[str] = []
        self._input_records: list[str] = []

    @property
    def input_artifact_ids(self) -> tuple[str, ...]:
        return tuple(self._input_artifact_ids)

    @property
    def input_dataset_ids(self) -> tuple[str, ...]:
        return tuple(self._input_dataset_ids)

    @property
    def input_records(self) -> tuple[str, ...]:
        return tuple(self._input_records)

    def record_ref(
        self,
        ref: str,
        *,
        path_escape_code: str,
        path_escape_message: str,
        location: ModelLocation,
    ) -> None:
        validate_run_entry_selector(
            ref,
            code=path_escape_code,
            message_prefix=path_escape_message,
            location=location,
        )
        self._append_input_record_ref(ref)

    def artifact_ref(
        self,
        *,
        artifact_id: str,
        ref: str,
        path_escape_code: str,
        path_escape_message: str,
        location: ModelLocation,
    ) -> StepInputArtifact:
        validate_run_entry_selector(
            ref,
            code=path_escape_code,
            message_prefix=path_escape_message,
            location=location,
        )
        self._append_input_artifact_id(artifact_id)
        return StepInputArtifact(
            artifact_id=artifact_id,
            ref=ref,
            path=self._storage.ref_path(self._run_id, ref),
        )

    def dataset_ref(
        self,
        *,
        dataset_id: str,
        ref: str,
        path_escape_code: str,
        path_escape_message: str,
        location: ModelLocation,
    ) -> StepInputArtifact:
        validate_run_entry_selector(
            ref,
            code=path_escape_code,
            message_prefix=path_escape_message,
            location=location,
        )
        self._append_input_dataset_id(dataset_id)
        dataset = get_dataset_by_id(self._manifest, dataset_id)
        return StepInputArtifact(
            artifact_id=dataset_id,
            ref=ref,
            path=self._storage.ref_path(self._run_id, ref),
            dataset=dataset,
            is_dataset=True,
        )

    def resolve_artifact(
        self,
        *,
        selector: str,
        expected_kind: str,
        contract: ArtifactInputContract,
    ) -> StepInputArtifact:
        artifact = resolve_artifact(
            manifest=self._manifest,
            selector=selector,
            expected_kind=expected_kind,
            not_found_code=contract.not_found_code,
            invalid_kind_code=contract.invalid_kind_code,
            path_escape_code=contract.path_escape_code,
            not_found_message=contract.not_found_message,
            invalid_kind_message=contract.invalid_kind_message,
            path_escape_message=contract.path_escape_message,
            location=contract.location,
        )
        self._append_input_artifact_id(artifact.id)
        ref = artifact_storage_ref(artifact)
        return StepInputArtifact(
            artifact_id=artifact.id,
            ref=ref,
            path=self._storage.ref_path(self._run_id, ref),
            artifact=artifact,
        )

    def resolve_dataset(
        self,
        *,
        selector: str,
        expected_kind: str,
        contract: ArtifactInputContract,
    ) -> StepInputArtifact:
        dataset = resolve_dataset(
            manifest=self._manifest,
            selector=selector,
            expected_kind=expected_kind,
            not_found_code=contract.not_found_code,
            invalid_kind_code=contract.invalid_kind_code,
            path_escape_code=contract.path_escape_code,
            not_found_message=contract.not_found_message,
            invalid_kind_message=contract.invalid_kind_message,
            path_escape_message=contract.path_escape_message,
            location=contract.location,
        )
        self._append_input_dataset_id(dataset.id)
        ref = dataset_storage_ref(dataset)
        return StepInputArtifact(
            artifact_id=dataset.id,
            ref=ref,
            path=self._storage.ref_path(self._run_id, ref),
            dataset=dataset,
            is_dataset=True,
        )

    def read_measurement_records(
        self,
        input_artifact: StepInputArtifact,
        *,
        contract: MeasurementInputContract,
    ) -> list[MeasurementRecord]:
        if input_artifact.is_dataset:
            self._append_input_dataset_id(input_artifact.artifact_id)
        else:
            self._append_input_artifact_id(input_artifact.artifact_id)
        return read_measurement_records_path(
            path=input_artifact.path,
            ref=input_artifact.ref,
            missing_code=contract.missing_code,
            empty_code=contract.empty_code,
            invalid_code=contract.invalid_code,
            noun=contract.noun,
        )

    def read_measurement_dataset(
        self,
        input_artifact: StepInputArtifact,
        *,
        contract: MeasurementDatasetReadContract,
    ) -> MeasurementDataset:
        self._append_input_dataset_id(input_artifact.artifact_id)
        if input_artifact.dataset is None:
            msg = "measurement dataset input requires a resolved RunDatasetEntry"
            raise AssertionError(msg)
        return read_measurement_dataset_path(
            path=input_artifact.path,
            dataset_id=input_artifact.artifact_id,
            ref=input_artifact.ref,
            schema_data=input_artifact.dataset.data_schema,
            metadata=input_artifact.dataset.metadata,
            contract=contract,
        )

    def _append_input_artifact_id(self, artifact_id: str) -> None:
        if artifact_id not in self._input_artifact_ids:
            self._input_artifact_ids.append(artifact_id)

    def _append_input_dataset_id(self, dataset_id: str) -> None:
        if dataset_id not in self._input_dataset_ids:
            self._input_dataset_ids.append(dataset_id)

    def _append_input_record_ref(self, ref: str) -> None:
        if ref not in self._input_records:
            self._input_records.append(ref)
