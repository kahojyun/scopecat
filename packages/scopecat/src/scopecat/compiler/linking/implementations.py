"""Validate and seal local execution implementation selections."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
)
from scopecat.compiler.semantic.operation_contract import (
    EffectClass,
    OperationContract,
    PlacementConstraint,
)
from scopecat.compiler.typed.program import TypedComputeNode
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.value_types import Route, ValueType


@dataclass(frozen=True, slots=True)
class ComputeInterface:
    """Canonical typed ports paired with one selected implementation."""

    inputs: tuple[tuple[str, ValueType | Route], ...]
    output_type: ValueType

    @classmethod
    def from_node(cls, node: TypedComputeNode) -> ComputeInterface:
        return cls(
            inputs=tuple(
                sorted((name, value.value_type) for name, value in node.inputs.items())
            ),
            output_type=node.result.value_type,
        )

    @property
    def input_names(self) -> tuple[str, ...]:
        return tuple(name for name, _value_type in self.inputs)


@dataclass(frozen=True, slots=True)
class SelectedLocalImplementation:
    """One exact callable selected for one typed semantic operation."""

    operation_id: OperationId
    implementation_id: ImplementationId
    operation_contract: OperationContract
    interface: ComputeInterface
    kernel: Callable[..., object] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class SelectedLocalImplementations:
    """Complete local implementation coverage for a typed program."""

    entries: tuple[SelectedLocalImplementation, ...]
    _by_operation: Mapping[OperationId, SelectedLocalImplementation] = field(
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_by_operation",
            MappingProxyType({entry.operation_id: entry for entry in self.entries}),
        )

    def selected_for(self, operation_id: OperationId) -> SelectedLocalImplementation:
        try:
            return self._by_operation[operation_id]
        except KeyError as error:
            msg = (
                "no local implementation was selected for operation "
                f"{operation_id.qualified_name!r}"
            )
            raise ValueError(msg) from error


def select_local_implementations(
    nodes: Sequence[TypedComputeNode],
    catalog: ImplementationCatalog,
    *,
    phase: ProblemPhase,
) -> tuple[SelectedLocalImplementations | None, tuple[Problem, ...]]:
    """Select complete local coverage from a verified implementation catalog."""

    by_operation: dict[OperationId, list[LocalPythonImplementation]] = {}
    for implementation in catalog.local_python:
        by_operation.setdefault(implementation.operation_id, []).append(implementation)
    problems: list[Problem] = []
    selected: list[SelectedLocalImplementation] = []
    for node in nodes:
        candidates = by_operation.get(node.id, [])
        if not candidates:
            problems.append(
                _problem(
                    "semantic_operation_implementation_missing",
                    "compute operation has no local Python implementation: "
                    f"{node.id.qualified_name!r}",
                    node.id,
                    phase=phase,
                    category=ProblemCategory.NOT_FOUND,
                )
            )
            continue
        if len(candidates) > 1:
            problems.append(
                _problem(
                    "semantic_operation_implementation_ambiguous",
                    "compute operation has more than one local Python "
                    f"implementation: {node.id.qualified_name!r}",
                    node.id,
                    phase=phase,
                    category=ProblemCategory.CONFLICT,
                )
            )
            continue
        implementation = candidates[0]
        if not _local_python_accepts(node.contract):
            problems.append(
                _problem(
                    "semantic_operation_local_target_unsupported",
                    "local Python execution cannot satisfy operation contract: "
                    f"{node.id.qualified_name!r}",
                    node.id,
                    phase=phase,
                    category=ProblemCategory.UNAVAILABLE,
                )
            )
            continue
        selected.append(
            SelectedLocalImplementation(
                operation_id=node.id,
                implementation_id=implementation.id,
                operation_contract=node.contract,
                interface=ComputeInterface.from_node(node),
                kernel=implementation.kernel,
            )
        )
    if problems:
        return None, tuple(problems)
    if len(selected) != len(nodes):
        raise AssertionError("successful local selection lost compute coverage")
    return (
        SelectedLocalImplementations(tuple(selected)),
        (),
    )


def _local_python_accepts(contract: OperationContract) -> bool:
    return contract.effect is EffectClass.PURE and (
        contract.placement is PlacementConstraint.HOST
        or contract.placement is PlacementConstraint.UNCONSTRAINED
    )


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
