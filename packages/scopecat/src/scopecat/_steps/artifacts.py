"""Internal artifact allocation helpers for persisted steps."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from scopecat._storage import ARTIFACTS_DIR
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.data_artifact import (
    DataArrayArtifact,
    DataArraySchema,
    DataTableArtifact,
    DataTableSchema,
    data_array_artifact_metadata,
    data_table_artifact_metadata,
)
from scopecat.results import (
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementRecord,
    measurement_dataset_artifact_metadata,
    validate_measurement_records_against_schema,
)


@dataclass(frozen=True)
class StepArtifactDiagnostics:
    missing_id_code: str
    duplicate_id_code: str
    missing_kind_code: str
    invalid_filename_code: str
    duplicate_filename_code: str
    noun: str
    path_prefix: str


@dataclass(frozen=True)
class StepArtifactHandle:
    """Step-owned artifact file allocated by Scopecat."""

    id: str
    kind: str
    filename: str
    path: Path
    media_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    ref_dir: str = ARTIFACTS_DIR

    @property
    def ref(self) -> str:
        return f"{self.ref_dir}/{self.filename}"

    def to_artifact(self) -> Artifact:
        return Artifact(
            id=self.id,
            kind=self.kind,
            path=self.ref,
            media_type=self.media_type,
            metadata=self.metadata,
        )


class StepArtifactWriter(Protocol):
    """Artifact writer surface exposed to processing and evaluation steps."""

    @property
    def artifacts(self) -> tuple[Artifact, ...]: ...

    @property
    def output_artifact_ids(self) -> tuple[str, ...]: ...

    def reserve_file(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...

    def write_model(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        model: BaseModel,
        media_type: str | None = "application/json",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...

    def write_jsonl(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        records: Iterable[BaseModel],
        media_type: str | None = "application/jsonl",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...

    def write_measurement_dataset(
        self,
        *,
        id: str,  # noqa: A002
        filename: str,
        dataset_role: MeasurementDatasetRole,
        records: Iterable[MeasurementRecord],
        media_type: str | None = "application/jsonl",
        source_step: str | None = None,
        source_artifact_ids: Sequence[str] = (),
        schema: MeasurementDatasetSchema | None = None,
        schema_metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...

    def write_data_table(
        self,
        *,
        id: str,  # noqa: A002
        filename: str,
        schema: DataTableSchema,
        rows: Iterable[Mapping[str, Any]],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        source_artifact_ids: Sequence[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...

    def write_data_array(
        self,
        *,
        id: str,  # noqa: A002
        filename: str,
        schema: DataArraySchema,
        variables: Mapping[str, Any],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        source_artifact_ids: Sequence[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...

    def write_text(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: str,
        media_type: str | None = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...

    def write_bytes(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: bytes,
        media_type: str | None = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle: ...


class StepArtifactStore:
    """Internal store for step-owned artifacts."""

    def __init__(
        self,
        *,
        root_dir: Path,
        ref_dir: str,
        diagnostics: StepArtifactDiagnostics,
    ) -> None:
        self._root_dir = root_dir
        self._ref_dir = ref_dir
        self._diagnostics = diagnostics
        self._handles: list[StepArtifactHandle] = []
        self._seen_ids: set[str] = set()
        self._seen_filenames: set[str] = set()

    @property
    def artifacts(self) -> tuple[Artifact, ...]:
        return tuple(
            handle.to_artifact() for handle in self._handles if handle.path.is_file()
        )

    @property
    def output_artifact_ids(self) -> tuple[str, ...]:
        return tuple(handle.id for handle in self._handles if handle.path.is_file())

    def reserve_file(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        media_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        handle = self._register(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        handle.path.parent.mkdir(parents=True, exist_ok=True)
        return handle

    def write_model(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        model: BaseModel,
        media_type: str | None = "application/json",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        content = json.dumps(model.model_dump(mode="json"), indent=2) + "\n"
        handle.path.write_text(content)
        return handle

    def write_jsonl(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        records: Iterable[BaseModel],
        media_type: str | None = "application/jsonl",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        with handle.path.open("w") as data_file:
            for record in records:
                data_file.write(record.model_dump_json() + "\n")
        return handle

    def write_measurement_dataset(
        self,
        *,
        id: str,  # noqa: A002
        filename: str,
        dataset_role: MeasurementDatasetRole,
        records: Iterable[MeasurementRecord],
        media_type: str | None = "application/jsonl",
        source_step: str | None = None,
        source_artifact_ids: Sequence[str] = (),
        schema: MeasurementDatasetSchema | None = None,
        schema_metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        record_list = list(records)
        if schema is not None:
            diagnostics = validate_measurement_records_against_schema(
                records=record_list,
                schema=schema,
                dataset_id=id,
                dataset_role=dataset_role,
            )
            if diagnostics:
                raise ValidationFailed(diagnostics)
        return self.write_jsonl(
            id=id,
            kind="measurement_dataset",
            filename=filename,
            records=record_list,
            media_type=media_type,
            metadata=measurement_dataset_artifact_metadata(
                dataset_id=id,
                dataset_role=dataset_role,
                records=record_list,
                expected_schema=schema,
                source_step=source_step,
                source_artifact_ids=source_artifact_ids,
                metadata=schema_metadata,
            ),
        )

    def write_data_table(
        self,
        *,
        id: str,  # noqa: A002
        filename: str,
        schema: DataTableSchema,
        rows: Iterable[Mapping[str, Any]],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        source_artifact_ids: Sequence[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        row_list = [dict(row) for row in rows]
        try:
            artifact = DataTableArtifact(schema=schema, rows=row_list)
        except ValidationError as error:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_data_table_artifact",
                        f"data table artifact is invalid: {error}",
                        f"{self._diagnostics.path_prefix}.{id}",
                    )
                ]
            ) from error
        return self.write_text(
            id=id,
            kind="data_table",
            filename=filename,
            content=artifact.model_dump_json(by_alias=True, indent=2),
            media_type=media_type,
            metadata=data_table_artifact_metadata(
                schema=schema,
                source_step=source_step,
                source_artifact_ids=source_artifact_ids,
                metadata=metadata,
            ),
        )

    def write_data_array(
        self,
        *,
        id: str,  # noqa: A002
        filename: str,
        schema: DataArraySchema,
        variables: Mapping[str, Any],
        media_type: str | None = "application/json",
        source_step: str | None = None,
        source_artifact_ids: Sequence[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        try:
            artifact = DataArrayArtifact(schema=schema, variables=dict(variables))
        except ValidationError as error:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_data_array_artifact",
                        f"data array artifact is invalid: {error}",
                        f"{self._diagnostics.path_prefix}.{id}",
                    )
                ]
            ) from error
        return self.write_text(
            id=id,
            kind="data_array",
            filename=filename,
            content=artifact.model_dump_json(by_alias=True, indent=2),
            media_type=media_type,
            metadata=data_array_artifact_metadata(
                schema=schema,
                source_step=source_step,
                source_artifact_ids=source_artifact_ids,
                metadata=metadata,
            ),
        )

    def write_text(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: str,
        media_type: str | None = "text/plain",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        handle.path.write_text(content)
        return handle

    def write_bytes(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        content: bytes,
        media_type: str | None = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> StepArtifactHandle:
        handle = self.reserve_file(
            id=id,
            kind=kind,
            filename=filename,
            media_type=media_type,
            metadata=metadata,
        )
        handle.path.write_bytes(content)
        return handle

    def _register(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
        media_type: str | None,
        metadata: dict[str, Any] | None,
    ) -> StepArtifactHandle:
        diagnostics = self._registration_diagnostics(
            id=id,
            kind=kind,
            filename=filename,
        )
        if diagnostics:
            raise ValidationFailed(diagnostics)
        handle = StepArtifactHandle(
            id=id,
            kind=kind,
            filename=filename,
            path=self._root_dir / filename,
            ref_dir=self._ref_dir,
            media_type=media_type,
            metadata=dict(metadata or {}),
        )
        self._seen_ids.add(id)
        self._seen_filenames.add(filename)
        self._handles.append(handle)
        return handle

    def _registration_diagnostics(
        self,
        *,
        id: str,  # noqa: A002
        kind: str,
        filename: str,
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        if not id:
            diagnostics.append(
                _diagnostic(
                    "error",
                    self._diagnostics.missing_id_code,
                    f"{self._diagnostics.noun} id must be non-empty",
                    f"{self._diagnostics.path_prefix}.id",
                )
            )
        elif id in self._seen_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    self._diagnostics.duplicate_id_code,
                    f"{self._diagnostics.noun} id is duplicated: {id}",
                    f"{self._diagnostics.path_prefix}.{id}",
                )
            )
        if not kind:
            diagnostics.append(
                _diagnostic(
                    "error",
                    self._diagnostics.missing_kind_code,
                    f"{self._diagnostics.noun} kind must be non-empty",
                    (
                        f"{self._diagnostics.path_prefix}.{id}.kind"
                        if id
                        else f"{self._diagnostics.path_prefix}.kind"
                    ),
                )
            )
        if not _is_artifact_filename(filename):
            diagnostics.append(
                _diagnostic(
                    "error",
                    self._diagnostics.invalid_filename_code,
                    (
                        f"{self._diagnostics.noun} filename must be a basename: "
                        f"{filename}"
                    ),
                    (
                        f"{self._diagnostics.path_prefix}.{id}.filename"
                        if id
                        else f"{self._diagnostics.path_prefix}.filename"
                    ),
                )
            )
        elif filename in self._seen_filenames:
            diagnostics.append(
                _diagnostic(
                    "error",
                    self._diagnostics.duplicate_filename_code,
                    f"{self._diagnostics.noun} filename is duplicated: {filename}",
                    (
                        f"{self._diagnostics.path_prefix}.{id}.filename"
                        if id
                        else f"{self._diagnostics.path_prefix}.filename"
                    ),
                )
            )
        return diagnostics


def _is_artifact_filename(filename: str) -> bool:
    if not filename or "\\" in filename:
        return False
    path = PurePosixPath(filename)
    return path.name == filename and not path.is_absolute() and ".." not in path.parts


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
