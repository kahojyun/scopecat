"""In-process journal boundary shared by concrete runtime effects."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from pydantic import JsonValue

from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.records.execution_journal import (
    ExecutionEffect,
    ExecutionStage,
    ExecutionTransition,
    JournalEntryState,
)
from scopecat.sdk.journal import (
    ExecutionJournal,
    claim_transition,
    commit_transition,
)
from scopecat.sdk.runtime_problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)


class JournaledEffectBoundary:
    """Own problem, certainty, and interruption state around external effects."""

    def __init__(self, *, run_id: str, journal: ExecutionJournal) -> None:
        self.run_id = run_id
        self.journal = journal
        self.problems: list[Problem] = []
        self.indeterminate = False
        self.interruption: BaseException | None = None

    @property
    def execution_journal(self) -> ExecutionJournal:
        return self.journal

    def entry(
        self,
        *,
        operation_id: str,
        stage: ExecutionStage,
        effect: ExecutionEffect,
        state: JournalEntryState,
        point_index: int | None = None,
        instrument_id: str | None = None,
        evidence: Mapping[str, JsonValue] | None = None,
    ) -> ExecutionTransition:
        return ExecutionTransition(
            run_id=self.run_id,
            operation_id=operation_id,
            stage=stage,
            effect=effect,
            state=state,
            point_index=point_index,
            instrument_id=instrument_id,
            evidence=dict(evidence or {}),
        )

    def invoke[ReceiptT](
        self,
        entry: ExecutionTransition,
        invoke: Callable[[], ReceiptT],
        *,
        unknown_code: str,
        unknown_message: str,
        unknown_evidence: Mapping[str, JsonValue] | None = None,
        after_intent: Callable[[], None] | None = None,
        phase: ProblemPhase = ProblemPhase.EXECUTION,
    ) -> ReceiptT | None:
        """Claim an effect, invoke it once, and record unknown outcomes."""

        claim_transition(self.journal, entry)
        if after_intent is not None:
            after_intent()
        try:
            return invoke()
        except Exception as error:
            self.indeterminate = True
            problem = self.problem_from_exception(
                unknown_code,
                unknown_message,
                error,
                operation_id=entry.operation_id,
                point_index=entry.point_index,
                instrument_id=entry.instrument_id,
                phase=phase,
            )
            self.problems.append(problem)
        except BaseException as error:
            self.indeterminate = True
            problem = self.record_interruption(
                error,
                operation_id=entry.operation_id,
                point_index=entry.point_index,
                instrument_id=entry.instrument_id,
                phase=phase,
            )
        self.commit_best_effort(
            entry.model_copy(
                update={
                    "state": "unknown",
                    "problems": (problem,),
                    "evidence": dict(unknown_evidence or entry.evidence),
                }
            )
        )
        return None

    def accept_receipt(
        self,
        entry: ExecutionTransition,
        *,
        status: str,
        success_status: str,
        problems: Sequence[Problem],
        evidence: Mapping[str, JsonValue],
    ) -> tuple[bool, tuple[Problem, ...]]:
        """Contextualize a driver receipt and close non-success outcomes."""

        receipt_problems = contextualize_problems(
            problems,
            run_id=self.run_id,
            operation_id=entry.operation_id,
            point_index=entry.point_index,
            instrument_id=entry.instrument_id,
        )
        self.problems.extend(receipt_problems)
        if status == success_status:
            return True, receipt_problems
        if status == "unknown":
            self.indeterminate = True
        self.commit_after_effect(
            entry.model_copy(
                update={
                    "state": "unknown" if status == "unknown" else "failed",
                    "problems": receipt_problems,
                    "evidence": dict(evidence),
                }
            )
        )
        return False, receipt_problems

    def commit_after_effect(self, entry: ExecutionTransition) -> None:
        try:
            commit_transition(self.journal, entry)
        except Exception:
            self.indeterminate = True
            raise

    def commit_best_effort(self, entry: ExecutionTransition) -> None:
        """Record a transition without allowing evidence failure to block safety."""

        try:
            commit_transition(self.journal, entry)
        except Exception as error:
            self.indeterminate = True
            self.problems.append(
                self.problem_from_exception(
                    "execution_journal_commit_failed",
                    f"failed to journal {entry.operation_id}",
                    error,
                    operation_id=entry.operation_id,
                    point_index=entry.point_index,
                    instrument_id=entry.instrument_id,
                    phase=ProblemPhase.PERSISTENCE,
                )
            )
        except BaseException as error:
            self.indeterminate = True
            self.record_interruption(error, operation_id=entry.operation_id)

    def record_interruption(
        self,
        error: BaseException,
        *,
        operation_id: str | None = None,
        point_index: int | None = None,
        instrument_id: str | None = None,
        phase: ProblemPhase = ProblemPhase.EXECUTION,
    ) -> Problem:
        if self.interruption is None:
            self.interruption = error
        problem = self.problem(
            "execution_interrupted",
            f"execution interrupted by {type(error).__name__}",
            operation_id=operation_id,
            point_index=point_index,
            instrument_id=instrument_id,
            phase=phase,
            details={
                "exception_type": f"{type(error).__module__}.{type(error).__qualname__}"
            },
        )
        self.problems.append(problem)
        return problem

    def problem(
        self,
        code: str,
        message: str,
        *,
        operation_id: str | None = None,
        point_index: int | None = None,
        instrument_id: str | None = None,
        phase: ProblemPhase = ProblemPhase.EXECUTION,
        details: Mapping[str, object] | None = None,
    ) -> Problem:
        return runtime_problem(
            code,
            message,
            run_id=self.run_id,
            operation_id=operation_id,
            point_index=point_index,
            instrument_id=instrument_id,
            phase=phase,
            details=details,
        )

    def problem_from_exception(
        self,
        code: str,
        message: str,
        error: Exception,
        *,
        operation_id: str | None = None,
        point_index: int | None = None,
        instrument_id: str | None = None,
        phase: ProblemPhase = ProblemPhase.EXECUTION,
    ) -> Problem:
        return problem_from_exception(
            code,
            message,
            run_id=self.run_id,
            error=error,
            operation_id=operation_id,
            point_index=point_index,
            instrument_id=instrument_id,
            phase=phase,
        )
