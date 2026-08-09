"""One synchronous, correlated effect for a closed domain invocation."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import (
    DomainExecutionFailed,
    DomainRuntimePersistenceError,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    DomainInvocationIntent,
)
from scopecat.sdk.journal import ExecutionJournal
from scopecat.sdk.journal import commit_transition as _commit_transition
from scopecat.sdk.problems import Problem, ProblemPhase
from scopecat.sdk.runtime_problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)

if TYPE_CHECKING:
    from scopecat.sdk.instruments.execution import (
        RunHardwareBatch,
        RunHardwareBatchReceipt,
    )


class DomainExecutionId(BaseModel):
    """Deterministic identity for one synchronous domain execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    logical_compute_node_id: str
    invocation_id: str
    intent_fingerprint: str

    @field_validator(
        "run_id",
        "logical_compute_node_id",
        "invocation_id",
        "intent_fingerprint",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("domain execution identity fields must be non-empty")
        return value

    @property
    def execution_key(self) -> str:
        return stable_content_hash(
            {
                "schema": "scopecat.domain_execution_key.v1",
                "run_id": self.run_id,
                "logical_compute_node_id": self.logical_compute_node_id,
                "invocation_id": self.invocation_id,
                "intent_fingerprint": self.intent_fingerprint,
            }
        )

    @property
    def operation_id(self) -> str:
        return f"domain:{self.execution_key}:execute"


class DomainExecutionReceipt(BaseModel):
    """Provider evidence for one complete synchronous target call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_key: str
    status: Literal["completed", "not_executed", "unknown"]
    result_fingerprint: str | None = None
    result_count: int | None = Field(default=None, ge=0)
    problems: tuple[Problem, ...] = ()

    @field_validator("execution_key")
    @classmethod
    def validate_execution_key(cls, value: str) -> str:
        if not value:
            raise ValueError("domain execution receipts require an execution key")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> DomainExecutionReceipt:
        has_result = (
            self.result_fingerprint is not None and self.result_count is not None
        )
        if self.status == "completed":
            if not has_result or not self.result_fingerprint or self.problems:
                raise ValueError(
                    "completed domain receipts require result evidence and no problems"
                )
        elif (
            has_result
            or self.result_fingerprint is not None
            or self.result_count is not None
            or not self.problems
        ):
            raise ValueError(
                "negative domain receipts require problems and no result evidence"
            )
        return self


@dataclass(frozen=True, slots=True)
class DomainExecutionResult[ResultT]:
    """One complete target result paired with correlated provider evidence."""

    receipt: DomainExecutionReceipt
    result: ResultT = field(repr=False)

    def __post_init__(self) -> None:
        if self.receipt.status != "completed":
            raise ValueError("domain results require completed receipt evidence")


class DomainInstrumentExecutor(Protocol):
    """Run-scoped access to instruments already reserved for a target."""

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt: ...


class DomainSetup[PayloadT](Protocol):
    """Perform slow target setup before host-managed state is reconciled."""

    def prepare(
        self,
        execution_key: str,
        payload: PayloadT,
        /,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> None: ...


class DomainRuntime[PayloadT, ResultT](Protocol):
    """Execute one target invocation completely in the current run host."""

    def execute(
        self,
        execution_key: str,
        payload: PayloadT,
        /,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> DomainExecutionReceipt | DomainExecutionResult[ResultT]: ...


def plan_domain_execution[
    ResultAddressT: Hashable,
    PayloadT,
](
    invocation: ClosedDomainInvocation[ResultAddressT, PayloadT],
    *,
    run_id: str,
    logical_compute_node_id: str,
) -> DomainExecutionId:
    intent = invocation.intent
    return DomainExecutionId(
        run_id=run_id,
        logical_compute_node_id=logical_compute_node_id,
        invocation_id=intent.invocation_id,
        intent_fingerprint=intent.intent_fingerprint,
    )


def execute_domain_invocation[
    ResultAddressT: Hashable,
    PayloadT,
    ResultT,
](
    runtime: DomainRuntime[PayloadT, ResultT],
    invocation: ClosedDomainInvocation[ResultAddressT, PayloadT],
    execution_id: DomainExecutionId,
    *,
    instruments: DomainInstrumentExecutor,
    journal: ExecutionJournal,
) -> DomainExecutionResult[ResultT]:
    """Persist intent, execute once, and close exact result evidence."""

    intent = invocation.intent
    _validate_execution_id(intent, execution_id)
    started = _transition(
        execution_id,
        state="started",
        evidence=_intent_evidence(intent, execution_id),
    )
    _append_before_effect(journal, started, execution_id)
    try:
        outcome = runtime.execute(
            execution_id.execution_key,
            invocation.payload,
            instruments=instruments,
        )
    except Exception as error:
        execution_problem = problem_from_exception(
            "domain_execution_raised",
            "domain runtime raised during synchronous execution",
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            error=error,
        )
        _append_after_effect(
            journal,
            _transition(
                execution_id,
                state="unknown",
                problems=(execution_problem,),
                evidence=_terminal_evidence(execution_id),
            ),
            execution_id,
            certainty="indeterminate",
            prior_problems=(execution_problem,),
        )
        raise DomainExecutionFailed(
            (execution_problem,),
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            invocation_id=intent.invocation_id,
            execution_key=execution_id.execution_key,
            certainty="indeterminate",
        ) from error
    except BaseException:
        _append_interruption_best_effort(journal, execution_id)
        raise

    try:
        receipt = (
            outcome.receipt if isinstance(outcome, DomainExecutionResult) else outcome
        )
        if receipt.execution_key != execution_id.execution_key:
            raise ValueError("domain receipt belongs to another execution")
        if receipt.status == "completed" and not isinstance(
            outcome, DomainExecutionResult
        ):
            raise ValueError("completed domain receipts require a result")
    except Exception as error:
        provider_problem = _provider_problem(execution_id, error)
        _append_after_effect(
            journal,
            _transition(
                execution_id,
                state="unknown",
                problems=(provider_problem,),
                evidence=_terminal_evidence(execution_id),
            ),
            execution_id,
            certainty="indeterminate",
            prior_problems=(provider_problem,),
        )
        raise DomainExecutionFailed(
            (provider_problem,),
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            invocation_id=intent.invocation_id,
            execution_key=execution_id.execution_key,
            certainty="indeterminate",
        ) from error

    problems = contextualize_problems(
        receipt.problems,
        run_id=execution_id.run_id,
        operation_id=execution_id.operation_id,
    )
    evidence = _terminal_evidence(execution_id, receipt=receipt)
    if isinstance(outcome, DomainExecutionResult):
        _append_after_effect(
            journal,
            _transition(
                execution_id,
                state="completed",
                problems=problems,
                evidence=evidence,
            ),
            execution_id,
            certainty="known",
            prior_problems=problems,
        )
        return outcome

    certainty: Literal["known", "indeterminate"] = (
        "known" if receipt.status == "not_executed" else "indeterminate"
    )
    state: Literal["failed", "unknown"] = (
        "failed" if certainty == "known" else "unknown"
    )
    _append_after_effect(
        journal,
        _transition(
            execution_id,
            state=state,
            problems=problems,
            evidence=evidence,
        ),
        execution_id,
        certainty=certainty,
        prior_problems=problems,
    )
    raise DomainExecutionFailed(
        problems,
        run_id=execution_id.run_id,
        operation_id=execution_id.operation_id,
        invocation_id=intent.invocation_id,
        execution_key=execution_id.execution_key,
        certainty=certainty,
    )


def _validate_execution_id(
    intent: DomainInvocationIntent,
    execution_id: DomainExecutionId,
) -> None:
    if (
        execution_id.invocation_id != intent.invocation_id
        or execution_id.intent_fingerprint != intent.intent_fingerprint
    ):
        raise ValueError("domain execution identity does not match its invocation")


def _transition(
    execution_id: DomainExecutionId,
    *,
    state: Literal["started", "completed", "failed", "unknown"],
    evidence: Mapping[str, JsonValue],
    problems: Sequence[Problem] = (),
) -> ExecutionTransition:
    return ExecutionTransition(
        run_id=execution_id.run_id,
        operation_id=execution_id.operation_id,
        stage="domain_execute",
        effect="acquisition",
        state=state,
        problems=tuple(problems),
        evidence=dict(evidence),
    )


def _intent_evidence(
    intent: DomainInvocationIntent,
    execution_id: DomainExecutionId,
) -> dict[str, JsonValue]:
    return {
        "invocation_intent": intent.model_dump(mode="json"),
        "logical_compute_node_id": execution_id.logical_compute_node_id,
        "execution_key": execution_id.execution_key,
    }


def _terminal_evidence(
    execution_id: DomainExecutionId,
    *,
    receipt: DomainExecutionReceipt | None = None,
) -> dict[str, JsonValue]:
    evidence: dict[str, JsonValue] = {
        "execution_key": execution_id.execution_key,
        "intent_fingerprint": execution_id.intent_fingerprint,
    }
    if receipt is not None:
        evidence["receipt"] = receipt.model_dump(mode="json")
    return evidence


def _append_before_effect(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
    execution_id: DomainExecutionId,
) -> None:
    try:
        _commit_transition(journal, transition)
    except Exception as error:
        persistence_problem = problem_from_exception(
            "domain_runtime_intent_persistence_failed",
            "failed to persist domain execution intent before the runtime call",
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            error=error,
            phase=ProblemPhase.PERSISTENCE,
        )
        raise DomainRuntimePersistenceError(
            (persistence_problem,),
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            invocation_id=execution_id.invocation_id,
            execution_key=execution_id.execution_key,
            phase="execute",
            certainty="known",
        ) from error


def _append_after_effect(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
    execution_id: DomainExecutionId,
    *,
    certainty: Literal["known", "indeterminate"],
    prior_problems: Sequence[Problem],
) -> None:
    try:
        _commit_transition(journal, transition)
    except Exception as error:
        persistence_problem = problem_from_exception(
            "domain_runtime_receipt_persistence_failed",
            "failed to persist domain execution result after the runtime call",
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            error=error,
            phase=ProblemPhase.PERSISTENCE,
        )
        raise DomainRuntimePersistenceError(
            (*prior_problems, persistence_problem),
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            invocation_id=execution_id.invocation_id,
            execution_key=execution_id.execution_key,
            phase="execute",
            certainty=certainty,
        ) from error


def _append_interruption_best_effort(
    journal: ExecutionJournal,
    execution_id: DomainExecutionId,
) -> None:
    interruption = runtime_problem(
        "domain_runtime_interrupted",
        "domain runtime call was interrupted before returning a receipt",
        run_id=execution_id.run_id,
        operation_id=execution_id.operation_id,
    )
    with suppress(BaseException):
        _commit_transition(
            journal,
            _transition(
                execution_id,
                state="unknown",
                problems=(interruption,),
                evidence=_terminal_evidence(execution_id),
            ),
        )


def _provider_problem(
    execution_id: DomainExecutionId,
    error: Exception,
) -> Problem:
    return runtime_problem(
        "domain_execution_receipt_invalid",
        "domain runtime returned invalid or uncorrelated result evidence",
        run_id=execution_id.run_id,
        operation_id=execution_id.operation_id,
        details={"error_type": f"{type(error).__module__}.{type(error).__qualname__}"},
    )


__all__ = [
    "DomainExecutionId",
    "DomainExecutionReceipt",
    "DomainExecutionResult",
    "DomainInstrumentExecutor",
    "DomainRuntime",
    "DomainSetup",
    "execute_domain_invocation",
    "plan_domain_execution",
]
