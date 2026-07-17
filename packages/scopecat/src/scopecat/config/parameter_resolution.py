"""Validate and resolve unified parameter snapshots for execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.model import (
    CellValue,
    Row,
)
from scopecat.config.validation import (
    ParameterValueValidationError,
    coerce_stored_parameter_value,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterSnapshot,
    ScalarParameterValue,
    SeriesParameterValue,
    StoredParameterValue,
)


@dataclass(frozen=True, slots=True)
class ResolvedConfigParameters:
    """Transient executable parameter data and validation findings."""

    data: ParameterRelationData
    problems: tuple[Problem, ...]


def validate_parameter_snapshot(
    catalog: ParameterCatalog,
    snapshot: ParameterSnapshot,
) -> tuple[Problem, ...]:
    """Cross-validate a durable snapshot against its catalog."""

    _normalized, problems = _normalize_snapshot(catalog, snapshot)
    return problems


def resolve_config_parameters(
    config: ConfigProfileSnapshot,
) -> ResolvedConfigParameters:
    """Normalize config parameters and project them into executable data."""

    normalized, problems = _normalize_snapshot(
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
        problems=problems,
    )


def _normalize_snapshot(
    catalog: ParameterCatalog,
    snapshot: ParameterSnapshot,
) -> tuple[tuple[StoredParameterValue, ...], tuple[Problem, ...]]:
    definitions = {definition.id: definition for definition in catalog.definitions}
    stored = {value.id: value for value in snapshot.values}
    problems: list[Problem] = []

    for definition in catalog.definitions:
        if definition.id not in stored:
            problems.append(
                _problem(
                    "missing_parameter_value",
                    f"parameter value {definition.id} is missing",
                    ("values",),
                    details={"parameter_id": definition.id},
                )
            )

    normalized: list[StoredParameterValue] = []
    for value in snapshot.values:
        definition = definitions.get(value.id)
        path = ("values", value.id)
        if definition is None:
            problems.append(
                _problem(
                    "unknown_parameter_definition",
                    f"parameter value {value.id} has no definition",
                    path,
                    details={"parameter_id": value.id},
                )
            )
            continue
        try:
            selected = coerce_stored_parameter_value(
                definition,
                value,
                path=("parameter_snapshot", *path),
            )
        except ParameterValueValidationError as error:
            problems.append(
                _problem(
                    error.code,
                    str(error),
                    (
                        error.path[1:]
                        if error.path and error.path[0] == "parameter_snapshot"
                        else error.path or path
                    ),
                    details={"parameter_id": value.id},
                )
            )
            continue
        normalized.append(selected)
    return tuple(normalized), tuple(problems)


def _problem(
    code: str,
    message: str,
    path: tuple[str | int, ...],
    *,
    details: dict[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("parameter_snapshot", *path),
        details=details,
    )
