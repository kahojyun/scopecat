"""Correlated job lifecycle for one closed domain invocation."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, cast

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
    """Deterministic identity for one domain job execution."""

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
    """Provider outcome evidence for one terminal target job.

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


class DomainJobCheckpoint(BaseModel):
    """One serializable pending transition for a submitted target job.

    ``resume_token`` contains the target-owned JSON state needed to advance the
    same job after this boundary. ``progress`` is inspectable evidence only and
    must not be required for resumption. Revisions are strictly monotonic within
    one job and let core reject stale or replayed transitions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_key: str
    job_id: str
    revision: int = Field(ge=1)
    resume_token: dict[str, JsonValue]
    progress: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("execution_key", "job_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value:
            raise ValueError("domain job checkpoint identities must be non-empty")
        return value


type DomainJobTransition[ResultT] = (
    DomainJobCheckpoint | DomainExecutionReceipt | DomainExecutionResult[ResultT]
)


class DomainExecutionCancellationRequested(Exception):
    """Stop a domain job before its next transition or hardware batch.

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


class DomainJobRuntime[PayloadT, ResultT](Protocol):
    """Start one target job in the current run host.

    A synchronously completing target returns terminal receipt/result evidence
    directly. A target with an externally resumable job returns a
    :class:`DomainJobCheckpoint` and also implements
    :class:`ResumableDomainJobRuntime`.
    """

    def start(
        self,
        execution_key: str,
        payload: PayloadT,
        /,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> DomainJobTransition[ResultT]: ...


class ResumableDomainJobRuntime[ResultT](Protocol):
    """Advance one previously checkpointed target job."""

    def resume(
        self,
        checkpoint: DomainJobCheckpoint,
        /,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> DomainJobTransition[ResultT]: ...


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


def run_domain_invocation[
    ResultAddressT: Hashable,
    PayloadT,
    ResultT,
](
    job_runtime: DomainJobRuntime[PayloadT, ResultT],
    invocation: ClosedDomainInvocation[ResultAddressT, PayloadT],
    execution_id: DomainExecutionId,
    *,
    instruments: DomainInstrumentExecutor,
    observe_checkpoint: Callable[[DomainJobCheckpoint], None] | None = None,
) -> DomainExecutionResult[ResultT]:
    """Advance one job to terminal and validate every correlated transition."""

    intent = invocation.intent
    _validate_execution_id(intent, execution_id)
    try:
        outcome = job_runtime.start(
            execution_id.execution_key,
            invocation.payload,
            instruments=instruments,
        )
        previous: DomainJobCheckpoint | None = None
        while isinstance(outcome, DomainJobCheckpoint):
            _validate_checkpoint(execution_id, previous, outcome)
            if observe_checkpoint is not None:
                observe_checkpoint(outcome)
            if not hasattr(job_runtime, "resume"):
                raise TypeError(
                    "a job runtime that returns a pending domain checkpoint must "
                    "implement resume"
                )
            resumable = cast(
                "ResumableDomainJobRuntime[ResultT]",
                cast("object", job_runtime),
            )
            previous = outcome
            outcome = resumable.resume(outcome, instruments=instruments)
    except DomainExecutionCancellationRequested:
        raise
    except Exception as error:
        execution_problem = problem_from_exception(
            "domain_execution_raised",
            "domain job runtime raised while advancing its job",
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
        result: DomainExecutionResult[ResultT] | None
        if isinstance(outcome, DomainExecutionResult):
            result = outcome
            receipt = result.receipt
        else:
            result = None
            receipt = outcome
        if receipt.execution_key != execution_id.execution_key:
            raise ValueError("domain receipt belongs to another execution")
        if receipt.status == "completed" and result is None:
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
    if result is not None:
        return result

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


def _validate_checkpoint(
    execution_id: DomainExecutionId,
    previous: DomainJobCheckpoint | None,
    checkpoint: DomainJobCheckpoint,
) -> None:
    if checkpoint.execution_key != execution_id.execution_key:
        raise ValueError("domain job checkpoint belongs to another execution")
    if previous is None:
        return
    if checkpoint.job_id != previous.job_id:
        raise ValueError("domain job checkpoint changed its job identity")
    if checkpoint.revision <= previous.revision:
        raise ValueError("domain job checkpoint revisions must increase")


def _provider_problem(
    execution_id: DomainExecutionId,
    error: Exception,
) -> Problem:
    return runtime_problem(
        "domain_execution_receipt_invalid",
        "domain job runtime returned invalid or uncorrelated result evidence",
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
    "DomainJobCheckpoint",
    "DomainJobRuntime",
    "DomainJobTransition",
    "DomainSetup",
    "ResumableDomainJobRuntime",
    "plan_domain_execution",
    "run_domain_invocation",
]
