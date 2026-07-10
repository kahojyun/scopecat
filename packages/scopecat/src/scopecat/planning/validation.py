"""Validation for config, experiments, and plans."""

from __future__ import annotations

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import (
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    ParameterViewSnapshot,
    Quantity,
)
from scopecat.parameter_validation import (
    ParameterTableCellValidationError,
    coerce_parameter_table_cell,
    parameter_table_key_part,
    validate_parameter_table_cell,
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

    entity_ids = {entity.id for entity in config.topology.entities}
    device_ids = {device.id for device in config.topology.devices}
    line_ids = {line.id for line in config.topology.lines}
    channel_ids = {channel.id for channel in config.topology.channels}
    group_ids = {group.id for group in config.topology.groups}
    lines_by_id = {line.id: line for line in config.topology.lines}
    channels_by_id = {channel.id: channel for channel in config.topology.channels}
    groups_by_id = {group.id: group for group in config.topology.groups}
    instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }

    if (
        config.primary_entity_id
        and entity_ids
        and config.primary_entity_id not in entity_ids
    ):
        diagnostics.append(
            _diagnostic(
                "error",
                "unknown_primary_entity",
                "primary_entity_id references an unknown entity "
                f"{config.primary_entity_id}",
                "system.primary_entity_id",
            )
        )

    for channel in config.topology.channels:
        if channel.device_id is not None and channel.device_id not in device_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_channel_device",
                    f"channel {channel.id} references unknown device "
                    f"{channel.device_id}",
                    "topology.channels",
                )
            )
        if channel.line_id is not None and channel.line_id not in line_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_channel_line",
                    f"channel {channel.id} references unknown line {channel.line_id}",
                    "topology.channels",
                )
            )
        elif channel.line_id is not None and channel.device_id is not None:
            line = lines_by_id[channel.line_id]
            if line.endpoints and channel.device_id not in line.endpoints:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "topology_channel_line_endpoint_mismatch",
                        f"channel {channel.id} references line {channel.line_id} "
                        f"and device {channel.device_id}, but the line endpoints "
                        "do not include that device",
                        "topology.channels",
                    )
                )
        for group_id in channel.group_ids:
            if group_id not in group_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_channel_group",
                        f"channel {channel.id} references unknown group {group_id}",
                        "topology.channels",
                    )
                )
            else:
                group = groups_by_id[group_id]
                if (
                    group.members
                    and channel.id not in group.members
                    and (
                        channel.line_id is None or channel.line_id not in group.members
                    )
                ):
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "topology_channel_group_mismatch",
                            f"channel {channel.id} references group {group_id}, "
                            "but that group does not list the channel or its line",
                            "topology.channels",
                        )
                    )

    for line in config.topology.lines:
        for endpoint in line.endpoints:
            if endpoint not in entity_ids and endpoint not in device_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_line_endpoint",
                        f"line {line.id} references unknown endpoint {endpoint}",
                        "topology.lines",
                    )
                )

    for group in config.topology.groups:
        for member in group.members:
            if member not in channel_ids and member not in line_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_group_member",
                        f"group {group.id} references unknown member {member}",
                        "topology.groups",
                    )
                )
            elif member in channel_ids:
                channel = channels_by_id[member]
                if channel.group_ids and group.id not in channel.group_ids:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "topology_group_member_mismatch",
                            f"group {group.id} lists channel {member}, but that "
                            "channel does not reference the group",
                            "topology.groups",
                        )
                    )
            else:
                for channel in config.topology.channels:
                    if channel.line_id != member:
                        continue
                    if channel.group_ids and group.id not in channel.group_ids:
                        diagnostics.append(
                            _diagnostic(
                                "error",
                                "topology_group_member_mismatch",
                                f"group {group.id} lists line {member}, but channel "
                                f"{channel.id} on that line does not reference the "
                                "group",
                                "topology.groups",
                            )
                        )

    for device in config.topology.devices:
        for channel_id in device.channels:
            if channel_id not in channel_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_device_channel",
                        f"device {device.id} references unknown channel {channel_id}",
                        "topology.devices",
                    )
                )

    for link in config.topology.links:
        for endpoint in link.endpoints:
            if endpoint not in entity_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_link_endpoint",
                        f"link {link.id} references unknown endpoint {endpoint}",
                        "topology.links",
                    )
                )

    for resource in config.routing.resources:
        if resource.kind == "instrument" and resource.id not in instrument_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_routing_resource_instrument",
                    f"routing resource {resource.id} references unknown instrument",
                    "system.routing.resources",
                )
            )
        for entity_id in resource.served_entities:
            if entity_id not in entity_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_routing_resource_served_entity",
                        f"routing resource {resource.id} serves unknown entity "
                        f"{entity_id}",
                        "system.routing.resources",
                    )
                )
        for channel_id in resource.channels:
            if channel_id not in channel_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_routing_resource_channel",
                        f"routing resource {resource.id} references unknown channel "
                        f"{channel_id}",
                        "system.routing.resources",
                    )
                )

    routing_resources = {resource.id: resource for resource in config.routing.resources}
    for edge in config.routing.edges:
        resource = routing_resources.get(edge.resource_id)
        if resource is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_routing_edge_resource",
                    f"routing edge {edge.id} references unknown resource "
                    f"{edge.resource_id}",
                    "system.routing.edges",
                )
            )
        for entity_id in edge.entity_ids:
            if entity_id not in entity_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_routing_edge_entity",
                        f"routing edge {edge.id} references unknown entity {entity_id}",
                        "system.routing.edges",
                    )
                )
            elif (
                resource is not None
                and resource.served_entities
                and entity_id not in resource.served_entities
            ):
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "routing_edge_resource_entity_mismatch",
                        f"routing edge {edge.id} references entity {entity_id}, "
                        f"but resource {edge.resource_id} does not serve it",
                        "system.routing.edges",
                    )
                )
        for channel_id in edge.channels:
            if channel_id not in channel_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_routing_edge_channel",
                        f"routing edge {edge.id} references unknown channel "
                        f"{channel_id}",
                        "system.routing.edges",
                    )
                )
            elif (
                resource is not None
                and resource.channels
                and channel_id not in resource.channels
            ):
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "routing_edge_resource_channel_mismatch",
                        f"routing edge {edge.id} references channel {channel_id}, "
                        f"but resource {edge.resource_id} does not list it",
                        "system.routing.edges",
                    )
                )
        for binding in edge.bindings:
            if binding.entity_id not in entity_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_routing_binding_entity",
                        f"routing edge {edge.id} binding references unknown entity "
                        f"{binding.entity_id}",
                        "system.routing.edges",
                    )
                )
            elif edge.entity_ids and binding.entity_id not in edge.entity_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "routing_binding_edge_entity_mismatch",
                        f"routing edge {edge.id} binding references entity "
                        f"{binding.entity_id}, but the edge does not list it",
                        "system.routing.edges",
                    )
                )
            elif (
                resource is not None
                and resource.served_entities
                and binding.entity_id not in resource.served_entities
            ):
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "routing_binding_resource_entity_mismatch",
                        f"routing edge {edge.id} binding references entity "
                        f"{binding.entity_id}, but resource {edge.resource_id} "
                        "does not serve it",
                        "system.routing.edges",
                    )
                )
            if binding.capability is not None:
                if edge.capabilities and binding.capability not in edge.capabilities:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "routing_binding_edge_capability_mismatch",
                            f"routing edge {edge.id} binding references capability "
                            f"{binding.capability}, but the edge does not list it",
                            "system.routing.edges",
                        )
                    )
                if (
                    resource is not None
                    and resource.capabilities
                    and binding.capability not in resource.capabilities
                ):
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "routing_binding_resource_capability_mismatch",
                            f"routing edge {edge.id} binding references capability "
                            f"{binding.capability}, but resource {edge.resource_id} "
                            "does not declare it",
                            "system.routing.edges",
                        )
                    )
            if binding.channel_id not in channel_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_routing_binding_channel",
                        f"routing edge {edge.id} binding references unknown channel "
                        f"{binding.channel_id}",
                        "system.routing.edges",
                    )
                )
            else:
                if edge.channels and binding.channel_id not in edge.channels:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "routing_binding_edge_channel_mismatch",
                            f"routing edge {edge.id} binding references channel "
                            f"{binding.channel_id}, but the edge does not list it",
                            "system.routing.edges",
                        )
                    )
                if (
                    resource is not None
                    and resource.channels
                    and binding.channel_id not in resource.channels
                ):
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "routing_binding_resource_channel_mismatch",
                            f"routing edge {edge.id} binding references channel "
                            f"{binding.channel_id}, but resource "
                            f"{edge.resource_id} does not list it",
                            "system.routing.edges",
                        )
                    )
                channel = channels_by_id[binding.channel_id]
                if (
                    binding.line_id is not None
                    and channel.line_id is not None
                    and binding.line_id != channel.line_id
                ):
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "routing_binding_line_mismatch",
                            f"routing edge {edge.id} binding line {binding.line_id} "
                            f"does not match topology channel {binding.channel_id} "
                            f"line {channel.line_id}",
                            "system.routing.edges",
                        )
                    )
                if (
                    binding.group_ids
                    and channel.group_ids
                    and set(binding.group_ids) != set(channel.group_ids)
                ):
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "routing_binding_group_mismatch",
                            f"routing edge {edge.id} binding groups "
                            f"{sorted(binding.group_ids)} do not match topology "
                            f"channel {binding.channel_id} groups "
                            f"{sorted(channel.group_ids)}",
                            "system.routing.edges",
                        )
                    )
            if binding.line_id is not None and binding.line_id not in line_ids:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "unknown_routing_binding_line",
                        f"routing edge {edge.id} binding references unknown line "
                        f"{binding.line_id}",
                        "system.routing.edges",
                    )
                )
            for group_id in binding.group_ids:
                if group_id not in group_ids:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "unknown_routing_binding_group",
                            f"routing edge {edge.id} binding references unknown "
                            f"group {group_id}",
                            "system.routing.edges",
                        )
                    )
        if resource is not None:
            for capability in edge.capabilities:
                if capability not in resource.capabilities:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "unknown_routing_edge_capability",
                            f"routing edge {edge.id} references capability "
                            f"{capability} not declared by resource "
                            f"{edge.resource_id}",
                            "system.routing.edges",
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

    parameter_view = _parameter_view(config)
    for item in parameter_view.diagnostics:
        diagnostics.append(
            _diagnostic(
                item.get("severity", "warning"),
                item.get("code", "parameter_view_diagnostic"),
                item.get("message", item.get("code", "parameter view diagnostic")),
                "parameter_view.diagnostics",
            )
        )

    definitions = {
        definition.id: definition
        for definition in config.parameter_catalog.scalar_definitions
    }
    for value in parameter_view.scalar_values:
        definition = definitions.get(value.id)
        if definition is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "unknown_parameter_value_definition",
                    f"parameter value {value.id} has no definition",
                    "parameter_view.scalar_values",
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
                    "parameter_view.scalar_values",
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
                    "parameter_view.scalar_values",
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


def _parameter_view(config: ConfigProfileSnapshot) -> ParameterViewSnapshot:
    return build_config_parameters(config)


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
                    "parameter_view.tables",
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
        path = f"parameter_view.tables.{table.id}.rows.{row_index}"
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
        key_values = [row.get(column_id) for column_id in definition.primary_key]
        if any(value is None for value in key_values):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "missing_parameter_table_primary_key",
                    f"parameter table {table.id} row is missing primary key values",
                    path,
                )
            )
        else:
            try:
                key = tuple(
                    parameter_table_key_part(
                        coerce_parameter_table_cell(
                            table_id=table.id,
                            column=columns[column_id],
                            value=row[column_id],
                            path=f"{path}.{column_id}",
                        )
                    )
                    for column_id in definition.primary_key
                )
            except ParameterTableCellValidationError:
                key = None
            if key is not None:
                if key in seen_keys:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "duplicate_parameter_table_primary_key",
                            f"parameter table {table.id} has duplicate primary key "
                            f"{key}",
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
    try:
        validate_parameter_table_cell(
            table_id=table_id,
            column=column,
            value=raw_value,
            path=path,
        )
    except ParameterTableCellValidationError as error:
        return [
            _diagnostic(
                "error",
                error.code,
                str(error),
                path,
            )
        ]
    return []
