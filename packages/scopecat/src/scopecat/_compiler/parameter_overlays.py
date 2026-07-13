"""Typed point-local parameter overlays and config-binding semantics."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat._compiler.problems import CompilerProblemError, compiler_problem
from scopecat._relations import (
    CellValue,
    EvalContext,
    ParameterRelationData,
    ScalarExpr,
)
from scopecat._scalar_operators import runtime_values_equal
from scopecat.models.entity import EntityRef, same_entity_identity
from scopecat.problems import ModelLocation, ProblemCategory, model_location
from scopecat.value_types import Scalar
from scopecat.value_validation import ValueValidationError, coerce_literal


class TypedOverlayExpression(BaseModel):
    """One scalar expression paired with its catalog-declared target type."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    expr: ScalarExpr
    value_type: Scalar


class PointParameterOverlay(BaseModel):
    """Replace one existing parameter-table cell for each experiment point.

    This is transient compiler intent, not a durable parameter edit or change
    record.  Its deliberately narrow shape prevents an experiment from adding
    or deleting rows, or from mutating scalar configuration values.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    table_id: str
    key: dict[str, TypedOverlayExpression] = Field(min_length=1)
    column_id: str
    value: TypedOverlayExpression

    @model_validator(mode="after")
    def validate_target(self) -> PointParameterOverlay:
        if not self.table_id:
            msg = "parameter overlay table_id must be non-empty"
            raise ValueError(msg)
        if not self.column_id:
            msg = "parameter overlay column_id must be non-empty"
            raise ValueError(msg)
        return self


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
        raise CompilerProblemError(
            compiler_problem(
                "experiment_parameter_overlay_table_missing",
                msg,
                model_location("parameters", overlay.table_id),
                category=ProblemCategory.NOT_FOUND,
            )
        ) from error

    key = {
        column_id: _coerce_overlay_value(
            expression.expr.eval(ctx),
            expression.value_type,
            code="experiment_parameter_overlay_key_invalid",
            location=model_location(
                "parameters",
                overlay.table_id,
                "key",
                column_id,
            ),
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
        raise CompilerProblemError(
            compiler_problem(
                "experiment_parameter_overlay_row_not_found",
                msg,
                model_location("parameters", overlay.table_id),
                category=ProblemCategory.NOT_FOUND,
            )
        )
    if len(matches) > 1:
        msg = f"{overlay.table_id!r} key {key!r} matched {len(matches)} rows"
        raise CompilerProblemError(
            compiler_problem(
                "experiment_parameter_overlay_row_ambiguous",
                msg,
                model_location("parameters", overlay.table_id),
                category=ProblemCategory.CONFLICT,
                details={"match_count": len(matches)},
            )
        )

    row = matches[0]
    if overlay.column_id not in row:
        msg = (
            f"parameter table {overlay.table_id!r} row does not contain "
            f"column {overlay.column_id!r}"
        )
        raise CompilerProblemError(
            compiler_problem(
                "experiment_parameter_overlay_column_missing",
                msg,
                model_location(
                    "parameters",
                    overlay.table_id,
                    "columns",
                    overlay.column_id,
                ),
                category=ProblemCategory.NOT_FOUND,
            )
        )
    _coerce_overlay_value(
        row[overlay.column_id],
        overlay.value.value_type,
        code="experiment_parameter_overlay_resolved_value_invalid",
        location=model_location(
            "parameters",
            overlay.table_id,
            "columns",
            overlay.column_id,
        ),
    )
    row[overlay.column_id] = _coerce_overlay_value(
        overlay.value.expr.eval(ctx),
        overlay.value.value_type,
        code="experiment_parameter_overlay_value_invalid",
        location=model_location(
            "parameters",
            overlay.table_id,
            "columns",
            overlay.column_id,
        ),
    )


def _coerce_overlay_value(
    value: object,
    value_type: Scalar,
    *,
    code: str,
    location: ModelLocation,
) -> CellValue:
    try:
        return cast(
            "CellValue",
            coerce_literal(
                value_type,
                value,
                path=(location.root, *location.path),
            ),
        )
    except ValueValidationError as error:
        raise CompilerProblemError(
            compiler_problem(code, str(error), location)
        ) from error


def _cell_matches(left: CellValue | None, right: CellValue) -> bool:
    if isinstance(left, EntityRef) and isinstance(right, EntityRef):
        return same_entity_identity(left, right)
    try:
        return runtime_values_equal(left, right)
    except TypeError:
        return False


__all__ = [
    "PointParameterOverlay",
    "TypedOverlayExpression",
    "apply_point_parameter_overlay",
]
