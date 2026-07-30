from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
)
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
)
from scopecat.graph.relations.model import (
    CellValue,
)
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)

type StateValueUse = RelationUse[ScalarValueExpr] | ComputeResultRef
type EvaluatedStateValue = ComputeResultRef | CellValue


@dataclass(frozen=True, slots=True)
class LogicalStateResourceTarget:
    """State target resolved through one declared logical resource port."""

    port_id: LogicalResourcePortId


@dataclass(frozen=True, slots=True)
class SetStateSpec:
    """Assign one interface property after point-local parameter overlays."""

    resource_target: LogicalStateResourceTarget
    interface_id: InterfaceId
    property_id: str
    value_use: StateValueUse
    component_path: tuple[str, ...] = ()

    @property
    def target(self) -> str:
        component = "/".join(self.component_path)
        prefix = f"{self.interface_id}/{component}" if component else self.interface_id
        return f"{prefix}.{self.property_id}"


@dataclass(frozen=True, slots=True)
class EnsureStateSpec:
    """One coherent desired-state assertion retained through planning."""

    assignments: tuple[SetStateSpec, ...]

    def __post_init__(self) -> None:
        if not self.assignments:
            raise ValueError("desired state requires at least one assignment")


type StateEffect = SetStateSpec | EnsureStateSpec


@dataclass(frozen=True, slots=True)
class StateRecord:
    point_index: int
    resource_target: LogicalResourcePortId
    interface_id: InterfaceId
    property_id: str
    value: EvaluatedStateValue
    component_path: tuple[str, ...] = ()

    @property
    def target(self) -> str:
        component = "/".join(self.component_path)
        prefix = f"{self.interface_id}/{component}" if component else self.interface_id
        return f"{prefix}.{self.property_id}"


def evaluate_state_spec(
    spec: SetStateSpec,
    *,
    point_index: int,
    ctx: EvalContext,
) -> list[StateRecord]:
    """Materialize one data-only state plan."""

    value_use = spec.value_use
    return [
        StateRecord(
            point_index=point_index,
            resource_target=spec.resource_target.port_id,
            interface_id=spec.interface_id,
            component_path=spec.component_path,
            property_id=spec.property_id,
            value=(
                value_use
                if isinstance(value_use, ComputeResultRef)
                else evaluate_scalar(value_use.value.plan, ctx)
            ),
        )
    ]
