"""Backend-neutral typed value and pure-operation graph.

The graph is semantic data only.  Python kernels and authoring provenance are
carried by explicit sidecars so implementation choice and diagnostics cannot
change graph equality.
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence

from scopecat.compiler.semantic.model import (
    AcquireEffect,
    MeasurementPostprocessorId,
    SemanticDomainExecution,
    SemanticGraphIR,
    SemanticMeasurementPostprocessor,
    SemanticOperation,
)
from scopecat.graph.values import (
    OperationId,
    ValueId,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import ValueType


def verify_semantic_graph(
    graph: SemanticGraphIR,
    *,
    effects: Sequence[SemanticDomainExecution | AcquireEffect] = (),
) -> SemanticGraphIR:
    """Validate closure and normalize semantic dataflow."""

    domain_executions = tuple(
        effect for effect in effects if isinstance(effect, SemanticDomainExecution)
    )
    acquisitions = tuple(
        effect for effect in effects if isinstance(effect, AcquireEffect)
    )
    problems: list[Problem] = []
    definitions = {definition.id: definition for definition in graph.value_defs}
    ambiguous_measurement_postprocessor_ids = _measurement_postprocessors_by_id(
        graph.measurement_postprocessors,
        problems,
    )
    operation_results = {
        operation.result_id: operation for operation in graph.operations
    }
    value_types = {
        definition.id: definition.value_type for definition in definitions.values()
    }
    value_types.update(
        {
            result_id: operation.result_type
            for result_id, operation in operation_results.items()
        }
    )
    for execution_index, execution in enumerate(domain_executions):
        _verify_domain_execution(
            execution,
            value_types,
            operation_results,
            problems,
            execution_index=execution_index,
        )
    unambiguous_measurement_postprocessors = tuple(
        postprocessor
        for postprocessor in graph.measurement_postprocessors
        if postprocessor.id not in ambiguous_measurement_postprocessor_ids
    )
    _verify_product_owners(
        acquisitions,
        domain_executions,
        unambiguous_measurement_postprocessors,
        problems,
    )
    ordered_measurement_postprocessors = _verify_measurement_postprocessor_sources(
        unambiguous_measurement_postprocessors,
        problems,
    )
    ordered_operations = _topological_operations(
        graph.operations,
        operation_results,
        problems,
    )
    if problems:
        raise CheckFailed(problems)
    ordered_defs = tuple(
        sorted(graph.value_defs, key=lambda item: item.id.qualified_name)
    )
    normalized = SemanticGraphIR(
        value_defs=ordered_defs,
        operations=ordered_operations,
        measurement_postprocessors=ordered_measurement_postprocessors,
    )
    return normalized


def _measurement_postprocessors_by_id(
    postprocessors: tuple[SemanticMeasurementPostprocessor, ...],
    problems: list[Problem],
) -> frozenset[MeasurementPostprocessorId]:
    grouped: dict[
        MeasurementPostprocessorId,
        list[SemanticMeasurementPostprocessor],
    ] = {}
    for postprocessor in postprocessors:
        grouped.setdefault(postprocessor.id, []).append(postprocessor)
    ambiguous = frozenset(
        transform_id
        for transform_id, declarations in grouped.items()
        if len(declarations) > 1
    )
    for transform_id in sorted(ambiguous, key=lambda item: item.qualified_name):
        problems.append(
            _problem(
                "semantic_measurement_postprocessor_duplicate",
                "measurement postprocessor "
                f"{transform_id.qualified_name!r} is declared more than once",
                "measurement_postprocessors",
                transform_id.qualified_name,
            )
        )
    return ambiguous


def _verify_product_owners(
    acquisitions: tuple[AcquireEffect, ...],
    executions: tuple[SemanticDomainExecution, ...],
    postprocessors: tuple[SemanticMeasurementPostprocessor, ...],
    problems: list[Problem],
) -> None:
    owners: dict[object, tuple[str, str]] = {}
    for acquire in acquisitions:
        for result in acquire.results:
            existing = owners.get(result.product_id)
            if existing is not None:
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "semantic_product_producer_duplicate",
                        f"logical product {result.product_id.qualified_name!r} is "
                        f"produced by both {owner}/{owner_port!r} and acquisition "
                        f"{acquire.id.qualified_name!r}/{result.result_id!r}",
                        "acquisitions",
                        acquire.id.qualified_name,
                        "results",
                        result.result_id,
                    )
                )
                continue
            owners[result.product_id] = (
                f"acquisition {acquire.id.qualified_name!r}",
                result.result_id,
            )
    for execution in executions:
        for result_id, product_id in execution.results:
            existing = owners.get(product_id)
            if existing is not None:
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "semantic_product_producer_duplicate",
                        f"logical product {product_id.qualified_name!r} is produced "
                        f"by both {owner}/{owner_port!r} and domain execution "
                        f"{execution.id!r}/{result_id!r}",
                        "domain_executions",
                        execution.id,
                        "results",
                        result_id,
                    )
                )
                continue
            owners[product_id] = (f"domain execution {execution.id!r}", result_id)
    for postprocessor in postprocessors:
        for role, product_id in postprocessor.outputs:
            existing = owners.get(product_id)
            if existing is not None:
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "semantic_product_producer_duplicate",
                        f"logical product {product_id.qualified_name!r} is "
                        f"produced by both {owner}/{owner_port!r} and measurement "
                        "postprocessor "
                        f"{postprocessor.id.qualified_name!r}/{role!r}",
                        "measurement_postprocessors",
                        postprocessor.id.qualified_name,
                        "outputs",
                        role,
                    )
                )
                continue
            owners[product_id] = (
                f"measurement postprocessor {postprocessor.id.qualified_name!r}",
                role,
            )


def _verify_measurement_postprocessor_sources(
    postprocessors: tuple[SemanticMeasurementPostprocessor, ...],
    problems: list[Problem],
) -> tuple[SemanticMeasurementPostprocessor, ...]:
    owner_by_output = {
        product_id: postprocessor.id
        for postprocessor in postprocessors
        for _role, product_id in postprocessor.outputs
    }
    for postprocessor in postprocessors:
        source_owner = owner_by_output.get(postprocessor.input)
        if source_owner is None:
            continue
        problems.append(
            _problem(
                "semantic_measurement_postprocessor_chaining_unsupported",
                f"measurement postprocessor "
                f"{postprocessor.id.qualified_name!r} consumes output from "
                f"{source_owner.qualified_name!r}; postprocessor chaining is "
                "not supported",
                "measurement_postprocessors",
                postprocessor.id.qualified_name,
                "input",
            )
        )
    return tuple(sorted(postprocessors, key=lambda item: item.id.qualified_name))


def _verify_domain_execution(
    execution: SemanticDomainExecution,
    value_types: Mapping[ValueId, ValueType],
    operation_results: Mapping[ValueId, SemanticOperation],
    problems: list[Problem],
    *,
    execution_index: int,
) -> None:
    program = execution.program
    location = ("domain_executions", str(execution_index))
    input_ports = {port.id: port for port in program.input_ports}
    for name, use in execution.inputs:
        value_type = value_types[use.value_id]
        port = input_ports[name]
        if not is_assignable(
            value_type,
            port.value_type,
        ):
            problems.append(
                _problem(
                    "semantic_domain_execution_input_type_mismatch",
                    f"domain execution input {name!r} is not assignable to its "
                    "declared port type",
                    *location,
                    "inputs",
                    name,
                )
            )
        if use.value_id in operation_results:
            problems.append(
                _problem(
                    "semantic_domain_execution_input_stage_unavailable",
                    f"domain execution input {name!r} must be available at plan stage",
                    *location,
                    "inputs",
                    name,
                )
            )
    compiler_input_ports = {port.id: port for port in program.compiler_input_ports}
    for name, use in execution.compiler_inputs:
        value_type = value_types[use.value_id]
        port = compiler_input_ports[name]
        if not is_assignable(
            value_type,
            port.value_type,
        ):
            problems.append(
                _problem(
                    "semantic_domain_compiler_input_type_mismatch",
                    f"domain compiler input {name!r} is not assignable to its "
                    "declared port type",
                    *location,
                    "compiler_inputs",
                    name,
                )
            )
        if use.value_id in operation_results:
            problems.append(
                _problem(
                    "semantic_domain_compiler_input_stage_unavailable",
                    f"domain compiler input {name!r} must be available at plan stage",
                    *location,
                    "compiler_inputs",
                    name,
                )
            )


def _topological_operations(
    declared: tuple[SemanticOperation, ...],
    operation_results: Mapping[ValueId, SemanticOperation],
    problems: list[Problem],
) -> tuple[SemanticOperation, ...]:
    operations = {operation.id: operation for operation in declared}
    dependencies: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    dependents: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    for operation in declared:
        for _name, use in operation.inputs:
            producer_operation = operation_results.get(use.value_id)
            if producer_operation is None:
                continue
            producer = producer_operation.id
            dependencies[operation.id].add(producer)
            dependents[producer].add(operation.id)
    indegree = {
        operation_id: len(upstream) for operation_id, upstream in dependencies.items()
    }
    ready = [
        (operation_id.qualified_name, operation_id)
        for operation_id, count in indegree.items()
        if count == 0
    ]
    heapq.heapify(ready)
    ordered: list[SemanticOperation] = []
    while ready:
        _name, operation_id = heapq.heappop(ready)
        ordered.append(operations[operation_id])
        for dependent in sorted(
            dependents[operation_id], key=lambda item: item.qualified_name
        ):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, (dependent.qualified_name, dependent))
    if len(ordered) != len(operations):
        cyclic = sorted(
            (operation_id for operation_id, count in indegree.items() if count > 0),
            key=lambda item: item.qualified_name,
        )
        first = cyclic[0]
        problems.append(
            _problem(
                "semantic_operation_cycle",
                "semantic operation graph contains a cycle involving: "
                + ", ".join(item.qualified_name for item in cyclic),
                "operations",
                first.qualified_name,
            )
        )
        return tuple(sorted(declared, key=lambda item: item.id.qualified_name))
    return tuple(ordered)


def _problem(
    code: str,
    message: str,
    root: str,
    *path: str,
) -> Problem:
    return problem(
        code=code,
        phase=ProblemPhase.AUTHORING,
        message=message,
        location=model_location(root, *path),
    )
