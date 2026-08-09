"""Execute prepared domain effects inside the unified Run lifecycle."""

from __future__ import annotations

from scopecat.kernel.errors import (
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    MeasurementRecordingError,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.runtime import (
    DomainInstrumentExecutor,
    execute_domain_invocation,
    plan_domain_execution,
)
from scopecat.sdk.journal import ExecutionJournal
from scopecat.sdk.runtime_problems import (
    runtime_problem,
)


def execute_domain_job_values(
    prepared: PreparedDomainExecution,
    *,
    logical_compute_node_id: str,
    run_id: str,
    instruments: DomainInstrumentExecutor,
    journal: ExecutionJournal,
) -> tuple[MeasurementValueCandidate, ...]:
    """Execute one closed domain job and return canonical logical candidates."""

    invocation = prepared.invocation
    runtime = prepared.runtime
    execution_id = plan_domain_execution(
        invocation,
        run_id=run_id,
        logical_compute_node_id=logical_compute_node_id,
    )
    result = execute_domain_invocation(
        runtime,
        invocation,
        execution_id,
        instruments=instruments,
        journal=journal,
    )
    return prepared.realize(result)


def domain_runtime_terminal_problem(
    error: DomainRuntimeFailure | DomainRuntimePersistenceError,
    *,
    run_id: str,
) -> Problem:
    """Retain actionable target correlation when a domain effect terminalizes."""

    details: dict[str, object] = {
        "phase": error.phase,
        "certainty": error.certainty,
        "invocation_id": error.invocation_id,
        "execution_key": error.execution_key,
    }
    return runtime_problem(
        "domain_runtime_terminalized",
        "the unified run was terminalized with domain target correlation retained",
        run_id=run_id,
        operation_id=error.operation_id,
        details=details,
    )


def measurement_recording_terminal_problem(
    error: MeasurementRecordingError,
    *,
    run_id: str,
) -> Problem:
    """Retain durable record correlation after recording terminalizes."""

    details: dict[str, object] = {
        "dataset_id": error.dataset_id,
        "recording_contract_fingerprint": error.recording_contract_fingerprint,
        "write_may_have_completed": error.write_may_have_completed,
    }
    if error.receipt is not None:
        details["dataset_ref"] = error.receipt.dataset_ref
    return runtime_problem(
        "measurement_recording_terminalized",
        (
            "the unified run was terminalized with measurement record "
            "correlation retained"
        ),
        run_id=run_id,
        operation_id=error.operation_id,
        phase=ProblemPhase.PERSISTENCE,
        details=details,
    )
