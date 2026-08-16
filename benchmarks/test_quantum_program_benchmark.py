from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

_STRESS_ENTITY_COUNTS = (100, 10_000)
_INSPECTION_PAGE_SIZE = 32
_MAX_INSPECTION_BYTES = 32 * 1024
_MAX_ENTITY_REFERENCES_PER_NODE = 64


def test_large_quantum_program_retains_structure_and_bounded_inspection() -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_quantum_program.py"
    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
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
        if line.startswith("QUANTUM_PROGRAM_BENCHMARK=")
    )
    result = cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("QUANTUM_PROGRAM_BENCHMARK=")),
    )

    assert result["schema"] == "scopecat.quantum_program_benchmark.v4"
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
        assert case["exact_node_index_count"] == entity_count
        assert case["exact_node_matching_count"] == 1
        assert case["exact_node_returned_count"] == 1
        assert case["exact_node_cold_returned_count"] == 1
        assert cast("int", case["exact_node_response_bytes"]) <= 4 * 1024
        assert case["filter_matching_count"] == entity_count // 64
        assert cast("int", case["filter_returned_count"]) <= _INSPECTION_PAGE_SIZE
        assert case["filter_materialized_node_count"] == case["filter_matching_count"]
        assert cast("int", case["filter_materialized_node_count"]) < entity_count
        assert cast("int", case["filter_response_bytes"]) <= _MAX_INSPECTION_BYTES
