from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from scopecat._execution.problems import problem_from_exception
from scopecat.errors import RunFailed, RunIndeterminate
from scopecat.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverFault,
    InstrumentReadback,
)
from scopecat.models.run import RunOutcome
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    blocking_problem,
    model_location,
)


def _blocking_problem() -> Problem:
    return blocking_problem(
        "runtime_test_blocked",
        "runtime operation was blocked",
        category=ProblemCategory.OPERATION,
        phase=ProblemPhase.EXECUTION,
        location=model_location("runtime_contract"),
    )


def _advisory_problem() -> Problem:
    return Problem(
        code="runtime_test_advisory",
        impact=ProblemImpact.ADVISORY,
        category=ProblemCategory.OPERATION,
        phase=ProblemPhase.EXECUTION,
        message="runtime advisory",
        location=model_location("runtime_contract"),
    )


@pytest.mark.parametrize(
    ("result", "certainty", "termination_reason", "problems"),
    [
        ("succeeded", "known", "completed", ()),
        ("succeeded", "known", "completed", (_advisory_problem(),)),
        ("failed", "known", "blocking_problem", (_blocking_problem(),)),
        (
            "failed",
            "indeterminate",
            "effect_outcome_unknown",
            (_blocking_problem(),),
        ),
        ("cancelled", "known", "interrupted", (_blocking_problem(),)),
        ("cancelled", "indeterminate", "interrupted", (_blocking_problem(),)),
    ],
)
def test_run_outcome_accepts_only_coherent_terminal_facts(
    result: str,
    certainty: str,
    termination_reason: str,
    problems: tuple[Problem, ...],
) -> None:
    outcome = RunOutcome.model_validate(
        {
            "run_id": "run-contract",
            "result": result,
            "certainty": certainty,
            "termination_reason": termination_reason,
            "problems": problems,
        }
    )

    assert outcome.problems == problems


@pytest.mark.parametrize(
    ("result", "certainty", "termination_reason", "problems"),
    [
        ("succeeded", "indeterminate", "completed", ()),
        ("succeeded", "known", "completed", (_blocking_problem(),)),
        ("succeeded", "known", "blocking_problem", ()),
        ("failed", "known", "blocking_problem", ()),
        ("failed", "known", "effect_outcome_unknown", (_blocking_problem(),)),
        ("failed", "indeterminate", "effect_outcome_unknown", ()),
        ("cancelled", "known", "interrupted", ()),
        (
            "cancelled",
            "indeterminate",
            "effect_outcome_unknown",
            (_blocking_problem(),),
        ),
    ],
)
def test_run_outcome_rejects_incoherent_terminal_facts(
    result: str,
    certainty: str,
    termination_reason: str,
    problems: tuple[Problem, ...],
) -> None:
    with pytest.raises(ValidationError):
        RunOutcome.model_validate(
            {
                "run_id": "run-contract",
                "result": result,
                "certainty": certainty,
                "termination_reason": termination_reason,
                "problems": problems,
            }
        )


def test_receipts_accept_only_coherent_status_and_problem_facts() -> None:
    blocking = _blocking_problem()
    advisory = _advisory_problem()
    readback = InstrumentReadback()

    assert ApplyReceipt(status="applied", problems=(advisory,)).status == "applied"
    assert ApplyReceipt(status="not_applied", problems=(blocking,)).status == (
        "not_applied"
    )
    assert ApplyReceipt(status="unknown", problems=(blocking,)).status == "unknown"
    assert (
        CollectReceipt(
            status="collected",
            problems=(advisory,),
            readback=readback,
        ).status
        == "collected"
    )
    assert (
        CollectReceipt(
            status="not_collected",
            problems=(blocking,),
        ).status
        == "not_collected"
    )
    assert CollectReceipt(status="unknown", problems=(blocking,)).status == "unknown"

    with pytest.raises(ValidationError):
        ApplyReceipt(status="applied", problems=(blocking,))
    with pytest.raises(ValidationError):
        ApplyReceipt(status="not_applied")
    with pytest.raises(ValidationError):
        ApplyReceipt(status="unknown", problems=(advisory,))
    with pytest.raises(ValidationError):
        CollectReceipt(status="collected", problems=(blocking,), readback=readback)
    with pytest.raises(ValidationError):
        CollectReceipt(status="not_collected")
    with pytest.raises(ValidationError):
        CollectReceipt(status="unknown", problems=(advisory,))


def test_driver_fault_requires_one_blocking_problem() -> None:
    blocking = _blocking_problem()

    assert DriverFault(blocking).problem is blocking
    with pytest.raises(ValueError, match="blocking problem"):
        DriverFault(_advisory_problem())


def test_expected_driver_fault_is_not_logged_as_an_unexpected_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = _blocking_problem()
    caplog.set_level(logging.ERROR, logger="scopecat._execution.problems")

    problem = problem_from_exception(
        "unexpected_driver_failure",
        "driver failed unexpectedly",
        run_id="run-contract",
        operation_id="collect.signal",
        error=DriverFault(source),
    )

    assert problem.code == source.code
    assert caplog.records == []


def test_unexpected_exception_is_logged_but_problem_is_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="scopecat._execution.problems")

    problem = problem_from_exception(
        "unexpected_driver_failure",
        "driver failed unexpectedly",
        run_id="run-contract",
        operation_id="collect.signal",
        error=RuntimeError("private device response"),
    )

    assert "private device response" not in problem.message
    assert problem.details["exception_type"] == "builtins.RuntimeError"
    assert [record.getMessage() for record in caplog.records] == [
        "runtime boundary raised an unexpected exception"
    ]


def test_run_failure_subtypes_require_matching_outcomes() -> None:
    problem = _blocking_problem()
    failed = RunOutcome(
        run_id="run-failed",
        result="failed",
        certainty="known",
        termination_reason="blocking_problem",
        problems=(problem,),
    )
    indeterminate = RunOutcome(
        run_id="run-indeterminate",
        result="failed",
        certainty="indeterminate",
        termination_reason="effect_outcome_unknown",
        problems=(problem,),
    )

    assert RunFailed(run_id=failed.run_id, outcome=failed).outcome is failed
    assert (
        RunIndeterminate(
            run_id=indeterminate.run_id,
            outcome=indeterminate,
        ).outcome
        is indeterminate
    )
    with pytest.raises(ValueError, match="known failed"):
        RunFailed(run_id=indeterminate.run_id, outcome=indeterminate)
    with pytest.raises(ValueError, match="indeterminate"):
        RunIndeterminate(run_id=failed.run_id, outcome=failed)
