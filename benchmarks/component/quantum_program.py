# pyright: reportPrivateUsage=false
"""Measure retained quantum lowering and indexed program inspection."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import asdict
from typing import cast

from benchmarks.record import BENCHMARK_RESULT_PREFIX, benchmark_record_header
from scopecat.inspection import CompiledProgramInspectionQuery
from scopecat_quantum import authoring
from scopecat_quantum._ids import PulseProgramId
from scopecat_quantum.inspection import (
    QuantumInspectionBounds,
    build_quantum_program_inspection_snapshot,
)
from scopecat_quantum.programs import (
    QuantumProgramExpansionError,
    estimate_quantum_program_workload,
    plan_quantum_pulse_lowering,
)
from scopecat_quantum.pulse_implementations import ResolvedPulseImplementations


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

    lowering_budget_limit = workload.expanded_operation_count - 1
    lowering_output_id = PulseProgramId("benchmark-large-map-pulses")
    lowering_rejected_started = time.perf_counter()
    lowering_budget_rejected = False
    try:
        plan_quantum_pulse_lowering(
            bound.verified,
            ResolvedPulseImplementations(),
            output_id=lowering_output_id,
            max_expanded_operations=lowering_budget_limit,
        )
    except QuantumProgramExpansionError as error:
        lowering_budget_rejected = (
            error.expanded_operation_count == workload.expanded_operation_count
            and error.limit == lowering_budget_limit
        )
    lowering_rejected_seconds = time.perf_counter() - lowering_rejected_started

    lowering_started = time.perf_counter()
    lowering_plan = plan_quantum_pulse_lowering(
        bound.verified,
        ResolvedPulseImplementations(),
        output_id=lowering_output_id,
        max_expanded_operations=workload.expanded_operation_count,
    )
    lowering_plan_seconds = time.perf_counter() - lowering_started

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

    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    returned_nodes = tuple(node for layer in inspection.layers for node in layer.nodes)
    return {
        "entity_count": entity_count,
        "structural_operation_count": workload.structural_operation_count,
        "expanded_operation_count": workload.expanded_operation_count,
        "selected_entity_count": workload.selected_entity_count,
        "unresolved_operation_count": len(bound.verified.unresolved.operations),
        "lowering_budget_limit": lowering_budget_limit,
        "lowering_budget_rejected": lowering_budget_rejected,
        "lowering_plan_expanded_operation_count": (
            lowering_plan.expanded_operation_count
        ),
        "lowering_plan_retains_control_flow": (
            lowering_plan.body is bound.verified.program.body
        ),
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
        "lowering_rejected_seconds": lowering_rejected_seconds,
        "lowering_plan_seconds": lowering_plan_seconds,
        "inspection_snapshot_seconds": inspection_snapshot_seconds,
        "inspection_cold_page_seconds": inspection_cold_page_seconds,
        "inspection_warm_exact_seconds": inspection_warm_exact_seconds,
        "inspection_warm_exact_returned_node_count": len(warm_layer.nodes),
        "elapsed_seconds": time.perf_counter() - started,
        "retained_bytes": retained_bytes,
        "peak_bytes": peak_bytes,
    }


def main() -> None:
    entity_counts, page_size = _options()
    result = {
        **benchmark_record_header(
            case_id="quantum-program",
            case_version=4,
            kind="component",
        ),
        "inspection_page_size": page_size,
        "case_count": len(entity_counts),
        "cases": [
            _benchmark_case(entity_count, page_size) for entity_count in entity_counts
        ],
    }
    print(BENCHMARK_RESULT_PREFIX + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
