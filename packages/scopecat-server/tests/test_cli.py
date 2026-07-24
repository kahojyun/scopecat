from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from scopecat.application import LabApplication
from scopecat.config.profiles import load_config_profile
from scopecat.project import Project
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from typer.testing import CliRunner

from scopecat_server.cli import app

_CONFIG_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-profile.json"
)


def test_config_check_resolves_lazy_bootstrap_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)
    config = load_config_profile(_CONFIG_FIXTURE)
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
    assert "warnings=0" in result.output
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
    config = load_config_profile(_CONFIG_FIXTURE)
    invalid_connection = config.connection_profile.connections[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid_config = config.model_copy(
        update={
            "environment": config.environment.model_copy(
                update={
                    "connection_profile": config.connection_profile.model_copy(
                        update={"connections": [invalid_connection]}
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
    assert "configuration.unknown_connection_instrument" in result.output
    assert not (tmp_path / ".scopecat").exists()


def test_config_check_reports_bootstrap_source_loader_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path)

    def bootstrap_config() -> ConfigProfileSnapshot:
        return load_config_profile(tmp_path / "missing-config.json")

    application = LabApplication(bootstrap_config=bootstrap_config)
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(application),
    )

    result = CliRunner().invoke(app, ["config", "check", str(tmp_path)])

    assert result.exit_code == 1
    assert "error:" in result.output
    assert "config.profile.not_found" in result.output
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


def _write_manifest(project: Path) -> None:
    (project / "scopecat.toml").write_text("[lab]\n", encoding="utf-8")


def _application_loader(
    application: LabApplication,
) -> Callable[[Project], LabApplication]:
    def load_application(_project: Project) -> LabApplication:
        return application

    return load_application
