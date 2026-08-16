from __future__ import annotations

import json
import subprocess
import sys
from typing import cast

_STRESS_ENTITY_COUNTS = (100, 10_000)
_INSPECTION_PAGE_SIZE = 32
_MAX_INSPECTION_BYTES = 32 * 1024
_MAX_ENTITY_REFERENCES_PER_NODE = 64


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
    assert result["case_version"] == 4
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
