"""Config-free verification for one fully composed authoring assembly.

This pass owns invariants that depend only on the source graph.  Keeping it
separate from linking prevents malformed dataflow from being hidden behind an
unrelated config or parameter-catalog error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from scopecat._compiler.graph import ComputeGraphError, order_compute_nodes
from scopecat._compiler.program import (
    ComputeEdge,
    ComputeInput,
    RouteInput,
    TypedComputeNode,
)
from scopecat._compiler.verification import is_point_coordinate_type
from scopecat.authoring._binding_intents import ResourcePort
from scopecat.authoring._intents import ComputeNodeIntent
from scopecat.authoring._module_composition import ExperimentAssemblyInternal
from scopecat.authoring._record_intents import (
    ModuleProductPort,
    RecordAxisIntent,
    RecordIntent,
)
from scopecat.authoring._value_availability import (
    ValueAvailabilityError,
    ValueRate,
    ValueStage,
    require_value_availability,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_availability,
    internal_value_ref_compute_node_id,
    internal_value_ref_compute_origin,
)
from scopecat.authoring.values import RouteRef
from scopecat.errors import CheckFailed
from scopecat.models.parameter import Quantity as QuantityValue
from scopecat.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemLocation,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.units import is_supported_unit
from scopecat.value_types import Payload, Scalar, Table


@dataclass(frozen=True, slots=True)
class VerifiedAssemblyGraph:
    """Source graph facts safe for config-dependent lowering to consume."""

    compute_nodes: tuple[ComputeNodeIntent, ...]
    resource_ports: Mapping[str, ResourcePort]


def verify_assembly_graph(
    assembly: ExperimentAssemblyInternal,
) -> VerifiedAssemblyGraph:
    """Verify and order the config-independent portion of an assembly.

    The verifier deliberately has no authoring context or config argument.  A
    successful result therefore proves that config-dependent linking will not
    encounter a missing compute producer, a compute cycle, or an incomplete
    route edge.
    """

    problems: list[Problem] = []
    resource_ports = _resource_ports(assembly.resource_ports, problems)
    _verify_compute_origins(assembly.compute_nodes, problems)
    compute_nodes = _ordered_compute_nodes(assembly.compute_nodes, problems)
    _verify_compute_input_availability(compute_nodes, problems)
    _verify_compute_routes(compute_nodes, resource_ports, problems)
    _verify_plan_value_availability(assembly, problems)
    _verify_state_compute_values(assembly, compute_nodes, problems)
    _verify_record_schema(assembly, problems)
    if problems:
        raise CheckFailed(problems)
    return VerifiedAssemblyGraph(
        compute_nodes=compute_nodes,
        resource_ports=MappingProxyType(resource_ports),
    )


def _resource_ports(
    ports: Sequence[ResourcePort],
    problems: list[Problem],
) -> dict[str, ResourcePort]:
    selected: dict[str, ResourcePort] = {}
    duplicates: set[str] = set()
    for port in ports:
        port_id = port.qualified_id
        if port_id in selected:
            duplicates.add(port_id)
            continue
        selected[port_id] = port
    for port_id in sorted(duplicates):
        problems.append(
            _problem(
                "module_resource_port_duplicate",
                f"duplicate resource port {port_id}",
                model_location("resources", port_id),
                category=ProblemCategory.CONFLICT,
            )
        )
    return selected


def _verify_compute_origins(
    nodes: Sequence[ComputeNodeIntent],
    problems: list[Problem],
) -> None:
    producers = {node.node_id: node for node in nodes}
    for node in nodes:
        for input_name, value in node.inputs:
            if not isinstance(value, ValueRef):
                continue
            producer_id = internal_value_ref_compute_node_id(value)
            if producer_id is None:
                continue
            producer = producers.get(producer_id)
            if producer is None:
                continue
            if internal_value_ref_compute_origin(value) == producer.origin:
                continue
            problems.append(
                _problem(
                    "compute_value_foreign_instance",
                    f"compute node {node.node_id.qualified_name!r} input "
                    f"{input_name!r} references producer "
                    f"{producer_id.qualified_name!r} from another module instance",
                    model_location(
                        "compute_nodes",
                        *node.node_id.scope,
                        node.node_id.local_id,
                        "inputs",
                        input_name,
                    ),
                )
            )


def _ordered_compute_nodes(
    nodes: Sequence[ComputeNodeIntent],
    problems: list[Problem],
) -> tuple[ComputeNodeIntent, ...]:
    selected = tuple(nodes)
    graph_nodes = tuple(_compute_graph_node(node) for node in selected)
    try:
        ordered = order_compute_nodes(graph_nodes)
    except ComputeGraphError as error:
        problems.append(_problem(error.code, str(error), error.location))
        return selected
    by_id = {node.node_id: node for node in selected}
    return tuple(by_id[node.id] for node in ordered)


def _compute_graph_node(node: ComputeNodeIntent) -> TypedComputeNode:
    graph_inputs: dict[str, ComputeInput] = {}
    for name, value in node.inputs:
        if isinstance(value, ValueRef):
            producer = internal_value_ref_compute_node_id(value)
            if producer is not None:
                graph_inputs[name] = ComputeEdge(
                    producer=producer,
                    value_type=value.value_type,
                )
        elif isinstance(value, RouteRef):
            graph_inputs[name] = RouteInput(
                port_id=value.port_id,
                value_type=value.value_type,
            )
    return TypedComputeNode(
        id=node.node_id,
        inputs=graph_inputs,
        output_type=node.output_type,
        fn=node.fn,
    )


def _verify_compute_routes(
    nodes: Sequence[ComputeNodeIntent],
    ports: Mapping[str, ResourcePort],
    problems: list[Problem],
) -> None:
    for node in nodes:
        for input_name, value in node.inputs:
            if not isinstance(value, RouteRef):
                continue
            location = model_location(
                "compute_nodes",
                *node.node_id.scope,
                node.node_id.local_id,
                "inputs",
                input_name,
            )
            port = ports.get(value.port_id)
            if port is None:
                problems.append(
                    _problem(
                        "compute_route_port_missing",
                        f"compute node {node.node_id.qualified_name!r} input "
                        f"{input_name!r} references undeclared route port "
                        f"{value.port_id!r}",
                        location,
                    )
                )
                continue
            missing = sorted(
                set(value.value_type.capabilities) - set(port.selector.capabilities)
            )
            if missing:
                problems.append(
                    _problem(
                        "compute_route_capability_missing",
                        f"compute node {node.node_id.qualified_name!r} input "
                        f"{input_name!r} requires capabilities not declared by "
                        f"route port {value.port_id!r}: {', '.join(missing)}",
                        location,
                    )
                )


def _verify_compute_input_availability(
    nodes: Sequence[ComputeNodeIntent],
    problems: list[Problem],
) -> None:
    for node in nodes:
        for input_name, value in node.inputs:
            if not isinstance(value, ValueRef):
                continue
            location = model_location(
                "compute_nodes",
                *node.node_id.scope,
                node.node_id.local_id,
                "inputs",
                input_name,
            )
            availability = internal_value_ref_availability(value)
            try:
                require_value_availability(
                    availability,
                    stages=(ValueStage.PLAN, ValueStage.EXECUTE),
                    context="compute input",
                    location=location,
                )
            except ValueAvailabilityError as error:
                problems.append(_availability_problem(error))
                continue
            if (
                availability.stage == ValueStage.EXECUTE
                and internal_value_ref_compute_node_id(value) is None
            ):
                problems.append(
                    _problem(
                        "execute_value_expression_unsupported",
                        "compute execute-stage inputs must be direct compute "
                        "outputs; expressions containing compute outputs are "
                        "not supported",
                        location,
                    )
                )


def _verify_state_compute_values(
    assembly: ExperimentAssemblyInternal,
    nodes: Sequence[ComputeNodeIntent],
    problems: list[Problem],
) -> None:
    producers = {node.node_id: node for node in nodes}
    values = [
        *(
            (model_location("bindings", index, "value"), binding.value)
            for index, binding in enumerate(assembly.bindings)
        ),
        *(
            (model_location("state", index, "value"), state.value)
            for index, state in enumerate(assembly.state_intents)
        ),
    ]
    for location, value in values:
        if not isinstance(value, ValueRef):
            continue
        availability = internal_value_ref_availability(value)
        try:
            require_value_availability(
                availability,
                stages=(ValueStage.PLAN, ValueStage.EXECUTE),
                context="state value",
                location=location,
            )
        except ValueAvailabilityError as error:
            problems.append(_availability_problem(error))
            continue
        if availability.stage == ValueStage.PLAN:
            continue
        node_id = internal_value_ref_compute_node_id(value)
        if node_id is None:
            problems.append(
                _problem(
                    "execute_value_expression_unsupported",
                    "state execute-stage values must be direct compute outputs",
                    location,
                )
            )
            continue
        producer = producers.get(node_id)
        if producer is None:
            problems.append(
                _problem(
                    "compute_payload_unknown_node",
                    f"state references unknown compute node {node_id.qualified_name!r}",
                    location,
                )
            )
            continue
        if internal_value_ref_compute_origin(value) != producer.origin:
            problems.append(
                _problem(
                    "compute_value_foreign_instance",
                    "state references a same-named compute producer from another "
                    f"module instance: {node_id.qualified_name!r}",
                    location,
                )
            )
            continue
        if producer.output_type != value.value_type:
            problems.append(
                _problem(
                    "compute_edge_type_mismatch",
                    f"state expects compute output {value.value_type!r}, but "
                    f"producer {node_id.qualified_name!r} returns "
                    f"{producer.output_type!r}",
                    location,
                )
            )
            continue
        if not _is_payload_type(producer.output_type):
            problems.append(
                _problem(
                    "compute_payload_unavailable",
                    "state compute output is not an available payload: "
                    f"{node_id.qualified_name!r}",
                    location,
                )
            )


def _is_payload_type(value_type: object) -> bool:
    return isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload)


def _verify_plan_value_availability(
    assembly: ExperimentAssemblyInternal,
    problems: list[Problem],
) -> None:
    for port in assembly.resource_ports:
        for index, value in enumerate(port.selector.entity_inputs):
            _require_plan_value(
                value,
                context="resource selector",
                location=model_location(
                    "resources",
                    *port.scope,
                    port.id,
                    "selector",
                    "entity_inputs",
                    index,
                ),
                problems=problems,
            )

    for index, state in enumerate(assembly.state_intents):
        _require_plan_value(
            state.relation,
            context="state relation",
            location=model_location("state", index, "relation"),
            problems=problems,
        )
        if isinstance(state.resource, ValueRef):
            _require_plan_value(
                state.resource,
                context="state resource selector",
                location=model_location("state", index, "resource"),
                problems=problems,
            )
        for route_index, route_entity in enumerate(state.route_entities):
            if isinstance(route_entity, ValueRef):
                _require_plan_value(
                    route_entity,
                    context="state route selector",
                    location=model_location(
                        "state",
                        index,
                        "route_entities",
                        route_index,
                    ),
                    problems=problems,
                )

    for record in (*assembly.records, *assembly.product_ports):
        for axis in record.axes:
            if not isinstance(axis.size, ValueRef):
                continue
            try:
                require_value_availability(
                    internal_value_ref_availability(axis.size),
                    stages=(ValueStage.PLAN,),
                    rates=(ValueRate.RUN,),
                    context="record axis",
                    location=model_location(
                        "records",
                        record.id,
                        "axes",
                        axis.id,
                        "size",
                    ),
                )
            except ValueAvailabilityError as error:
                problems.append(_availability_problem(error))


def _require_plan_value(
    value: ValueRef,
    *,
    context: str,
    location: ModelLocation,
    problems: list[Problem],
) -> None:
    try:
        require_value_availability(
            internal_value_ref_availability(value),
            stages=(ValueStage.PLAN,),
            context=context,
            location=location,
        )
    except ValueAvailabilityError as error:
        problems.append(_availability_problem(error))


def _verify_record_schema(
    assembly: ExperimentAssemblyInternal,
    problems: list[Problem],
) -> None:
    product_by_id: dict[str, ModuleProductPort] = {}
    duplicate_products: set[str] = set()
    for product in assembly.product_ports:
        if product.qualified_id in product_by_id:
            duplicate_products.add(product.qualified_id)
            continue
        product_by_id[product.qualified_id] = product
    if duplicate_products:
        problems.append(
            _problem(
                "module_product_duplicate",
                "experiment assembly defines duplicate products: "
                + ", ".join(sorted(duplicate_products)),
                model_location("products"),
                category=ProblemCategory.CONFLICT,
            )
        )

    records: list[tuple[str, RecordIntent | ModuleProductPort]] = [
        (record.id, record) for record in assembly.records
    ]
    for selection in assembly.record_selections:
        record_id = selection.record_id or selection.product_id
        product = product_by_id.get(selection.product_id)
        if product is None:
            problems.append(
                _problem(
                    "module_product_unknown",
                    f"experiment selects unknown product {selection.product_id}",
                    model_location("records"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        if (
            selection.product_origin is not None
            and selection.product_origin != product.origin
        ):
            problems.append(
                _problem(
                    "module_product_foreign_instance",
                    f"experiment selects product {selection.product_id!r} from "
                    "another module instance",
                    model_location("records"),
                )
            )
            continue
        records.append((record_id, product))

    record_ids = [
        *(record.id for record in assembly.records),
        *(
            selection.record_id or selection.product_id
            for selection in assembly.record_selections
        ),
    ]
    duplicate_records = _duplicates(record_ids)
    if duplicate_records:
        problems.append(
            _problem(
                "module_record_duplicate",
                "experiment assembly defines duplicate records: "
                + ", ".join(duplicate_records),
                model_location("records"),
                category=ProblemCategory.CONFLICT,
            )
        )

    point_columns = (
        {
            column.id
            for column in assembly.point_source.value_type.columns
            if is_point_coordinate_type(column.value_type)
        }
        if assembly.point_source is not None
        and isinstance(assembly.point_source.value_type, Table)
        else set[str]()
    )
    for record_id in sorted(set(record_ids) & point_columns):
        problems.append(
            _problem(
                "experiment_record_coordinate_collision",
                f"record {record_id!r} conflicts with a point coordinate",
                model_location("records", record_id),
                category=ProblemCategory.CONFLICT,
            )
        )

    axes_by_id: dict[str, tuple[str, RecordAxisIntent]] = {}
    product_keys_by_resource: dict[str | None, list[str]] = {}
    for record_id, record in records:
        _verify_record_definition(record_id, record, problems)
        seen_axis_ids: set[str] = set()
        for axis in record.axes:
            if axis.id in seen_axis_ids:
                continue
            seen_axis_ids.add(axis.id)
            existing = axes_by_id.get(axis.id)
            if existing is None:
                axes_by_id[axis.id] = (record_id, axis)
                continue
            existing_record_id, existing_axis = existing
            if _source_axes_can_conflict(existing_axis, axis):
                problems.append(
                    _problem(
                        "experiment_record_axis_conflict",
                        f"record {record_id!r} axis {axis.id!r} conflicts with "
                        f"record {existing_record_id!r}; shared axes must have "
                        "identical kind, size, and unit",
                        model_location("records", record_id, "axes", axis.id),
                        category=ProblemCategory.CONFLICT,
                        related_locations=(
                            model_location(
                                "records",
                                existing_record_id,
                                "axes",
                                axis.id,
                            ),
                        ),
                    )
                )
        if record.kind == "observable" and record.source == "instrument":
            product_keys_by_resource.setdefault(record.resource, []).append(
                record.product_key
                or record.capability
                or (record.id if isinstance(record, ModuleProductPort) else record_id)
            )
    for resource, product_keys in product_keys_by_resource.items():
        for product_key in _duplicates(product_keys):
            problems.append(
                _problem(
                    "experiment_record_product_duplicate",
                    f"instrument product {product_key!r} is mapped more than once",
                    model_location("records", *((resource,) if resource else ())),
                    category=ProblemCategory.CONFLICT,
                )
            )


def _verify_record_definition(
    record_id: str,
    record: RecordIntent | ModuleProductPort,
    problems: list[Problem],
) -> None:
    if record.unit is not None and not is_supported_unit(record.unit):
        problems.append(
            _problem(
                "experiment_record_unit_unsupported",
                f"record {record_id!r} uses unsupported unit {record.unit!r}",
                model_location("records", record_id, "unit"),
            )
        )
    if record.kind != "observable":
        problems.append(
            _problem(
                "experiment_record_kind_unsupported",
                f"record kind {record.kind!r} is not supported yet",
                model_location("records", record_id, "kind"),
            )
        )
    elif record.source != "instrument":
        problems.append(
            _problem(
                "experiment_record_source_unsupported",
                f"observable record source {record.source!r} is not supported yet",
                model_location("records", record_id, "source"),
            )
        )
    duplicate_axes = _duplicates([axis.id for axis in record.axes])
    for axis_id in duplicate_axes:
        problems.append(
            _problem(
                "experiment_record_axis_duplicate",
                f"record {record_id!r} axis {axis_id!r} is duplicated",
                model_location("records", record_id, "axes"),
                category=ProblemCategory.CONFLICT,
            )
        )
    for axis in record.axes:
        location = model_location("records", record_id, "axes", axis.id)
        if axis.id == "point":
            problems.append(
                _problem(
                    "experiment_record_axis_reserved",
                    "record axis 'point' conflicts with the point dimension",
                    location,
                )
            )
        if axis.unit is not None and not is_supported_unit(axis.unit):
            problems.append(
                _problem(
                    "experiment_record_axis_unit_unsupported",
                    f"record {record_id!r} axis {axis.id!r} uses unsupported "
                    f"unit {axis.unit!r}",
                    model_location(location.root, *location.path, "unit"),
                )
            )
        size = _literal_axis_size(axis)
        if size is not None and size <= 0:
            problems.append(
                _problem(
                    "module_records_value_invalid",
                    "records value must be a positive integer",
                    model_location(location.root, *location.path, "size"),
                )
            )


def _source_axes_can_conflict(
    left: RecordAxisIntent,
    right: RecordAxisIntent,
) -> bool:
    if (left.kind or left.id) != (right.kind or right.id):
        return True
    if left.unit != right.unit or left.entity_values != right.entity_values:
        return True
    left_size = _literal_axis_size(left)
    right_size = _literal_axis_size(right)
    return left_size is not None and right_size is not None and left_size != right_size


def _literal_axis_size(axis: RecordAxisIntent) -> int | None:
    value = axis.size
    if isinstance(value, tuple):
        return len(value)
    if isinstance(value, QuantityValue):
        number = value.value
    elif isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
    else:
        return None
    if not number.is_integer():
        return -1
    return int(number)


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


def _problem(
    code: str,
    message: str,
    location: ModelLocation,
    *,
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    related_locations: Sequence[ProblemLocation] = (),
) -> Problem:
    return blocking_problem(
        code=code,
        category=category,
        phase=ProblemPhase.AUTHORING,
        message=message,
        location=location,
        related_locations=related_locations,
    )


def _availability_problem(error: ValueAvailabilityError) -> Problem:
    return _problem(error.code, str(error), error.location)


__all__ = ["VerifiedAssemblyGraph", "verify_assembly_graph"]
