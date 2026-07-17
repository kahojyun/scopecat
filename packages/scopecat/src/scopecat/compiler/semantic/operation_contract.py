"""Implementation-independent semantic operation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from scopecat.compiler.relations.operators import ScalarOperator


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
    semantics = contract.semantics
    if isinstance(semantics, OpaqueSemantics):
        if contract.portability is not Portability.IMPLEMENTATION_DEFINED:
            issues.append(
                OperationContractIssue(
                    "semantic_opaque_operation_portability_invalid",
                    "opaque semantics must declare implementation-defined portability",
                )
            )
    elif contract.portability is not Portability.PORTABLE:
        issues.append(
            OperationContractIssue(
                "semantic_scalar_binary_portability_invalid",
                "scalar binary semantics must declare portable semantics",
            )
        )
    return tuple(issues)
