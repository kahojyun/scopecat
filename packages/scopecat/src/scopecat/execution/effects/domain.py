"""Execute prepared domain effects inside the unified Run lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

from scopecat.kernel.errors import (
    DomainExecutionFailed,
    MeasurementRecordingError,
    OperationFailure,
)
from scopecat.kernel.instrument_members import PropertyRef
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
)
from scopecat.records.instrument import state_member_target
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.runtime import (
    DomainExecutionCancellationRequested,
    DomainExecutionId,
    DomainExecutionReceipt,
    DomainExecutionResult,
    DomainInstrumentExecutor,
    DomainJobCheckpoint,
    ResumableDomainJobRuntime,
    plan_domain_execution,
    run_domain_invocation,
)
from scopecat.sdk.instruments.commands import InstrumentStateAssignment
from scopecat.sdk.instruments.execution import RunHardwareApply, RunHardwareBatch
from scopecat.sdk.runtime_problems import (
    problem_from_exception,
    runtime_problem,
)


def execute_domain_job_values(
    prepared: PreparedDomainExecution,
    *,
    logical_compute_node_id: str,
    run_id: str,
    instruments: DomainInstrumentExecutor,
    accept: Callable[[MeasurementValueCandidate], None],
    observe_attempt: Callable[
        [
            DomainExecutionId,
            tuple[DomainJobCheckpoint, ...],
            DomainExecutionReceipt | None,
        ],
        None,
    ],
    commit_invocation: Callable[[DomainExecutionId], None] | None = None,
    commit_checkpoint: Callable[[DomainExecutionId, DomainJobCheckpoint], None]
    | None = None,
    commit_terminal: Callable[[DomainExecutionId, DomainExecutionReceipt], None]
    | None = None,
) -> None:
    """Execute one closed domain job into the execution-owned coverage sink.

    The invocation identity is committed before domain setup or provider
    ``start``. Every terminal provider receipt is committed before adapter-owned
    result realization or failure propagation. The attempt retains the same
    receipt even when that durable commit fails.
    """

    invocation = prepared.invocation
    runtime = _PreparedDomainJobRuntime(prepared)
    execution_id = plan_domain_execution(
        invocation,
        run_id=run_id,
        logical_compute_node_id=logical_compute_node_id,
    )
    checkpoints: list[DomainJobCheckpoint] = []

    def commit_invocation_intent() -> None:
        if commit_invocation is None:
            return
        try:
            commit_invocation(execution_id)
        except DomainExecutionCancellationRequested:
            raise
        except Exception as error:
            operation_id = f"{execution_id.operation_id}:invocation"
            raise DomainExecutionFailed(
                (
                    problem_from_exception(
                        "domain_job_invocation_commit_failed",
                        "domain job invocation could not be committed before start",
                        run_id=run_id,
                        operation_id=operation_id,
                        phase=ProblemPhase.PERSISTENCE,
                        error=error,
                    ),
                ),
                run_id=run_id,
                operation_id=operation_id,
                invocation_id=invocation.intent.invocation_id,
                execution_key=execution_id.execution_key,
                certainty="known",
                receipt=None,
            ) from error

    def observe_checkpoint(checkpoint: DomainJobCheckpoint) -> None:
        checkpoints.append(checkpoint)
        if commit_checkpoint is None:
            return
        try:
            commit_checkpoint(execution_id, checkpoint)
        except DomainExecutionCancellationRequested:
            raise
        except Exception as error:
            operation_id = (
                f"{execution_id.operation_id}:checkpoint:{checkpoint.revision}"
            )
            raise DomainExecutionFailed(
                (
                    problem_from_exception(
                        "domain_job_checkpoint_commit_failed",
                        "domain job checkpoint could not be committed before resume",
                        run_id=run_id,
                        operation_id=operation_id,
                        phase=ProblemPhase.PERSISTENCE,
                        error=error,
                    ),
                ),
                run_id=run_id,
                operation_id=operation_id,
                invocation_id=invocation.intent.invocation_id,
                execution_key=execution_id.execution_key,
                certainty="indeterminate",
                receipt=None,
            ) from error

    def commit_terminal_receipt(
        receipt: DomainExecutionReceipt,
        *,
        certainty: Literal["known", "indeterminate"],
        prior_problems: tuple[Problem, ...] = (),
    ) -> None:
        if commit_terminal is None:
            return
        try:
            commit_terminal(execution_id, receipt)
        except Exception as error:
            operation_id = f"{execution_id.operation_id}:terminal"
            persistence_problem = problem_from_exception(
                "domain_job_terminal_commit_failed",
                "domain job terminal receipt could not be committed",
                run_id=run_id,
                operation_id=operation_id,
                phase=ProblemPhase.PERSISTENCE,
                error=error,
            )
            raise DomainExecutionFailed(
                (*prior_problems, persistence_problem),
                run_id=run_id,
                operation_id=operation_id,
                invocation_id=invocation.intent.invocation_id,
                execution_key=execution_id.execution_key,
                certainty=certainty,
                receipt=receipt,
            ) from error

    try:
        commit_invocation_intent()
    except BaseException:
        observe_attempt(execution_id, tuple(checkpoints), None)
        raise

    try:
        result = run_domain_invocation(
            runtime,
            invocation,
            execution_id,
            instruments=instruments,
            observe_checkpoint=observe_checkpoint,
        )
    except DomainExecutionFailed as error:
        receipt = (
            error.receipt if isinstance(error.receipt, DomainExecutionReceipt) else None
        )
        if receipt is not None:
            try:
                commit_terminal_receipt(
                    receipt,
                    certainty=error.certainty,
                    prior_problems=tuple(error.problems),
                )
            except DomainExecutionFailed:
                observe_attempt(execution_id, tuple(checkpoints), receipt)
                raise
        observe_attempt(
            execution_id,
            tuple(checkpoints),
            receipt,
        )
        raise
    except BaseException:
        observe_attempt(execution_id, tuple(checkpoints), None)
        raise
    try:
        commit_terminal_receipt(result.receipt, certainty="known")
    except DomainExecutionFailed:
        observe_attempt(execution_id, tuple(checkpoints), result.receipt)
        raise
    observe_attempt(execution_id, tuple(checkpoints), result.receipt)
    prepared.realize_into(result, accept)


@dataclass(frozen=True, slots=True)
class _PreparedDomainJobRuntime:
    prepared: PreparedDomainExecution

    def start(
        self,
        execution_key: str,
        payload: object,
        /,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> DomainJobCheckpoint | DomainExecutionReceipt | DomainExecutionResult[object]:
        try:
            setup = self.prepared.setup
            if setup is not None:
                setup.prepare(execution_key, payload, instruments=instruments)
            _reconcile_domain_state_requirements(
                self.prepared,
                execution_key=execution_key,
                instruments=instruments,
            )
        except OperationFailure as error:
            return DomainExecutionReceipt(
                execution_key=execution_key,
                status="not_executed",
                problems=error.problems,
            )
        return self.prepared.job_runtime.start(
            execution_key,
            payload,
            instruments=instruments,
        )

    def resume(
        self,
        checkpoint: DomainJobCheckpoint,
        /,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> DomainJobCheckpoint | DomainExecutionReceipt | DomainExecutionResult[object]:
        if not hasattr(self.prepared.job_runtime, "resume"):
            raise TypeError(
                "a job runtime that returns a pending domain checkpoint must "
                "implement resume"
            )
        resumable = cast(
            "ResumableDomainJobRuntime[object]",
            cast("object", self.prepared.job_runtime),
        )
        return resumable.resume(checkpoint, instruments=instruments)


def _reconcile_domain_state_requirements(
    prepared: PreparedDomainExecution,
    *,
    execution_key: str,
    instruments: DomainInstrumentExecutor,
) -> None:
    grouped: dict[str, list[InstrumentStateAssignment]] = {}
    for requirement in prepared.state_requirements:
        address = requirement.address
        grouped.setdefault(address.instrument_id, []).append(
            InstrumentStateAssignment(
                resource_id=address.instrument_id,
                target=state_member_target(
                    PropertyRef(
                        address.interface_id,
                        tuple(address.component_path),
                        address.property_id,
                    )
                ),
                value=requirement.value,
            )
        )
    if not grouped:
        return
    operation_id = f"domain:{execution_key}:reconcile-requirements"
    receipt = instruments.execute(
        RunHardwareBatch(
            operation_id=operation_id,
            actions=tuple(
                RunHardwareApply(
                    effect_id=f"{operation_id}:{instrument_id}",
                    instrument_id=instrument_id,
                    assignments=tuple(assignments),
                )
                for instrument_id, assignments in sorted(grouped.items())
            ),
        )
    )
    if receipt.operation_id != operation_id:
        raise RuntimeError(
            "instrument worker returned a mismatched state-reconciliation receipt"
        )
    if receipt.indeterminate:
        raise RuntimeError("domain state requirement reconciliation was indeterminate")
    if receipt.problems:
        raise OperationFailure(receipt.problems)


def domain_job_terminal_problem(
    error: DomainExecutionFailed,
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
        "domain_job_terminalized",
        "the unified run was terminalized with domain job correlation retained",
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
