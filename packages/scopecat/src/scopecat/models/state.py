"""Concrete scalar values used by instrument state commands and snapshots."""

from __future__ import annotations

import math
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from scopecat.models.parameter import Quantity


class PayloadRef(BaseModel):
    """Reference to one command-local payload."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    payload_id: str = Field(min_length=1)


type StateLiteral = float | Quantity | PayloadRef


class StateValue(RootModel[StateLiteral]):
    """A finite float, finite quantity, or command-local payload reference."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def validate_input(cls, value: object) -> object:
        if isinstance(value, bool):
            msg = "instrument state value must not be a bool"
            raise ValueError(msg)
        if isinstance(value, int | float):
            try:
                numeric_value = float(value)
            except OverflowError as error:
                msg = "instrument state number must be finite and representable"
                raise ValueError(msg) from error
            if not math.isfinite(numeric_value):
                msg = "instrument state number must be finite"
                raise ValueError(msg)
            return numeric_value
        if isinstance(value, Quantity):
            if not math.isfinite(value.value):
                msg = "instrument state quantity must be finite"
                raise ValueError(msg)
            return value
        if isinstance(value, PayloadRef | dict):
            return cast("object", value)
        msg = "instrument state value must be a number, quantity, or payload reference"
        raise ValueError(msg)

    @model_validator(mode="after")
    def validate_value(self) -> StateValue:
        if isinstance(self.root, Quantity) and not math.isfinite(self.root.value):
            msg = "instrument state quantity must be finite"
            raise ValueError(msg)
        return self


__all__ = ["PayloadRef", "StateLiteral", "StateValue"]
