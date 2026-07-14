"""Internal artifact allocation helpers for persisted steps."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, JsonValue, ValidationError

from scopecat.adapters.filesystem.io import ensure_durable_directory
from scopecat.adapters.filesystem.measurement_files import (
    write_measurement_records_path,
)
from scopecat.kernel.errors import CheckFailed, StorageError
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    model_location,
)
from scopecat.measurements.datasets import (
    MEASUREMENT_DATASET_KIND,
    MEASUREMENT_DATASET_MEDIA_TYPE,
    measurement_dataset_schema,
    validate_measurement_dataset_records,
)
from scopecat.measurements.results import (
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementRecord,
)
from scopecat.records.artifact import RunArtifactEntry, RunDatasetEntry
from scopecat.records.data_artifact import (
    DataArrayArtifact,
    DataArraySchema,
    DataTableArtifact,
    DataTableSchema,
)
from scopecat.runs.refs import artifact_content_ref, dataset_content_ref


@dataclass(frozen=True)
class StepArtifactContract:
    """Caller-specific codes and model root for step artifact allocation."""

    missing_id_code: str
    duplicate_id_code: str
    missing_kind_code: str
    noun: str
    location_root: str


@dataclass(frozen=True)
class StepArtifactHandle:
    """Step-owned artifact file allocated by Scopecat."""

    id: str
    kind: str
    path: Path
    media_type: str | None = None
    dataset_role: str | None = None
    dataset_schema: dict[str, Any] | None = None
    produced_by: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return _content_ref(id=self.id, kind=self.kind, is_dataset=self.is_dataset)

    def to_artifact(self) -> RunArtifactEntry:
        return RunArtifactEntry(
            id=self.id,
            kind=self.kind,
            media_type=self.media_type,
            produced_by=self.produced_by,
            metadata=self.metadata,
        )

    def to_dataset(self) -> RunDatasetEntry:
        if self.dataset_schema is None:
            msg = f"step output {self.id!r} is not a dataset"
            raise ValueError(msg)
        return RunDatasetEntry(
            id=self.id,
            kind=self.kind,
            media_type=self.media_type,
            role=self.dataset_role,
            schema=self.dataset_schema,
            produced_by=self.produced_by,
            metadata=self.metadata,
        )

    @property
    def is_dataset(self) -> bool:
        return self.dataset_schema is not None


class StepArtifactWriter(Protocol):
    """RunArtifactEntry writer surface exposed to artifact-producing helpers."""

    @property
    def artifacts(self) -> tuple[RunArtifactEntry, ...]: ...

    @property
    def datasets(self) -> tuple[RunDatasetEntry, ...]: ...

    @property
    def output_artifact_ids(self) -> tuple[str, ...]: ...

    @property
    def output_dataset_ids(self) -> tuple[str, ...]: ...

    def reserve_file(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        media_type: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...

    def write_model(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        model: BaseModel,
        media_type: str | None = "application/json",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...

    def write_jsonl(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        records: Iterable[BaseModel],
        media_type: str | None = "application/jsonl",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...

    def write_measurement_dataset(
        self,
        *,
        id: str,  # noqa: A002
        dataset_role: MeasurementDatasetRole,
        records: Iterable[MeasurementRecord],
        media_type: str | None = MEASUREMENT_DATASET_MEDIA_TYPE,
        source_step: str | None = None,
        schema: MeasurementDatasetSchema | None = None,
        schema_metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...

    def write_data_table(
        self,
        *,
        id: str,  # noqa: A002
        schema: DataTableSchema,
        rows: Iterable[Mapping[str, Any]],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...

    def write_data_array(
        self,
        *,
        id: str,  # noqa: A002
        schema: DataArraySchema,
        variables: Mapping[str, Any],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...

    def write_text(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        content: str,
        media_type: str | None = "text/plain",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...

    def write_bytes(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        content: bytes,
        media_type: str | None = "application/octet-stream",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle: ...


class StepArtifactStore:
    """Internal store for step-owned artifacts."""

    def __init__(
        self,
        *,
        root_dir: Path,
        contract: StepArtifactContract,
    ) -> None:
        self._root_dir = root_dir
        self._contract = contract
        self._handles: list[StepArtifactHandle] = []
        self._seen_ids: set[str] = set()

    @property
    def artifacts(self) -> tuple[RunArtifactEntry, ...]:
        return tuple(
            handle.to_artifact()
            for handle in self._handles
            if handle.path.is_file() and not handle.is_dataset
        )

    @property
    def datasets(self) -> tuple[RunDatasetEntry, ...]:
        return tuple(
            handle.to_dataset()
            for handle in self._handles
            if handle.path.is_file() and handle.is_dataset
        )

    @property
    def output_artifact_ids(self) -> tuple[str, ...]:
        return tuple(
            handle.id
            for handle in self._handles
            if handle.path.is_file() and not handle.is_dataset
        )

    @property
    def output_dataset_ids(self) -> tuple[str, ...]:
        return tuple(
            handle.id
            for handle in self._handles
            if handle.path.is_file() and handle.is_dataset
        )

    def reserve_file(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        media_type: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        handle = self._register(
            id=id,
            kind=kind,
            media_type=media_type,
            metadata=metadata,
            dataset_role=None,
            dataset_schema=None,
            produced_by=None,
        )
        self._ensure_parent(handle.path)
        return handle

    def write_model(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        model: BaseModel,
        media_type: str | None = "application/json",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            media_type=media_type,
            metadata=metadata,
        )
        content = json.dumps(model.model_dump(mode="json"), indent=2) + "\n"
        self._write_text_path(handle.path, content)
        return handle

    def write_jsonl(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        records: Iterable[BaseModel],
        media_type: str | None = "application/jsonl",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            media_type=media_type,
            metadata=metadata,
        )
        self._write_jsonl_path(handle.path, records)
        return handle

    def write_measurement_dataset(
        self,
        *,
        id: str,  # noqa: A002
        dataset_role: MeasurementDatasetRole,
        records: Iterable[MeasurementRecord],
        media_type: str | None = MEASUREMENT_DATASET_MEDIA_TYPE,
        source_step: str | None = None,
        schema: MeasurementDatasetSchema | None = None,
        schema_metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        record_list = list(records)
        if schema is not None:
            problems = validate_measurement_dataset_records(
                records=record_list,
                schema=schema,
                dataset_id=id,
                dataset_role=dataset_role,
            )
            if problems:
                raise CheckFailed(problems)
        dataset_schema = measurement_dataset_schema(
            dataset_id=id,
            dataset_role=dataset_role,
            records=record_list,
            expected_schema=schema,
            metadata=schema_metadata,
        )
        handle = self._register(
            id=id,
            kind=MEASUREMENT_DATASET_KIND,
            media_type=media_type,
            metadata={},
            dataset_role=dataset_role,
            dataset_schema=dataset_schema.model_dump(mode="json"),
            produced_by=_output_produced_by(source_step=source_step),
        )
        write_measurement_records_path(path=handle.path, records=record_list)
        return handle

    def write_data_table(
        self,
        *,
        id: str,  # noqa: A002
        schema: DataTableSchema,
        rows: Iterable[Mapping[str, Any]],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        row_list = [dict(row) for row in rows]
        try:
            artifact = DataTableArtifact(schema=schema, rows=row_list)
        except ValidationError as error:
            raise CheckFailed(
                [
                    self._problem(
                        "invalid_data_table_artifact",
                        "data table artifact is invalid",
                        id,
                    )
                ]
            ) from error
        return self._write_text_dataset(
            id=id,
            kind="data_table",
            content=artifact.model_dump_json(by_alias=True, indent=2),
            media_type=media_type,
            schema=schema.model_dump(mode="json"),
            metadata=dict(metadata or {}),
            produced_by=_output_produced_by(source_step=source_step),
        )

    def write_data_array(
        self,
        *,
        id: str,  # noqa: A002
        schema: DataArraySchema,
        variables: Mapping[str, Any],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        try:
            artifact = DataArrayArtifact(schema=schema, variables=dict(variables))
        except ValidationError as error:
            raise CheckFailed(
                [
                    self._problem(
                        "invalid_data_array_artifact",
                        "data array artifact is invalid",
                        id,
                    )
                ]
            ) from error
        return self._write_text_dataset(
            id=id,
            kind="data_array",
            content=artifact.model_dump_json(by_alias=True, indent=2),
            media_type=media_type,
            schema=schema.model_dump(mode="json"),
            metadata=dict(metadata or {}),
            produced_by=_output_produced_by(source_step=source_step),
        )

    def write_text(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        content: str,
        media_type: str | None = "text/plain",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            media_type=media_type,
            metadata=metadata,
        )
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        self._write_text_path(handle.path, content)
        return handle

    def write_bytes(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        content: bytes,
        media_type: str | None = "application/octet-stream",
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            media_type=media_type,
            metadata=metadata,
        )
        self._write_bytes_path(handle.path, content)
        return handle

    def _write_jsonl_dataset(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        records: Iterable[BaseModel],
        media_type: str | None,
        role: str | None,
        schema: dict[str, Any],
        metadata: Mapping[str, JsonValue] | None,
        produced_by: str | None,
    ) -> StepArtifactHandle:
        handle = self._register(
            id=id,
            kind=kind,
            media_type=media_type,
            metadata=metadata,
            dataset_role=role,
            dataset_schema=schema,
            produced_by=produced_by,
        )
        self._ensure_parent(handle.path)
        self._write_jsonl_path(handle.path, records)
        return handle

    def _write_text_dataset(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        content: str,
        media_type: str | None,
        schema: dict[str, Any],
        metadata: Mapping[str, JsonValue] | None,
        produced_by: str | None,
    ) -> StepArtifactHandle:
        handle = self._register(
            id=id,
            kind=kind,
            media_type=media_type,
            metadata=metadata,
            dataset_role=None,
            dataset_schema=schema,
            produced_by=produced_by,
        )
        self._ensure_parent(handle.path)
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        self._write_text_path(handle.path, content)
        return handle

    def _register(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        media_type: str | None,
        metadata: Mapping[str, JsonValue] | None,
        dataset_role: str | None,
        dataset_schema: dict[str, Any] | None,
        produced_by: str | None,
    ) -> StepArtifactHandle:
        problems = self._registration_problems(
            id=id,
            kind=kind,
        )
        if problems:
            raise CheckFailed(problems)
        handle = StepArtifactHandle(
            id=id,
            kind=kind,
            media_type=media_type,
            dataset_role=dataset_role,
            dataset_schema=dataset_schema,
            produced_by=produced_by,
            metadata=dict(metadata or {}),
            path=self._root_dir
            / _content_ref(
                id=id,
                kind=kind,
                is_dataset=dataset_schema is not None,
            ),
        )
        self._seen_ids.add(id)
        self._handles.append(handle)
        return handle

    def _registration_problems(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
    ) -> list[Problem]:
        problems: list[Problem] = []
        if not id:
            problems.append(
                self._problem(
                    self._contract.missing_id_code,
                    f"{self._contract.noun} id must be non-empty",
                    "id",
                )
            )
        elif id in self._seen_ids:
            problems.append(
                self._problem(
                    self._contract.duplicate_id_code,
                    f"{self._contract.noun} id is duplicated: {id}",
                    id,
                )
            )
        if not kind:
            problems.append(
                self._problem(
                    self._contract.missing_kind_code,
                    f"{self._contract.noun} kind must be non-empty",
                    *((id, "kind") if id else ("kind",)),
                )
            )
        return problems

    def _problem(
        self,
        code: str,
        message: str,
        *path: str | int,
    ) -> Problem:
        return blocking_problem(
            code,
            message,
            category=ProblemCategory.INVALID_INPUT,
            phase=ProblemPhase.ANALYSIS,
            location=model_location(self._contract.location_root, *path),
        )

    def _ensure_parent(self, path: Path) -> None:
        try:
            ensure_durable_directory(path.parent)
        except OSError as error:
            failure = self._storage_error(
                path,
                "step artifact directory could not be created",
            )
            raise failure from error

    def _write_text_path(self, path: Path, content: str) -> None:
        try:
            path.write_text(content)
        except OSError as error:
            raise self._storage_error(
                path,
                "step artifact could not be written",
            ) from error

    def _write_bytes_path(self, path: Path, content: bytes) -> None:
        try:
            path.write_bytes(content)
        except OSError as error:
            raise self._storage_error(
                path,
                "step artifact could not be written",
            ) from error

    def _write_jsonl_path(
        self,
        path: Path,
        records: Iterable[BaseModel],
    ) -> None:
        try:
            with path.open("w") as data_file:
                for record in records:
                    data_file.write(record.model_dump_json() + "\n")
        except OSError as error:
            raise self._storage_error(
                path,
                "step artifact could not be written",
            ) from error

    @staticmethod
    def _storage_error(path: Path, message: str) -> StorageError:
        return StorageError(
            [
                blocking_problem(
                    "step_artifact_write_failed",
                    message,
                    category=ProblemCategory.STORAGE,
                    phase=ProblemPhase.PERSISTENCE,
                    location=StorageLocation(ref=str(path)),
                )
            ]
        )


def _output_produced_by(
    *,
    source_step: str | None,
) -> str | None:
    return source_step


def _content_ref(*, id: str, kind: str, is_dataset: bool) -> str:  # noqa: A002
    if is_dataset:
        return dataset_content_ref(dataset_id=id, kind=kind)
    return artifact_content_ref(artifact_id=id, kind=kind)
