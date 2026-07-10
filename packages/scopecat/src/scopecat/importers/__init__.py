"""Untrusted parameter drafts and their explicit acceptance boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scopecat._parameter_resolution import validate_parameter_snapshot
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.models.artifact import RunArtifactEntry
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterSnapshot,
    ScalarParameterValue,
    SeriesParameterValue,
    StoredParameterValue,
    TableParameterValue,
)
from scopecat.parameter_validation import coerce_stored_parameter_value

ImportSourceKind = Literal["csv", "xlsx", "json", "registry", "legacy", "manual"]


class ImportSourceLocation(BaseModel):
    """External coordinates used to explain where a draft value came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_uri: str
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)
    column: str | int | None = None
    path: str | None = None


class ImportDiagnostic(BaseModel):
    """An importer or catalog diagnostic tied to its external source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: DiagnosticSeverity
    code: str
    message: str
    location: ImportSourceLocation | None = None


class ScalarParameterDraftValue(BaseModel):
    """An untyped scalar value parsed by an importer."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["scalar"] = "scalar"
    id: str
    value: Any
    location: ImportSourceLocation
    metadata: dict[str, Any] = Field(default_factory=dict)


class SeriesParameterDraftValue(BaseModel):
    """An untyped ordered series parsed by an importer."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["series"] = "series"
    id: str
    items: list[Any] = Field(default_factory=list)
    location: ImportSourceLocation
    item_locations: list[ImportSourceLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_item_locations(self) -> SeriesParameterDraftValue:
        if self.item_locations and len(self.item_locations) != len(self.items):
            msg = "item_locations must be empty or match items length"
            raise ValueError(msg)
        return self


class TableParameterDraftValue(BaseModel):
    """An untyped table parsed by an importer."""

    model_config = ConfigDict(extra="forbid")

    shape: Literal["table"] = "table"
    id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    location: ImportSourceLocation
    row_locations: list[ImportSourceLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_row_locations(self) -> TableParameterDraftValue:
        if self.row_locations and len(self.row_locations) != len(self.rows):
            msg = "row_locations must be empty or match rows length"
            raise ValueError(msg)
        return self


type DraftParameterValue = Annotated[
    ScalarParameterDraftValue | SeriesParameterDraftValue | TableParameterDraftValue,
    Field(discriminator="shape"),
]


class ParameterDraft(BaseModel):
    """Raw importer output that has not been accepted as a parameter snapshot."""

    model_config = ConfigDict(extra="forbid")

    id: str
    values: list[DraftParameterValue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParameterImportResult(BaseModel):
    """An importer result containing a draft, provenance, and findings."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source_kind: ImportSourceKind
    source_uri: str
    draft: ParameterDraft
    artifacts: list[RunArtifactEntry] = Field(default_factory=list)
    diagnostics: list[ImportDiagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_blocking_diagnostics(self) -> bool:
        return _has_blocking_diagnostics(self.diagnostics)


class ParameterImportRejected(ValueError):
    """A parameter draft could not cross the accepted-state boundary."""

    diagnostics: tuple[ImportDiagnostic, ...]

    def __init__(self, diagnostics: Sequence[ImportDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        codes = ", ".join(diagnostic.code for diagnostic in self.diagnostics)
        super().__init__(f"parameter import was rejected: {codes}")


def parameter_import_result(
    *,
    id: str,  # noqa: A002
    source_kind: ImportSourceKind,
    source_uri: str,
    values: Sequence[DraftParameterValue] = (),
    artifacts: Sequence[RunArtifactEntry] = (),
    diagnostics: Sequence[ImportDiagnostic] = (),
    draft_metadata: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ParameterImportResult:
    """Build a raw draft without implying that its values are accepted."""

    return ParameterImportResult(
        id=id,
        source_kind=source_kind,
        source_uri=source_uri,
        draft=ParameterDraft(
            id=f"{id}.draft",
            values=list(values),
            metadata=dict(draft_metadata or {}),
        ),
        artifacts=list(artifacts),
        diagnostics=list(diagnostics),
        metadata=dict(metadata or {}),
    )


def accept_parameter_import(
    result: ParameterImportResult,
    catalog: ParameterCatalog,
    *,
    snapshot_id: str | None = None,
) -> ParameterSnapshot:
    """Validate and freeze an imported draft into an accepted parameter snapshot.

    Importer diagnostics are checked first. The raw values are then represented
    as stored values and cross-validated against the catalog. No snapshot is
    returned if either stage reports an error or blocker.
    """

    if result.has_blocking_diagnostics:
        raise ParameterImportRejected(_blocking_diagnostics(result.diagnostics))

    stored_values: list[StoredParameterValue] = []
    for draft_value in result.draft.values:
        try:
            stored_values.append(_to_stored_parameter_value(draft_value))
        except (TypeError, ValueError) as error:
            raise ParameterImportRejected(
                [
                    ImportDiagnostic(
                        severity="error",
                        code="invalid_imported_parameter_value",
                        message=str(error),
                        location=_draft_validation_error_location(
                            draft_value,
                            error,
                        ),
                    )
                ]
            ) from error

    duplicate_diagnostics = _duplicate_value_diagnostics(result.draft.values)
    if duplicate_diagnostics:
        raise ParameterImportRejected(duplicate_diagnostics)

    try:
        candidate = ParameterSnapshot(
            id=snapshot_id or f"{result.id}.snapshot",
            values=stored_values,
            metadata={
                **result.draft.metadata,
                "import_id": result.id,
                "import_source_kind": result.source_kind,
                "import_source_uri": result.source_uri,
            },
        )
    except (TypeError, ValueError) as error:
        raise ParameterImportRejected(
            [
                ImportDiagnostic(
                    severity="error",
                    code="invalid_parameter_draft_metadata",
                    message=str(error),
                    location=ImportSourceLocation(source_uri=result.source_uri),
                )
            ]
        ) from error
    draft_values = {draft_value.id: draft_value for draft_value in result.draft.values}
    catalog_diagnostics = tuple(
        _import_diagnostic_from_catalog(
            diagnostic,
            drafts=draft_values,
            fallback=ImportSourceLocation(source_uri=result.source_uri),
        )
        for diagnostic in validate_parameter_snapshot(catalog, candidate)
    )
    if _has_blocking_diagnostics(catalog_diagnostics):
        raise ParameterImportRejected(_blocking_diagnostics(catalog_diagnostics))

    normalized: list[StoredParameterValue] = []
    for stored in candidate.values:
        definition = catalog.get(stored.id)
        if definition is None:
            # An unknown definition is a blocking catalog diagnostic above.
            continue
        normalized.append(
            coerce_stored_parameter_value(
                definition,
                stored,
                path=f"parameter_snapshot.values.{stored.id}",
            )
        )
    return ParameterSnapshot(
        id=candidate.id,
        values=normalized,
        metadata=candidate.metadata,
    )


def import_diagnostic(
    *,
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    location: ImportSourceLocation | None = None,
) -> ImportDiagnostic:
    return ImportDiagnostic(
        severity=severity,
        code=code,
        message=message,
        location=location,
    )


def _to_stored_parameter_value(
    draft: DraftParameterValue,
) -> StoredParameterValue:
    metadata: dict[str, Any] = {
        **draft.metadata,
        "import_location": _location_metadata(draft.location),
    }
    if isinstance(draft, ScalarParameterDraftValue):
        return ScalarParameterValue(
            id=draft.id,
            value=draft.value,
            metadata=metadata,
        )
    if isinstance(draft, SeriesParameterDraftValue):
        if draft.item_locations:
            metadata["import_item_locations"] = [
                _location_metadata(location) for location in draft.item_locations
            ]
        return SeriesParameterValue(
            id=draft.id,
            items=draft.items,
            metadata=metadata,
        )
    if draft.row_locations:
        metadata["import_row_locations"] = [
            _location_metadata(location) for location in draft.row_locations
        ]
    return TableParameterValue(
        id=draft.id,
        rows=draft.rows,
        metadata=metadata,
    )


def _duplicate_value_diagnostics(
    values: Sequence[DraftParameterValue],
) -> tuple[ImportDiagnostic, ...]:
    seen: set[str] = set()
    diagnostics: list[ImportDiagnostic] = []
    for value in values:
        if value.id in seen:
            diagnostics.append(
                ImportDiagnostic(
                    severity="error",
                    code="duplicate_imported_parameter_id",
                    message=f"parameter draft contains duplicate id {value.id!r}",
                    location=value.location,
                )
            )
        seen.add(value.id)
    return tuple(diagnostics)


def _import_diagnostic_from_catalog(
    diagnostic: Diagnostic,
    *,
    drafts: Mapping[str, DraftParameterValue],
    fallback: ImportSourceLocation,
) -> ImportDiagnostic:
    location = fallback
    if diagnostic.path is not None:
        prefix = "parameter_snapshot.values."
        if diagnostic.path.startswith(prefix):
            remainder = diagnostic.path.removeprefix(prefix)
            for parameter_id in sorted(drafts, key=len, reverse=True):
                if remainder == parameter_id or remainder.startswith(
                    f"{parameter_id}."
                ):
                    suffix = remainder.removeprefix(parameter_id).removeprefix(".")
                    location = _draft_path_location(drafts[parameter_id], suffix)
                    break
    return ImportDiagnostic(
        severity=diagnostic.severity,
        code=diagnostic.code,
        message=diagnostic.message,
        location=location,
    )


def _draft_validation_error_location(
    draft: DraftParameterValue,
    error: TypeError | ValueError,
) -> ImportSourceLocation:
    if not isinstance(error, ValidationError):
        return draft.location
    for finding in error.errors():
        parts = tuple(str(part) for part in finding["loc"])
        location = _draft_parts_location(draft, parts)
        if location is not None:
            return location
    return draft.location


def _draft_path_location(
    draft: DraftParameterValue,
    suffix: str,
) -> ImportSourceLocation:
    selected = _draft_parts_location(draft, tuple(suffix.split(".")))
    return draft.location if selected is None else selected


def _draft_parts_location(
    draft: DraftParameterValue,
    parts: tuple[str, ...],
) -> ImportSourceLocation | None:
    if isinstance(draft, SeriesParameterDraftValue) and draft.item_locations:
        index = _collection_index(parts, "items")
        if index is not None and index < len(draft.item_locations):
            return draft.item_locations[index]
    if isinstance(draft, TableParameterDraftValue) and draft.row_locations:
        index = _collection_index(parts, "rows")
        if index is not None and index < len(draft.row_locations):
            return draft.row_locations[index]
    return None


def _collection_index(parts: tuple[str, ...], collection: str) -> int | None:
    try:
        selected = parts.index(collection) + 1
    except ValueError:
        return None
    if selected >= len(parts):
        return None
    try:
        return int(parts[selected])
    except ValueError:
        return None


def _has_blocking_diagnostics(
    diagnostics: Sequence[ImportDiagnostic],
) -> bool:
    return any(
        diagnostic.severity in {"error", "blocker"} for diagnostic in diagnostics
    )


def _blocking_diagnostics(
    diagnostics: Sequence[ImportDiagnostic],
) -> tuple[ImportDiagnostic, ...]:
    return tuple(
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.severity in {"error", "blocker"}
    )


def _location_metadata(location: ImportSourceLocation) -> dict[str, Any]:
    return location.model_dump(mode="json", exclude_none=True)


__all__ = [
    "DraftParameterValue",
    "ImportDiagnostic",
    "ImportSourceKind",
    "ImportSourceLocation",
    "ParameterDraft",
    "ParameterImportRejected",
    "ParameterImportResult",
    "ScalarParameterDraftValue",
    "SeriesParameterDraftValue",
    "TableParameterDraftValue",
    "accept_parameter_import",
    "import_diagnostic",
    "parameter_import_result",
]
