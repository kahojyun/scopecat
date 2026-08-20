"""Verify logical resource declarations, interfaces, and selectors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.kernel.instrument_members import (
    AcquisitionRef,
    InstrumentCapabilityRef,
    OperationRef,
    PropertyRef,
)
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.value_types import Entity, Scalar
from scopecat.program.bindings import ResourcePort
from scopecat.program.expressions import ScalarExpr
from scopecat.program.logical import LogicalProgram
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_value_ref,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
)


def collect_resource_ports(
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
            compiler_problem(
                "module_resource_port_duplicate",
                f"duplicate resource port {port_id.qualified_name}",
                model_location("resources", *port_id.scope, port_id.local_id),
                phase=ProblemPhase.AUTHORING,
            )
        )
    return selected


def verify_effect_resource_ports(
    program: LogicalProgram,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    for index, binding in enumerate(program.bindings):
        _verify_capability_resource_port(
            binding.port_id,
            PropertyRef(
                binding.interface_id,
                binding.component_path,
                binding.property_id,
            ),
            ports,
            context="binding",
            location=model_location("bindings", index, "resource"),
            problems=problems,
        )
    for index, acquire in enumerate(program.acquisitions):
        _verify_capability_resource_port(
            acquire.resource_port_id,
            AcquisitionRef(
                acquire.interface_id,
                acquire.component_path,
                acquire.acquisition_id,
            ),
            ports,
            context="acquisition",
            location=model_location("acquisitions", index, "resource_port"),
            problems=problems,
        )
    for index, invocation in enumerate(program.invocations):
        _verify_capability_resource_port(
            invocation.port_id,
            OperationRef(
                invocation.interface_id,
                invocation.component_path,
                invocation.operation_id,
            ),
            ports,
            context="invocation",
            location=model_location("invocations", index, "resource"),
            problems=problems,
        )


def verify_resource_selector_values(
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


def verify_success_state_resources(
    program: LogicalProgram,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    problems: list[Problem],
) -> None:
    success_state = program.success_state
    if success_state is None:
        return
    selected_ports = {assignment.port_id for assignment in success_state.assignments}
    for port_id in selected_ports:
        port = ports.get(port_id)
        if port is None:
            continue
        for index, value in enumerate(port.selector.entity_inputs):
            if not internal_value_ref_point_dependencies(value):
                continue
            problems.append(
                compiler_problem(
                    "experiment_success_state_resource_depends_on_point",
                    (
                        "experiment on_success resource cannot depend on point "
                        "coordinates"
                    ),
                    model_location(
                        "success_state",
                        "resources",
                        port_id.qualified_name,
                        index,
                    ),
                    phase=ProblemPhase.AUTHORING,
                )
            )


def _verify_capability_resource_port(
    port_id: LogicalResourcePortId,
    capability: InstrumentCapabilityRef,
    ports: Mapping[LogicalResourcePortId, ResourcePort],
    *,
    context: str,
    location: ModelLocation,
    problems: list[Problem],
) -> None:
    port = ports.get(port_id)
    if port is None:
        problems.append(
            compiler_problem(
                "module_unknown_resource_port",
                f"{context} references undeclared resource port "
                f"{port_id.qualified_name!r}",
                location,
                phase=ProblemPhase.AUTHORING,
            )
        )
        return
    if not port.selector.covers(capability):
        problems.append(
            compiler_problem(
                "module_resource_port_capability_missing",
                f"resource port {port_id.qualified_name!r} does not declare "
                f"capability {_describe_capability(capability)}",
                location,
                phase=ProblemPhase.AUTHORING,
            )
        )


def _describe_capability(capability: InstrumentCapabilityRef) -> str:
    if not isinstance(capability, PropertyRef | OperationRef | AcquisitionRef):
        return f"interface {capability.interface_id!r}"
    path = "/".join(capability.component_path) or "<root>"
    if isinstance(capability, PropertyRef):
        member = f"property {capability.property_id!r}"
    elif isinstance(capability, OperationRef):
        member = f"operation {capability.operation_id!r}"
    else:
        member = f"acquisition {capability.acquisition_id!r}"
    return f"{member} on {capability.interface_id!r} at {path}"


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
        compiler_problem(
            "module_resource_entity_input_invalid",
            "resource entity source must be a scalar entity value",
            location,
            phase=ProblemPhase.AUTHORING,
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
            compiler_problem(
                "value_requires_execution",
                f"{context} cannot depend on an external operation",
                location,
                phase=ProblemPhase.AUTHORING,
            )
        )
        return False
    return True
