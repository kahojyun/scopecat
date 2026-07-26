"""Typed point-local parameter overlays and config-binding semantics."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.diagnostics import CompilerProblemError, compiler_problem
from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
)
from scopecat.compiler.relations.specialization import (
    KnownScalar,
    ParameterCellBinding,
    residual_scalar_expression,
    specialize_scalar,
)
from scopecat.compiler.relations.uses import (
    RelationUse,
    RelationUseId,
)
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.graph.relations.analysis import PlanNode
from scopecat.graph.relations.model import (
    CellValue,
    ScalarExpr,
)
from scopecat.graph.relations.operators import runtime_values_equal
from scopecat.kernel.entity import (
    EntityRef,
    same_entity_identity,
)
from scopecat.kernel.problems import ModelLocation, model_location
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_validation import ValueValidationError, coerce_literal

type RelationPlanResolver = Callable[[RelationUseId], VerifiedRelationPlan[PlanNode]]


@dataclass(frozen=True, slots=True)
class PointParameterOverlay:
    """Replace one existing parameter-table cell for each experiment point.

    This is transient compiler intent, not a durable parameter edit or change
    record.  Its deliberately narrow shape prevents an experiment from adding
    or deleting rows, or from mutating scalar configuration values.
    """

    table_id: str
    key_uses: dict[str, RelationUse[ScalarValueExpr]]
    column_id: str
    value_use: RelationUse[ScalarValueExpr]

    def __post_init__(self) -> None:
        if not self.table_id or not self.column_id or not self.key_uses:
            msg = "parameter overlay table, column, and key must be non-empty"
            raise ValueError(msg)
        object.__setattr__(self, "key_uses", dict(self.key_uses))


def resolve_point_parameters(
    base: ParameterRelationData,
    overlays: Sequence[PointParameterOverlay],
    *,
    point_row: Mapping[str, CellValue],
    relation_plan: RelationPlanResolver,
) -> ParameterRelationData:
    """Resolve lexical parameter bindings for one logical point."""

    resolved = base
    for overlay in overlays:
        resolved = _apply_point_parameter_overlay(
            overlay,
            ctx=EvalContext(params=resolved, point_row=dict(point_row)),
            params=resolved,
            relation_plan=relation_plan,
        )
    return resolved


def resolve_parameter_cell_bindings(
    overlays: Sequence[PointParameterOverlay],
    *,
    known: EvalContext,
) -> tuple[ParameterCellBinding, ...]:
    """Residualize statically identified point-driven parameter cells."""

    selected: list[ParameterCellBinding] = []
    for overlay in overlays:
        key_results = {
            column_id: specialize_scalar(
                use.value.plan.root,
                known=known,
                parameter_cells=selected,
            )
            for column_id, use in overlay.key_uses.items()
        }
        if not all(isinstance(result, KnownScalar) for result in key_results.values()):
            continue
        key = {
            column_id: cast("KnownScalar", result).value
            for column_id, result in key_results.items()
        }
        try:
            row = known.params.lookup_row(overlay.table_id, key)
        except KeyError, TypeError, ValueError:
            continue
        if overlay.column_id not in row:
            continue
        replacement = residual_scalar_expression(
            specialize_scalar(
                overlay.value_use.value.plan.root,
                known=known,
                parameter_cells=selected,
            )
        )
        binding = ParameterCellBinding(
            table_id=overlay.table_id,
            key=tuple(
                (column_id, deepcopy(row[column_id])) for column_id in sorted(key)
            ),
            column_id=overlay.column_id,
            replacement=replacement,
        )
        selected = [
            existing
            for existing in selected
            if not (
                existing.table_id == binding.table_id
                and existing.column_id == binding.column_id
                and existing.key == binding.key
            )
        ]
        selected.append(binding)
    return tuple(selected)


def _apply_point_parameter_overlay(
    overlay: PointParameterOverlay,
    *,
    ctx: EvalContext,
    params: ParameterRelationData,
    relation_plan: RelationPlanResolver,
) -> ParameterRelationData:
    """Return one binding set with a typed point-local cell override."""

    try:
        rows = params.table_rows(overlay.table_id)
    except KeyError as error:
        msg = f"unknown parameter table {overlay.table_id!r}"
        raise CompilerProblemError(
            compiler_problem(
                "experiment_parameter_overlay_table_missing",
                msg,
                model_location("parameters", overlay.table_id),
            )
        ) from error

    key = {
        column_id: _coerce_overlay_value(
            evaluate_scalar(
                cast(
                    "VerifiedRelationPlan[ScalarExpr]",
                    relation_plan(use.id),
                ),
                ctx,
            ),
            use.value.value_type,
            code="experiment_parameter_overlay_key_invalid",
            location=model_location(
                "parameters",
                overlay.table_id,
                "key",
                column_id,
            ),
        )
        for column_id, use in overlay.key_uses.items()
    }
    matches = [
        (row_index, row)
        for row_index, row in enumerate(rows)
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
            )
        )
    if len(matches) > 1:
        msg = f"{overlay.table_id!r} key {key!r} matched {len(matches)} rows"
        raise CompilerProblemError(
            compiler_problem(
                "experiment_parameter_overlay_row_ambiguous",
                msg,
                model_location("parameters", overlay.table_id),
                details={"match_count": len(matches)},
            )
        )

    row_index, row = matches[0]
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
            )
        )
    _coerce_overlay_value(
        row[overlay.column_id],
        overlay.value_use.value.value_type,
        code="experiment_parameter_overlay_resolved_value_invalid",
        location=model_location(
            "parameters",
            overlay.table_id,
            "columns",
            overlay.column_id,
        ),
    )
    return params.with_table_cell(
        overlay.table_id,
        row_index=row_index,
        column_id=overlay.column_id,
        value=_coerce_overlay_value(
            evaluate_scalar(
                cast(
                    "VerifiedRelationPlan[ScalarExpr]",
                    relation_plan(overlay.value_use.id),
                ),
                ctx,
            ),
            overlay.value_use.value.value_type,
            code="experiment_parameter_overlay_value_invalid",
            location=model_location(
                "parameters",
                overlay.table_id,
                "columns",
                overlay.column_id,
            ),
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
