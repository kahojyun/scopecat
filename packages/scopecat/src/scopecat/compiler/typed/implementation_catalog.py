"""Config-free validation of implementation catalogs against typed operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
)
from scopecat.compiler.typed.program import TypedComputeNode
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    model_location,
)


@dataclass(frozen=True, slots=True)
class LocalImplementationCatalogAnalysis:
    """Normalized candidates and catalog defects for one typed compute graph."""

    implementations_by_operation: Mapping[
        OperationId,
        tuple[LocalPythonImplementation, ...],
    ]
    blocked_operations: frozenset[OperationId]
    problems: tuple[Problem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "implementations_by_operation",
            MappingProxyType(dict(self.implementations_by_operation)),
        )


def analyze_local_implementation_catalog(
    nodes: Sequence[TypedComputeNode],
    catalog: ImplementationCatalog,
    *,
    phase: ProblemPhase,
) -> LocalImplementationCatalogAnalysis:
    """Normalize candidates while reporting identity and ownership defects."""

    problems: list[Problem] = []
    blocked_operations: set[OperationId] = set()
    nodes_by_id = {node.id: node for node in nodes}
    by_operation: dict[OperationId, list[LocalPythonImplementation]] = {}
    by_id: dict[ImplementationId, LocalPythonImplementation] = {}
    implementations = sorted(
        catalog.local_python,
        key=lambda item: (
            item.operation_id.qualified_name,
            item.id.value,
            (
                item.operation_contract != node.contract
                if (node := nodes_by_id.get(item.operation_id)) is not None
                else False
            ),
        ),
    )
    for implementation in implementations:
        existing = by_id.get(implementation.id)
        if existing is not None:
            blocked_operations.add(existing.operation_id)
            blocked_operations.add(implementation.operation_id)
            problems.append(
                _problem(
                    "semantic_implementation_duplicate",
                    f"implementation {implementation.id.value!r} is duplicated",
                    implementation.operation_id,
                    phase=phase,
                    category=ProblemCategory.CONFLICT,
                )
            )
        else:
            by_id[implementation.id] = implementation
        node = nodes_by_id.get(implementation.operation_id)
        if node is None:
            problems.append(
                _problem(
                    "semantic_implementation_orphan",
                    "implementation references unknown operation "
                    f"{implementation.operation_id.qualified_name!r}",
                    implementation.operation_id,
                    phase=phase,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        if implementation.operation_contract != node.contract:
            blocked_operations.add(implementation.operation_id)
            problems.append(
                _problem(
                    "semantic_implementation_contract_mismatch",
                    "implementation contract does not match its typed operation: "
                    f"{implementation.id.value!r}",
                    implementation.operation_id,
                    phase=phase,
                    category=ProblemCategory.CONFLICT,
                )
            )
            continue
        by_operation.setdefault(implementation.operation_id, []).append(implementation)
    return LocalImplementationCatalogAnalysis(
        implementations_by_operation={
            operation_id: tuple(candidates)
            for operation_id, candidates in by_operation.items()
        },
        blocked_operations=frozenset(blocked_operations),
        problems=tuple(problems),
    )


def validate_local_implementation_catalog(
    nodes: Sequence[TypedComputeNode],
    catalog: ImplementationCatalog,
    *,
    phase: ProblemPhase,
) -> tuple[Problem, ...]:
    """Check catalog identity, ownership, and declared operation contracts."""

    return analyze_local_implementation_catalog(
        nodes,
        catalog,
        phase=phase,
    ).problems


def _problem(
    code: str,
    message: str,
    operation_id: OperationId,
    *,
    phase: ProblemPhase,
    category: ProblemCategory,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location(
            "compute_nodes",
            *operation_id.scope,
            operation_id.local_id,
            "implementation",
        ),
        phase=phase,
        category=category,
    )


__all__ = [
    "LocalImplementationCatalogAnalysis",
    "analyze_local_implementation_catalog",
    "validate_local_implementation_catalog",
]
