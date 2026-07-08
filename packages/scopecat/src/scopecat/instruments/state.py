"""Instrument state value objects."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from scopecat.models.parameter import Quantity

StateValueKind = Literal["quantity", "number", "payload"]


class StateValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: StateValueKind
    quantity: Quantity | None = None
    value: float | None = None
    payload_id: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> StateValue:
        if self.kind == "quantity":
            if self.quantity is None:
                msg = "quantity state value requires quantity"
                raise ValueError(msg)
            if self.value is not None:
                msg = "quantity state value cannot contain numeric value"
                raise ValueError(msg)
            if self.payload_id is not None:
                msg = "quantity state value cannot contain payload_id"
                raise ValueError(msg)
            return self
        if self.kind == "number":
            if self.value is None:
                msg = "number state value requires value"
                raise ValueError(msg)
            if self.quantity is not None:
                msg = "number state value cannot contain quantity"
                raise ValueError(msg)
            if self.payload_id is not None:
                msg = "number state value cannot contain payload_id"
                raise ValueError(msg)
            return self
        if self.kind == "payload":
            if not self.payload_id:
                msg = "payload state value requires payload_id"
                raise ValueError(msg)
            if self.quantity is not None or self.value is not None:
                msg = "payload state value cannot contain quantity or numeric value"
                raise ValueError(msg)
            return self
        msg = f"unsupported state value kind: {self.kind}"
        raise ValueError(msg)
