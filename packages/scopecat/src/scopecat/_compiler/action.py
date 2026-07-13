"""Typed point-local instrument action effects."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from scopecat._compute_result import ComputeResultRef
from scopecat._relation_analysis import PlanNode
from scopecat._relation_backend import (
    EvalContext,
    RelationBackend,
    SelectedRelationPlan,
    evaluate_scalar,
)
from scopecat._relation_use import RelationUse, RelationUseId
from scopecat._relations import ScalarExpr
from scopecat._resource_identity import LogicalResourcePortId
from scopecat._semantic_graph import ActionId
from scopecat._value_expressions import ScalarValueExpr

type ActionValueUse = RelationUse[ScalarValueExpr] | ComputeResultRef
type EvaluatedActionValue = object
type SelectedPlanResolver = Callable[[RelationUseId], SelectedRelationPlan[PlanNode]]


class ActionFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)

    id: str = Field(min_length=1)
    value_use: ActionValueUse


class ActionSpec(BaseModel):
    """One ordered action invocation evaluated for every logical point."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)

    id: ActionId
    resource_port_id: LogicalResourcePortId
    capability_id: str = Field(min_length=1)
    fields: tuple[ActionFieldSpec, ...] = ()

    def model_post_init(self, _context: object) -> None:
        field_ids = tuple(field.id for field in self.fields)
        if len(field_ids) != len(set(field_ids)):
            msg = "action field ids must be unique"
            raise ValueError(msg)


class ActionFieldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str = Field(min_length=1)
    value: EvaluatedActionValue


class ActionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_index: int = Field(ge=0)
    id: ActionId
    resource_port_id: LogicalResourcePortId
    capability_id: str = Field(min_length=1)
    fields: tuple[ActionFieldRecord, ...] = ()


def evaluate_action_spec(
    spec: ActionSpec,
    *,
    point_index: int,
    ctx: EvalContext,
    backend: RelationBackend,
    selected_plan: SelectedPlanResolver,
) -> ActionRecord:
    return ActionRecord(
        point_index=point_index,
        id=spec.id,
        resource_port_id=spec.resource_port_id,
        capability_id=spec.capability_id,
        fields=tuple(
            ActionFieldRecord(
                id=field.id,
                value=(
                    field.value_use
                    if isinstance(field.value_use, ComputeResultRef)
                    else evaluate_scalar(
                        backend,
                        cast(
                            "SelectedRelationPlan[ScalarExpr]",
                            selected_plan(field.value_use.id),
                        ),
                        ctx,
                    )
                ),
            )
            for field in spec.fields
        ),
    )


__all__ = [
    "ActionFieldRecord",
    "ActionFieldSpec",
    "ActionRecord",
    "ActionSpec",
    "ActionValueUse",
    "evaluate_action_spec",
]
