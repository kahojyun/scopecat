"""Config-dependent validation for typed parameter dependencies."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    ParameterLookupContract,
    ParameterValueContract,
)
from scopecat.compiler.frontend.problems import raise_frontend_problem
from scopecat.kernel.problems import ProblemCategory
from scopecat.kernel.value_type_compatibility import describe_value_type, is_assignable
from scopecat.kernel.value_types import Entity, String, Table, ValueType
from scopecat.records.parameter import ParameterCatalog, ParameterDefinition


def validate_parameter_contracts(
    catalog: ParameterCatalog,
    contracts: Sequence[ParameterContract],
) -> None:
    """Validate typed dependencies against the selected unified catalog."""

    for contract in contracts:
        if isinstance(contract, ParameterLookupContract):
            _validate_parameter_lookup(catalog, contract)
        else:
            _validate_parameter(catalog, contract)


def _validate_parameter(
    catalog: ParameterCatalog,
    contract: ParameterValueContract,
) -> None:
    definition = catalog.get(contract.parameter_id)
    path = (contract.parameter_id,)
    if definition is None:
        raise_frontend_problem(
            "unknown_authoring_parameter",
            "experiment authoring references unknown parameter "
            f"{contract.parameter_id}",
            "parameters",
            path=path,
            category=ProblemCategory.NOT_FOUND,
        )
    _require_declared_type(
        actual=definition.value_type,
        declared=contract.value_type,
        code="authoring_parameter_type_mismatch",
        label=f"parameter {contract.parameter_id}",
        path=path,
    )


def _validate_parameter_lookup(
    catalog: ParameterCatalog,
    contract: ParameterLookupContract,
) -> None:
    definition = catalog.get(contract.parameter_id)
    table_path = (contract.parameter_id,)
    if definition is None:
        raise_frontend_problem(
            "unknown_authoring_parameter",
            "experiment authoring references unknown parameter "
            f"{contract.parameter_id}",
            "parameters",
            path=table_path,
            category=ProblemCategory.NOT_FOUND,
        )
    table_type = _require_table_definition(definition, table_path)
    _validate_parameter_lookup_key(contract, table_type)
    column = next(
        (
            candidate
            for candidate in table_type.columns
            if candidate.id == contract.column_id
        ),
        None,
    )
    column_path = (*table_path, "columns", contract.column_id)
    if column is None:
        raise_frontend_problem(
            "unknown_authoring_parameter_column",
            f"parameter table {contract.parameter_id} has no column "
            f"{contract.column_id}",
            "parameters",
            path=column_path,
            category=ProblemCategory.NOT_FOUND,
        )
    if not column.required:
        raise_frontend_problem(
            "authoring_parameter_lookup_column_optional",
            f"parameter table {contract.parameter_id} lookup result column "
            f"{contract.column_id} is not guaranteed to be present",
            "parameters",
            path=column_path,
        )
    _require_declared_type(
        actual=column.value_type,
        declared=contract.value_type,
        code="authoring_parameter_column_type_mismatch",
        label=f"parameter table {contract.parameter_id} column {contract.column_id}",
        path=column_path,
    )


def _require_table_definition(
    definition: ParameterDefinition,
    path: tuple[str | int, ...],
) -> Table:
    if isinstance(definition.value_type, Table):
        return definition.value_type
    raise_frontend_problem(
        "authoring_parameter_shape_mismatch",
        f"parameter {definition.id} is not table-shaped",
        "parameters",
        path=path,
    )


def _validate_parameter_lookup_key(
    contract: ParameterLookupContract,
    table_type: Table,
) -> None:
    table_path = (contract.parameter_id,)
    if set(contract.key_columns) != set(table_type.primary_key) or len(
        contract.key_columns
    ) != len(table_type.primary_key):
        raise_frontend_problem(
            "authoring_parameter_lookup_key_mismatch",
            f"parameter table {contract.parameter_id} lookup requires exactly the "
            f"primary key columns {table_type.primary_key!r}; got "
            f"{contract.key_columns!r}",
            "parameters",
            path=(*table_path, "key"),
        )
    columns = {column.id: column for column in table_type.columns}
    for column_id, source_type in contract.key_types:
        target_type = columns[column_id].value_type
        if is_assignable(source_type, target_type) or (
            column_id in contract.literal_key_columns
            and not source_type.nullable
            and isinstance(source_type.atom, String)
            and isinstance(target_type.atom, Entity)
        ):
            continue
        raise_frontend_problem(
            "authoring_parameter_lookup_key_type_mismatch",
            f"parameter table {contract.parameter_id} key column {column_id} requires "
            f"{describe_value_type(target_type)}, got "
            f"{describe_value_type(source_type)}",
            "parameters",
            path=(*table_path, "key", column_id),
        )


def _require_declared_type(
    *,
    actual: ValueType,
    declared: ValueType,
    code: str,
    label: str,
    path: tuple[str | int, ...],
) -> None:
    if is_assignable(actual, declared):
        return
    raise_frontend_problem(
        code,
        f"{label} has catalog type {describe_value_type(actual)}, which is not "
        f"compatible with declared type {describe_value_type(declared)}",
        "parameters",
        path=path,
    )


__all__ = ["validate_parameter_contracts"]
