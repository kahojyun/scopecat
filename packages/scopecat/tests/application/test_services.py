from __future__ import annotations

from pathlib import Path

from scopecat.composition.embedded import (
    embedded_run_repository,
    embedded_workspace_services,
)


def test_workspace_services_has_one_run_repository(tmp_path: Path) -> None:
    services = embedded_workspace_services(tmp_path)

    assert services.runs is services.execution.runs


def test_embedded_repository_is_isolated_from_daemon_state(tmp_path: Path) -> None:
    repository = embedded_run_repository(tmp_path)

    assert repository.database == (
        tmp_path / ".scopecat-embedded" / "workspace.sqlite3"
    )
    assert not (tmp_path / ".scopecat").exists()
