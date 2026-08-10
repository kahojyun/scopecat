"""Normalize and verify the dataflow fields of one logical program."""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence

from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import ValueType
from scopecat.program.logical import (
    AcquireEffect,
    LogicalComputeNode,
    LogicalDomainExecution,
    LogicalMeasurementPostprocessor,
    MeasurementPostprocessorId,
    ValueDef,
)
from scopecat.program.value_graph import OperationId


def verify_logical_graph(
    value_defs: Sequence[ValueDef],
    compute_nodes: Sequence[LogicalComputeNode],
    measurement_postprocessors: Sequence[LogicalMeasurementPostprocessor] = (),
    *,
    effects: Sequence[LogicalDomainExecution | AcquireEffect] = (),
) -> tuple[
    tuple[ValueDef, ...],
    tuple[LogicalComputeNode, ...],
    tuple[LogicalMeasurementPostprocessor, ...],
]:
    """Validate closure and normalize semantic dataflow."""

    definitions_in_order = tuple(value_defs)
    declared_compute_nodes = tuple(compute_nodes)
    declared_postprocessors = tuple(measurement_postprocessors)
    domain_executions = tuple(
        effect for effect in effects if isinstance(effect, LogicalDomainExecution)
    )
    acquisitions = tuple(
        effect for effect in effects if isinstance(effect, AcquireEffect)
    )
    problems: list[Problem] = []
    definitions = {definition.id: definition for definition in definitions_in_order}
    ambiguous_measurement_postprocessor_ids = _measurement_postprocessors_by_id(
        declared_postprocessors,
        problems,
    )
    operation_results = {
        operation.result_id: operation for operation in declared_compute_nodes
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
        for postprocessor in declared_postprocessors
        if postprocessor.id not in ambiguous_measurement_postprocessor_ids
    )
    ambiguous_product_ids = _verify_product_owners(
        acquisitions,
        domain_executions,
        unambiguous_measurement_postprocessors,
        problems,
    )
    ordered_measurement_postprocessors = _topological_measurement_postprocessors(
        unambiguous_measurement_postprocessors,
        problems,
        ambiguous_product_ids=ambiguous_product_ids,
    )
    ordered_operations = _topological_operations(
        declared_compute_nodes,
        operation_results,
        problems,
    )
    if problems:
        raise CheckFailed(problems)
    ordered_defs = tuple(
        sorted(definitions_in_order, key=lambda item: item.id.qualified_name)
    )
    return (
        ordered_defs,
        ordered_operations,
        ordered_measurement_postprocessors,
    )


def _measurement_postprocessors_by_id(
    postprocessors: tuple[LogicalMeasurementPostprocessor, ...],
    problems: list[Problem],
) -> frozenset[MeasurementPostprocessorId]:
    grouped: dict[
        MeasurementPostprocessorId,
        list[LogicalMeasurementPostprocessor],
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
                "logical_measurement_postprocessor_duplicate",
                "measurement postprocessor "
                f"{transform_id.qualified_name!r} is declared more than once",
                "measurement_postprocessors",
                transform_id.qualified_name,
            )
        )
    return ambiguous


def _verify_product_owners(
    acquisitions: tuple[AcquireEffect, ...],
    executions: tuple[LogicalDomainExecution, ...],
    postprocessors: tuple[LogicalMeasurementPostprocessor, ...],
    problems: list[Problem],
) -> frozenset[ProductId]:
    owners: dict[ProductId, tuple[str, str]] = {}
    ambiguous: set[ProductId] = set()
    for acquire in acquisitions:
        for result in acquire.results:
            existing = owners.get(result.product_id)
            if existing is not None:
                ambiguous.add(result.product_id)
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "logical_product_producer_duplicate",
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
                ambiguous.add(product_id)
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "logical_product_producer_duplicate",
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
                ambiguous.add(product_id)
                owner, owner_port = existing
                problems.append(
                    _problem(
                        "logical_product_producer_duplicate",
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
    return frozenset(ambiguous)


def _topological_measurement_postprocessors(
    postprocessors: tuple[LogicalMeasurementPostprocessor, ...],
    problems: list[Problem],
    *,
    ambiguous_product_ids: frozenset[ProductId],
) -> tuple[LogicalMeasurementPostprocessor, ...]:
    postprocessors_by_id = {
        postprocessor.id: postprocessor for postprocessor in postprocessors
    }
    owners_by_output: dict[ProductId, list[MeasurementPostprocessorId]] = {}
    for postprocessor in postprocessors:
        for _role, product_id in postprocessor.outputs:
            owners_by_output.setdefault(product_id, []).append(postprocessor.id)
    owner_by_output = {
        product_id: owners[0]
        for product_id, owners in owners_by_output.items()
        if len(owners) == 1 and product_id not in ambiguous_product_ids
    }
    dependencies: dict[MeasurementPostprocessorId, set[MeasurementPostprocessorId]] = {
        postprocessor.id: set() for postprocessor in postprocessors
    }
    dependents: dict[MeasurementPostprocessorId, set[MeasurementPostprocessorId]] = {
        postprocessor.id: set() for postprocessor in postprocessors
    }
    for postprocessor in postprocessors:
        for _name, input_product_id in postprocessor.inputs:
            producer = owner_by_output.get(input_product_id)
            if producer is None:
                continue
            dependencies[postprocessor.id].add(producer)
            dependents[producer].add(postprocessor.id)
    indegree = {
        postprocessor_id: len(upstream)
        for postprocessor_id, upstream in dependencies.items()
    }
    ready = [
        (postprocessor_id.qualified_name, postprocessor_id)
        for postprocessor_id, count in indegree.items()
        if count == 0
    ]
    heapq.heapify(ready)
    ordered: list[LogicalMeasurementPostprocessor] = []
    while ready:
        _name, postprocessor_id = heapq.heappop(ready)
        ordered.append(postprocessors_by_id[postprocessor_id])
        for dependent in sorted(
            dependents[postprocessor_id], key=lambda item: item.qualified_name
        ):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, (dependent.qualified_name, dependent))
    if len(ordered) == len(postprocessors):
        return tuple(ordered)
    cyclic = sorted(
        (postprocessor_id for postprocessor_id, count in indegree.items() if count > 0),
        key=lambda item: item.qualified_name,
    )
    first = cyclic[0]
    problems.append(
        _problem(
            "logical_measurement_postprocessor_cycle",
            "measurement postprocessor graph contains a cycle involving: "
            + ", ".join(item.qualified_name for item in cyclic),
            "measurement_postprocessors",
            first.qualified_name,
        )
    )
    return tuple(sorted(postprocessors, key=lambda item: item.id.qualified_name))


def _verify_domain_execution(
    execution: LogicalDomainExecution,
    value_types: Mapping[ValueId, ValueType],
    operation_results: Mapping[ValueId, LogicalComputeNode],
    problems: list[Problem],
    *,
    execution_index: int,
) -> None:
    program = execution.program
    location = ("domain_executions", str(execution_index))
    input_ports = {port.id: port for port in program.input_ports}
    for name, value_id in execution.inputs:
        value_type = value_types[value_id]
        port = input_ports[name]
        if not is_assignable(
            value_type,
            port.value_type,
        ):
            problems.append(
                _problem(
                    "logical_domain_execution_input_type_mismatch",
                    f"domain execution input {name!r} is not assignable to its "
                    "declared port type",
                    *location,
                    "inputs",
                    name,
                )
            )
        if value_id in operation_results:
            problems.append(
                _problem(
                    "logical_domain_execution_input_stage_unavailable",
                    f"domain execution input {name!r} must be available at plan stage",
                    *location,
                    "inputs",
                    name,
                )
            )
    compiler_input_ports = {port.id: port for port in program.compiler_input_ports}
    for name, value_id in execution.compiler_inputs:
        value_type = value_types[value_id]
        port = compiler_input_ports[name]
        if not is_assignable(
            value_type,
            port.value_type,
        ):
            problems.append(
                _problem(
                    "logical_domain_compiler_input_type_mismatch",
                    f"domain compiler input {name!r} is not assignable to its "
                    "declared port type",
                    *location,
                    "compiler_inputs",
                    name,
                )
            )
        if value_id in operation_results:
            problems.append(
                _problem(
                    "logical_domain_compiler_input_stage_unavailable",
                    f"domain compiler input {name!r} must be available at plan stage",
                    *location,
                    "compiler_inputs",
                    name,
                )
            )


def _topological_operations(
    declared: tuple[LogicalComputeNode, ...],
    operation_results: Mapping[ValueId, LogicalComputeNode],
    problems: list[Problem],
) -> tuple[LogicalComputeNode, ...]:
    operations = {operation.id: operation for operation in declared}
    dependencies: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    dependents: dict[OperationId, set[OperationId]] = {
        operation.id: set() for operation in declared
    }
    for operation in declared:
        for _name, value_id in operation.inputs:
            producer_operation = operation_results.get(value_id)
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
    ordered: list[LogicalComputeNode] = []
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
                "logical_operation_cycle",
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
