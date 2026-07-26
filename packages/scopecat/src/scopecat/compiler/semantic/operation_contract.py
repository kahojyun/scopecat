"""Implementation-independent semantic operation contracts."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.graph.relations.operators import ScalarOperator


@dataclass(frozen=True, slots=True)
class OpaqueSemantics:
    """Meaning defined by the local implementation, not by Scopecat core."""


@dataclass(frozen=True, slots=True)
class ScalarBinarySemantics:
    """One portable scalar operation defined by Scopecat core."""

    operator: ScalarOperator


type OperationContract = OpaqueSemantics | ScalarBinarySemantics


LOCAL_OPAQUE_OPERATION_CONTRACT: OperationContract = OpaqueSemantics()


def scalar_binary_operation_contract(operator: ScalarOperator) -> OperationContract:
    return ScalarBinarySemantics(operator)
