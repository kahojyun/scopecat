from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from scopecat.daemon.endpoint import (
    DaemonEndpointRecord,
    daemon_record_path,
    read_daemon_endpoint_record,
)
from scopecat.project import open_project
from typer.testing import CliRunner

from scopecat_server.cli import app
from scopecat_server.lifecycle import (
    DaemonLifecycleError,
    initialize_project,
    inspect_daemon,
    stop_project,
    write_daemon_endpoint_record,
)


def test_init_creates_only_minimal_project_files_and_does_not_overwrite(
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("results/\n", encoding="utf-8")

    project = initialize_project(tmp_path)

    assert project.manifest.read_text(encoding="utf-8") == "[lab]\n"
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == (
        "results/\n.scopecat/\n"
    )
    assert not (tmp_path / ".scopecat").exists()

    with pytest.raises(DaemonLifecycleError, match="already initialized"):
        initialize_project(tmp_path)
    assert project.manifest.read_text(encoding="utf-8") == "[lab]\n"


def test_endpoint_record_is_private_and_round_trips(tmp_path: Path) -> None:
    initialize_project(tmp_path)
    record = _record(tmp_path, pid=123, process_create_time=45)

    path = write_daemon_endpoint_record(record)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_daemon_endpoint_record(tmp_path) == record


def test_stale_pid_identity_is_removed_without_terminating_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = initialize_project(tmp_path)
    write_daemon_endpoint_record(_record(tmp_path, pid=4321, process_create_time=10))
    process = _FakeProcess(create_time=20)

    def process_factory(_pid: int | None = None) -> _FakeProcess:
        return process

    monkeypatch.setattr(
        "scopecat_server.lifecycle.psutil.Process",
        process_factory,
    )

    observed = stop_project(project)

    assert observed.state == "stale"
    assert process.terminate_calls == 0
    assert not daemon_record_path(tmp_path).exists()


def test_matching_process_with_unreachable_health_is_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = initialize_project(tmp_path)
    record = _record(tmp_path, pid=4321, process_create_time=10)
    write_daemon_endpoint_record(record)

    def process_factory(_pid: int | None = None) -> _FakeProcess:
        return _FakeProcess(create_time=10)

    monkeypatch.setattr(
        "scopecat_server.lifecycle.psutil.Process",
        process_factory,
    )

    observed = inspect_daemon(project, health_timeout=0.01)

    assert observed.state == "degraded"
    assert observed.record == record


def test_cli_start_uses_actual_dynamic_port_and_stop_cleans_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    initialized = runner.invoke(app, ["init", str(tmp_path)])
    assert initialized.exit_code == 0, initialized.output

    started = runner.invoke(app, ["start", str(tmp_path)])
    assert started.exit_code == 0, started.output
    project = open_project(tmp_path)
    record = read_daemon_endpoint_record(tmp_path)
    assert record is not None
    try:
        assert record.base_url != "http://127.0.0.1:0"
        assert int(record.base_url.rsplit(":", maxsplit=1)[1]) > 0
        assert stat.S_IMODE(daemon_record_path(tmp_path).stat().st_mode) == 0o600
        with httpx.Client(timeout=2, trust_env=False) as client:
            health = client.get(f"{record.base_url}/api/v1/health")
        assert health.status_code == 200

        status = runner.invoke(app, ["status", str(tmp_path)])
        assert status.exit_code == 0, status.output
        assert "running" in status.output

        opened_urls: list[str] = []

        def open_browser(url: str) -> bool:
            opened_urls.append(url)
            return True

        monkeypatch.setattr(
            "scopecat_server.lifecycle.webbrowser.open",
            open_browser,
        )
        opened = runner.invoke(app, ["open", str(tmp_path)])
        assert opened.exit_code == 0, opened.output
        assert opened_urls == [record.base_url]

        stopped = runner.invoke(app, ["stop", str(tmp_path)])
        assert stopped.exit_code == 0, stopped.output
    finally:
        if daemon_record_path(tmp_path).exists():
            stop_project(project)

    assert not daemon_record_path(tmp_path).exists()


def _record(
    project_root: Path,
    *,
    pid: int,
    process_create_time: float,
) -> DaemonEndpointRecord:
    return DaemonEndpointRecord(
        project_root=project_root,
        pid=pid,
        process_create_time=process_create_time,
        base_url="http://127.0.0.1:1",
        started_at=datetime.now(UTC),
    )


class _FakeProcess:
    def __init__(self, *, create_time: float) -> None:
        self._create_time = create_time
        self.terminate_calls = 0

    def create_time(self) -> float:
        return self._create_time

    def terminate(self) -> None:
        self.terminate_calls += 1
