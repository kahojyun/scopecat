"""Execute prepared domain effects inside the unified Run lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

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
from scopecat.measurements.transforms import execute_host_measurement_transforms
from scopecat.measurements.values import (
    ClosedMeasurementProductValues,
    assemble_measurement_values,
    domain_output_fragment,
)
from scopecat.sdk.domain.execution import (
    PreparedDomainExecution,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    fetch_domain_invocation,
    plan_domain_submission,
    submit_domain_invocation,
)


@dataclass(slots=True)
class DomainSynchronousCompletionPending(Exception):
    """A synchronous unit returned a durable pending target job."""

    operation_id: str
    job_id: str
    submission_key: str


def execute_domain_job_values(
    prepared: PreparedDomainExecution,
    *,
    run_id: str,
    journal: ExecutionJournal,
) -> ClosedMeasurementProductValues:
    """Execute one closed domain job and return producer-neutral values."""

    submission_id = plan_domain_submission(
        prepared.invocation,
        run_id=run_id,
        semantic_operation_id=prepared.semantic_operation_id,
    )
    submission = submit_domain_invocation(
        prepared.runtime,
        prepared.invocation,
        submission_id,
        journal=journal,
    )
    fetched = fetch_domain_invocation(
        prepared.runtime,
        prepared.invocation.intent,
        submission,
        journal=journal,
    )
    if not isinstance(fetched, CorrelatedDomainFetch):
        raise DomainSynchronousCompletionPending(
            operation_id=submission_id.fetch_operation_id,
            job_id=submission.job_id,
            submission_key=submission_id.submission_key,
        )
    outputs = prepared.realize(fetched)
    source = domain_output_fragment(prepared.source_fragment, outputs)
    return (
        assemble_measurement_values(source.selection, (source,))
        if prepared.transforms is None
        else execute_host_measurement_transforms(
            prepared.transforms,
            (source,),
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
    """Retain idempotent record correlation after recording terminalizes."""

    details: dict[str, object] = {
        "dataset_id": error.dataset_id,
        "recording_contract_fingerprint": error.recording_contract_fingerprint,
        "attempt": error.attempt,
        "logical_point_id": error.logical_point_id,
        "point_index": error.point_index,
        "committed_record_refs": [
            receipt.record_ref for receipt in error.committed_prefix
        ],
        "write_may_have_completed": error.write_may_have_completed,
        "retry_contract": error.retry,
        "reconciliation": error.reconciliation,
        "automatic_resume": False,
    }
    if error.pending_receipt is not None:
        details["pending_record_ref"] = error.pending_receipt.record_ref
    return runtime_problem(
        "measurement_recording_terminalized",
        (
            "the unified run was terminalized with measurement "
            "record correlation retained; automatic resume is not available"
        ),
        run_id=run_id,
        operation_id=error.operation_id,
        point_index=error.point_index,
        phase=ProblemPhase.PERSISTENCE,
        category=ProblemCategory.STORAGE,
        details=details,
    )


__all__ = [
    "DomainSynchronousCompletionPending",
    "domain_runtime_terminal_problem",
    "execute_domain_job_values",
    "measurement_recording_terminal_problem",
]
