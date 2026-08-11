from __future__ import annotations

import subprocess
import sys


def test_service_facade_loads_only_selected_service() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import scopecat_server.services as services

forbidden = {
    "scopecat_server.instruments.service",
    "scopecat_server.services.admission",
    "scopecat_server.services.application",
    "scopecat_server.services.config",
    "scopecat_server.services.executor",
    "scopecat_server.services.leases",
    "scopecat_server.services.payloads",
    "scopecat_server.services.runs",
}
loaded = forbidden.intersection(sys.modules)
if loaded:
    raise SystemExit(f"service facade imported implementations: {sorted(loaded)}")

services.CommandPayloadService
loaded = (forbidden - {"scopecat_server.services.payloads"}).intersection(sys.modules)
if loaded:
    raise SystemExit(f"payload service imported sibling services: {sorted(loaded)}")
""",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_sqlite_facade_loads_only_selected_adapter() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import scopecat_server.storage.sqlite as sqlite

forbidden = {
    "scopecat_server.storage.sqlite.config_registry",
    "scopecat_server.storage.sqlite.connection",
    "scopecat_server.storage.sqlite.control_plane",
    "scopecat_server.storage.sqlite.execution",
    "scopecat_server.storage.sqlite.object_store",
    "scopecat_server.storage.sqlite.project_store",
    "scopecat_server.storage.sqlite.run_repository",
}
loaded = forbidden.intersection(sys.modules)
if loaded:
    raise SystemExit(f"SQLite facade imported adapters: {sorted(loaded)}")

sqlite.SQLiteDatabase
loaded = (forbidden - {"scopecat_server.storage.sqlite.connection"}).intersection(
    sys.modules
)
if loaded:
    raise SystemExit(f"SQLite database imported sibling adapters: {sorted(loaded)}")
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
