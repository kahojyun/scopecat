"""Implementation-independent semantic operation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from scopecat.compiler.relations.operators import ScalarOperator, is_scalar_operator


@dataclass(frozen=True, slots=True)
class OpaqueSemantics:
    """Meaning defined by a selected implementation, not by Scopecat core."""


@dataclass(frozen=True, slots=True)
class ScalarBinarySemantics:
    """One portable scalar operation defined by Scopecat core."""

    operator: ScalarOperator


type OperationSemantics = OpaqueSemantics | ScalarBinarySemantics


class EffectClass(StrEnum):
    PURE = "pure"


class Portability(StrEnum):
    IMPLEMENTATION_DEFINED = "implementation_defined"
    PORTABLE = "portable"


class PlacementConstraint(StrEnum):
    HOST = "host"
    UNCONSTRAINED = "unconstrained"


@dataclass(frozen=True, slots=True)
class OperationContract:
    """Meaning category and constraints without selecting an implementation."""

    semantics: OperationSemantics
    effect: EffectClass
    portability: Portability
    placement: PlacementConstraint


@dataclass(frozen=True, slots=True)
class OperationContractIssue:
    """One intrinsic inconsistency in an operation contract."""

    code: str
    message: str


LOCAL_OPAQUE_OPERATION_CONTRACT = OperationContract(
    semantics=OpaqueSemantics(),
    effect=EffectClass.PURE,
    portability=Portability.IMPLEMENTATION_DEFINED,
    placement=PlacementConstraint.HOST,
)


def scalar_binary_operation_contract(operator: ScalarOperator) -> OperationContract:
    return OperationContract(
        semantics=ScalarBinarySemantics(operator),
        effect=EffectClass.PURE,
        portability=Portability.PORTABLE,
        placement=PlacementConstraint.UNCONSTRAINED,
    )


def operation_contract_issues(
    contract: OperationContract,
) -> tuple[OperationContractIssue, ...]:
    """Return every target-independent consistency failure for one contract."""

    issues: list[OperationContractIssue] = []
    effect = cast("object", contract.effect)
    portability = cast("object", contract.portability)
    placement = cast("object", contract.placement)
    effect_valid = isinstance(effect, EffectClass)
    portability_valid = isinstance(portability, Portability)
    placement_valid = isinstance(placement, PlacementConstraint)
    if not effect_valid:
        issues.append(
            OperationContractIssue(
                "semantic_operation_effect_unknown",
                f"unknown operation effect {effect!r}",
            )
        )
    elif effect is not EffectClass.PURE:
        issues.append(
            OperationContractIssue(
                "semantic_operation_effect_invalid",
                "current semantic operations must declare a pure effect",
            )
        )
    if not portability_valid:
        issues.append(
            OperationContractIssue(
                "semantic_operation_portability_unknown",
                f"unknown operation portability {portability!r}",
            )
        )
    if not placement_valid:
        issues.append(
            OperationContractIssue(
                "semantic_operation_placement_unknown",
                f"unknown operation placement {placement!r}",
            )
        )

    semantics = cast("object", contract.semantics)
    if isinstance(semantics, OpaqueSemantics):
        if portability_valid and portability is not Portability.IMPLEMENTATION_DEFINED:
            issues.append(
                OperationContractIssue(
                    "semantic_opaque_operation_portability_invalid",
                    "opaque semantics must declare implementation-defined portability",
                )
            )
    elif isinstance(semantics, ScalarBinarySemantics):
        if not is_scalar_operator(semantics.operator):
            issues.append(
                OperationContractIssue(
                    "semantic_scalar_binary_operator_invalid",
                    f"unknown scalar binary operator {semantics.operator!r}",
                )
            )
        if portability_valid and portability is not Portability.PORTABLE:
            issues.append(
                OperationContractIssue(
                    "semantic_scalar_binary_portability_invalid",
                    "scalar binary semantics must declare portable semantics",
                )
            )
    else:
        issues.append(
            OperationContractIssue(
                "semantic_operation_semantics_unknown",
                f"unknown semantic operation {semantics!r}",
            )
        )
    return tuple(issues)


__all__ = [
    "LOCAL_OPAQUE_OPERATION_CONTRACT",
    "EffectClass",
    "OpaqueSemantics",
    "OperationContract",
    "OperationContractIssue",
    "OperationSemantics",
    "PlacementConstraint",
    "Portability",
    "ScalarBinarySemantics",
    "operation_contract_issues",
    "scalar_binary_operation_contract",
]
