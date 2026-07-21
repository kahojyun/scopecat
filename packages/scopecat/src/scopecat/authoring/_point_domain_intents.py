"""Authoring adapters for the shared point-domain algebra."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.authoring._value_refs import (
    PointValueDependency,
    ValueRef,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
    internal_value_ref_scalar_input_ids,
)
from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointAxis,
    PointAxisLinear,
    PointDomainAnalysis,
    PointDomainExpr,
    PointDomainPath,
    PointProduct,
    PointRows,
    PointUnit,
    PointZip,
    analyze_point_domain,
    iter_point_axis_linear,
    map_point_axis_centers,
    point_dependent_product,
    point_product,
)
from scopecat.kernel.value_types import Scalar, Table

type PointDomainIntent = PointDomainExpr[ValueRef]


def compose_point_domain_intents(
    *domains: PointDomainIntent,
) -> PointDomainIntent:
    """Compose ordered fragments while retaining directional dependencies."""

    combined: PointDomainIntent = POINT_UNIT
    for domain in domains:
        provided = set(point_domain_intent_output_types(combined))
        required = {
            dependency.id
            for dependency in point_domain_intent_free_point_dependencies(domain)
        } | set(point_domain_intent_free_point_input_ids(domain))
        combined = (
            point_dependent_product(combined, domain)
            if provided & required
            else point_product(combined, domain)
        )
    return combined


def analyze_point_domain_intent(domain: PointDomainIntent) -> PointDomainAnalysis:
    """Project schema and cardinality facts from the structural domain."""

    return analyze_point_domain(domain)


def point_domain_intent_value_type(domain: PointDomainIntent) -> Table:
    return analyze_point_domain_intent(domain).root.value_type


def point_domain_intent_output_types(
    domain: PointDomainIntent,
) -> dict[str, Scalar]:
    return {
        column.id: column.value_type
        for column in point_domain_intent_value_type(domain).columns
    }


def iter_point_domain_value_refs(
    domain: PointDomainIntent,
) -> Iterator[tuple[PointDomainPath, ValueRef]]:
    for path, source in iter_point_axis_linear(domain):
        yield path, source.center


def map_point_domain_value_refs(
    domain: PointDomainIntent,
    transform: Callable[[ValueRef, PointDomainPath], ValueRef],
) -> PointDomainIntent:
    return map_point_axis_centers(domain, transform)


def point_domain_intent_parameter_contracts(
    domain: PointDomainIntent,
) -> tuple[ParameterContract, ...]:
    return merge_parameter_contracts(
        *(
            internal_value_ref_parameter_contracts(value)
            for _path, value in iter_point_domain_value_refs(domain)
        )
    )


def point_domain_intent_free_point_dependencies(
    domain: PointDomainIntent,
) -> tuple[PointValueDependency, ...]:
    """Return typed point requirements not closed by dependent products."""

    selected: dict[str, PointValueDependency] = {}

    def merge(dependencies: tuple[PointValueDependency, ...]) -> None:
        for dependency in dependencies:
            existing = selected.get(dependency.id)
            if existing is not None and existing.value_type != dependency.value_type:
                msg = (
                    f"point value {dependency.id!r} is used with conflicting "
                    "declared types"
                )
                raise TypeError(msg)
            selected.setdefault(dependency.id, dependency)

    def visit(node: PointDomainIntent) -> tuple[PointValueDependency, ...]:
        if isinstance(node, PointUnit | PointRows):
            return ()
        if isinstance(node, PointAxis):
            return (
                internal_value_ref_point_dependencies(node.source.center)
                if isinstance(node.source, PointAxisLinear)
                else ()
            )
        if isinstance(node, PointProduct):
            return tuple(
                dependency for factor in node.factors for dependency in visit(factor)
            )
        if isinstance(node, PointZip):
            return tuple(
                dependency for source in node.sources for dependency in visit(source)
            )
        left = visit(node.left)
        bound_ids = set(point_domain_intent_output_types(node.left))
        right = tuple(
            dependency
            for dependency in visit(node.right)
            if dependency.id not in bound_ids
        )
        return (*left, *right)

    merge(visit(domain))
    return tuple(selected.values())


def point_domain_intent_free_point_input_ids(
    domain: PointDomainIntent,
) -> frozenset[str]:
    """Return scalar imports not closed by dependent products."""

    def visit(node: PointDomainIntent) -> frozenset[str]:
        if isinstance(node, PointUnit | PointRows):
            return frozenset()
        if isinstance(node, PointAxis):
            return (
                internal_value_ref_scalar_input_ids(node.source.center)
                if isinstance(node.source, PointAxisLinear)
                else frozenset()
            )
        if isinstance(node, PointProduct):
            return frozenset(
                input_id for factor in node.factors for input_id in visit(factor)
            )
        if isinstance(node, PointZip):
            return frozenset(
                input_id for source in node.sources for input_id in visit(source)
            )
        bound_ids = set(point_domain_intent_output_types(node.left))
        return visit(node.left) | (visit(node.right) - bound_ids)

    return visit(domain)


__all__ = [
    "POINT_UNIT",
    "PointDomainIntent",
    "analyze_point_domain_intent",
    "compose_point_domain_intents",
    "iter_point_domain_value_refs",
    "map_point_domain_value_refs",
    "point_domain_intent_free_point_dependencies",
    "point_domain_intent_free_point_input_ids",
    "point_domain_intent_output_types",
    "point_domain_intent_parameter_contracts",
    "point_domain_intent_value_type",
]
