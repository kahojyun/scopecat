"""Execute prepared domain effects inside the unified Run lifecycle."""

from __future__ import annotations

from scopecat.execution.ports.journal import ExecutionJournal
from scopecat.execution.problems import (
    runtime_problem,
)
from scopecat.kernel.errors import (
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    MeasurementRecordingError,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
)
from scopecat.measurements.host_transforms import execute_host_measurement_transforms
from scopecat.measurements.values import (
    MeasurementValueCandidate,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.runtime import (
    fetch_domain_invocation,
    plan_domain_submission,
    submit_domain_invocation,
)


def execute_domain_job_values(
    prepared: PreparedDomainExecution,
    *,
    semantic_operation_id: str,
    run_id: str,
    journal: ExecutionJournal,
) -> tuple[MeasurementValueCandidate, ...]:
    """Execute one closed domain job and return canonical logical candidates."""

    invocation = prepared.invocation
    runtime = prepared.runtime
    submission_id = plan_domain_submission(
        invocation,
        run_id=run_id,
        semantic_operation_id=semantic_operation_id,
    )
    submission = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )
    fetched = fetch_domain_invocation(
        runtime,
        invocation.intent,
        submission,
        journal=journal,
    )
    source = prepared.realize(fetched)
    transforms = prepared.transforms
    return (
        source
        if transforms is None
        else execute_host_measurement_transforms(
            transforms,
            source,
            points=prepared.points,
        ).values
    )


def domain_runtime_terminal_problem(
    error: DomainRuntimeFailure | DomainRuntimePersistenceError,
    *,
    run_id: str,
) -> Problem:
    """Retain actionable target correlation when a domain effect terminalizes."""

    details: dict[str, object] = {
        "phase": error.phase,
        "attempt": error.attempt,
        "invocation_id": error.invocation_id,
        "submission_key": error.submission_key,
        "retry_contract": error.retry,
        "reconciliation": error.reconciliation,
        "automatic_resume": False,
    }
    if error.job_id is not None:
        details["job_id"] = error.job_id
    return runtime_problem(
        "domain_runtime_terminalized",
        (
            "the unified run was terminalized with domain target "
            "correlation retained; automatic resume is not available"
        ),
        run_id=run_id,
        operation_id=error.operation_id,
        category=ProblemCategory.OPERATION,
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
        category=ProblemCategory.STORAGE,
        details=details,
    )
