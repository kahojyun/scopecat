"""Host-side evaluation for config-dependent frontend constants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
)
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    verify_scalar_expression,
)
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Scalar
from scopecat.program.expressions import ScalarExpr


def _static_bindings(bindings: ExpressionTypeBindings) -> ExpressionTypeBindings:
    """Exclude the point row, which does not exist during host evaluation."""

    return ExpressionTypeBindings(
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
        bindings: ExpressionTypeBindings,
        inputs: Mapping[str, object],
        expected_type: Scalar | None = None,
    ) -> CellValue:
        selected_bindings = _static_bindings(bindings)
        verified = verify_scalar_expression(
            expression,
            bindings=selected_bindings,
            expected_type=expected_type,
        )
        return evaluate_scalar(
            verified,
            EvalContext(params=self.parameters, inputs=dict(inputs)),
            bindings=selected_bindings,
            expected_type=expected_type,
        )
