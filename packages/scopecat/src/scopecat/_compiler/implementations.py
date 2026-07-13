"""Validate and seal local execution implementation selections."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat._compiler.problems import compiler_problem
from scopecat._compiler.program import TypedComputeNode
from scopecat._operation_contract import (
    EffectClass,
    OpaqueSemantics,
    OperationContract,
    PlacementConstraint,
    ScalarBinarySemantics,
    operation_contract_issues,
)
from scopecat._semantic_graph import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
)
from scopecat._value_availability import ValueRate, ValueStage
from scopecat.problems import Problem, ProblemCategory, ProblemPhase, model_location
from scopecat.value_types import Route, ValueType

_SELECTION_TOKEN = object()


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


@dataclass(frozen=True, slots=True, init=False)
class SelectedLocalImplementation:
    """One exact callable selected for one typed semantic operation."""

    operation_id: OperationId
    implementation_id: ImplementationId
    operation_contract: OperationContract
    interface: ComputeInterface
    kernel: Callable[..., object] = field(repr=False, compare=False)

    def __init__(
        self,
        operation_id: OperationId,
        implementation_id: ImplementationId,
        operation_contract: OperationContract,
        interface: ComputeInterface,
        kernel: Callable[..., object],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _SELECTION_TOKEN:
            msg = (
                "SelectedLocalImplementation can only be created by "
                "select_local_implementations"
            )
            raise TypeError(msg)
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "implementation_id", implementation_id)
        object.__setattr__(self, "operation_contract", operation_contract)
        object.__setattr__(self, "interface", interface)
        object.__setattr__(self, "kernel", kernel)

    def __copy__(self) -> SelectedLocalImplementation:
        return self

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> SelectedLocalImplementation:
        return self


@dataclass(frozen=True, slots=True, init=False)
class SelectedLocalImplementations:
    """Complete, unique local implementation coverage for a typed program."""

    entries: tuple[SelectedLocalImplementation, ...]
    _by_operation: Mapping[OperationId, SelectedLocalImplementation] = field(
        repr=False,
        compare=False,
        hash=False,
    )

    def __init__(
        self,
        entries: tuple[SelectedLocalImplementation, ...],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _SELECTION_TOKEN:
            msg = (
                "SelectedLocalImplementations can only be created by "
                "select_local_implementations"
            )
            raise TypeError(msg)
        by_operation = {entry.operation_id: entry for entry in entries}
        if len(by_operation) != len(entries):
            msg = "selected local implementations must have unique operation owners"
            raise ValueError(msg)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "_by_operation", MappingProxyType(by_operation))

    def __copy__(self) -> SelectedLocalImplementations:
        return self

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> SelectedLocalImplementations:
        return self

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
    """Seal complete unique local Python coverage for the typed compute graph."""

    by_operation, blocked_operations, problems = _local_implementations_by_operation(
        nodes,
        catalog,
        phase=phase,
    )
    selected: list[SelectedLocalImplementation] = []
    for node in nodes:
        if node.id in blocked_operations:
            continue
        if (
            node.result.availability.stage is not ValueStage.EXECUTE
            or node.result.availability.rate is not ValueRate.POINT
        ):
            problems.append(_output_availability_problem(node, phase=phase))
            continue
        candidates = by_operation.get(node.id, ())
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
        if implementation.operation_contract != node.contract:
            continue
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
                _token=_SELECTION_TOKEN,
            )
        )
    if problems:
        return None, tuple(problems)
    if len(selected) != len(nodes):
        raise AssertionError("successful local selection lost compute coverage")
    return (
        SelectedLocalImplementations(tuple(selected), _token=_SELECTION_TOKEN),
        (),
    )


def validate_local_implementation_catalog(
    nodes: Sequence[TypedComputeNode],
    catalog: ImplementationCatalog,
    *,
    phase: ProblemPhase,
) -> tuple[Problem, ...]:
    """Check catalog identity, ownership, and declared operation contracts."""

    _by_operation, _blocked_operations, problems = _local_implementations_by_operation(
        nodes,
        catalog,
        phase=phase,
    )
    return tuple(problems)


def _local_implementations_by_operation(
    nodes: Sequence[TypedComputeNode],
    catalog: ImplementationCatalog,
    *,
    phase: ProblemPhase,
) -> tuple[
    dict[OperationId, list[LocalPythonImplementation]],
    set[OperationId],
    list[Problem],
]:
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
    return by_operation, blocked_operations, problems


def _local_python_accepts(contract: OperationContract) -> bool:
    semantics = cast("object", contract.semantics)
    return (
        not operation_contract_issues(contract)
        and isinstance(semantics, OpaqueSemantics | ScalarBinarySemantics)
        and contract.effect is EffectClass.PURE
        and (
            contract.placement is PlacementConstraint.HOST
            or contract.placement is PlacementConstraint.UNCONSTRAINED
        )
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


def _output_availability_problem(
    node: TypedComputeNode,
    *,
    phase: ProblemPhase,
) -> Problem:
    availability = node.result.availability
    return compiler_problem(
        "semantic_operation_local_output_availability_unsupported",
        "local point execution requires execute-stage, point-rate compute "
        f"outputs; {node.result.id.qualified_name!r} is "
        f"{availability.stage.value}-stage, {availability.rate.value}-rate",
        model_location(
            "compute_nodes",
            *node.id.scope,
            node.id.local_id,
            "result",
            "availability",
        ),
        phase=phase,
        category=ProblemCategory.UNAVAILABLE,
    )


__all__ = [
    "ComputeInterface",
    "SelectedLocalImplementation",
    "SelectedLocalImplementations",
    "select_local_implementations",
    "validate_local_implementation_catalog",
]
