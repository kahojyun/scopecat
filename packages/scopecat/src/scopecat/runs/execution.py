"""Read-only inspection of durable run execution evidence."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.application.services import WorkspaceServices
from scopecat.execution.evidence import run_outcome_ref
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.run import RunLifecycle, RunOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class RunExecutionInspection:
    """A read-only reconciliation view over manifest, outcome, and journal."""

    run_id: str
    lifecycle: RunLifecycle
    manifest_outcome: RunOutcome | None = None
    persisted_outcome: RunOutcome | None = None
    transitions: tuple[ExecutionTransition, ...] = ()
    unresolved_operation_ids: tuple[str, ...] = ()
    indeterminate_operation_ids: tuple[str, ...] = ()
    reconciliation_required: bool
    automatic_retry_safe: bool


def inspect_run_execution(
    *,
    run_id: str,
    services: WorkspaceServices,
) -> RunExecutionInspection:
    """Inspect durable execution state without mutating or recovering the run."""

    execution = services.execution
    storage = execution.runs
    manifest = storage.read_manifest(run_id)
    transitions = execution.journal_for(run_id).entries()
    persisted_outcome = (
        storage.read_model(run_id, run_outcome_ref(), RunOutcome)
        if storage.exists(run_id, run_outcome_ref())
        else None
    )
    latest = _latest_transitions(transitions)
    unresolved = tuple(
        operation_id
        for operation_id, transition in latest.items()
        if transition.state == "started"
    )
    indeterminate = tuple(
        operation_id
        for operation_id, transition in latest.items()
        if transition.state == "unknown"
    )
    outcome_mismatch = (
        manifest.outcome is not None
        and persisted_outcome is not None
        and manifest.outcome != persisted_outcome
    )
    reconciliation_required = bool(
        manifest.lifecycle != "terminal"
        or unresolved
        or indeterminate
        or outcome_mismatch
        or (manifest.lifecycle == "terminal" and persisted_outcome is None)
    )
    unsafe_effect = any(
        transition.effect in {"state_write", "acquisition", "lifecycle"}
        and transition.state in {"started", "unknown"}
        for transition in latest.values()
    )
    return RunExecutionInspection(
        run_id=run_id,
        lifecycle=manifest.lifecycle,
        manifest_outcome=manifest.outcome,
        persisted_outcome=persisted_outcome,
        transitions=transitions,
        unresolved_operation_ids=unresolved,
        indeterminate_operation_ids=indeterminate,
        reconciliation_required=reconciliation_required,
        automatic_retry_safe=not reconciliation_required or not unsafe_effect,
    )


def _latest_transitions(
    transitions: tuple[ExecutionTransition, ...],
) -> dict[str, ExecutionTransition]:
    latest: dict[str, ExecutionTransition] = {}
    for transition in transitions:
        latest[transition.operation_id] = transition
    return latest
