"""Typed atomic instrument-operation effects."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import evaluate_scalar
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.graph.relations.model import CellValue
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId

type InvocationValueUse = RelationUse[ScalarValueExpr] | ComputeResultRef
type EvaluatedInvocationValue = CellValue | ComputeResultRef


@dataclass(frozen=True, slots=True)
class InvokeId:
    """Nominal identity in the instrument-invocation effect space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    def prefixed(self, *scope: str) -> InvokeId:
        return InvokeId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class InvokeArgument:
    id: str
    value_use: InvocationValueUse


@dataclass(frozen=True, slots=True)
class InvokeEffect:
    """One ordered atomic operation through a logical resource interface."""

    id: InvokeId
    resource_port_id: LogicalResourcePortId
    interface_id: InterfaceId
    operation_id: str
    arguments: tuple[InvokeArgument, ...]
    component_path: tuple[str, ...] = ()


def evaluate_invoke_argument(
    argument: InvokeArgument,
    *,
    ctx: EvalContext,
) -> EvaluatedInvocationValue:
    value_use = argument.value_use
    return (
        value_use
        if isinstance(value_use, ComputeResultRef)
        else evaluate_scalar(value_use.value.plan, ctx)
    )
