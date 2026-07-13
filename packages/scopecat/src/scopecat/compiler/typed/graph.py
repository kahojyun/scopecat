"""Validation and stable ordering for typed compute graphs."""

from __future__ import annotations

import heapq
from collections.abc import Sequence

from scopecat.compiler.semantic.model import (
    OperationId,
    ValueId,
)
from scopecat.compiler.typed.program import ComputeEdge, TypedComputeNode
from scopecat.kernel.problems import ModelLocation, model_location


class ComputeGraphError(ValueError):
    """One structural compiler error in the compute graph."""

    def __init__(self, code: str, message: str, location: ModelLocation) -> None:
        super().__init__(message)
        self.code = code
        self.location = location


def order_compute_nodes(
    nodes: Sequence[TypedComputeNode],
) -> tuple[TypedComputeNode, ...]:
    """Validate producers and return an identity-stable topological order."""

    selected = tuple(nodes)
    operations: dict[OperationId, TypedComputeNode] = {}
    for node in selected:
        existing = operations.get(node.id)
        if existing is not None:
            raise ComputeGraphError(
                "compute_operation_duplicate",
                (
                    f"compute operation {node.id.qualified_name!r} is declared "
                    "more than once"
                ),
                model_location("compute_nodes", *node.id.scope, node.id.local_id),
            )
        operations[node.id] = node

    outputs: dict[ValueId, TypedComputeNode] = {}
    for node in selected:
        output_id = node.result.id
        existing = outputs.get(output_id)
        if existing is not None:
            raise ComputeGraphError(
                "compute_output_duplicate",
                f"compute output {output_id.qualified_name!r} is defined by both "
                f"{existing.id.qualified_name!r} and {node.id.qualified_name!r}",
                model_location(
                    "compute_nodes",
                    *node.id.scope,
                    node.id.local_id,
                    "result",
                    "id",
                ),
            )
        outputs[output_id] = node

    dependencies: dict[OperationId, tuple[OperationId, ...]] = {}
    dependents: dict[OperationId, list[OperationId]] = {
        node.id: [] for node in selected
    }
    indegree: dict[OperationId, int] = {node.id: 0 for node in selected}
    for node in selected:
        upstream: list[OperationId] = []
        for input_name, input_value in node.inputs.items():
            if not isinstance(input_value, ComputeEdge):
                continue
            producer = outputs.get(input_value.value_id)
            if producer is None:
                raise ComputeGraphError(
                    "compute_output_missing",
                    (
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} references missing output "
                        f"{input_value.value_id.qualified_name!r}"
                    ),
                    model_location(
                        "compute_nodes",
                        *node.id.scope,
                        node.id.local_id,
                        "inputs",
                        input_name,
                    ),
                )
            if producer.result.value_type != input_value.expected_type:
                raise ComputeGraphError(
                    "compute_edge_type_mismatch",
                    (
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} expects {input_value.expected_type!r}, but "
                        f"output {input_value.value_id.qualified_name!r} has type "
                        f"{producer.result.value_type!r}"
                    ),
                    model_location(
                        "compute_nodes",
                        *node.id.scope,
                        node.id.local_id,
                        "inputs",
                        input_name,
                    ),
                )
            producer_id = producer.id
            if producer_id not in upstream:
                upstream.append(producer_id)
        dependencies[node.id] = tuple(upstream)
        indegree[node.id] = len(upstream)
        for producer_id in upstream:
            dependents[producer_id].append(node.id)

    ready = [
        (node_id.qualified_name, node_id)
        for node_id, count in indegree.items()
        if count == 0
    ]
    heapq.heapify(ready)
    ordered: list[TypedComputeNode] = []
    while ready:
        _qualified_name, node_id = heapq.heappop(ready)
        node = operations[node_id]
        ordered.append(node)
        for dependent_id in dependents[node.id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                heapq.heappush(
                    ready,
                    (dependent_id.qualified_name, dependent_id),
                )

    if len(ordered) != len(selected):
        cycle = _cycle_path(
            dependencies,
            remaining={node_id for node_id, count in indegree.items() if count > 0},
        )
        rendered = " -> ".join(node_id.qualified_name for node_id in cycle)
        first = cycle[0]
        raise ComputeGraphError(
            "compute_graph_cycle",
            f"compute graph contains a dependency cycle: {rendered}",
            model_location("compute_nodes", *first.scope, first.local_id),
        )

    return tuple(ordered)


def _cycle_path(
    dependencies: dict[OperationId, tuple[OperationId, ...]],
    *,
    remaining: set[OperationId],
) -> tuple[OperationId, ...]:
    visited: set[OperationId] = set()
    active: list[OperationId] = []
    active_positions: dict[OperationId, int] = {}

    def visit(node_id: OperationId) -> tuple[OperationId, ...] | None:
        visited.add(node_id)
        active_positions[node_id] = len(active)
        active.append(node_id)
        for producer_id in sorted(
            dependencies[node_id],
            key=lambda item: item.qualified_name,
        ):
            if producer_id not in remaining:
                continue
            cycle_start = active_positions.get(producer_id)
            if cycle_start is not None:
                return (*active[cycle_start:], producer_id)
            if producer_id not in visited:
                found = visit(producer_id)
                if found is not None:
                    return found
        active.pop()
        active_positions.pop(node_id)
        return None

    for node_id in sorted(remaining, key=lambda item: item.qualified_name):
        if node_id in visited:
            continue
        found = visit(node_id)
        if found is not None:
            return found
    raise AssertionError("cyclic compute graph did not yield a cycle path")


__all__ = ["ComputeGraphError", "order_compute_nodes"]
