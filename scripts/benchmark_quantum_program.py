"""Measure retained-map verification and bounded quantum-program inspection."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import asdict
from typing import cast

from scopecat_quantum import authoring
from scopecat_quantum.inspection import QuantumInspectionBounds, inspect_quantum_program
from scopecat_quantum.programs import (
    QuantumProgramExpansionError,
    estimate_quantum_program_workload,
)


def _options() -> tuple[int, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entities", type=int, default=1_000)
    parser.add_argument("--inspection-page-size", type=int, default=128)
    options = parser.parse_args()
    entities = cast("int", options.entities)
    page_size = cast("int", options.inspection_page_size)
    if entities < 2:
        raise ValueError("entities must be at least two to exercise budget preflight")
    if not 1 <= page_size <= 512:
        raise ValueError("inspection page size must be between one and 512")
    return entities, page_size


def main() -> None:
    entity_count, page_size = _options()
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
        bound.verified.expand_unresolved(
            max_expanded_operations=preflight_limit,
        )
    except QuantumProgramExpansionError as error:
        expansion_preflight_rejected = (
            error.expanded_operation_count == workload.expanded_operation_count
            and error.limit == preflight_limit
        )
    preflight_seconds = time.perf_counter() - preflight_started

    inspection_started = time.perf_counter()
    inspection = inspect_quantum_program(
        declaration,
        bound=bound,
        bounds=QuantumInspectionBounds(max_nodes_per_layer=page_size),
        snapshot_id="benchmark-large-map",
    )
    inspection_seconds = time.perf_counter() - inspection_started
    inspection_bytes = len(
        json.dumps(asdict(inspection), separators=(",", ":"), sort_keys=True).encode()
    )
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    returned_nodes = tuple(node for layer in inspection.layers for node in layer.nodes)
    result = {
        "schema": "scopecat.quantum_program_benchmark.v1",
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
        "inspection_seconds": inspection_seconds,
        "elapsed_seconds": time.perf_counter() - started,
        "retained_bytes": retained_bytes,
        "peak_bytes": peak_bytes,
    }
    print("QUANTUM_PROGRAM_BENCHMARK=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
