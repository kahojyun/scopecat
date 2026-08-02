from __future__ import annotations

import pytest

from scopecat.kernel.errors import OperationFailure
from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.sdk.instruments import (
    CollectReceipt,
    InstrumentCollectFailure,
    InstrumentReadback,
)


def _collect_problem():
    return problem(
        "instrument_collect_failed",
        "instrument collection failed",
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument", "collect"),
    )


@pytest.mark.parametrize(
    ("status", "certainty"),
    [
        ("not_collected", "known"),
        ("unknown", "indeterminate"),
    ],
)
def test_collect_failure_preserves_receipt_and_certainty(
    status: str,
    certainty: str,
) -> None:
    selected = _collect_problem()
    receipt = CollectReceipt.model_validate(
        {
            "status": status,
            "problems": (selected,),
        }
    )

    error = InstrumentCollectFailure(receipt)

    assert isinstance(error, OperationFailure)
    assert error.receipt is receipt
    assert error.certainty == certainty
    assert error.problems == (selected,)
    assert str(error) == "instrument_collect_failed: instrument collection failed"


def test_collect_failure_rejects_success_receipt() -> None:
    receipt = CollectReceipt(status="collected", readback=InstrumentReadback())

    with pytest.raises(ValueError, match="negative or unknown receipt"):
        InstrumentCollectFailure(receipt)
