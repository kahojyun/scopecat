from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat._planning.diagnostics import PlanningDiagnosticError
from scopecat.models.entity import EntityArray, EntityRef
from scopecat.models.parameter import (
    ParameterPatch,
    ParameterPatchValue,
    Quantity,
)
from scopecat.relations import (
    CellValue,
    EvalContext,
    ParameterRelationData,
    Row,
    ScalarExpr,
)
from scopecat.units import compatible_units

type ParameterPatchSpecKind = Literal[
    "set_scalar",
    "update_rows",
    "insert_rows",
    "delete_rows",
]


class ParameterPatchPlanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_index: int
    patch: ParameterPatch
    affected_rows: list[dict[str, ParameterPatchValue]] = Field(default_factory=list)


class ParameterPatchSpec(BaseModel):
    """Point-local parameter patch spec evaluated against a point row."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: ParameterPatchSpecKind
    parameter_id: str | None = None
    table_id: str | None = None
    key: dict[str, ScalarExpr] | None = None
    values: dict[str, ScalarExpr] | None = None
    rows: list[dict[str, ScalarExpr]] | None = None
    value: ScalarExpr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ParameterPatchSpec:
        if self.kind == "set_scalar":
            if self.parameter_id is None or self.value is None:
                msg = "set_scalar patch requires parameter_id and value"
                raise ValueError(msg)
            self._reject("table_id", "key", "values")
        elif self.kind == "update_rows":
            if self.table_id is None or self.key is None or self.values is None:
                msg = "update_rows patch requires table_id, key, and values"
                raise ValueError(msg)
            self._reject("parameter_id", "rows", "value")
        elif self.kind == "insert_rows":
            if self.table_id is None or not self.rows:
                msg = "insert_rows patch requires table_id and rows"
                raise ValueError(msg)
            self._reject("parameter_id", "key", "values", "value")
        elif self.kind == "delete_rows":
            if self.table_id is None or self.key is None:
                msg = "delete_rows patch requires table_id and key"
                raise ValueError(msg)
            self._reject("parameter_id", "values", "rows", "value")
        return self

    def apply(
        self,
        *,
        point_index: int,
        ctx: EvalContext,
        params: ParameterRelationData,
        allow_table_row_changes: bool,
    ) -> ParameterPatchPlanRecord:
        if self.kind == "set_scalar":
            value = _required(self.value).eval(ctx)
            parameter_id = _required(self.parameter_id)
            current = params.scalars.get(parameter_id)
            if current is None:
                msg = f"unknown scalar parameter {parameter_id!r}"
                raise PlanningDiagnosticError(
                    "experiment_parameter_patch_scalar_missing",
                    msg,
                )
            _validate_patch_cell_compatible(
                current,
                value,
                path=parameter_id,
            )
            params.scalars[parameter_id] = value
            return ParameterPatchPlanRecord(
                point_index=point_index,
                patch=ParameterPatch(
                    kind=self.kind,
                    parameter_id=parameter_id,
                    value=_patch_value(value),
                ),
            )
        if self.kind == "update_rows":
            table_id = _required(self.table_id)
            key = {name: expr.eval(ctx) for name, expr in _required(self.key).items()}
            values = {
                name: expr.eval(ctx) for name, expr in _required(self.values).items()
            }
            row = _lookup_mutable_row(params, table_id, key)
            for column_id, value in values.items():
                _validate_patch_cell_compatible(
                    row.get(column_id),
                    value,
                    path=f"{table_id}.{column_id}",
                )
            row.update(values)
            return ParameterPatchPlanRecord(
                point_index=point_index,
                patch=ParameterPatch(
                    kind=self.kind,
                    table_id=table_id,
                    key=_patch_values(key),
                    values=_patch_values(values),
                ),
                affected_rows=[_patch_values(row)],
            )
        if self.kind == "insert_rows":
            _validate_experiment_table_row_change_allowed(
                allow_table_row_changes,
                patch_kind=self.kind,
            )
            table_id = _required(self.table_id)
            table_rows = _lookup_mutable_table(params, table_id)
            rows = [
                {name: expr.eval(ctx) for name, expr in row.items()}
                for row in _required(self.rows)
            ]
            table_rows.extend(dict(row) for row in rows)
            return ParameterPatchPlanRecord(
                point_index=point_index,
                patch=ParameterPatch(
                    kind=self.kind,
                    table_id=table_id,
                    rows=[_patch_values(row) for row in rows],
                ),
                affected_rows=[_patch_values(row) for row in rows],
            )
        if self.kind == "delete_rows":
            _validate_experiment_table_row_change_allowed(
                allow_table_row_changes,
                patch_kind=self.kind,
            )
            table_id = _required(self.table_id)
            key = {name: expr.eval(ctx) for name, expr in _required(self.key).items()}
            rows = _lookup_mutable_table(params, table_id)
            row = _lookup_mutable_row(params, table_id, key)
            affected_row = dict(row)
            rows.remove(row)
            return ParameterPatchPlanRecord(
                point_index=point_index,
                patch=ParameterPatch(
                    kind=self.kind,
                    table_id=table_id,
                    key=_patch_values(key),
                ),
                affected_rows=[_patch_values(affected_row)],
            )
        msg = f"unsupported parameter patch kind: {self.kind}"
        raise ValueError(msg)

    def _reject(self, *field_names: str) -> None:
        unexpected = [
            field_name
            for field_name in field_names
            if getattr(self, field_name) is not None
        ]
        if unexpected:
            msg = f"{self.kind} patch cannot contain: {', '.join(unexpected)}"
            raise ValueError(msg)


def _lookup_mutable_row(
    params: ParameterRelationData,
    table_id: str,
    key: dict[str, CellValue],
) -> Row:
    rows = _lookup_mutable_table(params, table_id)
    matches = [
        row
        for row in rows
        if all(_cell_matches(row.get(column), value) for column, value in key.items())
    ]
    if not matches:
        msg = f"{table_id!r} key {key!r} matched no rows"
        raise PlanningDiagnosticError(
            "experiment_parameter_patch_row_not_found",
            msg,
        )
    if len(matches) > 1:
        msg = f"{table_id!r} key {key!r} matched {len(matches)} rows"
        raise PlanningDiagnosticError(
            "experiment_parameter_patch_row_ambiguous",
            msg,
        )
    return matches[0]


def _lookup_mutable_table(params: ParameterRelationData, table_id: str) -> list[Row]:
    try:
        return params.tables[table_id]
    except KeyError as exc:
        msg = f"unknown parameter table {table_id!r}"
        raise PlanningDiagnosticError(
            "experiment_parameter_patch_table_missing",
            msg,
        ) from exc


def _validate_experiment_table_row_change_allowed(
    allow_table_row_changes: bool,
    *,
    patch_kind: str,
) -> None:
    if not allow_table_row_changes:
        msg = f"{patch_kind} patches require explicit table row change opt-in"
        raise PlanningDiagnosticError(
            "experiment_parameter_patch_row_change_not_allowed",
            msg,
        )


def _patch_values(values: dict[str, CellValue]) -> dict[str, ParameterPatchValue]:
    return {key: _patch_value(value) for key, value in values.items()}


def _patch_value(value: CellValue) -> ParameterPatchValue:
    if isinstance(value, EntityArray | EntityRef):
        msg = "entity values are not valid parameter patch values"
        raise TypeError(msg)
    return value


def _cell_matches(left: CellValue, right: CellValue) -> bool:
    if isinstance(left, EntityRef) and isinstance(right, str):
        return left.id == right
    if isinstance(left, str) and isinstance(right, EntityRef):
        return left == right.id
    return left == right


def _validate_patch_cell_compatible(
    current: CellValue,
    value: CellValue,
    *,
    path: str,
) -> None:
    current_type = _patch_cell_type(current)
    value_type = _patch_cell_type(value)
    if current_type != value_type:
        msg = f"{path} value type {value_type!r} is incompatible with {current_type!r}"
        raise PlanningDiagnosticError(
            "experiment_parameter_patch_type_incompatible",
            msg,
        )
    if (
        isinstance(current, Quantity)
        and isinstance(value, Quantity)
        and not compatible_units(current.unit, value.unit)
    ):
        msg = f"{path} unit {value.unit!r} is incompatible with {current.unit!r}"
        raise PlanningDiagnosticError(
            "experiment_parameter_patch_unit_incompatible",
            msg,
        )


def _patch_cell_type(value: CellValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, Quantity):
        return "quantity"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "object"


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value
