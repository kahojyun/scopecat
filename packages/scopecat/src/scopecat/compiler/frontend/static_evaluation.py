"""Host-side evaluation for config-dependent frontend constants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.compiler.relations.evaluation import (
    ParameterRelationData,
    evaluate_relation,
    evaluate_scalar,
    evaluate_series,
)
from scopecat.compiler.relations.model import (
    CellValue,
    RelationExpr,
    Row,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    verify_relation_plan,
)
from scopecat.kernel.value_types import Scalar, Series, Table


def _static_bindings(bindings: RelationTypeBindings) -> RelationTypeBindings:
    """Exclude lexical rows that do not exist during host-side evaluation."""

    return RelationTypeBindings(
        inputs=bindings.inputs,
        parameters=bindings.parameters,
        parameter_lookups=bindings.parameter_lookups,
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
            self.parameters.to_context(inputs=inputs),
        )

    def series(
        self,
        expression: SeriesExpr,
        *,
        bindings: RelationTypeBindings,
        inputs: Mapping[str, object],
        expected_type: Series | None = None,
    ) -> list[CellValue]:
        verified = verify_relation_plan(
            expression,
            bindings=_static_bindings(bindings),
            expected_type=expected_type,
        )
        return evaluate_series(
            verified,
            self.parameters.to_context(inputs=inputs),
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
            self.parameters,
            inputs=inputs,
        )


__all__ = ["StaticRelationEvaluator"]
