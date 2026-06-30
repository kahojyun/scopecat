"""Validation for config, experiments, and plans."""

from __future__ import annotations

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterBuildSnapshot,
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    Quantity,
)
from scopecat.units import compatible_units, to_base_value

BLOCKING_SEVERITIES = {"error", "blocker"}


def has_blocking_diagnostics(diagnostics: list[Diagnostic]) -> bool:
    return any(diagnostic.severity in BLOCKING_SEVERITIES for diagnostic in diagnostics)


def format_diagnostics(diagnostics: list[Diagnostic]) -> str:
    if not diagnostics:
        return "no diagnostics"
    return "\n".join(
        f"{item.severity.upper()} {item.code}: {item.message}"
        + (f" ({item.path})" if item.path else "")
        for item in diagnostics
    )


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


def validate_config_profile(config: ConfigProfileSnapshot) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    if config.environment.workspace_id != config.system.workspace_id:
        diagnostics.append(
            _diagnostic(
                "error",
                "config_profile_workspace_mismatch",
                "environment workspace does not match system workspace",
                "environment.workspace_id",
            )
        )

    device_ids = {device.id for device in config.device_topology.devices}
    channel_ids = {channel.id for channel in config.device_topology.channels}
    instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }

    for channel in config.device_topology.channels:
        if channel.device_id is not None and channel.device_id not in device_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_channel_device",
                    f"channel {channel.id} references unknown device "
                    f"{channel.device_id}",
                    "device_topology.channels",
                )
            )

    for device in config.device_topology.devices:
        for channel_id in device.channels:
            if channel_id not in channel_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_device_channel",
                        f"device {device.id} references unknown channel {channel_id}",
                        "device_topology.devices",
                    )
                )

    for link in config.device_topology.links:
        for endpoint in link.endpoints:
            if endpoint not in device_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_link_endpoint",
                        f"link {link.id} references unknown endpoint {endpoint}",
                        "device_topology.links",
                    )
                )

    for instrument in config.instrument_registry.instruments:
        for channel_id in instrument.channels:
            if channel_id not in channel_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_instrument_channel",
                        f"instrument {instrument.id} references unknown channel "
                        f"{channel_id}",
                        "instrument_registry.instruments",
                    )
                )

    for connection in config.connection_profile.connections:
        if connection.instrument_id not in instrument_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_connection_instrument",
                    f"connection {connection.id} references unknown instrument "
                    f"{connection.instrument_id}",
                    "connection_profile.connections",
                )
            )

    parameter_build = _parameter_build(config)
    for item in parameter_build.diagnostics:
        diagnostics.append(
            _diagnostic(
                item.get("severity", "warning"),
                item.get("code", "parameter_build_diagnostic"),
                item.get("message", item.get("code", "parameter build diagnostic")),
                "parameter_build.diagnostics",
            )
        )

    definitions = {
        definition.id: definition
        for definition in config.parameter_catalog.scalar_definitions
    }
    for value in parameter_build.scalar_values:
        definition = definitions.get(value.id)
        if definition is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_parameter_value_definition",
                    f"parameter value {value.id} has no definition",
                    "parameter_build.scalar_values",
                )
            )
            continue
        if not compatible_units(definition.unit, value.quantity.unit):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "incompatible_parameter_value_unit",
                    f"parameter value {value.id} uses unit {value.quantity.unit}, "
                    f"but definition uses {definition.unit}",
                    "parameter_build.scalar_values",
                )
            )
        if _outside_safety(
            value.quantity, definition.safety_min, definition.safety_max
        ):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "parameter_value_outside_safety_limits",
                    f"parameter value {value.id} is outside safety limits",
                    "parameter_build.scalar_values",
                )
            )

    diagnostics.extend(
        _validate_parameter_tables(
            definitions=config.parameter_catalog.table_definitions,
            tables=config.parameter_tables,
        )
    )

    return diagnostics


def validate_config(config: ConfigProfileSnapshot) -> list[Diagnostic]:
    return validate_config_profile(config)


def _parameter_build(config: ConfigProfileSnapshot) -> ParameterBuildSnapshot:
    if config.parameter_build is None:
        msg = "config profile snapshot has no parameter build"
        raise ValueError(msg)
    return config.parameter_build


def _outside_safety(
    point: Quantity, safety_min: Quantity | None, safety_max: Quantity | None
) -> bool:
    point_base = to_base_value(point.value, point.unit)
    if point_base is None:
        return False
    if safety_min is not None:
        min_base = to_base_value(safety_min.value, safety_min.unit)
        if min_base is not None and point_base < min_base:
            return True
    if safety_max is not None:
        max_base = to_base_value(safety_max.value, safety_max.unit)
        if max_base is not None and point_base > max_base:
            return True
    return False


def _validate_parameter_tables(
    *,
    definitions: list[ParameterTableDefinition],
    tables: list[ParameterTable],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    definitions_by_id = {definition.id: definition for definition in definitions}
    for table in tables:
        definition = definitions_by_id.get(table.id)
        if definition is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_parameter_table_definition",
                    f"parameter table {table.id} has no definition",
                    "parameter_build.tables",
                )
            )
            continue
        diagnostics.extend(_validate_parameter_table(definition, table))
    return diagnostics


def _validate_parameter_table(
    definition: ParameterTableDefinition,
    table: ParameterTable,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    columns = {column.id: column for column in definition.columns}
    required_columns = {column.id for column in definition.columns if column.required}
    seen_keys: set[tuple[object, ...]] = set()
    for row_index, row in enumerate(table.rows):
        path = f"parameter_build.tables.{table.id}.rows.{row_index}"
        missing = sorted(required_columns - row.keys())
        if missing:
            diagnostics.append(
                _diagnostic(
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
                _diagnostic(
                    "error",
                    "unknown_parameter_table_columns",
                    f"parameter table {table.id} row contains unknown columns: "
                    + ", ".join(extra),
                    path,
                )
            )
        key = tuple(row.get(column_id) for column_id in definition.primary_key)
        if any(value is None for value in key):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "missing_parameter_table_primary_key",
                    f"parameter table {table.id} row is missing primary key values",
                    path,
                )
            )
        elif key in seen_keys:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "duplicate_parameter_table_primary_key",
                    f"parameter table {table.id} has duplicate primary key {key}",
                    path,
                )
            )
        else:
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
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if raw_value is None:
        if column.required:
            diagnostics.append(
                _diagnostic(
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
                _diagnostic(
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
                _diagnostic(
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
                _diagnostic(
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
                _diagnostic(
                    "error",
                    "invalid_parameter_table_string",
                    f"parameter table {table_id} column {column.id} must be a string",
                    path,
                )
            )
        return diagnostics
    if column.kind == "bool" and not isinstance(raw_value, bool):
        diagnostics.append(
            _diagnostic(
                "error",
                "invalid_parameter_table_bool",
                f"parameter table {table_id} column {column.id} must be a bool",
                path,
            )
        )
    return diagnostics
