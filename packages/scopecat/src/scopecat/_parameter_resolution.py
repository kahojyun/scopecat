"""Validate and resolve unified parameter snapshots for execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from scopecat._relations import CellValue, ParameterRelationData, Row
from scopecat.diagnostics import Diagnostic
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterSnapshot,
    ScalarParameterValue,
    SeriesParameterValue,
    StoredParameterValue,
)
from scopecat.parameter_validation import (
    ParameterValueValidationError,
    coerce_stored_parameter_value,
)


@dataclass(frozen=True, slots=True)
class ResolvedConfigParameters:
    """Transient executable parameter data and validation findings."""

    data: ParameterRelationData
    diagnostics: tuple[Diagnostic, ...]


def validate_parameter_snapshot(
    catalog: ParameterCatalog,
    snapshot: ParameterSnapshot,
) -> tuple[Diagnostic, ...]:
    """Cross-validate a durable snapshot against its catalog."""

    _normalized, diagnostics = _normalize_snapshot(catalog, snapshot)
    return diagnostics


def resolve_config_parameters(
    config: ConfigProfileSnapshot,
) -> ResolvedConfigParameters:
    """Normalize config parameters and project them into executable data."""

    normalized, diagnostics = _normalize_snapshot(
        config.parameter_catalog,
        config.parameter_snapshot,
    )
    scalars: dict[str, CellValue] = {}
    series: dict[str, list[CellValue]] = {}
    tables: dict[str, list[Row]] = {}
    for value in normalized:
        if isinstance(value, ScalarParameterValue):
            scalars[value.id] = cast("CellValue", value.value)
        elif isinstance(value, SeriesParameterValue):
            series[value.id] = [cast("CellValue", item) for item in value.items]
        else:
            tables[value.id] = [cast("Row", dict(row)) for row in value.rows]
    return ResolvedConfigParameters(
        data=ParameterRelationData(
            scalars=scalars,
            series=series,
            tables=tables,
        ),
        diagnostics=diagnostics,
    )


def _normalize_snapshot(
    catalog: ParameterCatalog,
    snapshot: ParameterSnapshot,
) -> tuple[tuple[StoredParameterValue, ...], tuple[Diagnostic, ...]]:
    definitions = {definition.id: definition for definition in catalog.definitions}
    stored = {value.id: value for value in snapshot.values}
    diagnostics: list[Diagnostic] = []

    for definition in catalog.definitions:
        if definition.id not in stored:
            diagnostics.append(
                _diagnostic(
                    "missing_parameter_value",
                    f"parameter value {definition.id} is missing",
                    "parameter_snapshot.values",
                )
            )

    normalized: list[StoredParameterValue] = []
    for value in snapshot.values:
        definition = definitions.get(value.id)
        path = f"parameter_snapshot.values.{value.id}"
        if definition is None:
            diagnostics.append(
                _diagnostic(
                    "unknown_parameter_definition",
                    f"parameter value {value.id} has no definition",
                    path,
                )
            )
            continue
        try:
            selected = coerce_stored_parameter_value(
                definition,
                value,
                path=path,
            )
        except ParameterValueValidationError as error:
            diagnostics.append(_diagnostic(error.code, str(error), error.path or path))
            continue
        normalized.append(selected)
    return tuple(normalized), tuple(diagnostics)


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = [
    "ResolvedConfigParameters",
    "resolve_config_parameters",
    "validate_parameter_snapshot",
]
