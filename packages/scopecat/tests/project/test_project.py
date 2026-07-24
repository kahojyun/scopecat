from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scopecat.api.lab import LabClient
from scopecat.application.lab import LabApplication
from scopecat.daemon.endpoint import (
    DAEMON_URL_ENV,
    DaemonEndpointError,
    DaemonEndpointRecord,
    daemon_record_path,
)
from scopecat.project import (
    ProjectManifestError,
    load_application_factory,
    load_project,
    open_project,
)


def test_project_paths_are_resolved_from_manifest(tmp_path: Path) -> None:
    config = tmp_path / "config" / "initial.json"
    config.parent.mkdir()
    config.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "scopecat.toml"
    manifest.write_text(
        (
            "[lab]\n"
            'application = "my_lab.application:create"\n'
            'bootstrap-config = "config/initial.json"\n'
        ),
        encoding="utf-8",
    )

    project = load_project(manifest)

    assert project.root == tmp_path
    assert project.application_spec == "my_lab.application:create"
    assert project.bootstrap_config == config


def test_project_is_discovered_from_a_child_directory(tmp_path: Path) -> None:
    (tmp_path / "scopecat.toml").write_text(
        '[lab]\napplication = "my_lab.application:create"\n',
        encoding="utf-8",
    )
    child = tmp_path / "notebooks" / "calibration"
    child.mkdir(parents=True)

    assert open_project(child).root == tmp_path


def test_empty_lab_manifest_can_open_before_code_or_config_exists(
    tmp_path: Path,
) -> None:
    (tmp_path / "scopecat.toml").write_text("[lab]\n", encoding="utf-8")

    project = open_project(tmp_path)
    client = project.connect("http://daemon.local")

    assert project.application_spec is None
    assert isinstance(project.load_application(), LabApplication)
    assert isinstance(client, LabClient)
    client.close()


def test_project_connect_prioritizes_explicit_then_environment_then_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "scopecat.toml").write_text("[lab]\n", encoding="utf-8")
    project = open_project(tmp_path)
    record = DaemonEndpointRecord(
        project_root=tmp_path,
        pid=123,
        process_create_time=1,
        base_url="http://record.local:3000",
        started_at=datetime.now(UTC),
    )
    path = daemon_record_path(tmp_path)
    path.parent.mkdir()
    path.write_text(record.model_dump_json(), encoding="utf-8")

    monkeypatch.setenv(DAEMON_URL_ENV, "http://environment.local:2000")
    explicit = project.connect("http://explicit.local:1000")
    environment = project.connect()
    monkeypatch.delenv(DAEMON_URL_ENV)
    discovered = project.connect()

    assert str(explicit._daemon._client._http.base_url) == "http://explicit.local:1000"
    assert str(environment._daemon._client._http.base_url) == (
        "http://environment.local:2000"
    )
    assert str(discovered._daemon._client._http.base_url) == "http://record.local:3000"
    explicit.close()
    environment.close()
    discovered.close()


def test_project_connect_does_not_guess_a_fixed_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "scopecat.toml").write_text("[lab]\n", encoding="utf-8")
    monkeypatch.delenv(DAEMON_URL_ENV, raising=False)

    with pytest.raises(DaemonEndpointError, match="scopecat start"):
        open_project(tmp_path).connect()


def test_application_is_imported_from_project_src(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "src" / "project_application_fixture"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "application.py").write_text(
        (
            "from scopecat import LabApplication\n\n"
            "def create(_project):\n"
            "    return LabApplication()\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "path", sys.path.copy())

    factory = load_application_factory(
        "project_application_fixture.application:create",
        tmp_path,
    )

    assert isinstance(factory(tmp_path), LabApplication)


@pytest.mark.parametrize(
    "content, message",
    [
        ("", r"requires a \[lab\] table"),
        ("[lab]\nunknown = true\n", r"unknown \[lab\] field"),
        ("[lab]\napplication = ''\n", "must be a non-empty string"),
    ],
)
def test_invalid_project_manifests_fail_at_the_boundary(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    manifest = tmp_path / "scopecat.toml"
    manifest.write_text(content, encoding="utf-8")

    with pytest.raises(ProjectManifestError, match=message):
        load_project(manifest)


@pytest.mark.parametrize("spec", ["factory", ":factory", "module:"])
def test_invalid_application_specs_fail_at_the_boundary(
    tmp_path: Path,
    spec: str,
) -> None:
    with pytest.raises(ValueError, match="MODULE:CALLABLE"):
        load_application_factory(spec, tmp_path)
