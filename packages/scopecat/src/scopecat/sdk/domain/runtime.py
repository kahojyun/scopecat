"""One synchronous, correlated effect for a closed domain invocation."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import (
    DomainExecutionFailed,
)
from scopecat.kernel.json_types import JsonValue
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    DomainInvocationIntent,
)
from scopecat.sdk.problems import Problem
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
    """Provider outcome evidence for one synchronous target call.

    ``completed`` supplies correlated result evidence and proves that the
    realtime call completed. ``not_executed`` proves that realtime execution
    did not begin, even if declared setup work changed state. ``unknown`` means
    hardware may have changed without a correlated completion. Both negative
    statuses carry problems and no result evidence. ``execution_evidence`` is
    target-owned structured context reported with the call outcome. It is not
    host instrument readback and does not imply that the described state can
    be restored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_key: str
    status: Literal["completed", "not_executed", "unknown"]
    result_fingerprint: str | None = None
    result_count: int | None = Field(default=None, ge=0)
    execution_evidence: dict[str, JsonValue] = Field(default_factory=dict)
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


class DomainExecutionCancellationRequested(Exception):
    """Stop a synchronous domain call before its next hardware batch.

    Core raises this only at a boundary where no new hardware batch has been
    submitted. It is control flow rather than provider failure evidence and
    therefore must not be normalized into an indeterminate domain receipt.
    """


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
) -> DomainExecutionResult[ResultT]:
    """Execute once and validate exact, correlated provider evidence."""

    intent = invocation.intent
    _validate_execution_id(intent, execution_id)
    try:
        outcome = runtime.execute(
            execution_id.execution_key,
            invocation.payload,
            instruments=instruments,
        )
    except DomainExecutionCancellationRequested:
        raise
    except Exception as error:
        execution_problem = problem_from_exception(
            "domain_execution_raised",
            "domain runtime raised during synchronous execution",
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            error=error,
        )
        raise DomainExecutionFailed(
            (execution_problem,),
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            invocation_id=intent.invocation_id,
            execution_key=execution_id.execution_key,
            certainty="indeterminate",
            receipt=None,
        ) from error
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
        raise DomainExecutionFailed(
            (provider_problem,),
            run_id=execution_id.run_id,
            operation_id=execution_id.operation_id,
            invocation_id=intent.invocation_id,
            execution_key=execution_id.execution_key,
            certainty="indeterminate",
            receipt=None,
        ) from error

    problems = contextualize_problems(
        receipt.problems,
        run_id=execution_id.run_id,
        operation_id=execution_id.operation_id,
    )
    if isinstance(outcome, DomainExecutionResult):
        return outcome

    certainty: Literal["known", "indeterminate"] = (
        "known" if receipt.status == "not_executed" else "indeterminate"
    )
    raise DomainExecutionFailed(
        problems,
        run_id=execution_id.run_id,
        operation_id=execution_id.operation_id,
        invocation_id=intent.invocation_id,
        execution_key=execution_id.execution_key,
        certainty=certainty,
        receipt=receipt,
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
    "DomainExecutionCancellationRequested",
    "DomainExecutionId",
    "DomainExecutionReceipt",
    "DomainExecutionResult",
    "DomainInstrumentExecutor",
    "DomainRuntime",
    "DomainSetup",
    "execute_domain_invocation",
    "plan_domain_execution",
]
