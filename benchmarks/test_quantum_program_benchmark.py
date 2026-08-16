from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

_STRESS_ENTITY_COUNT = 10_000
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
            str(_STRESS_ENTITY_COUNT),
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

    assert result["schema"] == "scopecat.quantum_program_benchmark.v1"
    assert result["entity_count"] == _STRESS_ENTITY_COUNT
    assert result["selected_entity_count"] == _STRESS_ENTITY_COUNT
    assert result["structural_operation_count"] == 1
    assert result["expanded_operation_count"] == _STRESS_ENTITY_COUNT
    assert result["unresolved_operation_count"] == 1
    assert result["expansion_preflight_rejected"] is True
    assert cast("int", result["inspection_returned_node_count"]) <= (
        cast("int", result["inspection_layer_count"]) * _INSPECTION_PAGE_SIZE
    )
    assert (
        cast("int", result["inspection_max_entity_references"])
        <= _MAX_ENTITY_REFERENCES_PER_NODE
    )
    assert cast("int", result["inspection_bytes"]) <= _MAX_INSPECTION_BYTES
