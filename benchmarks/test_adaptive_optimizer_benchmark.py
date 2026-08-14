from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast


def test_adaptive_optimizer_benchmark_retains_bounded_suffixes() -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_adaptive_optimizer.py"
    completed = subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(script),
            "--decisions",
            "1025",
            "--domain-points",
            "1024",
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result_line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("ADAPTIVE_OPTIMIZER_BENCHMARK=")
    )
    result = cast(
        "dict[str, object]",
        json.loads(result_line.removeprefix("ADAPTIVE_OPTIMIZER_BENCHMARK=")),
    )
    assert result["schema"] == "scopecat.adaptive_optimizer_benchmark.v2"
    assert result["decisions"] == 1025
    assert result["accepted"] == 256
    assert result["rejected"] == 769
    assert result["retained_decisions"] == result["decision_window"] == 1024
    assert result["retained_observations"] == result["observation_window"] == 256
    assert result["retained_array_observables"] == 0
    assert result["proposal_point_count"] == 1024
    assert result["retained_fragment_payloads"] == 0
    assert result["omitted_array_observables"] == 256
    retained_bytes = cast("int", result["retained_bytes"])
    discarded_waveform_payload_bytes = cast(
        "int", result["discarded_waveform_payload_bytes"]
    )
    assert retained_bytes < discarded_waveform_payload_bytes
