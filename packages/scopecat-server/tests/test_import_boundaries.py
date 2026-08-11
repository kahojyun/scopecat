from __future__ import annotations

import subprocess
import sys


def test_daemon_runtime_keeps_optional_data_runtimes_cold() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import scopecat_server.runtime

forbidden = {
    "pandas",
    "pyarrow",
    "scopecat.measurements.dataset",
    "scopecat.measurements.results",
    "scopecat.sdk.domain",
    "scopecat_server.storage.sqlite.measurement_arrow",
    "xarray",
}
loaded = forbidden.intersection(sys.modules)
if loaded:
    raise SystemExit(
        f"daemon runtime imported optional data runtimes: {sorted(loaded)}"
    )
""",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
