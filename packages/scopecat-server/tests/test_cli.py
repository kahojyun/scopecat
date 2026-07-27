from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scopecat.application import LabApplication
from scopecat.config.documents import load_config_snapshot_document
from scopecat.daemon.endpoint import DaemonEndpointRecord
from scopecat.project import Project
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from typer.testing import CliRunner

from scopecat_server.cli import app

_CONFIG_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-snapshot.json"
)


def test_config_check_resolves_lazy_bootstrap_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    config = load_config_snapshot_document(_CONFIG_FIXTURE)
    bootstrap_calls = 0

    def bootstrap_config() -> ConfigProfileSnapshot:
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        return config

    application = LabApplication(bootstrap_config=bootstrap_config)
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(application),
    )

    assert bootstrap_calls == 0
    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert bootstrap_calls == 1
    assert f"snapshot={config.id}" in result.output
    assert f"content_hash={config_content_hash(config)}" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_rejects_missing_bootstrap_factory(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert (
        "error: project application does not define bootstrap_config" in result.output
    )
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_reports_invalid_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    config = load_config_snapshot_document(_CONFIG_FIXTURE)
    invalid_binding = config.routing.bindings[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "routing": config.routing.model_copy(
                        update={"bindings": [invalid_binding]}
                    )
                }
            )
        }
    )
    application = LabApplication(bootstrap_config=lambda: invalid_config)
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(application),
    )

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error:" in result.output
    assert "configuration.unknown_routing_binding_instrument" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_reports_bootstrap_source_loader_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)

    def bootstrap_config() -> ConfigProfileSnapshot:
        return load_config_snapshot_document(tmp_path / "missing-config.json")

    application = LabApplication(bootstrap_config=bootstrap_config)
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(application),
    )

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error:" in result.output
    assert "missing-config.json" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_reports_application_import_error(tmp_path: Path) -> None:
    (tmp_path / "scopecat.toml").write_text(
        '[lab]\napplication = "missing_cli_application:create"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error:" in result.output
    assert "No module named 'missing_cli_application'" in result.output


def test_hidden_executor_lease_ttl_option_reaches_start_and_serve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    start_ttls: list[timedelta | None] = []
    serve_ttls: list[timedelta | None] = []

    def start_selected(
        project: Project,
        *,
        host: str,
        port: int,
        static_dir: Path | None,
        lease_ttl: timedelta | None,
    ) -> DaemonEndpointRecord:
        del host, port, static_dir
        start_ttls.append(lease_ttl)
        return DaemonEndpointRecord(
            project_root=project.root,
            pid=123,
            process_create_time=1,
            base_url="http://127.0.0.1:4321",
            started_at=datetime.now(UTC),
        )

    def serve_selected(
        project: Project,
        *,
        host: str,
        port: int,
        static_dir: Path | None,
        lease_ttl: timedelta | None,
    ) -> None:
        del project, host, port, static_dir
        serve_ttls.append(lease_ttl)

    monkeypatch.setattr("scopecat_server.cli.start_project", start_selected)
    monkeypatch.setattr("scopecat_server.cli.serve_project", serve_selected)
    runner = CliRunner()

    default_start = runner.invoke(app, ["start", str(tmp_path), "--api-only"])
    explicit_start = runner.invoke(
        app,
        [
            "start",
            str(tmp_path),
            "--api-only",
            "--executor-lease-ttl-seconds",
            "1.25",
        ],
    )
    explicit_serve = runner.invoke(
        app,
        [
            "serve",
            str(tmp_path),
            "--api-only",
            "--executor-lease-ttl-seconds",
            "1.25",
        ],
    )
    help_result = runner.invoke(app, ["start", "--help"])

    assert default_start.exit_code == 0, default_start.output
    assert explicit_start.exit_code == 0, explicit_start.output
    assert explicit_serve.exit_code == 0, explicit_serve.output
    assert start_ttls == [None, timedelta(seconds=1.25)]
    assert serve_ttls == [timedelta(seconds=1.25)]
    assert "--executor-lease-ttl-seconds" not in help_result.output


def _write_manifest(project: Path) -> None:
    (project / "scopecat.toml").write_text("[lab]\n", encoding="utf-8")


def _application_loader(
    application: LabApplication,
) -> Callable[[Project], LabApplication]:
    def load_application(_project: Project) -> LabApplication:
        return application

    return load_application
