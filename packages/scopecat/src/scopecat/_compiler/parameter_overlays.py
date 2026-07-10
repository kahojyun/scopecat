"""Typed point-local parameter overlays in the transient compiler graph."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat._relations import ScalarExpr
from scopecat.value_types import Scalar


class TypedOverlayExpression(BaseModel):
    """One scalar expression paired with its catalog-declared target type."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    expr: ScalarExpr
    value_type: Scalar


class PointParameterOverlay(BaseModel):
    """Replace one existing parameter-table cell for each experiment point.

    This is transient compiler intent, not a durable parameter edit or change
    record.  Its deliberately narrow shape prevents an experiment from adding
    or deleting rows, or from mutating scalar configuration values.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    table_id: str
    key: dict[str, TypedOverlayExpression] = Field(min_length=1)
    column_id: str
    value: TypedOverlayExpression

    @model_validator(mode="after")
    def validate_target(self) -> PointParameterOverlay:
        if not self.table_id:
            msg = "parameter overlay table_id must be non-empty"
            raise ValueError(msg)
        if not self.column_id:
            msg = "parameter overlay column_id must be non-empty"
            raise ValueError(msg)
        return self


__all__ = ["PointParameterOverlay", "TypedOverlayExpression"]
