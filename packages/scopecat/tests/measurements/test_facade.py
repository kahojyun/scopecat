"""Public measurement-result facade import boundaries."""

from __future__ import annotations

import subprocess
import sys


def test_result_facade_keeps_native_projection_runtime_cold() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import scopecat.measurements.results as results

facade_forbidden = {
    "numpy",
    "pandas",
    "scopecat.measurements.dataset",
    "scopecat.measurements.interop",
    "scopecat.records.measurement",
    "xarray",
}
loaded = facade_forbidden.intersection(sys.modules)
if loaded:
    raise SystemExit(f"result facade imported native runtimes: {sorted(loaded)}")

results.MeasurementDatasetSchema
record_forbidden = {
    "pandas",
    "scopecat.measurements.dataset",
    "scopecat.measurements.interop",
    "xarray",
}
loaded = record_forbidden.intersection(sys.modules)
if loaded:
    raise SystemExit(f"record export imported native runtimes: {sorted(loaded)}")
""",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
