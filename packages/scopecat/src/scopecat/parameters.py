"""parameter derivation recipes and accepted-state patch utilities."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat._parameter_patching import apply_parameter_patches, diff_parameter_states
from scopecat.models.parameter import (
    ParameterBuildSnapshot,
    ParameterCatalog,
    ParameterChangeSet,
    ParameterDefinition,
    ParameterPatch,
    ParameterState,
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    ParameterValue,
    ParameterValueSet,
    Quantity,
)
from scopecat.relations import ParameterRelationData, RelationExpr, ScalarExpr
from scopecat.units import compatible_units, to_base_value


class ScalarParameterDerivation(BaseModel):
    """Named scalar parameter derived from a deterministic scalar expression."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str
    expression: ScalarExpr

    def evaluate(self, params: ParameterRelationData) -> ParameterValue:
        value = self.expression.eval(params.to_context())
        if not isinstance(value, Quantity):
            msg = f"scalar derivation {self.id!r} must evaluate to a quantity"
            raise TypeError(msg)
        return ParameterValue(id=self.id, quantity=value)


class TableParameterDerivation(BaseModel):
    """Named table parameter derived from a deterministic relation expression."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str
    relation: RelationExpr

    def evaluate(self, params: ParameterRelationData) -> ParameterTable:
        return ParameterTable(id=self.id, rows=self.relation.evaluate(params))


class ParameterDerivationSet(BaseModel):
    """Deterministic parameter build recipe evaluated before planning."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_version: str = "scopecat.parameter_derivation_set.v1"
    id: str
    scalars: list[ScalarParameterDerivation] = Field(default_factory=list)
    tables: list[TableParameterDerivation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_outputs(self) -> ParameterDerivationSet:
        scalar_ids = [item.id for item in self.scalars]
        table_ids = [item.id for item in self.tables]
        duplicate_scalars = sorted(_duplicates(scalar_ids))
        duplicate_tables = sorted(_duplicates(table_ids))
        collisions = sorted(set(scalar_ids) & set(table_ids))
        if duplicate_scalars:
            msg = "duplicate scalar derivations: " + ", ".join(duplicate_scalars)
            raise ValueError(msg)
        if duplicate_tables:
            msg = "duplicate table derivations: " + ", ".join(duplicate_tables)
            raise ValueError(msg)
        if collisions:
            msg = "scalar/table derivation id collisions: " + ", ".join(collisions)
            raise ValueError(msg)
        return self

    def evaluate(
        self,
        params: ParameterRelationData,
    ) -> tuple[list[ParameterValue], list[ParameterTable]]:
        scalar_values: list[ParameterValue] = []
        tables: list[ParameterTable] = []
        working = params.model_copy(deep=True)
        for derivation in self.scalars:
            value = derivation.evaluate(working)
            working.scalars[value.id] = value.quantity
            scalar_values.append(value)
        for derivation in self.tables:
            table = derivation.evaluate(working)
            working.tables[table.id] = [dict(row) for row in table.rows]
            tables.append(table)
        return scalar_values, tables


PARAMETER_BUILD_IMPLEMENTATION_ID = "scopecat.parameter_build.local"
PARAMETER_BUILD_IMPLEMENTATION_VERSION = "v1"


def build_parameter_snapshot(
    *,
    catalog: ParameterCatalog,
    parameter_state: ParameterState,
    derivations: ParameterDerivationSet | None = None,
) -> ParameterBuildSnapshot:
    """Resolve accepted parameter inputs into an immutable build snapshot."""

    diagnostics: list[dict[str, Any]] = []
    scalar_by_id = {
        value.id: value for value in parameter_state.scalar_value_set().values
    }
    table_by_id = {table.id: table for table in parameter_state.tables}
    diagnostics.extend(
        _validate_parameter_state_against_catalog(
            catalog=catalog,
            scalar_values=list(scalar_by_id.values()),
            tables=list(table_by_id.values()),
        )
    )

    if derivations is not None:
        relation_params = ParameterRelationData(
            scalars={value.id: value.quantity for value in scalar_by_id.values()},
            tables={
                table.id: [dict(row) for row in table.rows]
                for table in table_by_id.values()
            },
        )
        try:
            derived_scalars, derived_tables = derivations.evaluate(relation_params)
        except Exception as error:
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "parameter_derivation_evaluation_failed",
                    f"parameter derivation {derivations.id} failed: {error}",
                    "parameter_derivations",
                )
            )
            derived_scalars = []
            derived_tables = []
        for value in derived_scalars:
            if value.id in scalar_by_id:
                diagnostics.append(
                    _parameter_diagnostic(
                        "info",
                        "derived_scalar_replaces_source",
                        f"derived scalar {value.id} replaces a source value",
                        f"parameter_build.scalar_values.{value.id}",
                    )
                )
            scalar_by_id[value.id] = value
        for table in derived_tables:
            if table.id in table_by_id:
                diagnostics.append(
                    _parameter_diagnostic(
                        "info",
                        "derived_table_replaces_source",
                        f"derived table {table.id} replaces a source table",
                        f"parameter_build.tables.{table.id}",
                    )
                )
            table_by_id[table.id] = table
        diagnostics.extend(
            _validate_parameter_state_against_catalog(
                catalog=catalog,
                scalar_values=derived_scalars,
                tables=derived_tables,
                path_prefix="parameter_derivations",
                validate_missing_catalog_values=False,
            )
        )

    catalog_hash = _model_hash(catalog)
    source_state_hash = _model_hash(parameter_state.model_dump(mode="json"))
    derivation_set_hash = _model_hash(derivations) if derivations is not None else None
    scalar_values = list(scalar_by_id.values())
    tables = list(table_by_id.values())
    content_hash = _parameter_build_content_hash(
        id=f"{parameter_state.id}-parameter-build",
        catalog_id=catalog.id,
        catalog_hash=catalog_hash,
        source_state_id=parameter_state.id,
        source_state_hash=source_state_hash,
        derivation_set_id=derivations.id if derivations is not None else None,
        derivation_set_hash=derivation_set_hash,
        scalar_values=scalar_values,
        tables=tables,
        diagnostics=diagnostics,
    )

    return ParameterBuildSnapshot(
        id=f"{parameter_state.id}-parameter-build",
        catalog_id=catalog.id,
        catalog_hash=catalog_hash,
        source_state_id=parameter_state.id,
        source_state_hash=source_state_hash,
        derivation_set_id=derivations.id if derivations is not None else None,
        derivation_set_hash=derivation_set_hash,
        content_hash=content_hash,
        build_implementation_id=PARAMETER_BUILD_IMPLEMENTATION_ID,
        build_implementation_version=PARAMETER_BUILD_IMPLEMENTATION_VERSION,
        scalar_values=scalar_values,
        tables=tables,
        diagnostics=diagnostics,
    )


def _parameter_build_content_hash(
    *,
    id: str,  # noqa: A002
    catalog_id: str,
    catalog_hash: str,
    source_state_id: str,
    source_state_hash: str,
    derivation_set_id: str | None,
    derivation_set_hash: str | None,
    scalar_values: list[ParameterValue],
    tables: list[ParameterTable],
    diagnostics: list[dict[str, Any]],
) -> str:
    return _payload_hash(
        {
            "schema_version": "scopecat.parameter_build_snapshot.v1",
            "id": id,
            "catalog_id": catalog_id,
            "catalog_hash": catalog_hash,
            "source_state_id": source_state_id,
            "source_state_hash": source_state_hash,
            "derivation_set_id": derivation_set_id,
            "derivation_set_hash": derivation_set_hash,
            "build_implementation_id": PARAMETER_BUILD_IMPLEMENTATION_ID,
            "build_implementation_version": PARAMETER_BUILD_IMPLEMENTATION_VERSION,
            "scalar_values": [value.model_dump(mode="json") for value in scalar_values],
            "tables": [table.model_dump(mode="json") for table in tables],
            "diagnostics": diagnostics,
        }
    )


def _model_hash(model: BaseModel | dict[str, Any]) -> str:
    payload = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    return _payload_hash(payload)


def _payload_hash(payload: dict[str, Any]) -> str:
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_parameter_state_against_catalog(
    *,
    catalog: ParameterCatalog,
    scalar_values: list[ParameterValue],
    tables: list[ParameterTable],
    path_prefix: str = "parameter_state",
    validate_missing_catalog_values: bool = True,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    scalar_definitions = {
        definition.id: definition for definition in catalog.scalar_definitions
    }
    table_definitions = {
        definition.id: definition for definition in catalog.table_definitions
    }
    scalar_value_ids = {value.id for value in scalar_values}

    if validate_missing_catalog_values:
        for definition in catalog.scalar_definitions:
            if definition.id not in scalar_value_ids:
                diagnostics.append(
                    _parameter_diagnostic(
                        "error",
                        "missing_parameter_value",
                        f"parameter value {definition.id} is missing",
                        f"{path_prefix}.scalar_values",
                    )
                )

    for value in scalar_values:
        definition = scalar_definitions.get(value.id)
        if definition is None:
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "unknown_parameter_value_definition",
                    f"parameter value {value.id} has no definition",
                    f"{path_prefix}.scalar_values",
                )
            )
            continue
        diagnostics.extend(
            _validate_parameter_value(definition, value, path_prefix=path_prefix)
        )

    for table in tables:
        definition = table_definitions.get(table.id)
        if definition is None:
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "unknown_parameter_table_definition",
                    f"parameter table {table.id} has no definition",
                    f"{path_prefix}.tables",
                )
            )
            continue
        diagnostics.extend(
            _validate_parameter_table(
                definition=definition,
                table=table,
                path_prefix=path_prefix,
            )
        )
    return diagnostics


def _validate_parameter_value(
    definition: ParameterDefinition,
    value: ParameterValue,
    *,
    path_prefix: str,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    path = f"{path_prefix}.scalar_values.{value.id}"
    if not compatible_units(definition.unit, value.quantity.unit):
        diagnostics.append(
            _parameter_diagnostic(
                "error",
                "incompatible_parameter_value_unit",
                f"parameter value {value.id} uses unit {value.quantity.unit}, "
                f"but definition uses {definition.unit}",
                path,
            )
        )
        return diagnostics
    if _outside_safety(value.quantity, definition.safety_min, definition.safety_max):
        diagnostics.append(
            _parameter_diagnostic(
                "error",
                "parameter_value_outside_safety_limits",
                f"parameter value {value.id} is outside safety limits",
                path,
            )
        )
    return diagnostics


def _validate_parameter_table(
    *,
    definition: ParameterTableDefinition,
    table: ParameterTable,
    path_prefix: str,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    columns = {column.id: column for column in definition.columns}
    required_columns = {column.id for column in definition.columns if column.required}
    seen_keys: set[tuple[str, ...]] = set()
    for row_index, row in enumerate(table.rows):
        path = f"{path_prefix}.tables.{table.id}.rows.{row_index}"
        missing = sorted(required_columns - row.keys())
        if missing:
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "missing_parameter_table_columns",
                    f"parameter table {table.id} row is missing columns: "
                    + ", ".join(missing),
                    path,
                )
            )
        extra = sorted(row.keys() - columns.keys())
        if extra:
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "unknown_parameter_table_columns",
                    f"parameter table {table.id} row contains unknown columns: "
                    + ", ".join(extra),
                    path,
                )
            )
        key_values = [row.get(column_id) for column_id in definition.primary_key]
        if any(value is None for value in key_values):
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "missing_parameter_table_primary_key",
                    f"parameter table {table.id} row is missing primary key values",
                    path,
                )
            )
        else:
            key = tuple(_build_key_part(value) for value in key_values)
            if key in seen_keys:
                diagnostics.append(
                    _parameter_diagnostic(
                        "error",
                        "duplicate_parameter_table_primary_key",
                        f"parameter table {table.id} has duplicate primary key {key}",
                        path,
                    )
                )
            seen_keys.add(key)

        for column_id, raw_value in row.items():
            column = columns.get(column_id)
            if column is None:
                continue
            diagnostics.extend(
                _validate_parameter_table_cell(
                    table_id=table.id,
                    column=column,
                    raw_value=raw_value,
                    path=f"{path}.{column_id}",
                )
            )
    return diagnostics


def _validate_parameter_table_cell(
    *,
    table_id: str,
    column: ParameterTableColumn,
    raw_value: object,
    path: str,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    if raw_value is None:
        if column.required:
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "missing_required_parameter_table_cell",
                    f"parameter table {table_id} column {column.id} is required",
                    path,
                )
            )
        return diagnostics
    if column.kind == "quantity":
        try:
            quantity = Quantity.model_validate(raw_value)
        except ValueError as error:
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "invalid_parameter_table_quantity",
                    f"parameter table {table_id} column {column.id} is not a "
                    f"valid quantity: {error}",
                    path,
                )
            )
            return diagnostics
        if column.unit is not None and not compatible_units(column.unit, quantity.unit):
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "incompatible_parameter_table_quantity_unit",
                    f"parameter table {table_id} column {column.id} uses unit "
                    f"{quantity.unit}, but definition uses {column.unit}",
                    path,
                )
            )
        return diagnostics
    if column.kind == "number":
        if not isinstance(raw_value, int | float) or isinstance(raw_value, bool):
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "invalid_parameter_table_number",
                    f"parameter table {table_id} column {column.id} must be numeric",
                    path,
                )
            )
        return diagnostics
    if column.kind == "string":
        if not isinstance(raw_value, str):
            diagnostics.append(
                _parameter_diagnostic(
                    "error",
                    "invalid_parameter_table_string",
                    f"parameter table {table_id} column {column.id} must be a string",
                    path,
                )
            )
        return diagnostics
    if column.kind == "bool" and not isinstance(raw_value, bool):
        diagnostics.append(
            _parameter_diagnostic(
                "error",
                "invalid_parameter_table_bool",
                f"parameter table {table_id} column {column.id} must be a bool",
                path,
            )
        )
    return diagnostics


def _outside_safety(
    point: Quantity,
    safety_min: Quantity | None,
    safety_max: Quantity | None,
) -> bool:
    point_base = to_base_value(point.value, point.unit)
    if safety_min is not None:
        min_base = to_base_value(safety_min.value, safety_min.unit)
        if point_base is None or min_base is None:
            if point.unit == safety_min.unit:
                return point.value < safety_min.value
            return point.value < safety_min.to(point.unit).value
        if point_base < min_base:
            return True
    if safety_max is not None:
        max_base = to_base_value(safety_max.value, safety_max.unit)
        if point_base is None or max_base is None:
            if point.unit == safety_max.unit:
                return point.value > safety_max.value
            return point.value > safety_max.to(point.unit).value
        if point_base > max_base:
            return True
    return False


def _build_key_part(value: object) -> str:
    if isinstance(value, Quantity):
        return f"quantity:{value.value!r}:{value.unit}"
    return repr(value)


def _parameter_diagnostic(
    severity: Literal["info", "warning", "error", "blocker"],
    code: str,
    message: str,
    path: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "path": path,
    }


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


__all__ = [
    "ParameterCatalog",
    "ParameterChangeSet",
    "ParameterDerivationSet",
    "ParameterPatch",
    "ParameterState",
    "ParameterTable",
    "ParameterTableColumn",
    "ParameterTableDefinition",
    "ParameterValue",
    "ParameterValueSet",
    "Quantity",
    "ScalarParameterDerivation",
    "TableParameterDerivation",
    "apply_parameter_patches",
    "build_parameter_snapshot",
    "diff_parameter_states",
]
