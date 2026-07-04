"""Anti-corruption records for external parameter imports."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.diagnostics import DiagnosticSeverity
from scopecat.models.artifact import RunArtifactEntry
from scopecat.models.parameter import (
    ParameterState,
    ParameterTable,
    ParameterValue,
    ParameterValueSet,
    Quantity,
)

ImportSourceKind = Literal["csv", "xlsx", "json", "registry", "legacy", "manual"]


class ImportSourceLocation(BaseModel):
    """External source coordinates for importer diagnostics and provenance."""

    model_config = ConfigDict(extra="forbid")

    source_uri: str
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)
    column: str | int | None = None
    path: str | None = None


class ImportDiagnostic(BaseModel):
    """Diagnostic tied to the exact external source location when available."""

    model_config = ConfigDict(extra="forbid")

    severity: DiagnosticSeverity
    code: str
    message: str
    location: ImportSourceLocation | None = None


class ImportedScalarParameter(BaseModel):
    """Scalar parameter candidate parsed from an external source."""

    model_config = ConfigDict(extra="forbid")

    id: str
    quantity: Quantity
    location: ImportSourceLocation
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_value(self) -> ParameterValue:
        return ParameterValue(
            id=self.id,
            quantity=self.quantity,
            metadata={
                **self.metadata,
                "import_location": _location_metadata(self.location),
            },
        )


class ImportedParameterTable(BaseModel):
    """Table parameter candidate parsed from an external source."""

    model_config = ConfigDict(extra="forbid")

    id: str
    rows: list[dict[str, Any]]
    location: ImportSourceLocation
    row_locations: list[ImportSourceLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_row_locations(self) -> ImportedParameterTable:
        if self.row_locations and len(self.row_locations) != len(self.rows):
            msg = "row_locations must be empty or match rows length"
            raise ValueError(msg)
        return self

    def to_table(self) -> ParameterTable:
        metadata = {
            **self.metadata,
            "import_location": _location_metadata(self.location),
        }
        if self.row_locations:
            metadata["import_row_locations"] = [
                _location_metadata(location) for location in self.row_locations
            ]
        return ParameterTable(id=self.id, rows=self.rows, metadata=metadata)


class ParameterImportResult(BaseModel):
    """Typed output from importer boundaries before review or activation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.parameter_import_result.v1"] = (
        "scopecat.parameter_import_result.v1"
    )
    id: str
    source_kind: ImportSourceKind
    source_uri: str
    parameter_state: ParameterState
    artifacts: list[RunArtifactEntry] = Field(default_factory=list)
    diagnostics: list[ImportDiagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(
            diagnostic.severity in {"error", "blocker"}
            for diagnostic in self.diagnostics
        )


def parameter_import_result(
    *,
    id: str,  # noqa: A002
    source_kind: ImportSourceKind,
    source_uri: str,
    scalars: list[ImportedScalarParameter] | None = None,
    tables: list[ImportedParameterTable] | None = None,
    artifacts: list[RunArtifactEntry] | None = None,
    diagnostics: list[ImportDiagnostic] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ParameterImportResult:
    return ParameterImportResult(
        id=id,
        source_kind=source_kind,
        source_uri=source_uri,
        parameter_state=ParameterState(
            id=f"{id}.state",
            scalar_values=ParameterValueSet(
                id=f"{id}.scalars",
                values=[scalar.to_value() for scalar in scalars or []],
            ),
            tables=[table.to_table() for table in tables or []],
            metadata={
                "import_source_kind": source_kind,
                "import_source_uri": source_uri,
            },
        ),
        artifacts=artifacts or [],
        diagnostics=diagnostics or [],
        metadata=metadata or {},
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


def _location_metadata(location: ImportSourceLocation) -> dict[str, Any]:
    return location.model_dump(mode="json", exclude_none=True)


__all__ = [
    "ImportDiagnostic",
    "ImportSourceKind",
    "ImportSourceLocation",
    "ImportedParameterTable",
    "ImportedScalarParameter",
    "ParameterImportResult",
    "import_diagnostic",
    "parameter_import_result",
]
