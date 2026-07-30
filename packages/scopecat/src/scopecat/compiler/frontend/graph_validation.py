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
from scopecat.authoring._products import (
    ModuleProductDecl,
    ProductAxis,
    product_axis_dimension_id,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
)
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.semantic_elaboration import semantic_value_id
from scopecat.compiler.semantic.model import (
    LocalPythonImplementation,
)
from scopecat.compiler.semantic.verification import (
    VerifiedSemanticGraph,
    verify_semantic_graph,
)
from scopecat.graph.relations.model import ScalarExpr
from scopecat.graph.relations.point_domain import (
    analyze_point_domain,
    is_point_coordinate_type,
)
from scopecat.graph.values import (
    OperationId,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemLocation,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.units import is_supported_unit
from scopecat.kernel.value_types import Entity, Payload, Scalar


@dataclass(frozen=True, slots=True)
class VerifiedAssemblyGraph:
    """Source graph facts safe for config-dependent lowering to consume."""

    semantic_graph: VerifiedSemanticGraph
    implementations: Mapping[OperationId, LocalPythonImplementation]
    product_declarations: Mapping[ProductId, ModuleProductDecl]


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
    resource_ports = _resource_ports(assembly.resource_ports, problems)
    product_declarations = _verify_product_schema(assembly, problems)
    try:
        semantic_graph = verify_semantic_graph(
            assembly.semantic_graph,
            effects=assembly.semantic_effects,
        )
    except CheckFailed as error:
        problems.extend(error.problems)
        semantic_graph = None
    if semantic_graph is not None:
        _verify_binding_compute_values(assembly, semantic_graph, problems)
    _verify_property_resource_ports(assembly, resource_ports, problems)
    _verify_postcondition_dependencies(assembly, resource_ports, problems)
    if semantic_graph is not None:
        _verify_static_value_dependencies(assembly, problems)
    if problems:
        raise CheckFailed(problems)
    if semantic_graph is None:
        raise AssertionError("successful assembly verification requires graph proofs")
    return VerifiedAssemblyGraph(
        semantic_graph=semantic_graph,
        implementations=assembly.implementations,
        product_declarations=MappingProxyType(product_declarations),
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
            )
        )
    return selected


def _verify_property_resource_ports(
    assembly: SemanticExperimentIR,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    for index, binding in enumerate(assembly.bindings):
        _verify_interface_resource_port(
            binding.port_id,
            binding.interface_id,
            ports,
            context="binding",
            location=model_location("bindings", index, "resource"),
            problems=problems,
        )
    for index, acquire in enumerate(assembly.acquisitions):
        _verify_interface_resource_port(
            acquire.resource_port_id,
            acquire.interface_id,
            ports,
            context="acquisition",
            location=model_location("acquisitions", index, "resource_port"),
            problems=problems,
        )
    for index, invocation in enumerate(assembly.invocations):
        _verify_interface_resource_port(
            invocation.port_id,
            invocation.interface_id,
            ports,
            context="invocation",
            location=model_location("invocations", index, "resource"),
            problems=problems,
        )


def _verify_interface_resource_port(
    port_id: LogicalResourcePortId,
    interface_id: str | None,
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
            )
        )
        return
    _verify_resource_port_interface(
        port_id,
        interface_id,
        port,
        location=location,
        problems=problems,
    )


def _verify_resource_port_interface(
    port_id: LogicalResourcePortId,
    interface_id: str | None,
    port: ResourcePort,
    *,
    location: ModelLocation,
    problems: list[Problem],
) -> None:
    if interface_id is not None and interface_id not in port.selector.interfaces:
        problems.append(
            _problem(
                "module_resource_port_interface_missing",
                f"resource port {port_id.qualified_name!r} does not declare "
                f"interface {interface_id!r}",
                location,
            )
        )


def _verify_binding_compute_values(
    assembly: SemanticExperimentIR,
    graph: VerifiedSemanticGraph,
    problems: list[Problem],
) -> None:
    values = [
        (model_location("bindings", index, "value"), binding.value)
        for index, binding in enumerate(assembly.bindings)
    ]
    values.extend(
        (
            model_location("invocations", invocation_index, "arguments", argument.id),
            argument.value,
        )
        for invocation_index, invocation in enumerate(assembly.invocations)
        for argument in invocation.arguments
    )
    for location, value in values:
        if not isinstance(value, ValueRef) or not internal_value_ref_requires_execution(
            value
        ):
            continue
        value_id = semantic_value_id(value)
        operation = graph.operation_results.get(value_id)
        if operation is None:
            problems.append(
                _problem(
                    "compute_payload_unknown_output",
                    "state references unknown compute output "
                    f"{value_id.qualified_name!r}",
                    location,
                )
            )
            continue
        if operation.result_type != value.value_type:
            problems.append(
                _problem(
                    "compute_edge_type_mismatch",
                    f"state expects compute output {value.value_type!r}, but "
                    f"output {operation.result_id.qualified_name!r} has type "
                    f"{operation.result_type!r}",
                    location,
                )
            )
            continue
        if not _is_payload_type(operation.result_type):
            problems.append(
                _problem(
                    "compute_payload_unavailable",
                    "state compute output is not an available payload: "
                    f"{operation.result_id.qualified_name!r}",
                    location,
                )
            )


def _is_payload_type(value_type: object) -> bool:
    return isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload)


def _verify_static_value_dependencies(
    assembly: SemanticExperimentIR,
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

    for product in assembly.product_declarations:
        for axis in product.axes:
            if not isinstance(axis.size, ValueRef):
                continue
            location = model_location(
                "products",
                *product.scope,
                product.id,
                "axes",
                axis.id,
                "size",
            )
            if internal_value_ref_requires_execution(axis.size):
                problems.append(
                    _problem(
                        "product_axis_value_requires_execution",
                        "product axis size cannot depend on an external operation",
                        location,
                    )
                )
            elif internal_value_ref_point_dependencies(axis.size):
                problems.append(
                    _problem(
                        "product_axis_value_depends_on_point",
                        "product axis size cannot depend on point coordinates",
                        location,
                    )
                )


def _verify_postcondition_dependencies(
    assembly: SemanticExperimentIR,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    postcondition = assembly.postcondition
    if postcondition is None:
        return
    selected_ports: set[LogicalResourcePortId] = set()
    for index, assignment in enumerate(postcondition.assignments):
        selected_ports.add(assignment.port_id)
        value = assignment.value
        if not isinstance(value, ValueRef):
            continue
        location = model_location("postcondition", index, "value")
        if internal_value_ref_requires_execution(value):
            problems.append(
                _problem(
                    "experiment_postcondition_requires_execution",
                    "experiment postcondition cannot depend on point-local compute",
                    location,
                )
            )
        if internal_value_ref_point_dependencies(value):
            problems.append(
                _problem(
                    "experiment_postcondition_depends_on_point",
                    "experiment postcondition cannot depend on scan coordinates",
                    location,
                )
            )
    for port_id in selected_ports:
        port = ports.get(port_id)
        if port is None:
            continue
        for index, value in enumerate(port.selector.entity_inputs):
            if not internal_value_ref_point_dependencies(value):
                continue
            problems.append(
                _problem(
                    "experiment_postcondition_resource_depends_on_point",
                    "experiment postcondition resource cannot depend on "
                    "scan coordinates",
                    model_location(
                        "postcondition",
                        "resources",
                        port_id.qualified_name,
                        index,
                    ),
                )
            )


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
    )
    if valid:
        return
    problems.append(
        _problem(
            "module_resource_entity_input_invalid",
            "resource entity source must be a scalar entity value",
            location,
        )
    )


def _require_plan_value(
    value: ValueRef,
    *,
    context: str,
    location: ModelLocation,
    problems: list[Problem],
) -> bool:
    if internal_value_ref_requires_execution(value):
        problems.append(
            _problem(
                "value_requires_execution",
                f"{context} cannot depend on an external operation",
                location,
            )
        )
        return False
    return True


def _verify_product_schema(
    assembly: SemanticExperimentIR,
    problems: list[Problem],
) -> dict[ProductId, ModuleProductDecl]:
    product_by_id: dict[ProductId, ModuleProductDecl] = {}
    duplicate_products: set[ProductId] = set()
    for product in assembly.product_declarations:
        if product.product_id in product_by_id:
            duplicate_products.add(product.product_id)
            continue
        product_by_id[product.product_id] = product
    for acquire_index, acquire in enumerate(assembly.acquisitions):
        for result_index, result in enumerate(acquire.results):
            if result.product_id in product_by_id:
                continue
            problems.append(
                _problem(
                    "acquire_product_definition_missing",
                    f"acquisition {acquire.id.qualified_name!r} references unknown "
                    f"product {result.product_id.qualified_name!r}",
                    model_location(
                        "acquisitions",
                        acquire_index,
                        "results",
                        result_index,
                        "product_id",
                    ),
                )
            )
    if duplicate_products:
        problems.append(
            _problem(
                "module_product_duplicate",
                "experiment assembly defines duplicate products: "
                + ", ".join(sorted(item.qualified_name for item in duplicate_products)),
                model_location("products"),
            )
        )

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
                    model_location("record_selections"),
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
                    model_location("record_selections"),
                )
            )
            continue
    for use_id in sorted(conflicting_product_uses, key=lambda item: item.value):
        existing_use, conflicting_use = conflicting_product_uses[use_id]
        problems.append(
            _problem(
                "product_use_identity_conflict",
                f"product use {use_id.value!r} refers to both "
                f"{existing_use.product_id.qualified_name!r} and "
                f"{conflicting_use.product_id.qualified_name!r}",
                model_location("record_selections"),
            )
        )

    record_ids = [
        selection.record_id or selection.product_id.qualified_name
        for selection in assembly.record_selections
    ]
    duplicate_records = _duplicates(record_ids)
    if duplicate_records:
        problems.append(
            _problem(
                "experiment_record_duplicate",
                "experiment definition selects duplicate record ids: "
                + ", ".join(duplicate_records),
                model_location("record_selections"),
            )
        )

    point_columns = {
        column.id
        for column in analyze_point_domain(assembly.point_domain).value_type.columns
        if is_point_coordinate_type(column.value_type)
    }
    for record_id in sorted(set(record_ids) & point_columns):
        problems.append(
            _problem(
                "experiment_record_coordinate_collision",
                f"record {record_id!r} conflicts with a point coordinate",
                model_location("record_selections", record_id),
            )
        )

    _verify_product_axes(assembly.product_declarations, problems)
    return product_by_id


def _verify_product_axes(
    products: Sequence[ModuleProductDecl],
    problems: list[Problem],
) -> None:
    shared_axes_by_dimension_id: dict[str, tuple[str, ProductAxis]] = {}
    for product in products:
        product_id = product.qualified_id
        _verify_product_definition(product, problems)
        seen_axis_ids: set[str] = set()
        seen_shared_dimensions: set[str] = set()
        for axis in product.axes:
            if axis.id in seen_axis_ids:
                continue
            seen_axis_ids.add(axis.id)
            if axis.shared_as is None:
                continue
            dimension_id = product_axis_dimension_id(product, axis)
            if dimension_id in seen_shared_dimensions:
                continue
            seen_shared_dimensions.add(dimension_id)
            existing = shared_axes_by_dimension_id.get(dimension_id)
            if existing is None:
                shared_axes_by_dimension_id[dimension_id] = (product_id, axis)
                continue
            existing_product_id, existing_axis = existing
            if _source_axes_can_conflict(existing_axis, axis):
                problems.append(
                    _problem(
                        "product_axis_conflict",
                        f"product {product_id!r} axis {axis.id!r} conflicts with "
                        f"product {existing_product_id!r} on shared dimension "
                        f"{dimension_id!r}; shared axes must have identical kinds, "
                        "sizes, and units",
                        model_location("products", product_id, "axes", axis.id),
                        related_locations=(
                            model_location(
                                "products",
                                existing_product_id,
                                "axes",
                                existing_axis.id,
                            ),
                        ),
                    )
                )


def _verify_product_definition(
    product: ModuleProductDecl,
    problems: list[Problem],
) -> None:
    product_id = product.qualified_id
    location = model_location("products", *product.scope, product.id)
    if product.unit is not None and not is_supported_unit(product.unit):
        problems.append(
            _problem(
                "product_unit_unsupported",
                f"product {product_id!r} uses unsupported unit {product.unit!r}",
                model_location(location.root, *location.path, "unit"),
            )
        )
    duplicate_axes = _duplicates([axis.id for axis in product.axes])
    for axis_id in duplicate_axes:
        problems.append(
            _problem(
                "product_axis_duplicate",
                f"product {product_id!r} axis {axis_id!r} is duplicated",
                model_location(location.root, *location.path, "axes"),
            )
        )
    axes_by_dimension_id: dict[str, ProductAxis] = {}
    for axis in product.axes:
        dimension_id = product_axis_dimension_id(product, axis)
        existing_axis = axes_by_dimension_id.get(dimension_id)
        if existing_axis is None:
            axes_by_dimension_id[dimension_id] = axis
            continue
        if existing_axis.id == axis.id:
            continue
        problems.append(
            _problem(
                "product_axis_dimension_duplicate",
                f"product {product_id!r} axes {existing_axis.id!r} and "
                f"{axis.id!r} use the same dataset dimension {dimension_id!r}",
                model_location(location.root, *location.path, "axes", axis.id),
                related_locations=(
                    model_location(
                        location.root,
                        *location.path,
                        "axes",
                        existing_axis.id,
                    ),
                ),
            )
        )
    for axis in product.axes:
        axis_location = model_location(location.root, *location.path, "axes", axis.id)
        if axis.unit is not None and not is_supported_unit(axis.unit):
            problems.append(
                _problem(
                    "product_axis_unit_unsupported",
                    f"product {product_id!r} axis {axis.id!r} uses unsupported "
                    f"unit {axis.unit!r}",
                    model_location(axis_location.root, *axis_location.path, "unit"),
                )
            )
        size = _literal_axis_size(axis)
        if size is not None and size <= 0:
            problems.append(
                _problem(
                    "product_axis_size_invalid",
                    "product axis size must be a positive integer",
                    model_location(axis_location.root, *axis_location.path, "size"),
                )
            )


def _source_axes_can_conflict(
    left: ProductAxis,
    right: ProductAxis,
) -> bool:
    if (left.kind or left.id) != (right.kind or right.id):
        return True
    if left.unit != right.unit or left.entity_values != right.entity_values:
        return True
    left_size = _literal_axis_size(left)
    right_size = _literal_axis_size(right)
    return left_size is not None and right_size is not None and left_size != right_size


def _literal_axis_size(axis: ProductAxis) -> int | None:
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
    related_locations: Sequence[ProblemLocation] = (),
) -> Problem:
    return problem(
        code=code,
        phase=ProblemPhase.AUTHORING,
        message=message,
        location=location,
        related_locations=related_locations,
    )
