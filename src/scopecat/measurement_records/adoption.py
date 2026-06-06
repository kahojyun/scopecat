"""User-facing JNY-007 adoption facade for Measurement Records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    APPROVAL_STATES,
    RECORD_MANIFEST_NAME,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.durable_import import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordDurableImportRun,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)
from scopecat.measurement_records.legacy_primary_import import (
    LegacyPrimaryImportRequest,
    LegacyPrimaryImportRun,
    attach_converted_primary_data_to_legacy_record_from_request,
)
from scopecat.measurement_records.legacy_run import (
    LegacyRunLocator,
    LegacyRunRecordRequest,
    LegacyRunRecordRun,
    record_legacy_measurement_run_from_request,
)
from scopecat.measurement_records.recorded_reference import (
    MeasurementRecordReference,
    MeasurementRecordReferenceRequest,
    MeasurementRecordReferenceRun,
    record_measurement_record_references_from_request,
)

ADOPTION_ROUTES = {"adopt_first", "import_ready"}
PRIMARY_DATA_FILENAME = "primary.csv"
WRITER_RECEIPT_FILENAME = "writer-receipt.json"
FINALIZATION_RECEIPT_FILENAME = "finalization-receipt.json"
READ_MODEL_FILENAME = "record-read-model.json"


@dataclass(frozen=True)
class MeasurementRecordHandle:
    """Stable local handle for a canonical Measurement Record."""

    record_id: str
    record_dir: str
    manifest_path: str
    read_model_path: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.record_id, "measurement record handle record_id")
        validate_relative_path(self.record_dir, "measurement record handle record_dir")
        validate_relative_path(self.manifest_path, "measurement record handle manifest_path")
        if self.read_model_path is not None:
            validate_relative_path(
                self.read_model_path,
                "measurement record handle read_model_path",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "primary_data_attached": self.read_model_path is not None,
        }


@dataclass(frozen=True)
class MeasurementRecordAdoptionLocator:
    """Declared legacy locator accepted by the adoption facade."""

    locator_id: str
    kind: str
    role: str
    value: str

    def __post_init__(self) -> None:
        validate_public_identifier(self.locator_id, "adoption locator locator_id")
        if self.kind not in {"workspace_relative_path", "opaque_reference"}:
            raise ValueError("adoption locator kind is unsupported")
        if self.role not in {"primary_data", "notebook"}:
            raise ValueError("adoption locator role is unsupported")
        if self.kind == "workspace_relative_path":
            validate_relative_path(self.value, "adoption locator value")
        else:
            validate_text(self.value, "adoption locator value")

    def to_legacy_locator(self) -> LegacyRunLocator:
        return LegacyRunLocator(
            locator_id=self.locator_id,
            kind=self.kind,
            role=self.role,
            value=self.value,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator_id": self.locator_id,
            "kind": self.kind,
            "role": self.role,
            "value": self.value,
        }


@dataclass(frozen=True)
class MeasurementRecordAdoptionRequest:
    """Approved request to adopt an already-produced run as a local record."""

    request_id: str
    approval_state: str
    record_id: str
    route: str
    import_source: MeasurementRecordImportSource | None = None
    legacy_system_id: str | None = None
    legacy_run_id: str | None = None
    created_at: str | None = None
    label: str | None = None
    experiment_type: str | None = None
    run_started_at: str | None = None
    run_completed_at: str | None = None
    locators: tuple[MeasurementRecordAdoptionLocator, ...] = ()
    operator_notes: str | None = None
    references: tuple[MeasurementRecordReference, ...] = ()
    reference_set_id: str | None = None
    reference_operator_notes: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "adoption request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("adoption approval_state is unsupported")
        validate_public_identifier(self.record_id, "adoption record_id")
        if self.route not in ADOPTION_ROUTES:
            raise ValueError("adoption route is unsupported")
        if self.route == "adopt_first":
            validate_public_identifier(self.legacy_system_id, "adoption legacy_system_id")
            validate_public_identifier(self.legacy_run_id, "adoption legacy_run_id")
        if self.route == "import_ready" and self.import_source is None:
            raise ValueError("import-ready adoption requires import_source")
        if self.import_source is not None and not isinstance(
            self.import_source,
            MeasurementRecordImportSource,
        ):
            raise ValueError("adoption import_source is unsupported")
        for value, owner in (
            (self.created_at, "adoption created_at"),
            (self.label, "adoption label"),
            (self.experiment_type, "adoption experiment_type"),
            (self.run_started_at, "adoption run_started_at"),
            (self.run_completed_at, "adoption run_completed_at"),
            (self.operator_notes, "adoption operator_notes"),
            (self.reference_operator_notes, "adoption reference_operator_notes"),
        ):
            if value is not None:
                validate_text(value, owner)
        if not isinstance(self.locators, tuple):
            raise ValueError("adoption locators must be a tuple")
        if not isinstance(self.references, tuple):
            raise ValueError("adoption references must be a tuple")
        if self.references:
            validate_public_identifier(self.reference_set_id, "adoption reference_set_id")
        elif self.reference_set_id is not None:
            raise ValueError("adoption reference_set_id requires references")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def record_dir(self) -> str:
        return canonical_record_dir(self.record_id)

    @property
    def manifest_path(self) -> str:
        return f"{self.record_dir}/{RECORD_MANIFEST_NAME}"

    @property
    def read_model_path(self) -> str:
        return f"{self.record_dir}/{READ_MODEL_FILENAME}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "record_id": self.record_id,
            "route": self.route,
            "import_source": None if self.import_source is None else self.import_source.to_dict(),
            "legacy_system_id": self.legacy_system_id,
            "legacy_run_id": self.legacy_run_id,
            "created_at": self.created_at,
            "label": self.label,
            "experiment_type": self.experiment_type,
            "run_started_at": self.run_started_at,
            "run_completed_at": self.run_completed_at,
            "locators": [locator.to_dict() for locator in self.locators],
            "operator_notes": self.operator_notes,
            "reference_set_id": self.reference_set_id,
            "references": [reference.to_dict() for reference in self.references],
            "reference_operator_notes": self.reference_operator_notes,
        }


@dataclass(frozen=True)
class MeasurementRecordAdoptionRun:
    """Result for the user-facing JNY-007 adoption facade."""

    request: MeasurementRecordAdoptionRequest
    storage_root: Path
    handle: MeasurementRecordHandle | None = None
    legacy_run: LegacyRunRecordRun | None = None
    primary_data: MeasurementRecordDurableImportRun | LegacyPrimaryImportRun | None = None
    recorded_references: MeasurementRecordReferenceRun | None = None
    adoption_error: str | None = None

    @property
    def adopted(self) -> bool:
        return self.handle is not None and self.adoption_error is None

    @property
    def classification(self) -> str:
        if not self.request.approved:
            return "blocked_before_measurement_record_adoption"
        if self.handle is None:
            return "blocked_before_measurement_record_adoption"
        if self.adoption_error is not None:
            return "adopted_measurement_record_with_error"
        return "adopted_measurement_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "request": self.request.to_dict(),
            "handle": None if self.handle is None else self.handle.to_dict(),
            "steps": {
                "legacy_run": None
                if self.legacy_run is None
                else {
                    "performed": self.legacy_run.recorded,
                    "classification": self.legacy_run.classification,
                    "record_error": self.legacy_run.record_error,
                },
                "primary_data": None
                if self.primary_data is None
                else _primary_data_step_summary(self.primary_data),
                "recorded_references": None
                if self.recorded_references is None
                else {
                    "performed": self.recorded_references.recorded,
                    "classification": self.recorded_references.classification,
                    "references_error": self.recorded_references.references_error,
                },
            },
            "adoption_error": self.adoption_error,
        }


def canonical_record_dir(record_id: str) -> str:
    """Return the canonical local record directory for a public record id."""

    return f"records/{validate_public_identifier(record_id, 'record_id')}"


def _primary_data_step_summary(
    run: MeasurementRecordDurableImportRun | LegacyPrimaryImportRun,
) -> dict[str, Any]:
    import_error = getattr(run, "import_error", None)
    performed = bool(getattr(run, "imported", getattr(run, "attached", False)))
    return {
        "performed": performed,
        "classification": run.classification,
        "import_error": import_error,
    }


def canonical_record_handle(
    record_id: str,
    *,
    has_read_model: bool = False,
) -> MeasurementRecordHandle:
    """Build a canonical handle without exposing caller-managed storage paths."""

    record_dir = canonical_record_dir(record_id)
    return MeasurementRecordHandle(
        record_id=record_id,
        record_dir=record_dir,
        manifest_path=f"{record_dir}/{RECORD_MANIFEST_NAME}",
        read_model_path=f"{record_dir}/{READ_MODEL_FILENAME}" if has_read_model else None,
    )


def adopt_existing_run_from_request(
    request: MeasurementRecordAdoptionRequest,
    *,
    storage_root: str | Path,
    content_root: str | Path | None = None,
) -> MeasurementRecordAdoptionRun:
    """Adopt an already-produced run into canonical Measurement Records storage."""

    storage = Path(storage_root)
    if not request.approved:
        return MeasurementRecordAdoptionRun(request=request, storage_root=storage)
    if request.route == "adopt_first":
        return _adopt_first(request, storage_root=storage, content_root=content_root)
    return _import_ready(request, storage_root=storage, content_root=content_root)


def _adopt_first(
    request: MeasurementRecordAdoptionRequest,
    *,
    storage_root: Path,
    content_root: str | Path | None,
) -> MeasurementRecordAdoptionRun:
    legacy_run = record_legacy_measurement_run_from_request(
        LegacyRunRecordRequest(
            request_id=request.request_id,
            approval_state=request.approval_state,
            record_id=request.record_id,
            record_dir=request.record_dir,
            legacy_system_id=request.legacy_system_id or "",
            legacy_run_id=request.legacy_run_id or "",
            created_at=request.created_at,
            label=request.label,
            experiment_type=request.experiment_type,
            run_started_at=request.run_started_at,
            run_completed_at=request.run_completed_at,
            locators=tuple(locator.to_legacy_locator() for locator in request.locators),
            operator_notes=request.operator_notes,
        ),
        storage_root=storage_root,
    )
    if not legacy_run.recorded:
        return MeasurementRecordAdoptionRun(
            request=request,
            storage_root=storage_root,
            legacy_run=legacy_run,
            adoption_error=legacy_run.record_error,
        )

    handle = canonical_record_handle(request.record_id, has_read_model=False)
    primary_data = None
    adoption_error = None
    if request.import_source is not None:
        if content_root is None:
            return MeasurementRecordAdoptionRun(
                request=request,
                storage_root=storage_root,
                handle=handle,
                legacy_run=legacy_run,
                adoption_error="adoption content_root is required for reviewed primary data",
            )
        primary_data = attach_converted_primary_data_to_legacy_record_from_request(
            LegacyPrimaryImportRequest(
                request_id=f"{request.request_id}-primary",
                approval_state=request.approval_state,
                record_id=request.record_id,
                record_dir=request.record_dir,
                legacy_receipt_path=f"{request.record_dir}/legacy-run-receipt.json",
                primary_data_path=f"{request.record_dir}/{PRIMARY_DATA_FILENAME}",
                writer_receipt_path=f"{request.record_dir}/{WRITER_RECEIPT_FILENAME}",
                finalization_receipt_path=(f"{request.record_dir}/{FINALIZATION_RECEIPT_FILENAME}"),
                read_model_path=request.read_model_path,
                import_source=request.import_source,
            ),
            content_root=content_root,
            storage_root=storage_root,
        )
        if primary_data.attached:
            handle = canonical_record_handle(request.record_id, has_read_model=True)
        else:
            adoption_error = primary_data.import_error

    recorded_references = _record_references_if_requested(request, storage_root)
    if recorded_references is not None and not recorded_references.recorded:
        adoption_error = adoption_error or recorded_references.references_error

    return MeasurementRecordAdoptionRun(
        request=request,
        storage_root=storage_root,
        handle=handle,
        legacy_run=legacy_run,
        primary_data=primary_data,
        recorded_references=recorded_references,
        adoption_error=adoption_error,
    )


def _import_ready(
    request: MeasurementRecordAdoptionRequest,
    *,
    storage_root: Path,
    content_root: str | Path | None,
) -> MeasurementRecordAdoptionRun:
    if request.import_source is None:
        return MeasurementRecordAdoptionRun(
            request=request,
            storage_root=storage_root,
            adoption_error="import-ready adoption requires import_source",
        )
    if content_root is None:
        return MeasurementRecordAdoptionRun(
            request=request,
            storage_root=storage_root,
            adoption_error="adoption content_root is required for reviewed primary data",
        )

    primary_data = import_measurement_record_from_request(
        MeasurementRecordDurableImportRequest(
            request_id=request.request_id,
            approval_state=request.approval_state,
            record_id=request.record_id,
            record_dir=request.record_dir,
            primary_data_path=f"{request.record_dir}/{PRIMARY_DATA_FILENAME}",
            writer_receipt_path=f"{request.record_dir}/{WRITER_RECEIPT_FILENAME}",
            finalization_receipt_path=f"{request.record_dir}/{FINALIZATION_RECEIPT_FILENAME}",
            read_model_path=request.read_model_path,
            import_source=request.import_source,
            creation_source_kind="import",
            label=request.label,
            experiment_type=request.experiment_type,
        ),
        content_root=content_root,
        storage_root=storage_root,
    )
    if not primary_data.imported:
        return MeasurementRecordAdoptionRun(
            request=request,
            storage_root=storage_root,
            primary_data=primary_data,
            adoption_error=primary_data.import_error,
        )

    recorded_references = _record_references_if_requested(request, storage_root)
    adoption_error = None
    if recorded_references is not None and not recorded_references.recorded:
        adoption_error = recorded_references.references_error

    return MeasurementRecordAdoptionRun(
        request=request,
        storage_root=storage_root,
        handle=canonical_record_handle(request.record_id, has_read_model=True),
        primary_data=primary_data,
        recorded_references=recorded_references,
        adoption_error=adoption_error,
    )


def _record_references_if_requested(
    request: MeasurementRecordAdoptionRequest,
    storage_root: Path,
) -> MeasurementRecordReferenceRun | None:
    if not request.references:
        return None
    return record_measurement_record_references_from_request(
        MeasurementRecordReferenceRequest(
            request_id=f"{request.request_id}-references",
            approval_state=request.approval_state,
            record_id=request.record_id,
            record_dir=request.record_dir,
            reference_set_id=request.reference_set_id or "references",
            references=request.references,
            operator_notes=request.reference_operator_notes,
        ),
        storage_root=storage_root,
    )
