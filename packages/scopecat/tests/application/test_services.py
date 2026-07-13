from __future__ import annotations

from typing import get_type_hints

from scopecat.application.services import WorkspaceServices
from scopecat.composition.local import (
    local_config_registry_unit_of_work,
    local_execution_services,
    local_run_repository,
    local_workspace_services,
    open_local_workspace,
)


def test_workspace_services_has_one_run_repository(tmp_path) -> None:
    services = local_workspace_services(tmp_path)

    assert services.runs is services.execution.runs


def test_workspace_service_annotations_resolve_at_runtime() -> None:
    annotations = get_type_hints(WorkspaceServices)

    assert set(annotations) == {"execution", "config_registry"}


def test_local_composition_annotations_resolve_at_runtime() -> None:
    for function in (
        local_config_registry_unit_of_work,
        local_execution_services,
        local_run_repository,
        local_workspace_services,
        open_local_workspace,
    ):
        assert get_type_hints(function)
