"""Authoring projections for the shared point-domain algebra."""

from __future__ import annotations

from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_parameter_contracts,
)
from scopecat.graph.relations.point_domain import (
    POINT_UNIT,
    PointDomainExpr,
    analyze_point_domain,
    iter_point_axis_linear,
)
from scopecat.kernel.value_types import Scalar, Table

type PointDomainIntent = PointDomainExpr[ValueRef]


def point_domain_intent_value_type(domain: PointDomainIntent) -> Table:
    return analyze_point_domain(domain).value_type


def point_domain_intent_output_types(
    domain: PointDomainIntent,
) -> dict[str, Scalar]:
    return {
        column.id: column.value_type
        for column in point_domain_intent_value_type(domain).columns
    }


def point_domain_intent_parameter_contracts(
    domain: PointDomainIntent,
) -> tuple[ParameterContract, ...]:
    return merge_parameter_contracts(
        *(
            internal_value_ref_parameter_contracts(source.center)
            for _path, source in iter_point_axis_linear(domain)
        )
    )


__all__ = [
    "POINT_UNIT",
    "PointDomainIntent",
    "point_domain_intent_output_types",
    "point_domain_intent_parameter_contracts",
    "point_domain_intent_value_type",
]
