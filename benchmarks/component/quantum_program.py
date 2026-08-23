# pyright: reportPrivateUsage=false
"""Measure bounded quantum authoring, retained lowering, and result shape."""

from __future__ import annotations

import argparse
import gc
import json
import time
import tracemalloc
from dataclasses import asdict
from typing import Annotated, cast

import scopecat as sc
from benchmarks.record import BENCHMARK_RESULT_PREFIX, benchmark_record_header
from scopecat.inspection import CompiledProgramInspectionQuery
from scopecat_quantum import authoring
from scopecat_quantum._ids import PulseProgramId
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import GateCall
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


def _integer_sequence(value: str, *, name: str) -> tuple[int, ...]:
    selected = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not selected or any(item <= 0 for item in selected):
        raise ValueError(f"{name} must contain positive integers")
    if len(selected) != len(set(selected)):
        raise ValueError(f"{name} must contain unique integers")
    return selected


def _options() -> tuple[tuple[int, ...], int, tuple[int, ...], int, int, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entities",
        default="1000",
        help="comma-separated entity counts, for example 100,1000,10000",
    )
    parser.add_argument("--inspection-page-size", type=int, default=128)
    parser.add_argument(
        "--family-points",
        default="10,1000",
        help="comma-separated point counts for exact family expansion",
    )
    parser.add_argument("--family-sequence-length", type=int, default=64)
    parser.add_argument("--local-shots", type=int, default=1024)
    parser.add_argument("--local-rounds", type=int, default=32)
    options = parser.parse_args()
    entities = _integer_sequence(
        cast("str", options.entities),
        name="entity counts",
    )
    page_size = cast("int", options.inspection_page_size)
    family_points = _integer_sequence(
        cast("str", options.family_points),
        name="family point counts",
    )
    family_sequence_length = cast("int", options.family_sequence_length)
    local_shots = cast("int", options.local_shots)
    local_rounds = cast("int", options.local_rounds)
    if any(count < 2 for count in entities):
        raise ValueError(
            "every entity count must be at least two to exercise budget preflight"
        )
    if not 1 <= page_size <= 512:
        raise ValueError("inspection page size must be between one and 512")
    if family_sequence_length <= 0:
        raise ValueError("family sequence length must be positive")
    if local_shots <= 0 or local_rounds <= 0:
        raise ValueError("local shot and round counts must be positive")
    return (
        entities,
        page_size,
        family_points,
        family_sequence_length,
        local_shots,
        local_rounds,
    )


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


def _family_program(
    *,
    sequence_length: int,
    local_rounds: int,
) -> tuple[
    authoring.ProgramDefinition,
    authoring.ProgramFamilyEnvelope,
    list[int],
]:
    x = authoring.single_qubit_gate("benchmark.family.x")
    y = authoring.single_qubit_gate("benchmark.family.y")
    envelope = authoring.ProgramFamilyEnvelope(
        allowed_gates=(x, y),
        max_operations=sequence_length,
        max_depth=sequence_length,
    )
    elaboration_count = [0]

    @authoring.fragment(
        id="benchmark.quantum.seeded-family",
        envelope=envelope,
    )
    def seeded_family(
        qubit: authoring.Qubit,
        length: Annotated[int, sc.IntType(minimum=1)],
        seed: Annotated[int, sc.IntType(minimum=0)],
    ) -> authoring.QuantumFragment:
        elaboration_count[0] += 1
        return authoring.sequence(
            *(
                x(qubit) if (seed + index) % 2 == 0 else y(qubit)
                for index in range(length)
            )
        )

    result_contract = authoring.CLASSIFIED_STATE_RESULT.with_dimensions(
        authoring.QuantumResultDimension("round", "round", local_rounds)
    )

    @authoring.program(id="benchmark.quantum.seeded-family-program")
    def declaration(
        qubit: authoring.Qubit,
        length: Annotated[int, sc.IntType(minimum=1)],
        seed: Annotated[int, sc.IntType(minimum=0)],
    ) -> authoring.QuantumFragment:
        return authoring.sequence(
            seeded_family(qubit, length, seed),
            authoring.measure(qubit, result="state", contract=result_contract),
        )

    return declaration, envelope, elaboration_count


def _benchmark_family_case(
    declaration: authoring.ProgramDefinition,
    envelope: authoring.ProgramFamilyEnvelope,
    elaboration_count: list[int],
    *,
    point_count: int,
    sequence_length: int,
    local_axis_kinds: tuple[str, ...],
    local_axis_sizes: tuple[int, ...],
) -> dict[str, object]:
    elaborations_before = elaboration_count[0]
    expanded_gate_operations = 0
    expanded_acquisition_operations = 0

    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    for point_index in range(point_count):
        bound = authoring.bind(
            declaration,
            {
                "qubit": "q0",
                "length": sequence_length,
                "seed": point_index,
            },
        )
        expanded_gate_operations += sum(
            isinstance(operation, GateCall) for operation in bound.verified.operations
        )
        expanded_acquisition_operations += sum(
            isinstance(operation, Measure) for operation in bound.verified.operations
        )
        del bound
    exact_point_preflight_seconds = time.perf_counter() - started
    (
        exact_point_preflight_retained_bytes,
        exact_point_preflight_peak_bytes,
    ) = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    result_values_per_point = 1
    for size in local_axis_sizes:
        result_values_per_point *= size
    return {
        "point_count": point_count,
        "sequence_length": sequence_length,
        "static_envelope_gate_operation_bound": (point_count * envelope.max_operations),
        "exact_expanded_gate_operation_count": expanded_gate_operations,
        "exact_expanded_acquisition_operation_count": (expanded_acquisition_operations),
        "exact_elaboration_count": elaboration_count[0] - elaborations_before,
        "exact_point_preflight_seconds": exact_point_preflight_seconds,
        "exact_point_preflight_seconds_per_point": (
            exact_point_preflight_seconds / point_count
        ),
        "exact_point_preflight_retained_bytes": (exact_point_preflight_retained_bytes),
        "exact_point_preflight_peak_bytes": exact_point_preflight_peak_bytes,
        "result_dataset_axis_kinds": ("point", *local_axis_kinds),
        "result_dataset_axis_sizes": (point_count, *local_axis_sizes),
        "result_values_per_point": result_values_per_point,
        "total_result_value_count": point_count * result_values_per_point,
    }


def _benchmark_program_family(
    point_counts: tuple[int, ...],
    *,
    sequence_length: int,
    local_shots: int,
    local_rounds: int,
) -> dict[str, object]:
    static_started = time.perf_counter()
    declaration, envelope, elaboration_count = _family_program(
        sequence_length=sequence_length,
        local_rounds=local_rounds,
    )
    static_closure_seconds = time.perf_counter() - static_started

    static_inspection_started = time.perf_counter()
    static_inspection = declaration.draw()
    static_inspection_seconds = time.perf_counter() - static_inspection_started

    call = declaration("q0", sequence_length, 0).with_shots(local_shots)
    [product] = call.domain_call.product_declarations
    local_axis_kinds = tuple(axis.kind or axis.id for axis in product.axes)
    local_axis_sizes = tuple(
        axis.size
        for axis in product.axes
        if isinstance(axis.size, int) and not isinstance(axis.size, bool)
    )
    if len(local_axis_sizes) != len(product.axes):
        raise AssertionError("benchmark local result extents must be concrete integers")

    static_elaboration_count = elaboration_count[0]
    cases = tuple(
        _benchmark_family_case(
            declaration,
            envelope,
            elaboration_count,
            point_count=point_count,
            sequence_length=sequence_length,
            local_axis_kinds=local_axis_kinds,
            local_axis_sizes=local_axis_sizes,
        )
        for point_count in point_counts
    )
    return {
        "static_closure_seconds": static_closure_seconds,
        "static_inspection_seconds": static_inspection_seconds,
        "static_inspection_bytes": len(static_inspection.encode()),
        "static_elaboration_count": static_elaboration_count,
        "allowed_gate_count": len(envelope.allowed_gates),
        "envelope_max_operations": envelope.max_operations,
        "envelope_max_depth": envelope.max_depth,
        "local_result_axis_kinds": local_axis_kinds,
        "local_result_axis_sizes": local_axis_sizes,
        "cases": cases,
    }


def main() -> None:
    (
        entity_counts,
        page_size,
        family_point_counts,
        family_sequence_length,
        local_shots,
        local_rounds,
    ) = _options()
    result = {
        **benchmark_record_header(
            case_id="quantum-program",
            case_version=5,
            kind="component",
        ),
        "inspection_page_size": page_size,
        "case_count": len(entity_counts),
        "cases": [
            _benchmark_case(entity_count, page_size) for entity_count in entity_counts
        ],
        "program_family": _benchmark_program_family(
            family_point_counts,
            sequence_length=family_sequence_length,
            local_shots=local_shots,
            local_rounds=local_rounds,
        ),
    }
    print(BENCHMARK_RESULT_PREFIX + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
