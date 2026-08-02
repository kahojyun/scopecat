"""Typed instrument-client operation failures."""

from __future__ import annotations

from typing import Literal

from scopecat.kernel.errors import OperationFailure
from scopecat.sdk.instruments.commands import CollectReceipt


class InstrumentCollectFailure(OperationFailure):
    """A typed acquisition did not establish a successful collection."""

    receipt: CollectReceipt
    certainty: Literal["known", "indeterminate"]

    def __init__(self, receipt: CollectReceipt) -> None:
        if receipt.status == "collected":
            msg = "InstrumentCollectFailure requires a negative or unknown receipt"
            raise ValueError(msg)
        self.receipt = receipt
        self.certainty = (
            "known" if receipt.status == "not_collected" else "indeterminate"
        )
        super().__init__(receipt.problems)
