"""Execute prepared domain effects inside the unified Run lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from scopecat.kernel.errors import (
    DomainExecutionFailed,
    DomainRuntimeFailure,
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
    DomainExecutionId,
    DomainExecutionReceipt,
    DomainExecutionResult,
    DomainInstrumentExecutor,
    execute_domain_invocation,
    plan_domain_execution,
)
from scopecat.sdk.instruments.commands import InstrumentStateAssignment
from scopecat.sdk.instruments.execution import RunHardwareApply, RunHardwareBatch
from scopecat.sdk.runtime_problems import (
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
        [DomainExecutionId, DomainExecutionReceipt | None],
        None,
    ],
) -> None:
    """Execute one closed domain job into the execution-owned coverage sink.

    The attempt is observed before adapter-owned result realization. A valid
    negative receipt or a missing receipt is retained before failure escapes.
    """

    invocation = prepared.invocation
    runtime = _RequirementReconciledRuntime(prepared)
    execution_id = plan_domain_execution(
        invocation,
        run_id=run_id,
        logical_compute_node_id=logical_compute_node_id,
    )
    try:
        result = execute_domain_invocation(
            runtime,
            invocation,
            execution_id,
            instruments=instruments,
        )
    except DomainExecutionFailed as error:
        observe_attempt(
            execution_id,
            cast("DomainExecutionReceipt | None", error.receipt),
        )
        raise
    except BaseException:
        observe_attempt(execution_id, None)
        raise
    observe_attempt(execution_id, result.receipt)
    prepared.realize_into(result, accept)


@dataclass(frozen=True, slots=True)
class _RequirementReconciledRuntime:
    prepared: PreparedDomainExecution

    def execute(
        self,
        execution_key: str,
        payload: object,
        /,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> DomainExecutionReceipt | DomainExecutionResult[object]:
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
        return self.prepared.runtime.execute(
            execution_key,
            payload,
            instruments=instruments,
        )


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


def domain_runtime_terminal_problem(
    error: DomainRuntimeFailure,
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
