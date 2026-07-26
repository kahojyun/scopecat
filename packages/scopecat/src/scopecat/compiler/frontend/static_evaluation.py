"""Host-side evaluation for config-dependent frontend constants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.evaluation import (
    evaluate_relation,
    evaluate_scalar,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    verify_relation_plan,
)
from scopecat.graph.relations.model import (
    CellValue,
    RelationExpr,
    Row,
    ScalarExpr,
)
from scopecat.kernel.value_types import Scalar, Table


def _static_bindings(bindings: RelationTypeBindings) -> RelationTypeBindings:
    """Exclude the point row, which does not exist during host evaluation."""

    return RelationTypeBindings(
        inputs=bindings.inputs,
        parameters=bindings.parameters,
    )


@dataclass(frozen=True, slots=True)
class StaticRelationEvaluator:
    """Evaluate verified config-time relations."""

    parameters: ParameterRelationData

    def scalar(
        self,
        expression: ScalarExpr,
        *,
        bindings: RelationTypeBindings,
        inputs: Mapping[str, object],
        expected_type: Scalar | None = None,
    ) -> CellValue:
        verified = verify_relation_plan(
            expression,
            bindings=_static_bindings(bindings),
            expected_type=expected_type,
        )
        return evaluate_scalar(
            verified,
            EvalContext(params=self.parameters, inputs=dict(inputs)),
        )

    def relation(
        self,
        expression: RelationExpr,
        *,
        bindings: RelationTypeBindings,
        inputs: Mapping[str, object],
        expected_type: Table | None = None,
    ) -> list[Row]:
        verified = verify_relation_plan(
            expression,
            bindings=_static_bindings(bindings),
            expected_type=expected_type,
        )
        return evaluate_relation(
            verified,
            EvalContext(params=self.parameters, inputs=dict(inputs)),
        )
