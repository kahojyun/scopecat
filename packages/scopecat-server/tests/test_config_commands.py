from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self, cast

import pytest
from scopecat.api.lab import LabClient
from scopecat.application import LabApplication
from scopecat.config.profiles import load_config_profile
from scopecat.daemon.endpoint import DAEMON_URL_ENV, DaemonEndpointRecord
from scopecat.daemon.wire import ConfigDefaultReceipt
from scopecat.kernel.errors import CheckFailed
from scopecat.project import Project
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash

from scopecat_server.config_commands import (
    apply_project_config,
    diff_project_config,
    export_project_config,
    load_source_config,
)
from scopecat_server.lifecycle import write_daemon_endpoint_record

_CONFIG_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-profile.json"
)


def test_source_config_is_freshly_built_and_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    baseline = load_config_profile(_CONFIG_FIXTURE)
    calls = 0

    def bootstrap_config() -> ConfigProfileSnapshot:
        nonlocal calls
        calls += 1
        return baseline.model_copy(update={"id": f"source-{calls}"})

    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(LabApplication(bootstrap_config=bootstrap_config)),
    )

    first = load_source_config(project)
    second = load_source_config(project)

    assert first.id == "source-1"
    assert second.id == "source-2"
    assert calls == 2


def test_source_config_rejects_missing_or_invalid_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(LabApplication()),
    )

    with pytest.raises(
        ValueError,
        match="project application does not define bootstrap_config",
    ):
        load_source_config(project)

    config = load_config_profile(_CONFIG_FIXTURE)
    invalid_connection = config.connection_profile.connections[0].model_copy(
        update={"instrument_id": "missing-source"}
    )
    invalid = config.model_copy(
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
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(LabApplication(bootstrap_config=lambda: invalid)),
    )

    with pytest.raises(CheckFailed):
        load_source_config(project)


@pytest.mark.parametrize("drift", [False, True])
def test_diff_compares_content_hash_and_only_renders_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    drift: bool,
) -> None:
    project = _project(tmp_path)
    active = load_config_profile(_CONFIG_FIXTURE).model_copy(update={"id": "active"})
    source = active.model_copy(update={"id": "project-source"}) if drift else active
    lab = _FakeLab(active)
    _patch_project(monkeypatch, source=source, lab=lab)

    result = diff_project_config(project)

    assert result.has_drift is drift
    assert result.source_content_hash == config_content_hash(source)
    assert result.active_content_hash == config_content_hash(active)
    diff = result.unified_json_diff()
    if drift:
        assert "--- daemon-default" in diff
        assert "+++ project-source" in diff
        assert '-  "id": "active",' in diff
        assert '+  "id": "project-source",' in diff
    else:
        assert diff == ()
    assert lab.closed


def test_diff_uses_selected_project_record_instead_of_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    config = load_config_profile(_CONFIG_FIXTURE)
    lab = _FakeLab(config)
    write_daemon_endpoint_record(
        DaemonEndpointRecord(
            project_root=project.root,
            pid=1,
            process_create_time=1,
            base_url="http://project-daemon.local",
            started_at=datetime.now(UTC),
        )
    )
    monkeypatch.setenv(DAEMON_URL_ENV, "http://different-project.local")
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(LabApplication(bootstrap_config=lambda: config)),
    )
    observed_urls: list[str | None] = []

    def connect(_project: Project, daemon: str | None = None) -> LabClient:
        observed_urls.append(daemon)
        return cast("LabClient", cast("object", lab))

    monkeypatch.setattr(Project, "connect", connect)

    result = diff_project_config(project)

    assert not result.has_drift
    assert observed_urls == ["http://project-daemon.local"]


@pytest.mark.parametrize("changed", [False, True])
def test_apply_uses_config_intent_even_when_content_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    changed: bool,
) -> None:
    project = _project(tmp_path)
    active = load_config_profile(_CONFIG_FIXTURE).model_copy(update={"id": "active"})
    source = active.model_copy(update={"id": "project-source"}) if changed else active
    lab = _FakeLab(active)
    _patch_project(monkeypatch, source=source, lab=lab)

    result = apply_project_config(
        project,
        actor="config-cli",
        note="publish reviewed source",
    )

    assert result.changed is changed
    assert result.previous == active
    assert result.source == source
    assert result.receipt is lab.receipt
    assert lab.set_default_calls == [
        _SetDefaultCall(
            config=source,
            registered_by="config-cli",
            operator="config-cli",
            note="publish reviewed source",
        )
    ]
    assert lab.closed


def test_export_writes_complete_active_snapshot_via_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    active = load_config_profile(_CONFIG_FIXTURE).model_copy(update={"id": "active"})
    lab = _FakeLab(active)
    _patch_project(monkeypatch, source=active, lab=lab)
    destination = tmp_path / "review" / "active-config.json"
    destination.parent.mkdir()
    replacements: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def observed_replace(source: Path, target: Path) -> Path:
        replacements.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", observed_replace)

    result = export_project_config(project, destination)

    assert result.destination == destination.resolve()
    assert result.config == active
    assert result.content_hash == config_content_hash(active)
    assert (
        ConfigProfileSnapshot.model_validate_json(
            destination.read_text(encoding="utf-8")
        )
        == active
    )
    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert len(replacements) == 1
    temporary, target = replacements[0]
    assert temporary.parent == destination.parent
    assert temporary.name.startswith(f".{destination.name}.")
    assert target == destination
    assert not temporary.exists()
    assert lab.closed


def test_export_refuses_overwrite_by_default_and_can_replace_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    active = load_config_profile(_CONFIG_FIXTURE)
    lab = _FakeLab(active)
    _patch_project(monkeypatch, source=active, lab=lab)
    destination = tmp_path / "active-config.json"
    destination.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        export_project_config(project, destination)

    assert destination.read_text(encoding="utf-8") == "keep me\n"
    assert not lab.closed

    result = export_project_config(project, destination, overwrite=True)

    assert result.config == active
    assert json.loads(destination.read_text(encoding="utf-8")) == active.model_dump(
        mode="json"
    )
    assert lab.closed


@dataclass(frozen=True, slots=True)
class _SetDefaultCall:
    config: ConfigProfileSnapshot
    registered_by: str
    operator: str
    note: str


class _FakeLab:
    def __init__(self, active: ConfigProfileSnapshot) -> None:
        self.active = active
        self.receipt = cast("ConfigDefaultReceipt", object())
        self.set_default_calls: list[_SetDefaultCall] = []
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.closed = True

    @property
    def config(self) -> _FakeLab:
        return self

    def resolve_config(self, selector: str) -> ConfigProfileSnapshot:
        assert selector == "active"
        return self.active

    def set_default(
        self,
        config: ConfigProfileSnapshot,
        *,
        registered_by: str,
        operator: str,
        note: str,
    ) -> ConfigDefaultReceipt:
        self.set_default_calls.append(
            _SetDefaultCall(
                config=config,
                registered_by=registered_by,
                operator=operator,
                note=note,
            )
        )
        return self.receipt


def _project(root: Path) -> Project:
    manifest = root / "scopecat.toml"
    manifest.write_text("[lab]\n", encoding="utf-8")
    return Project(root=root, manifest=manifest, application_spec=None)


def _patch_project(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: ConfigProfileSnapshot,
    lab: _FakeLab,
) -> None:
    monkeypatch.setattr(
        Project,
        "load_application",
        _application_loader(LabApplication(bootstrap_config=lambda: source)),
    )

    def recorded_url(_project: Project) -> str:
        return "http://project-daemon.local"

    monkeypatch.setattr(
        "scopecat_server.config_commands._recorded_daemon_url",
        recorded_url,
    )

    def connect(_project: Project, daemon: str | None = None) -> LabClient:
        assert daemon == "http://project-daemon.local"
        return cast("LabClient", cast("object", lab))

    monkeypatch.setattr(Project, "connect", connect)


def _application_loader(
    application: LabApplication,
) -> Callable[[Project], LabApplication]:
    def load_application(_project: Project) -> LabApplication:
        return application

    return load_application
