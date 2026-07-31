"""Config-free verification for one fully composed logical program.

This pass owns invariants that depend only on the source graph.  Keeping it
separate from binding prevents malformed dataflow from being hidden behind an
unrelated config or parameter-catalog error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import cast

from scopecat.compiler.frontend.logical_lowering import (
    coerce_logical_inputs,
    validate_consumed_inputs,
)
from scopecat.compiler.frontend.value_binding import (
    bind_scalar_input_refs,
    bind_table_source,
)
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    ExpressionVerificationError,
    RowType,
    verify_scalar_expression,
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
from scopecat.kernel.value_types import Entity, Payload, Scalar, ValueType
from scopecat.program.bindings import ResourcePort
from scopecat.program.expression_analysis import expression_point_refs
from scopecat.program.expressions import ScalarExpr
from scopecat.program.logical import (
    LogicalComputeNode,
    LogicalProgram,
    ValueDef,
)
from scopecat.program.logical_graph import verify_logical_graph
from scopecat.program.parameters import ParameterValueContract
from scopecat.program.point_domain import (
    analyze_point_domain,
    is_point_coordinate_type,
)
from scopecat.program.products import (
    ModuleProductDecl,
    ProductAxis,
    product_axis_dimension_id,
)
from scopecat.program.value_graph import ValueId
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
)


@dataclass(frozen=True, slots=True)
class VerifiedLogicalProgram:
    """The only config-free compiler artifact accepted by binding."""

    program: LogicalProgram
    product_declarations: Mapping[ProductId, ModuleProductDecl]
    scalar_values: Mapping[ValueId, ScalarExpr]
    value_defs: Mapping[ValueId, ValueDef] = field(
        init=False,
        compare=False,
        hash=False,
    )
    operation_results: Mapping[ValueId, LogicalComputeNode] = field(
        init=False,
        compare=False,
        hash=False,
    )
    value_types: Mapping[ValueId, ValueType] = field(
        init=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scalar_values",
            MappingProxyType(dict(self.scalar_values)),
        )
        value_defs = {
            definition.id: definition for definition in self.program.value_defs
        }
        operation_results = {
            operation.result_id: operation for operation in self.program.compute_nodes
        }
        value_types = {
            definition.id: definition.value_type
            for definition in self.program.value_defs
        }
        value_types.update(
            {
                operation.result_id: operation.result_type
                for operation in self.program.compute_nodes
            }
        )
        object.__setattr__(self, "value_defs", MappingProxyType(value_defs))
        object.__setattr__(
            self,
            "operation_results",
            MappingProxyType(operation_results),
        )
        object.__setattr__(self, "value_types", MappingProxyType(value_types))

    @property
    def experiment_id(self) -> str:
        """Return the verified entrypoint identity."""

        return self.program.experiment_id

    @property
    def kind(self) -> str:
        """Return the verified experiment kind."""

        return self.program.kind


def verify_logical_program(program: LogicalProgram) -> VerifiedLogicalProgram:
    """Normalize and close every config-independent invariant once.

    The verifier deliberately has no authoring context or config argument.  A
    successful result therefore proves that config-dependent binding will not
    encounter a missing compute producer, a compute cycle, or a dangling
    logical-resource reference.
    """

    inputs = coerce_logical_inputs(program.input_ports, program.inputs)
    normalized = replace(
        program,
        inputs=inputs,
        value_defs=tuple(
            _bind_value_definition_inputs(definition, inputs)
            for definition in program.value_defs
        ),
    )
    problems: list[Problem] = []
    scalar_values = _verify_scalar_values(normalized, problems)
    resource_ports = _resource_ports(normalized.resource_ports, problems)
    product_declarations = _verify_product_schema(normalized, problems)
    try:
        verified_graph = verify_logical_graph(
            normalized.value_defs,
            normalized.compute_nodes,
            normalized.measurement_postprocessors,
            effects=normalized.product_effects,
        )
    except CheckFailed as error:
        problems.extend(error.problems)
        verified_graph = None
    if verified_graph is not None:
        _value_defs, compute_nodes, _measurement_postprocessors = verified_graph
        operation_results = {
            operation.result_id: operation for operation in compute_nodes
        }
        _verify_binding_compute_values(
            normalized,
            {definition.id for definition in normalized.value_defs},
            operation_results,
            problems,
        )
    _verify_property_resource_ports(normalized, resource_ports, problems)
    _verify_final_state_dependencies(normalized, resource_ports, problems)
    if verified_graph is not None:
        _verify_static_value_dependencies(normalized, problems)
    if problems:
        raise CheckFailed(problems)
    if verified_graph is None:
        raise AssertionError("successful logical verification requires graph proofs")
    value_defs, compute_nodes, measurement_postprocessors = verified_graph
    canonical = replace(
        normalized,
        value_defs=value_defs,
        compute_nodes=compute_nodes,
        measurement_postprocessors=measurement_postprocessors,
    )
    validate_consumed_inputs(canonical, inputs)
    return VerifiedLogicalProgram(
        program=canonical,
        product_declarations=MappingProxyType(product_declarations),
        scalar_values=scalar_values,
    )


def _bind_value_definition_inputs(
    definition: ValueDef,
    inputs: Mapping[str, object],
) -> ValueDef:
    source = definition.source
    if isinstance(source, ScalarExpr):
        return replace(
            definition,
            source=bind_scalar_input_refs(source, inputs),
        )
    return replace(definition, source=bind_table_source(source, inputs))


def _verify_scalar_values(
    program: LogicalProgram,
    problems: list[Problem],
) -> Mapping[ValueId, ScalarExpr]:
    point_columns = analyze_point_domain(program.point_domain).columns
    bindings = ExpressionTypeBindings(
        inputs={
            port.id: port.value_type
            for port in program.input_ports
            if isinstance(port.value_type, Scalar)
        },
        parameters={
            contract.parameter_id: contract.value_type
            for contract in program.parameter_contracts
            if isinstance(contract, ParameterValueContract)
            and isinstance(contract.value_type, Scalar)
        },
        point_row=RowType(point_columns) if point_columns else None,
    )
    verified: dict[ValueId, ScalarExpr] = {}
    for definition in sorted(
        program.value_defs,
        key=lambda item: item.id.qualified_name,
    ):
        source = definition.source
        if not isinstance(source, ScalarExpr):
            continue
        try:
            verified[definition.id] = verify_scalar_expression(
                source,
                bindings=bindings,
                expected_type=cast("Scalar", definition.value_type),
            )
        except ExpressionVerificationError as error:
            problems.append(
                problem(
                    code=f"expression_{error.code}",
                    phase=ProblemPhase.AUTHORING,
                    message=error.reason,
                    location=model_location(
                        "logical_program",
                        "values",
                        definition.id.qualified_name,
                        *error.path,
                    ),
                    details={
                        "relation_code": error.code,
                        "expression_path": list(error.path),
                    },
                )
            )
    return MappingProxyType(verified)


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
    program: LogicalProgram,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    for index, binding in enumerate(program.bindings):
        _verify_interface_resource_port(
            binding.port_id,
            binding.interface_id,
            ports,
            context="binding",
            location=model_location("bindings", index, "resource"),
            problems=problems,
        )
    for index, acquire in enumerate(program.acquisitions):
        _verify_interface_resource_port(
            acquire.resource_port_id,
            acquire.interface_id,
            ports,
            context="acquisition",
            location=model_location("acquisitions", index, "resource_port"),
            problems=problems,
        )
    for index, invocation in enumerate(program.invocations):
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
    program: LogicalProgram,
    definition_ids: set[ValueId],
    operation_results: Mapping[ValueId, LogicalComputeNode],
    problems: list[Problem],
) -> None:
    values = [
        (model_location("bindings", index, "value"), binding.value_id)
        for index, binding in enumerate(program.bindings)
    ]
    values.extend(
        (
            model_location("invocations", invocation_index, "arguments", argument.id),
            argument.value_id,
        )
        for invocation_index, invocation in enumerate(program.invocations)
        for argument in invocation.arguments
    )
    for location, value_id in values:
        operation = operation_results.get(value_id)
        if operation is None:
            if value_id not in definition_ids:
                problems.append(
                    _problem(
                        "logical_effect_value_unknown",
                        "logical effect references unknown value "
                        f"{value_id.qualified_name!r}",
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
    program: LogicalProgram,
    problems: list[Problem],
) -> None:
    for port in program.resource_ports:
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

    for product in program.product_declarations:
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


def _verify_final_state_dependencies(
    program: LogicalProgram,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    final_state = program.final_state
    if final_state is None:
        return
    selected_ports: set[LogicalResourcePortId] = set()
    definitions = {definition.id: definition for definition in program.value_defs}
    operation_result_ids = {operation.result_id for operation in program.compute_nodes}
    for index, assignment in enumerate(final_state.assignments):
        selected_ports.add(assignment.port_id)
        location = model_location("final_state", index, "value")
        if assignment.value_id in operation_result_ids:
            problems.append(
                _problem(
                    "experiment_final_state_requires_execution",
                    "experiment final_state cannot depend on point-local compute",
                    location,
                )
            )
        definition = definitions.get(assignment.value_id)
        source = None if definition is None else definition.source
        if isinstance(source, ScalarExpr) and expression_point_refs(source):
            problems.append(
                _problem(
                    "experiment_final_state_depends_on_point",
                    "experiment final_state cannot depend on scan coordinates",
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
                    "experiment_final_state_resource_depends_on_point",
                    "experiment final_state resource cannot depend on scan coordinates",
                    model_location(
                        "final_state",
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
    program: LogicalProgram,
    problems: list[Problem],
) -> dict[ProductId, ModuleProductDecl]:
    product_by_id: dict[ProductId, ModuleProductDecl] = {}
    duplicate_products: set[ProductId] = set()
    for product in program.product_declarations:
        if product.product_id in product_by_id:
            duplicate_products.add(product.product_id)
            continue
        product_by_id[product.product_id] = product
    for acquire_index, acquire in enumerate(program.acquisitions):
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
                "logical program defines duplicate products: "
                + ", ".join(sorted(item.qualified_name for item in duplicate_products)),
                model_location("products"),
            )
        )

    product_uses: dict[ProductUseId, ProductUse] = {}
    conflicting_product_uses: dict[ProductUseId, tuple[ProductUse, ProductUse]] = {}
    for selection in program.record_selections:
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
        for selection in program.record_selections
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
        for column in analyze_point_domain(program.point_domain).value_type.columns
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

    _verify_product_axes(program.product_declarations, problems)
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
