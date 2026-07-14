"""Typed point-local instrument action effects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.backend import (
    EvalContext,
    RelationBackend,
    SelectedRelationPlan,
    evaluate_scalar,
)
from scopecat.compiler.relations.model import ScalarExpr
from scopecat.compiler.relations.uses import (
    RelationUse,
    RelationUseId,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import ActionId
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.kernel.resource_identity import LogicalResourcePortId

type ActionValueUse = RelationUse[ScalarValueExpr] | ComputeResultRef
type EvaluatedActionValue = object
type SelectedPlanResolver = Callable[[RelationUseId], SelectedRelationPlan[PlanNode]]


@dataclass(frozen=True, slots=True)
class ActionFieldSpec:
    id: str
    value_use: ActionValueUse

    def __post_init__(self) -> None:
        if not self.id:
            msg = "action field id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """One ordered action invocation evaluated for every logical point."""

    id: ActionId
    resource_port_id: LogicalResourcePortId
    capability_id: str
    fields: tuple[ActionFieldSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id:
            msg = "action capability id must be non-empty"
            raise ValueError(msg)
        field_ids = tuple(field.id for field in self.fields)
        if len(field_ids) != len(set(field_ids)):
            msg = "action field ids must be unique"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ActionFieldRecord:
    id: str
    value: EvaluatedActionValue

    def __post_init__(self) -> None:
        if not self.id:
            msg = "action field record id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ActionRecord:
    point_index: int
    id: ActionId
    resource_port_id: LogicalResourcePortId
    capability_id: str
    fields: tuple[ActionFieldRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.point_index < 0 or not self.capability_id:
            msg = "action records require a nonnegative point and capability id"
            raise ValueError(msg)


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
