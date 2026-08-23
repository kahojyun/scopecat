from __future__ import annotations

import json
import subprocess
import sys
from typing import cast

_STRESS_ENTITY_COUNTS = (100, 10_000)
_INSPECTION_PAGE_SIZE = 32
_MAX_INSPECTION_BYTES = 32 * 1024
_MAX_ENTITY_REFERENCES_PER_NODE = 64
_FAMILY_POINT_COUNTS = (4, 128)
_FAMILY_SEQUENCE_LENGTH = 32
_LOCAL_SHOTS = 64
_LOCAL_ROUNDS = 8


def test_large_quantum_program_retains_structure_and_bounded_inspection() -> None:
    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            "-m",
            "benchmarks",
            "run",
            "quantum-program",
            "--entities",
            ",".join(str(count) for count in _STRESS_ENTITY_COUNTS),
            "--inspection-page-size",
            str(_INSPECTION_PAGE_SIZE),
            "--family-points",
            ",".join(str(count) for count in _FAMILY_POINT_COUNTS),
            "--family-sequence-length",
            str(_FAMILY_SEQUENCE_LENGTH),
            "--local-shots",
            str(_LOCAL_SHOTS),
            "--local-rounds",
            str(_LOCAL_ROUNDS),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result_line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("BENCHMARK_RESULT=")
    )
    result = cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("BENCHMARK_RESULT=")),
    )

    assert result["schema"] == "scopecat.benchmark_result.v1"
    assert result["case_id"] == "quantum-program"
    assert result["case_version"] == 5
    assert result["kind"] == "component"
    assert result["case_count"] == len(_STRESS_ENTITY_COUNTS)
    assert result["inspection_page_size"] == _INSPECTION_PAGE_SIZE
    cases = cast("list[dict[str, object]]", result["cases"])
    assert [case["entity_count"] for case in cases] == list(_STRESS_ENTITY_COUNTS)
    for case, entity_count in zip(cases, _STRESS_ENTITY_COUNTS, strict=True):
        assert case["selected_entity_count"] == entity_count
        assert case["structural_operation_count"] == 1
        assert case["expanded_operation_count"] == entity_count
        assert case["unresolved_operation_count"] == 1
        assert case["lowering_budget_rejected"] is True
        assert case["lowering_plan_expanded_operation_count"] == entity_count
        assert case["lowering_plan_retains_control_flow"] is True
        assert cast("int", case["inspection_returned_node_count"]) <= (
            cast("int", case["inspection_layer_count"]) * _INSPECTION_PAGE_SIZE
        )
        assert (
            cast("int", case["inspection_max_entity_references"])
            <= _MAX_ENTITY_REFERENCES_PER_NODE
        )
        assert cast("int", case["inspection_bytes"]) <= _MAX_INSPECTION_BYTES
        assert case["inspection_warm_exact_returned_node_count"] == 1

    family = cast("dict[str, object]", result["program_family"])
    assert family["static_elaboration_count"] == 0
    assert family["allowed_gate_count"] == 2
    assert family["envelope_max_operations"] == _FAMILY_SEQUENCE_LENGTH
    assert family["envelope_max_depth"] == _FAMILY_SEQUENCE_LENGTH
    assert family["local_result_axis_kinds"] == ["shot", "round"]
    assert family["local_result_axis_sizes"] == [_LOCAL_SHOTS, _LOCAL_ROUNDS]

    family_cases = cast("list[dict[str, object]]", family["cases"])
    assert [case["point_count"] for case in family_cases] == list(_FAMILY_POINT_COUNTS)
    for case, point_count in zip(
        family_cases,
        _FAMILY_POINT_COUNTS,
        strict=True,
    ):
        assert case["static_envelope_gate_operation_bound"] == (
            point_count * _FAMILY_SEQUENCE_LENGTH
        )
        assert case["exact_expanded_gate_operation_count"] == (
            point_count * _FAMILY_SEQUENCE_LENGTH
        )
        assert case["exact_expanded_acquisition_operation_count"] == point_count
        assert case["exact_elaboration_count"] == point_count
        assert case["result_dataset_axis_kinds"] == ["point", "shot", "round"]
        assert case["result_dataset_axis_sizes"] == [
            point_count,
            _LOCAL_SHOTS,
            _LOCAL_ROUNDS,
        ]
        assert case["result_values_per_point"] == _LOCAL_SHOTS * _LOCAL_ROUNDS
        assert case["total_result_value_count"] == (
            point_count * _LOCAL_SHOTS * _LOCAL_ROUNDS
        )
