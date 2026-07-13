"""Config-free verification for closed transient compiler programs."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from scopecat._compiler.graph import ComputeGraphError, order_compute_nodes
from scopecat._compiler.problems import compiler_problem
from scopecat._compiler.program import RouteInput, TypedProgram
from scopecat._compiler.records import plan_records, validate_record_plan
from scopecat._compiler.state import StateSpec
from scopecat._compute_result import ComputeResultRef
from scopecat.errors import CheckFailed
from scopecat.problems import ModelLocation, Problem, ProblemPhase, model_location
from scopecat.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Scalar,
    String,
)


def verify_typed_program(program: TypedProgram) -> TypedProgram:
    """Return a topologically ordered program after pure IR verification."""

    problems: list[Problem] = []
    try:
        compute_nodes = order_compute_nodes(program.compute_nodes)
    except ComputeGraphError as error:
        problems.append(_problem(error.code, str(error), error.location))
        compute_nodes = program.compute_nodes

    route_capabilities: dict[str, set[str]] = {}
    duplicate_routes: set[str] = set()
    for route in program.route_intents:
        if route.port_id in route_capabilities:
            duplicate_routes.add(route.port_id)
            continue
        route_capabilities[route.port_id] = set(route.capabilities)
    for port_id in sorted(duplicate_routes):
        problems.append(
            _problem(
                "resource_route_duplicate",
                f"route port {port_id!r} is declared more than once",
                model_location("route_intents", port_id),
            )
        )

    for node in compute_nodes:
        for input_name, input_value in node.inputs.items():
            if not isinstance(input_value, RouteInput):
                continue
            location = model_location(
                "compute_nodes",
                *node.id.scope,
                node.id.local_id,
                "inputs",
                input_name,
            )
            declared = route_capabilities.get(input_value.port_id)
            if declared is None:
                problems.append(
                    _problem(
                        "compute_route_port_missing",
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} references undeclared route port "
                        f"{input_value.port_id!r}",
                        location,
                    )
                )
                continue
            missing = sorted(set(input_value.value_type.capabilities) - declared)
            if missing:
                problems.append(
                    _problem(
                        "compute_route_capability_missing",
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} requires capabilities not declared by "
                        f"route port {input_value.port_id!r}: "
                        f"{', '.join(missing)}",
                        location,
                    )
                )

    producers = {node.id: node for node in compute_nodes}
    for location, state in _state_specs(program.state):
        if state.kind == "set" and (not state.capability_id or not state.field_path):
            problems.append(
                _problem(
                    "state_field_requires_capability",
                    "state capability and field path must be non-empty",
                    model_location(location.root, *location.path, "field"),
                )
            )
        value = state.value
        if not isinstance(value, ComputeResultRef):
            continue
        producer = producers.get(value.node_id)
        if producer is None:
            problems.append(
                _problem(
                    "compute_payload_unknown_node",
                    "state references unknown compute node "
                    f"{value.node_id.qualified_name!r}",
                    model_location(location.root, *location.path, "value"),
                )
            )
        elif not _is_payload_type(producer.output_type):
            problems.append(
                _problem(
                    "compute_payload_unavailable",
                    "state compute output is not an available payload: "
                    f"{value.node_id.qualified_name!r}",
                    model_location(location.root, *location.path, "value"),
                )
            )

    coordinate_ids = tuple(
        column.id
        for column in program.point_source.value_type.columns
        if is_point_coordinate_type(column.value_type)
    )
    problems.extend(
        validate_record_plan(
            plan_records(program.records, point_count=1),
            coordinate_ids=coordinate_ids,
            phase=ProblemPhase.AUTHORING,
        )
    )

    if problems:
        raise CheckFailed(problems)
    if compute_nodes == program.compute_nodes:
        return program
    return program.model_copy(update={"compute_nodes": compute_nodes})


def _state_specs(
    roots: Sequence[StateSpec],
) -> Iterator[tuple[ModelLocation, StateSpec]]:
    def visit(
        location: ModelLocation,
        state: StateSpec,
    ) -> Iterator[tuple[ModelLocation, StateSpec]]:
        yield location, state
        for index, child in enumerate(state.state or ()):
            yield from visit(
                model_location(location.root, *location.path, "state", index),
                child,
            )

    for index, state in enumerate(roots):
        yield from visit(model_location("state", index), state)


def _is_payload_type(value_type: object) -> bool:
    return isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload)


def is_point_coordinate_type(value_type: Scalar) -> bool:
    """Return whether point values of this type become dataset coordinates."""

    return isinstance(
        value_type.atom,
        Bool | Int | Float | String | Quantity | Entity,
    )


def _problem(code: str, message: str, location: ModelLocation) -> Problem:
    return compiler_problem(
        code,
        message,
        location,
        phase=ProblemPhase.AUTHORING,
    )


__all__ = [
    "is_point_coordinate_type",
    "verify_typed_program",
]
