from __future__ import annotations

from scopecat.composition.local import local_workspace_services


def test_workspace_services_has_one_run_repository(tmp_path) -> None:
    services = local_workspace_services(tmp_path)

    assert services.runs is services.execution.runs
