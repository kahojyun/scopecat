from __future__ import annotations

import subprocess
import sys


def test_internal_package_facades_are_empty() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from importlib import import_module

for module_name in (
    "scopecat.analysis",
    "scopecat_server.http",
    "scopecat_server.services",
    "scopecat_server.storage.sqlite",
):
    module = import_module(module_name)
    public_names = sorted(name for name in vars(module) if not name.startswith("_"))
    if public_names:
        raise SystemExit(f"internal package facade is not empty: {module_name}")
""",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


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
