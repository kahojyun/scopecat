"""Measure retained-map verification and indexed quantum-program inspection."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import asdict
from typing import cast

from scopecat.inspection import (
    CompiledProgramInspectionInvertedIndexBuilder,
    CompiledProgramInspectionLayerIndex,
    CompiledProgramInspectionNode,
    CompiledProgramInspectionNodeIndex,
    CompiledProgramInspectionQuery,
)
from scopecat_quantum import authoring
from scopecat_quantum.inspection import (
    QuantumInspectionBounds,
    build_quantum_program_inspection_snapshot,
)
from scopecat_quantum.programs import (
    QuantumProgramExpansionError,
    estimate_quantum_program_workload,
)


def _options() -> tuple[tuple[int, ...], int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entities",
        default="1000",
        help="comma-separated entity counts, for example 100,1000,10000",
    )
    parser.add_argument("--inspection-page-size", type=int, default=128)
    options = parser.parse_args()
    entities = tuple(
        int(value.strip())
        for value in cast("str", options.entities).split(",")
        if value.strip()
    )
    page_size = cast("int", options.inspection_page_size)
    if not entities or any(count < 2 for count in entities):
        raise ValueError(
            "every entity count must be at least two to exercise budget preflight"
        )
    if len(entities) != len(set(entities)):
        raise ValueError("entity counts must be unique")
    if not 1 <= page_size <= 512:
        raise ValueError("inspection page size must be between one and 512")
    return entities, page_size


def _benchmark_case(entity_count: int, page_size: int) -> dict[str, object]:
    gate = authoring.single_qubit_gate("benchmark.x90")

    @authoring.program(id="benchmark.quantum.large-map")
    def declaration(qubits: authoring.QubitSet) -> authoring.QuantumFragment:
        return authoring.parallel_each(qubits, gate)

    entity_ids = tuple(f"q{index}" for index in range(entity_count))
    tracemalloc.start()
    started = time.perf_counter()
    bound = authoring.bind(declaration, {"qubits": entity_ids})
    bound_seconds = time.perf_counter() - started
    workload = estimate_quantum_program_workload(bound.verified)

    preflight_limit = workload.expanded_operation_count - 1
    preflight_started = time.perf_counter()
    expansion_preflight_rejected = False
    try:
        bound.verified.require_expansion_budget(preflight_limit)
    except QuantumProgramExpansionError as error:
        expansion_preflight_rejected = (
            error.expanded_operation_count == workload.expanded_operation_count
            and error.limit == preflight_limit
        )
    preflight_seconds = time.perf_counter() - preflight_started

    snapshot_started = time.perf_counter()
    snapshot = build_quantum_program_inspection_snapshot(
        declaration,
        bound=bound,
        bounds=QuantumInspectionBounds(max_nodes_per_layer=page_size),
        snapshot_id="benchmark-large-map",
    )
    inspection_snapshot_seconds = time.perf_counter() - snapshot_started
    inspection_started = time.perf_counter()
    inspection = snapshot.project()
    inspection_cold_page_seconds = time.perf_counter() - inspection_started
    warm_query = CompiledProgramInspectionQuery(
        layer_id="logical",
        snapshot_id=snapshot.snapshot_id,
        node_id="logical:0",
        limit=1,
    )
    warm_started = time.perf_counter()
    warm_inspection = snapshot.project(warm_query)
    inspection_warm_exact_seconds = time.perf_counter() - warm_started
    warm_layer = next(
        layer for layer in warm_inspection.layers if layer.id == "logical"
    )
    inspection_bytes = len(
        json.dumps(asdict(inspection), separators=(",", ":"), sort_keys=True).encode()
    )

    exact_index_started = time.perf_counter()
    exact_ordinals = {
        f"physical:event:{ordinal}": ordinal for ordinal in range(entity_count)
    }
    filter_index = CompiledProgramInspectionInvertedIndexBuilder()
    for ordinal in range(entity_count):
        filter_index.add(
            ordinal,
            parent_id=None,
            kind="placement",
            entity_ids=(f"q{ordinal}",),
            resource_ids=(f"channel-{ordinal % 64}",),
        )
    materialized_node_count = 0

    def exact_node_at(
        ordinal: int,
        _query: CompiledProgramInspectionQuery | None,
    ) -> CompiledProgramInspectionNode:
        nonlocal materialized_node_count
        materialized_node_count += 1
        return CompiledProgramInspectionNode(
            id=f"physical:event:{ordinal}",
            kind="placement",
            label=f"physical event {ordinal}",
            entity_ids=(f"q{ordinal}",),
            resource_ids=(f"channel-{ordinal % 64}",),
        )

    exact_layer = CompiledProgramInspectionLayerIndex(
        id="physical",
        label="Physical placement",
        kind="physical",
        root_ids=(),
        nodes=CompiledProgramInspectionNodeIndex(
            node_count=entity_count,
            node_at=exact_node_at,
            ordinal_by_id=exact_ordinals.get,
            inverted_index=filter_index.build(),
        ),
    )
    exact_index_seconds = time.perf_counter() - exact_index_started
    exact_node_id = f"physical:event:{entity_count - 1}"
    exact_query = CompiledProgramInspectionQuery(
        layer_id="physical",
        snapshot_id="benchmark-exact-node",
        node_id=exact_node_id,
        limit=1,
    )
    exact_cold_started = time.perf_counter()
    _cold_layer, cold_selection = exact_layer.project(
        query=exact_query,
        default_limit=page_size,
        snapshot_id="benchmark-exact-node",
    )
    exact_cold_seconds = time.perf_counter() - exact_cold_started
    exact_warm_started = time.perf_counter()
    exact_projection, exact_selection = exact_layer.project(
        query=exact_query,
        default_limit=page_size,
        snapshot_id="benchmark-exact-node",
    )
    exact_warm_seconds = time.perf_counter() - exact_warm_started
    exact_response_bytes = len(
        json.dumps(
            asdict(exact_projection), separators=(",", ":"), sort_keys=True
        ).encode()
    )
    materialized_node_count = 0
    filter_query = CompiledProgramInspectionQuery(
        layer_id="physical",
        snapshot_id="benchmark-exact-node",
        kind="placement",
        resource_id="channel-63",
        limit=page_size,
    )
    filter_started = time.perf_counter()
    filter_projection, filter_selection = exact_layer.project(
        query=filter_query,
        default_limit=page_size,
        snapshot_id="benchmark-exact-node",
    )
    filter_seconds = time.perf_counter() - filter_started
    filter_response_bytes = len(
        json.dumps(
            asdict(filter_projection), separators=(",", ":"), sort_keys=True
        ).encode()
    )
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    returned_nodes = tuple(node for layer in inspection.layers for node in layer.nodes)
    return {
        "entity_count": entity_count,
        "structural_operation_count": workload.structural_operation_count,
        "expanded_operation_count": workload.expanded_operation_count,
        "selected_entity_count": workload.selected_entity_count,
        "unresolved_operation_count": len(bound.verified.unresolved.operations),
        "expansion_preflight_limit": preflight_limit,
        "expansion_preflight_rejected": expansion_preflight_rejected,
        "inspection_page_size": page_size,
        "inspection_layer_count": len(inspection.layers),
        "inspection_node_count": sum(layer.node_count for layer in inspection.layers),
        "inspection_returned_node_count": len(returned_nodes),
        "inspection_max_entity_references": max(
            (len(node.entity_ids) for node in returned_nodes),
            default=0,
        ),
        "inspection_bytes": inspection_bytes,
        "bound_seconds": bound_seconds,
        "expansion_preflight_seconds": preflight_seconds,
        "inspection_snapshot_seconds": inspection_snapshot_seconds,
        "inspection_cold_page_seconds": inspection_cold_page_seconds,
        "inspection_warm_exact_seconds": inspection_warm_exact_seconds,
        "inspection_warm_exact_returned_node_count": len(warm_layer.nodes),
        "exact_node_index_count": entity_count,
        "exact_node_index_seconds": exact_index_seconds,
        "exact_node_id": exact_node_id,
        "exact_node_cold_seconds": exact_cold_seconds,
        "exact_node_warm_seconds": exact_warm_seconds,
        "exact_node_matching_count": exact_selection.page.matching_node_count,
        "exact_node_returned_count": len(exact_selection.nodes),
        "exact_node_cold_returned_count": len(cold_selection.nodes),
        "exact_node_response_bytes": exact_response_bytes,
        "filter_query_seconds": filter_seconds,
        "filter_matching_count": filter_selection.page.matching_node_count,
        "filter_returned_count": len(filter_selection.nodes),
        "filter_materialized_node_count": materialized_node_count,
        "filter_response_bytes": filter_response_bytes,
        "elapsed_seconds": time.perf_counter() - started,
        "retained_bytes": retained_bytes,
        "peak_bytes": peak_bytes,
    }


def main() -> None:
    entity_counts, page_size = _options()
    result = {
        "schema": "scopecat.quantum_program_benchmark.v3",
        "inspection_page_size": page_size,
        "case_count": len(entity_counts),
        "cases": [
            _benchmark_case(entity_count, page_size) for entity_count in entity_counts
        ],
    }
    print("QUANTUM_PROGRAM_BENCHMARK=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
