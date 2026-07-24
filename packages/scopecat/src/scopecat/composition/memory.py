"""Compose an entirely in-memory workspace application."""

from __future__ import annotations

from scopecat.adapters.memory import MemoryWorkspaceStore
from scopecat.application.services import WorkspaceServices
from scopecat.execution.services import ExecutionServices


def memory_workspace_services(
    store: MemoryWorkspaceStore | None = None,
) -> WorkspaceServices:
    """Bind every workspace port to stateful in-memory adapters."""

    workspace = store or MemoryWorkspaceStore()
    state = workspace.execution
    execution = ExecutionServices(
        runs=workspace.runs,
        resources=state.resources,
        journal_for=state.journal_for,
        measurements_for=state.measurements_for,
        collections_for=state.collections_for,
        payloads_for=state.payloads_for,
    )
    return WorkspaceServices(
        runs=workspace.runs,
        execution=execution,
        config_registry=workspace.unit_of_work,
    )
