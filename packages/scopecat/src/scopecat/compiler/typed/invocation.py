"""Typed atomic instrument-operation effects."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import evaluate_scalar
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Scalar
from scopecat.program.expressions import ComputeResultScalarExpr, ScalarExpression

type InvocationValueUse = ScalarExpression
type EvaluatedInvocationValue = CellValue | ComputeResultScalarExpr


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
    value_type: Scalar


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
        if isinstance(value_use, ComputeResultScalarExpr)
        else evaluate_scalar(
            value_use,
            ctx,
            expected_type=argument.value_type,
        )
    )
