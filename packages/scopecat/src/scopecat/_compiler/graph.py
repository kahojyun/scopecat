"""Validation and stable ordering for typed compute graphs."""

from __future__ import annotations

import heapq
from collections.abc import Sequence

from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import ComputeEdge, TypedComputeNode


class ComputeGraphError(ValueError):
    """One structural compiler error in the compute graph."""

    def __init__(self, code: str, message: str, path: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def order_compute_nodes(
    nodes: Sequence[TypedComputeNode],
) -> tuple[TypedComputeNode, ...]:
    """Validate producers and return a declaration-stable topological order."""

    selected = tuple(nodes)
    positions: dict[NodeId, int] = {}
    producers: dict[NodeId, TypedComputeNode] = {}
    for index, node in enumerate(selected):
        existing = producers.get(node.id)
        if existing is not None:
            raise ComputeGraphError(
                "compute_producer_duplicate",
                (
                    f"compute producer {node.id.qualified_name!r} is declared "
                    "more than once"
                ),
                f"compute_nodes.{node.id.qualified_name}",
            )
        positions[node.id] = index
        producers[node.id] = node

    dependencies: dict[NodeId, tuple[NodeId, ...]] = {}
    dependents: dict[NodeId, list[NodeId]] = {node.id: [] for node in selected}
    indegree: dict[NodeId, int] = {node.id: 0 for node in selected}
    for node in selected:
        upstream: list[NodeId] = []
        for input_name, input_value in node.inputs.items():
            if not isinstance(input_value, ComputeEdge):
                continue
            producer_id = input_value.producer
            if producer_id not in producers:
                raise ComputeGraphError(
                    "compute_producer_missing",
                    (
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} references missing producer "
                        f"{producer_id.qualified_name!r}"
                    ),
                    f"compute_nodes.{node.id.qualified_name}.inputs.{input_name}",
                )
            producer = producers[producer_id]
            if producer.output_type != input_value.value_type:
                raise ComputeGraphError(
                    "compute_edge_type_mismatch",
                    (
                        f"compute node {node.id.qualified_name!r} input "
                        f"{input_name!r} expects {input_value.value_type!r}, but "
                        f"producer {producer_id.qualified_name!r} returns "
                        f"{producer.output_type!r}"
                    ),
                    f"compute_nodes.{node.id.qualified_name}.inputs.{input_name}",
                )
            if producer_id not in upstream:
                upstream.append(producer_id)
        dependencies[node.id] = tuple(upstream)
        indegree[node.id] = len(upstream)
        for producer_id in upstream:
            dependents[producer_id].append(node.id)

    ready = [positions[node_id] for node_id, count in indegree.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[TypedComputeNode] = []
    while ready:
        position = heapq.heappop(ready)
        node = selected[position]
        ordered.append(node)
        for dependent_id in dependents[node.id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                heapq.heappush(ready, positions[dependent_id])

    if len(ordered) != len(selected):
        cycle = _cycle_path(
            dependencies,
            remaining={node_id for node_id, count in indegree.items() if count > 0},
            positions=positions,
        )
        rendered = " -> ".join(node_id.qualified_name for node_id in cycle)
        first = cycle[0]
        raise ComputeGraphError(
            "compute_graph_cycle",
            f"compute graph contains a dependency cycle: {rendered}",
            f"compute_nodes.{first.qualified_name}",
        )

    return tuple(ordered)


def _cycle_path(
    dependencies: dict[NodeId, tuple[NodeId, ...]],
    *,
    remaining: set[NodeId],
    positions: dict[NodeId, int],
) -> tuple[NodeId, ...]:
    visited: set[NodeId] = set()
    active: list[NodeId] = []
    active_positions: dict[NodeId, int] = {}

    def visit(node_id: NodeId) -> tuple[NodeId, ...] | None:
        visited.add(node_id)
        active_positions[node_id] = len(active)
        active.append(node_id)
        for producer_id in dependencies[node_id]:
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

    for node_id in sorted(remaining, key=positions.__getitem__):
        if node_id in visited:
            continue
        found = visit(node_id)
        if found is not None:
            return found
    raise AssertionError("cyclic compute graph did not yield a cycle path")


__all__ = ["ComputeGraphError", "order_compute_nodes"]
