"""Config-free verification for one fully composed authoring assembly.

This pass owns invariants that depend only on the source graph.  Keeping it
separate from linking prevents malformed dataflow from being hidden behind an
unrelated config or parameter-catalog error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from scopecat.authoring._binding_intents import ResourcePort
from scopecat.authoring._point_domain_intents import (
    point_domain_intent_value_type,
)
from scopecat.authoring._record_intents import (
    ModuleProductPort,
    RecordAxisIntent,
    RecordIntent,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_availability,
)
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.semantic_elaboration import semantic_value_id
from scopecat.compiler.relations.model import ScalarExpr, SeriesExpr
from scopecat.compiler.semantic.availability import (
    ValueAvailabilityError,
    ValueRate,
    ValueStage,
    require_value_availability,
)
from scopecat.compiler.semantic.model import (
    OperationOutputSource,
    RouteValueSource,
    SourceMap,
    ValueUse,
)
from scopecat.compiler.semantic.operation_contract import ScalarBinarySemantics
from scopecat.compiler.semantic.verification import (
    VerifiedSemanticGraph,
    verify_implementation_catalog,
    verify_semantic_graph,
    verify_source_map,
)
from scopecat.compiler.typed.point_domain import is_point_coordinate_type
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemLocation,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.units import is_supported_unit
from scopecat.kernel.value_types import Entity, Payload, Route, Scalar, Series, Table
from scopecat.records.parameter import Quantity as QuantityValue


@dataclass(frozen=True, slots=True)
class VerifiedAssemblyGraph:
    """Source graph facts safe for config-dependent lowering to consume."""

    semantic_graph: VerifiedSemanticGraph
    source_map: SourceMap
    resource_ports: Mapping[LogicalResourcePortId, ResourcePort]
    product_ports: Mapping[ProductId, ModuleProductPort]


@dataclass(frozen=True, slots=True)
class VerifiedAssembly:
    """One source assembly paired with its config-free verification proof."""

    source: SemanticExperimentIR
    graph: VerifiedAssemblyGraph

    @property
    def experiment_id(self) -> str:
        """Return the entrypoint identity established by assembly verification."""

        return cast("str", self.source.experiment_id)

    @property
    def kind(self) -> str:
        """Return the experiment kind established by assembly verification."""

        return cast("str", self.source.kind)


def verify_assembly_graph(
    assembly: SemanticExperimentIR,
) -> VerifiedAssemblyGraph:
    """Verify and order the config-independent portion of an assembly.

    The verifier deliberately has no authoring context or config argument.  A
    successful result therefore proves that config-dependent linking will not
    encounter a missing compute producer, a compute cycle, or a dangling
    logical-resource reference.
    """

    problems: list[Problem] = []
    try:
        semantic_graph = verify_semantic_graph(assembly.semantic_graph)
    except CheckFailed as error:
        problems.extend(error.problems)
        semantic_graph = None
    try:
        verify_implementation_catalog(
            assembly.semantic_graph,
            assembly.implementation_catalog,
        )
    except CheckFailed as error:
        problems.extend(error.problems)
    try:
        source_map = verify_source_map(assembly.semantic_graph, assembly.source_map)
    except CheckFailed as error:
        problems.extend(error.problems)
        source_map = None
    resource_ports = _resource_ports(assembly.resource_ports, problems)
    if semantic_graph is not None:
        _verify_compute_input_availability(semantic_graph, problems)
        _verify_compute_routes(semantic_graph, resource_ports, problems)
        _verify_state_compute_values(assembly, semantic_graph, problems)
    _verify_state_resource_ports(assembly, resource_ports, problems)
    if semantic_graph is not None:
        _verify_plan_value_availability(assembly, semantic_graph, problems)
    product_ports = _verify_record_schema(assembly, resource_ports, problems)
    if problems:
        raise CheckFailed(problems)
    if semantic_graph is None or source_map is None:
        raise AssertionError(
            "successful assembly verification requires graph and source-map proofs"
        )
    return VerifiedAssemblyGraph(
        semantic_graph=semantic_graph,
        source_map=source_map,
        resource_ports=MappingProxyType(resource_ports),
        product_ports=MappingProxyType(product_ports),
    )


def _resource_ports(
    ports: Sequence[ResourcePort],
    problems: list[Problem],
) -> dict[LogicalResourcePortId, ResourcePort]:
    selected: dict[LogicalResourcePortId, ResourcePort] = {}
    duplicates: set[LogicalResourcePortId] = set()
    for port in ports:
        port_id = port.symbol_id
        if port_id in selected:
            duplicates.add(port_id)
            continue
        selected[port_id] = port
    for port_id in sorted(duplicates, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "module_resource_port_duplicate",
                f"duplicate resource port {port_id.qualified_name}",
                model_location("resources", *port_id.scope, port_id.local_id),
                category=ProblemCategory.CONFLICT,
            )
        )
    return selected


def _verify_compute_routes(
    graph: VerifiedSemanticGraph,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    for operation in graph.graph.operations:
        for input_name, use in operation.inputs:
            definition = graph.value_defs.get(use.value_id)
            if definition is None or not isinstance(
                definition.source, RouteValueSource
            ):
                continue
            location = model_location(
                "compute_nodes",
                *operation.id.scope,
                operation.id.local_id,
                "inputs",
                input_name,
            )
            port = ports.get(definition.source.port_id)
            if port is None:
                problems.append(
                    _problem(
                        "compute_route_port_missing",
                        f"compute node {operation.id.qualified_name!r} input "
                        f"{input_name!r} references undeclared route port "
                        f"{definition.source.port_id.qualified_name!r}",
                        location,
                    )
                )
                continue
            if not isinstance(definition.value_type, Route):
                problems.append(
                    _problem(
                        "compute_route_type_invalid",
                        f"compute node {operation.id.qualified_name!r} input "
                        f"{input_name!r} has a non-route route source",
                        location,
                    )
                )
                continue
            missing = sorted(
                set(definition.value_type.capabilities)
                - set(port.selector.capabilities)
            )
            if missing:
                problems.append(
                    _problem(
                        "compute_route_capability_missing",
                        f"compute node {operation.id.qualified_name!r} input "
                        f"{input_name!r} requires capabilities not declared by "
                        "route port "
                        f"{definition.source.port_id.qualified_name!r}: "
                        f"{', '.join(missing)}",
                        location,
                    )
                )


def _verify_state_resource_ports(
    assembly: SemanticExperimentIR,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    for index, binding in enumerate(assembly.bindings):
        _verify_state_resource_port(
            binding.port_id,
            binding.capability_id,
            ports,
            context="binding",
            location=model_location("bindings", index, "resource"),
            problems=problems,
        )
    for index, state in enumerate(assembly.semantic_graph.row_regions):
        if state.resource_port is None:
            continue
        _verify_state_resource_port(
            state.resource_port,
            state.capability_id,
            ports,
            context="state binding",
            location=model_location("state", index, "resource_port"),
            problems=problems,
        )
    for index, action in enumerate(assembly.semantic_graph.actions):
        _verify_state_resource_port(
            action.resource_port_id,
            action.capability_id,
            ports,
            context="action",
            location=model_location("actions", index, "resource_port"),
            problems=problems,
        )


def _verify_state_resource_port(
    port_id: LogicalResourcePortId,
    capability_id: str,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    *,
    context: str,
    location: ModelLocation,
    problems: list[Problem],
) -> None:
    port = ports.get(port_id)
    if port is None:
        problems.append(
            _problem(
                "module_unknown_resource_port",
                f"{context} references undeclared resource port "
                f"{port_id.qualified_name!r}",
                location,
                category=ProblemCategory.NOT_FOUND,
            )
        )
        return
    _verify_resource_port_capability(
        port_id,
        capability_id,
        port,
        location=location,
        problems=problems,
    )


def _verify_resource_port_capability(
    port_id: LogicalResourcePortId,
    capability_id: str | None,
    port: ResourcePort,
    *,
    location: ModelLocation,
    problems: list[Problem],
) -> None:
    if capability_id is not None and capability_id not in port.selector.capabilities:
        problems.append(
            _problem(
                "module_resource_port_capability_missing",
                f"resource port {port_id.qualified_name!r} does not declare "
                f"capability {capability_id!r}",
                location,
            )
        )


def _verify_compute_input_availability(
    graph: VerifiedSemanticGraph,
    problems: list[Problem],
) -> None:
    for operation in graph.graph.operations:
        for input_name, use in operation.inputs:
            definition = graph.value_defs.get(use.value_id)
            if definition is None:
                continue
            location = model_location(
                "compute_nodes",
                *operation.id.scope,
                operation.id.local_id,
                "inputs",
                input_name,
            )
            try:
                require_value_availability(
                    definition.availability,
                    stages=(ValueStage.PLAN, ValueStage.EXECUTE),
                    rates=(
                        (ValueRate.RUN, ValueRate.POINT, ValueRate.ROW)
                        if isinstance(
                            operation.contract.semantics,
                            ScalarBinarySemantics,
                        )
                        else (ValueRate.RUN, ValueRate.POINT)
                    ),
                    context="compute input",
                    location=location,
                )
            except ValueAvailabilityError as error:
                problems.append(_availability_problem(error))


def _verify_state_compute_values(
    assembly: SemanticExperimentIR,
    graph: VerifiedSemanticGraph,
    problems: list[Problem],
) -> None:
    values = [
        (model_location("bindings", index, "value"), binding.value)
        for index, binding in enumerate(assembly.bindings)
    ]
    for location, value in values:
        if not isinstance(value, ValueRef):
            continue
        availability = internal_value_ref_availability(value)
        try:
            require_value_availability(
                availability,
                stages=(ValueStage.PLAN, ValueStage.EXECUTE),
                rates=(ValueRate.RUN, ValueRate.POINT, ValueRate.ROW),
                context="state value",
                location=location,
            )
        except ValueAvailabilityError as error:
            problems.append(_availability_problem(error))
            continue
        if availability.stage == ValueStage.PLAN:
            lowered = internal_lower_value_ref(value)
            if not (
                isinstance(value.value_type, Scalar) and isinstance(lowered, ScalarExpr)
            ):
                problems.append(
                    _problem(
                        "state_binding_value_shape_invalid",
                        "state binding value must be scalar-shaped",
                        location,
                    )
                )
            continue
        value_id = semantic_value_id(value)
        definition = graph.value_defs.get(value_id)
        if definition is None or not isinstance(
            definition.source, OperationOutputSource
        ):
            problems.append(
                _problem(
                    "compute_payload_unknown_output",
                    "state references unknown compute output "
                    f"{value_id.qualified_name!r}",
                    location,
                )
            )
            continue
        if definition.value_type != value.value_type:
            problems.append(
                _problem(
                    "compute_edge_type_mismatch",
                    f"state expects compute output {value.value_type!r}, but "
                    f"output {definition.id.qualified_name!r} has type "
                    f"{definition.value_type!r}",
                    location,
                )
            )
            continue
        if not _is_payload_type(definition.value_type):
            problems.append(
                _problem(
                    "compute_payload_unavailable",
                    "state compute output is not an available payload: "
                    f"{definition.id.qualified_name!r}",
                    location,
                )
            )
    for index, region in enumerate(graph.graph.row_regions):
        definition = graph.value_defs.get(region.value.value_id)
        if definition is None:
            continue
        location = model_location("state", index, "value")
        try:
            require_value_availability(
                definition.availability,
                stages=(ValueStage.PLAN, ValueStage.EXECUTE),
                rates=(ValueRate.RUN, ValueRate.POINT, ValueRate.ROW),
                context="state value",
                location=location,
            )
        except ValueAvailabilityError as error:
            problems.append(_availability_problem(error))
            continue
        if definition.availability.stage is ValueStage.PLAN:
            assert isinstance(definition.value_type, Scalar), (
                "verified row-region state values must be scalar-shaped"
            )
            continue
        if not isinstance(definition.source, OperationOutputSource):
            problems.append(
                _problem(
                    "compute_payload_unknown_output",
                    "state references an execute value without a compute output: "
                    f"{definition.id.qualified_name!r}",
                    location,
                )
            )
        elif not _is_payload_type(definition.value_type):
            problems.append(
                _problem(
                    "compute_payload_unavailable",
                    "state compute output is not an available payload: "
                    f"{definition.id.qualified_name!r}",
                    location,
                )
            )
    for action_index, action in enumerate(graph.graph.actions):
        for field_name, use in action.fields:
            definition = graph.value_defs.get(use.value_id)
            if definition is None:
                continue
            location = model_location(
                "actions",
                action_index,
                "fields",
                field_name,
            )
            try:
                require_value_availability(
                    definition.availability,
                    stages=(ValueStage.PLAN, ValueStage.EXECUTE),
                    rates=(ValueRate.RUN, ValueRate.POINT),
                    context="action field",
                    location=location,
                )
            except ValueAvailabilityError as error:
                problems.append(_availability_problem(error))
                continue
            if definition.availability.stage is ValueStage.PLAN:
                if not isinstance(definition.value_type, Scalar):
                    problems.append(
                        _problem(
                            "action_field_value_shape_invalid",
                            "action field value must be scalar-shaped",
                            location,
                        )
                    )
                continue
            if not isinstance(definition.source, OperationOutputSource):
                problems.append(
                    _problem(
                        "compute_payload_unknown_output",
                        "action references an execute value without a compute output: "
                        f"{definition.id.qualified_name!r}",
                        location,
                    )
                )
            elif not _is_payload_type(definition.value_type):
                problems.append(
                    _problem(
                        "compute_payload_unavailable",
                        "action compute output is not an available payload: "
                        f"{definition.id.qualified_name!r}",
                        location,
                    )
                )


def _is_payload_type(value_type: object) -> bool:
    return isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload)


def _verify_plan_value_availability(
    assembly: SemanticExperimentIR,
    graph: VerifiedSemanticGraph,
    problems: list[Problem],
) -> None:
    for port in assembly.resource_ports:
        for index, value in enumerate(port.selector.entity_inputs):
            location = model_location(
                "resources",
                *port.scope,
                port.id,
                "selector",
                "entity_inputs",
                index,
            )
            if _require_plan_value(
                value,
                context="resource selector",
                location=location,
                problems=problems,
            ):
                _verify_resource_entity_input(
                    value,
                    location=location,
                    problems=problems,
                )

    for index, state in enumerate(graph.graph.row_regions):
        relation = graph.value_defs[state.relation.value_id]
        assert isinstance(relation.value_type, Table), (
            "verified row-region relations must be table-shaped"
        )
        _require_semantic_plan_value(
            graph,
            state.relation,
            context="state relation",
            location=model_location("state", index, "relation"),
            problems=problems,
        )
        if state.resource is not None:
            resource = graph.value_defs[state.resource.value_id]
            assert isinstance(resource.value_type, Scalar), (
                "verified row-region resource selectors must be scalar-shaped"
            )
            _require_semantic_plan_value(
                graph,
                state.resource,
                context="state resource selector",
                location=model_location("state", index, "resource"),
                problems=problems,
                rates=(ValueRate.RUN, ValueRate.POINT, ValueRate.ROW),
            )
        for route_index, route_entity in enumerate(state.route_entities):
            route = graph.value_defs[route_entity.value_id]
            assert isinstance(route.value_type, Scalar | Series), (
                "verified row-region route selectors must be scalar- or series-shaped"
            )
            _require_semantic_plan_value(
                graph,
                route_entity,
                context="state route selector",
                location=model_location(
                    "state",
                    index,
                    "route_entities",
                    route_index,
                ),
                problems=problems,
                rates=(ValueRate.RUN, ValueRate.POINT, ValueRate.ROW),
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


def _verify_resource_entity_input(
    value: ValueRef,
    *,
    location: ModelLocation,
    problems: list[Problem],
) -> None:
    value_type = value.value_type
    lowered = internal_lower_value_ref(value)
    valid = (
        isinstance(value_type, Scalar)
        and isinstance(value_type.atom, Entity)
        and isinstance(lowered, ScalarExpr)
    ) or (
        isinstance(value_type, Series)
        and isinstance(value_type.item_type.atom, Entity)
        and isinstance(lowered, SeriesExpr)
    )
    if valid:
        return
    problems.append(
        _problem(
            "module_resource_entity_input_invalid",
            "resource entity source must be a scalar or series entity value",
            location,
        )
    )


def _require_plan_value(
    value: ValueRef,
    *,
    context: str,
    location: ModelLocation,
    problems: list[Problem],
    rates: tuple[ValueRate, ...] = (ValueRate.RUN, ValueRate.POINT),
) -> bool:
    try:
        require_value_availability(
            internal_value_ref_availability(value),
            stages=(ValueStage.PLAN,),
            rates=rates,
            context=context,
            location=location,
        )
    except ValueAvailabilityError as error:
        problems.append(_availability_problem(error))
        return False
    return True


def _require_semantic_plan_value(
    graph: VerifiedSemanticGraph,
    use: ValueUse,
    *,
    context: str,
    location: ModelLocation,
    problems: list[Problem],
    rates: tuple[ValueRate, ...] = (ValueRate.RUN, ValueRate.POINT),
) -> None:
    definition = graph.value_defs.get(use.value_id)
    if definition is None:
        return
    try:
        require_value_availability(
            definition.availability,
            stages=(ValueStage.PLAN,),
            rates=rates,
            context=context,
            location=location,
        )
    except ValueAvailabilityError as error:
        problems.append(_availability_problem(error))


def _verify_record_schema(
    assembly: SemanticExperimentIR,
    resource_ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> dict[ProductId, ModuleProductPort]:
    _verify_record_resource_ports(assembly, resource_ports, problems)
    product_by_id: dict[ProductId, ModuleProductPort] = {}
    duplicate_products: set[ProductId] = set()
    for product in assembly.product_ports:
        if product.product_id in product_by_id:
            duplicate_products.add(product.product_id)
            continue
        product_by_id[product.product_id] = product
    if duplicate_products:
        problems.append(
            _problem(
                "module_product_duplicate",
                "experiment assembly defines duplicate products: "
                + ", ".join(sorted(item.qualified_name for item in duplicate_products)),
                model_location("products"),
                category=ProblemCategory.CONFLICT,
            )
        )

    records: list[tuple[str, RecordIntent | ModuleProductPort]] = [
        (record.id, record) for record in assembly.records
    ]
    product_uses: dict[ProductUseId, ProductUse] = {}
    conflicting_product_uses: dict[ProductUseId, tuple[ProductUse, ProductUse]] = {}
    for selection in assembly.record_selections:
        use = selection.product_use
        existing_use = product_uses.get(use.id)
        if existing_use is None:
            product_uses[use.id] = use
        elif existing_use != use:
            conflicting_product_uses.setdefault(use.id, (existing_use, use))
        record_id = selection.record_id or selection.product_id.qualified_name
        product = product_by_id.get(selection.product_id)
        if product is None:
            problems.append(
                _problem(
                    "module_product_unknown",
                    "experiment selects unknown product "
                    f"{selection.product_id.qualified_name}",
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
                    "experiment selects product "
                    f"{selection.product_id.qualified_name!r} from "
                    "another module instance",
                    model_location("records"),
                )
            )
            continue
        records.append((record_id, product))

    for use_id in sorted(conflicting_product_uses, key=lambda item: item.value):
        existing_use, conflicting_use = conflicting_product_uses[use_id]
        problems.append(
            _problem(
                "product_use_identity_conflict",
                f"product use {use_id.value!r} refers to both "
                f"{existing_use.product_id.qualified_name!r} and "
                f"{conflicting_use.product_id.qualified_name!r}",
                model_location("records"),
                category=ProblemCategory.CONFLICT,
            )
        )

    record_ids = [
        *(record.id for record in assembly.records),
        *(
            selection.record_id or selection.product_id.qualified_name
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

    point_columns = {
        column.id
        for column in point_domain_intent_value_type(assembly.point_domain).columns
        if is_point_coordinate_type(column.value_type)
    }
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
    return product_by_id


def _verify_record_resource_ports(
    assembly: SemanticExperimentIR,
    resource_ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    for record in assembly.records:
        if record.resource_port_id is None:
            continue
        port = resource_ports.get(record.resource_port_id)
        if port is None:
            problems.append(
                _problem(
                    "module_record_resource_port_missing",
                    f"record {record.id!r} references undeclared resource port "
                    f"{record.resource_port_id.qualified_name!r}",
                    model_location("records", record.id, "resource"),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        _verify_resource_port_capability(
            record.resource_port_id,
            record.capability,
            port,
            location=model_location("records", record.id, "capability"),
            problems=problems,
        )
    for product in assembly.product_ports:
        if product.resource_port_id is None:
            continue
        port = resource_ports.get(product.resource_port_id)
        if port is None:
            problems.append(
                _problem(
                    "module_record_resource_port_missing",
                    f"product {product.qualified_id!r} references undeclared resource "
                    f"port {product.resource_port_id.qualified_name!r}",
                    model_location(
                        "products",
                        *product.scope,
                        product.id,
                        "resource",
                    ),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        _verify_resource_port_capability(
            product.resource_port_id,
            product.capability,
            port,
            location=model_location(
                "products",
                *product.scope,
                product.id,
                "capability",
            ),
            problems=problems,
        )


def _verify_record_definition(
    record_id: str,
    record: RecordIntent | ModuleProductPort,
    problems: list[Problem],
) -> None:
    if record.unit is not None and not is_supported_unit(record.unit):
        problems.append(
            _problem(
                "product_unit_unsupported",
                f"product {record_id!r} uses unsupported unit {record.unit!r}",
                model_location("records", record_id, "unit"),
            )
        )
    duplicate_axes = _duplicates([axis.id for axis in record.axes])
    for axis_id in duplicate_axes:
        problems.append(
            _problem(
                "product_axis_duplicate",
                f"product {record_id!r} axis {axis_id!r} is duplicated",
                model_location("records", record_id, "axes"),
                category=ProblemCategory.CONFLICT,
            )
        )
    for axis in record.axes:
        location = model_location("records", record_id, "axes", axis.id)
        if axis.id == "point":
            problems.append(
                _problem(
                    "product_axis_reserved",
                    "product axis 'point' conflicts with the point dimension",
                    location,
                )
            )
        if axis.unit is not None and not is_supported_unit(axis.unit):
            problems.append(
                _problem(
                    "product_axis_unit_unsupported",
                    f"product {record_id!r} axis {axis.id!r} uses unsupported "
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


__all__ = [
    "VerifiedAssembly",
    "VerifiedAssemblyGraph",
    "verify_assembly_graph",
]
