"""Apply typed point-local parameter overlays during transient planning."""

from __future__ import annotations

from typing import cast

from scopecat._compiler.parameter_overlays import PointParameterOverlay
from scopecat._planning.diagnostics import PlanningDiagnosticError
from scopecat._relations import CellValue, EvalContext, ParameterRelationData
from scopecat._scalar_operators import runtime_values_equal
from scopecat.models.entity import EntityRef, same_entity_identity
from scopecat.value_types import Scalar
from scopecat.value_validation import ValueValidationError, coerce_literal


def apply_point_parameter_overlay(
    overlay: PointParameterOverlay,
    *,
    ctx: EvalContext,
    params: ParameterRelationData,
) -> None:
    """Apply one catalog-typed cell replacement to a point-local environment."""

    try:
        rows = params.tables[overlay.table_id]
    except KeyError as error:
        msg = f"unknown parameter table {overlay.table_id!r}"
        raise PlanningDiagnosticError(
            "experiment_parameter_overlay_table_missing",
            msg,
        ) from error

    key = {
        column_id: _coerce_overlay_value(
            expression.expr.eval(ctx),
            expression.value_type,
            code="experiment_parameter_overlay_key_invalid",
            path=f"{overlay.table_id}.key.{column_id}",
        )
        for column_id, expression in overlay.key.items()
    }
    matches = [
        row
        for row in rows
        if all(
            _cell_matches(row.get(column_id), value) for column_id, value in key.items()
        )
    ]
    if not matches:
        msg = f"{overlay.table_id!r} key {key!r} matched no rows"
        raise PlanningDiagnosticError(
            "experiment_parameter_overlay_row_not_found",
            msg,
        )
    if len(matches) > 1:
        msg = f"{overlay.table_id!r} key {key!r} matched {len(matches)} rows"
        raise PlanningDiagnosticError(
            "experiment_parameter_overlay_row_ambiguous",
            msg,
        )

    row = matches[0]
    if overlay.column_id not in row:
        msg = (
            f"parameter table {overlay.table_id!r} row does not contain "
            f"column {overlay.column_id!r}"
        )
        raise PlanningDiagnosticError(
            "experiment_parameter_overlay_column_missing",
            msg,
        )
    _coerce_overlay_value(
        row[overlay.column_id],
        overlay.value.value_type,
        code="experiment_parameter_overlay_resolved_value_invalid",
        path=f"{overlay.table_id}.{overlay.column_id}",
    )
    row[overlay.column_id] = _coerce_overlay_value(
        overlay.value.expr.eval(ctx),
        overlay.value.value_type,
        code="experiment_parameter_overlay_value_invalid",
        path=f"{overlay.table_id}.{overlay.column_id}",
    )


def _coerce_overlay_value(
    value: object,
    value_type: Scalar,
    *,
    code: str,
    path: str,
) -> CellValue:
    try:
        return cast("CellValue", coerce_literal(value_type, value, path=path))
    except ValueValidationError as error:
        raise PlanningDiagnosticError(code, str(error)) from error


def _cell_matches(left: CellValue | None, right: CellValue) -> bool:
    if isinstance(left, EntityRef) and isinstance(right, EntityRef):
        return same_entity_identity(left, right)
    try:
        return runtime_values_equal(left, right)
    except TypeError:
        return False


__all__ = ["apply_point_parameter_overlay"]
