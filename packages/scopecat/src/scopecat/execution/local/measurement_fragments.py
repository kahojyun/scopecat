"""Adapt committed local collection chunks into neutral value fragments.

This module is the local counterpart of domain measurement ingress. It binds
the provider-addressed collection inventory to one selected logical fragment
before effects, then closes producer-neutral value entries from correlated
runtime chunks and receipts. The retained selection remains a control-plane
proof over the linked plan; runtime collection addresses do not enter values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from pydantic import JsonValue

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.typed.point_domain import LogicalPointId
from scopecat.execution.local.program import CollectStage, ExecutionProgram
from scopecat.execution.ports.journal import CollectionRepository
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.measurements.values import (
    ClosedMeasurementValueFragment,
    MeasurementValueCandidate,
    SelectedMeasurementValueAssembly,
    seal_measurement_value_fragment,
)
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
)


@dataclass(frozen=True, slots=True)
class _LocalCollectionOutputBinding:
    """One provider-addressed edge retained outside the neutral value plane."""

    provider_key: str
    product_use_id: ProductUseId
    product_id: ProductId


@dataclass(frozen=True, slots=True)
class _LocalCollectionOperationBinding:
    """One expected committed chunk and its canonical logical outputs."""

    logical_point_id: LogicalPointId
    point_index: int
    operation_id: str
    attempt: int
    instrument_id: str
    command_content_hash: str
    outputs: tuple[_LocalCollectionOutputBinding, ...]


@dataclass(frozen=True, slots=True)
class BoundLocalCollectionFragment:
    """Trusted transient binding from one local program to a value fragment."""

    selection: SelectedMeasurementValueAssembly = field(repr=False)
    experiment_id: str
    fragment_id: str
    collection_product_use_ids: tuple[ProductUseId, ...]
    _operations: tuple[_LocalCollectionOperationBinding, ...] = field(
        repr=False,
    )

    @property
    def operation_bindings(self) -> tuple[_LocalCollectionOperationBinding, ...]:
        """Return the snapshotted control-plane collection inventory."""

        return self._operations


def bind_local_collection_fragment(
    selection: SelectedMeasurementValueAssembly,
    fragment_id: str,
    program: ExecutionProgram,
) -> BoundLocalCollectionFragment:
    """Bind one local program's collection inventory to a value fragment.

    This proof gates value ingress after collection. It does not authorize the
    program's effects or prove state/compute context for the execution engine.
    """

    selected = selection

    problems: list[Problem] = []
    linked_experiment_id = selected.linked_points.linked_plan.program.id
    if program.experiment_id != linked_experiment_id:
        problems.append(
            _binding_problem(
                "local_collection_experiment_mismatch",
                "local execution program belongs to another linked experiment",
                path=("experiment_id",),
                category=ProblemCategory.CONFLICT,
                details={
                    "expected": linked_experiment_id,
                    "actual": program.experiment_id,
                },
            )
        )
    try:
        fragment = selected.fragment(fragment_id)
    except KeyError:
        problems.append(
            _binding_problem(
                "local_collection_fragment_missing",
                f"local collection references unknown fragment {fragment_id!r}",
                path=("fragment_id",),
                category=ProblemCategory.NOT_FOUND,
            )
        )
        fragment = None

    collection_use_ids = tuple(program.collection_product_use_ids)
    if fragment is not None and collection_use_ids != fragment.product_use_ids:
        problems.append(
            _binding_problem(
                "local_collection_fragment_inventory_mismatch",
                "local collection inventory does not exactly own the selected fragment",
                path=("collection_product_use_ids",),
                category=ProblemCategory.CONFLICT,
                details={
                    "expected": [item.value for item in fragment.product_use_ids],
                    "actual": [item.value for item in collection_use_ids],
                },
            )
        )

    linked_uses = {
        use.id: use for use in selected.linked_points.linked_plan.product_uses
    }
    program_uses = {use.id: use for use in program.product_uses}
    for use_index, use_id in enumerate(collection_use_ids):
        expected = linked_uses.get(use_id)
        retained = program_uses.get(use_id)
        if expected is None or retained is None:
            problems.append(
                _binding_problem(
                    "local_collection_product_use_missing",
                    f"collected product use {use_id.value!r} is not retained by "
                    "both linked and local programs",
                    path=("collection_product_use_ids", use_index),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
        elif retained != expected:
            problems.append(
                _binding_problem(
                    "local_collection_product_use_mismatch",
                    f"collected product use {use_id.value!r} changed its product",
                    path=("collection_product_use_ids", use_index),
                    category=ProblemCategory.CONFLICT,
                )
            )

    operations, operation_problems = _collect_program_contract(
        selected,
        program,
        collection_use_ids,
    )
    problems.extend(operation_problems)
    if problems:
        raise CheckFailed(problems)
    if fragment is None:
        raise AssertionError("successful local collection binding lost its fragment")

    return BoundLocalCollectionFragment(
        selected,
        program.experiment_id,
        fragment.id,
        collection_use_ids,
        operations,
    )


def local_collection_fragment(
    binding: BoundLocalCollectionFragment,
    *,
    run_id: str,
    repository: CollectionRepository,
    receipts: Sequence[CollectionChunkReceipt],
) -> ClosedMeasurementValueFragment:
    """Resolve committed chunks and close their exact logical value entries."""

    bound = binding
    if not run_id:
        msg = "local collection fragment run_id must be non-empty"
        raise ValueError(msg)
    resolver = getattr(repository, "resolve", None)
    if not callable(resolver):
        msg = "local collection fragments require a resolvable collection repository"
        raise TypeError(msg)
    supplied_receipts = tuple(receipts)

    operation_bindings = bound.operation_bindings
    operation_by_id = {
        operation.operation_id: operation for operation in operation_bindings
    }
    problems: list[Problem] = []
    chunks_by_operation: dict[str, CollectionChunk] = {}
    receipts_by_operation: dict[str, CollectionChunkReceipt] = {}
    first_receipt_index: dict[str, int] = {}
    for receipt_index, candidate in enumerate(supplied_receipts):
        try:
            receipt = CollectionChunkReceipt.model_validate(
                candidate.model_dump(mode="python", warnings=False)
            )
        except (TypeError, ValueError) as error:
            problems.append(
                _runtime_problem(
                    "local_collection_receipt_invalid",
                    "durable local collection receipt is invalid",
                    path=("receipts", receipt_index),
                    details={"error_type": type(error).__name__},
                )
            )
            continue
        expected = operation_by_id.get(receipt.operation_id)
        if receipt.operation_id in receipts_by_operation:
            problems.append(
                _runtime_problem(
                    "local_collection_receipt_duplicate",
                    f"collection receipt {receipt.operation_id!r} is repeated",
                    path=("receipts", receipt_index, "operation_id"),
                    category=ProblemCategory.CONFLICT,
                    details={
                        "first_receipt_index": first_receipt_index[receipt.operation_id]
                    },
                )
            )
            continue
        receipts_by_operation[receipt.operation_id] = receipt
        first_receipt_index[receipt.operation_id] = receipt_index
        if expected is None:
            problems.append(
                _runtime_problem(
                    "local_collection_receipt_unexpected",
                    f"collection receipt {receipt.operation_id!r} is not bound",
                    path=("receipts", receipt_index, "operation_id"),
                )
            )
            continue
        try:
            chunk = _normalize_resolved_chunk(repository.resolve(receipt))
        except Exception as error:
            problems.append(
                _runtime_problem(
                    "local_collection_receipt_unresolvable",
                    "collection receipt could not resolve its durable chunk",
                    path=("receipts", receipt_index, "ref"),
                    category=ProblemCategory.STORAGE,
                    details={"error_type": type(error).__name__},
                )
            )
            continue
        chunks_by_operation[receipt.operation_id] = chunk
        _validate_chunk(
            chunk,
            expected,
            run_id=run_id,
            receipt_index=receipt_index,
            problems=problems,
        )
        _validate_chunk_receipt_correlation(
            chunk,
            receipt,
            receipt_index=receipt_index,
            problems=problems,
        )

    for operation in operation_bindings:
        receipt = receipts_by_operation.get(operation.operation_id)
        if receipt is None:
            problems.append(
                _runtime_problem(
                    "local_collection_receipt_missing",
                    f"bound collection operation {operation.operation_id!r} has no "
                    "durable commit receipt",
                    path=("receipts", operation.operation_id),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
    if problems:
        raise ProviderContractError(problems)

    candidates = tuple(
        MeasurementValueCandidate(
            logical_point_id=operation.logical_point_id,
            product_use_id=output.product_use_id,
            value=chunks_by_operation[operation.operation_id].readback.values[
                output.provider_key
            ],
        )
        for operation in operation_bindings
        for output in operation.outputs
    )
    return seal_measurement_value_fragment(
        bound.selection,
        bound.fragment_id,
        candidates,
    )


def _collect_program_contract(
    selection: SelectedMeasurementValueAssembly,
    program: ExecutionProgram,
    collection_use_ids: tuple[ProductUseId, ...],
) -> tuple[tuple[_LocalCollectionOperationBinding, ...], tuple[Problem, ...]]:
    points = selection.linked_points.point_domain.points
    problems: list[Problem] = []
    operations: list[_LocalCollectionOperationBinding] = []
    operation_ids: set[str] = set()
    if len(program.points) != len(points):
        problems.append(
            _binding_problem(
                "local_collection_point_inventory_mismatch",
                "local execution point inventory does not match linked points",
                path=("points",),
                category=ProblemCategory.CONFLICT,
                details={"expected": len(points), "actual": len(program.points)},
            )
        )

    use_order = {use_id: index for index, use_id in enumerate(collection_use_ids)}
    selected_use_ids = set(selection.product_use_ids)
    product_by_use = {
        use_id: selection.product_for_use(use_id)
        for use_id in collection_use_ids
        if use_id in selected_use_ids
    }
    for point_index, (point, point_program) in enumerate(
        zip(points, program.points, strict=False)
    ):
        expected_coordinates = {
            coordinate_id: point.row[coordinate_id]
            for coordinate_id in point_program.coordinates
        }
        if (
            point_program.point_index != point.logical_ordinal
            or point_program.point_uid != point.logical_id.value
        ):
            problems.append(
                _binding_problem(
                    "local_collection_point_identity_mismatch",
                    "local execution point does not retain its exact logical identity",
                    path=("points", point_index),
                    category=ProblemCategory.CONFLICT,
                )
            )
        if dict(point_program.coordinates) != expected_coordinates:
            problems.append(
                _binding_problem(
                    "local_collection_point_coordinates_mismatch",
                    "local execution point coordinates do not match the linked row",
                    path=("points", point_index, "coordinates"),
                    category=ProblemCategory.CONFLICT,
                )
            )

        point_outputs: dict[ProductUseId, _LocalCollectionOutputBinding] = {}
        point_operations: list[_LocalCollectionOperationBinding] = []
        collect_operations = tuple(
            operation
            for stage in point_program.stages
            if isinstance(stage, CollectStage)
            for operation in stage.operations
        )
        for operation_index, operation in enumerate(collect_operations):
            path = ("points", point_index, "collection", operation_index)
            if operation.operation_id in operation_ids:
                problems.append(
                    _binding_problem(
                        "local_collection_operation_duplicate",
                        f"collection operation {operation.operation_id!r} is repeated",
                        path=(*path, "operation_id"),
                        category=ProblemCategory.CONFLICT,
                    )
                )
            operation_ids.add(operation.operation_id)
            command = operation.command
            if (
                command.operation_id != operation.operation_id
                or command.instrument_id != operation.instrument_id
                or command.attempt != 1
                or command.point_index != point.logical_ordinal
                or command.point_count != len(points)
            ):
                problems.append(
                    _binding_problem(
                        "local_collection_command_contract_mismatch",
                        "collection command does not retain its operation, instrument, "
                        "initial attempt, and point contract",
                        path=(*path, "command"),
                        category=ProblemCategory.CONFLICT,
                    )
                )
            requests = tuple(command.requests)
            result_bindings = tuple(operation.result_bindings)
            request_keys = tuple(request.id for request in requests)
            binding_keys = tuple(binding.provider_key for binding in result_bindings)
            if request_keys != binding_keys or len(set(request_keys)) != len(
                request_keys
            ):
                problems.append(
                    _binding_problem(
                        "local_collection_result_inventory_mismatch",
                        "collection requests and result bindings do not form one exact "
                        "provider-key inventory",
                        path=(*path, "result_bindings"),
                        category=ProblemCategory.CONFLICT,
                    )
                )

            output_bindings: list[_LocalCollectionOutputBinding] = []
            for result_index, (request, result) in enumerate(
                zip(requests, result_bindings, strict=False)
            ):
                result_path = (*path, "result_bindings", result_index)
                if result.product_use_id not in use_order:
                    problems.append(
                        _binding_problem(
                            "local_collection_result_use_unexpected",
                            f"collection result owns unexpected product use "
                            f"{result.product_use_id.value!r}",
                            path=(*result_path, "product_use_id"),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
                    continue
                if result.product_use_id in point_outputs:
                    problems.append(
                        _binding_problem(
                            "local_collection_result_use_duplicate",
                            f"point collects product use "
                            f"{result.product_use_id.value!r} more than once",
                            path=(*result_path, "product_use_id"),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
                    continue
                product = product_by_use.get(result.product_use_id)
                retained_use = selection.product_use(result.product_use_id)
                if product is None or result.product_id != retained_use.product_id:
                    problems.append(
                        _binding_problem(
                            "local_collection_result_product_mismatch",
                            "collection result changed its logical product identity",
                            path=(*result_path, "product_id"),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
                    continue
                if not _request_matches_product(request, product):
                    problems.append(
                        _binding_problem(
                            "local_collection_request_contract_mismatch",
                            f"collection request for use "
                            f"{result.product_use_id.value!r} does not exactly retain "
                            "its dtype, unit, and axes",
                            path=(*path, "command", "requests", result_index),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
                output = _LocalCollectionOutputBinding(
                    result.provider_key,
                    result.product_use_id,
                    result.product_id,
                )
                point_outputs[result.product_use_id] = output
                output_bindings.append(output)
            point_operations.append(
                _LocalCollectionOperationBinding(
                    logical_point_id=point.logical_id,
                    point_index=point.logical_ordinal,
                    operation_id=operation.operation_id,
                    attempt=command.attempt,
                    instrument_id=operation.instrument_id,
                    command_content_hash=stable_content_hash(
                        command.model_dump(mode="json", warnings=False)
                    ),
                    outputs=tuple(
                        sorted(
                            output_bindings,
                            key=lambda item: use_order[item.product_use_id],
                        )
                    ),
                )
            )
        if set(point_outputs) != set(collection_use_ids):
            problems.append(
                _binding_problem(
                    "local_collection_point_output_inventory_mismatch",
                    "local point does not exactly collect the selected fragment uses",
                    path=("points", point_index, "collection"),
                    category=ProblemCategory.CONFLICT,
                    details={
                        "expected": [item.value for item in collection_use_ids],
                        "actual": [
                            item.value
                            for item in collection_use_ids
                            if item in point_outputs
                        ],
                    },
                )
            )
        operations.extend(
            sorted(point_operations, key=lambda operation: operation.operation_id)
        )
    return tuple(operations), tuple(problems)


def _normalize_resolved_chunk(value: object) -> CollectionChunk:
    if not isinstance(value, CollectionChunk):
        msg = "collection repository returned a non-CollectionChunk value"
        raise TypeError(msg)
    return CollectionChunk.model_validate(
        value.model_dump(mode="python", warnings=False)
    )


def _validate_chunk(
    chunk: CollectionChunk,
    expected: _LocalCollectionOperationBinding,
    *,
    run_id: str,
    receipt_index: int,
    problems: list[Problem],
) -> None:
    path = ("receipts", receipt_index, "chunk")
    checks = (
        (
            chunk.operation_id == expected.operation_id,
            "local_collection_chunk_operation_mismatch",
            "resolved collection chunk belongs to another operation",
            "operation_id",
        ),
        (
            chunk.run_id == run_id,
            "local_collection_chunk_run_mismatch",
            "collection chunk belongs to another run",
            "run_id",
        ),
        (
            chunk.attempt == expected.attempt,
            "local_collection_chunk_attempt_mismatch",
            "collection chunk attempt does not match its bound command",
            "attempt",
        ),
        (
            chunk.point_index == expected.point_index,
            "local_collection_chunk_point_mismatch",
            "collection chunk belongs to another logical point",
            "point_index",
        ),
        (
            chunk.instrument_id == expected.instrument_id,
            "local_collection_chunk_instrument_mismatch",
            "collection chunk belongs to another instrument",
            "instrument_id",
        ),
        (
            chunk.command_content_hash == expected.command_content_hash,
            "local_collection_chunk_command_mismatch",
            "collection chunk was produced by another command contract",
            "command_content_hash",
        ),
    )
    for valid, code, message, field_name in checks:
        if not valid:
            problems.append(_runtime_problem(code, message, path=(*path, field_name)))
    expected_keys = {output.provider_key for output in expected.outputs}
    actual_keys = set(chunk.readback.values)
    if actual_keys != expected_keys:
        problems.append(
            _runtime_problem(
                "local_collection_chunk_readback_inventory_mismatch",
                "collection chunk readback keys do not exactly match its bound "
                "provider outputs",
                path=(*path, "readback", "values"),
                details=cast(
                    "Mapping[str, JsonValue]",
                    {
                        "expected": sorted(expected_keys),
                        "actual": sorted(actual_keys),
                    },
                ),
            )
        )


def _validate_chunk_receipt_correlation(
    chunk: CollectionChunk,
    receipt: CollectionChunkReceipt,
    *,
    receipt_index: int,
    problems: list[Problem],
) -> None:
    path = ("receipts", receipt_index)
    if receipt.content_hash != chunk.content_hash:
        problems.append(
            _runtime_problem(
                "local_collection_receipt_chunk_mismatch",
                "collection receipt does not cover the exact resolved chunk",
                path=(*path, "content_hash"),
            )
        )


def _request_matches_product(request: object, product: object) -> bool:
    from scopecat.compiler.typed.products import ProductDef
    from scopecat.sdk.instruments.contracts import CollectProductRequest

    if not isinstance(request, CollectProductRequest) or not isinstance(
        product, ProductDef
    ):
        return False
    axes = tuple(
        (axis.id, axis.kind, axis.size, axis.unit, dict(axis.metadata))
        for axis in request.dimensions
    )
    expected_axes = tuple(
        (axis.id, axis.kind, axis.size, axis.unit, dict(axis.metadata))
        for axis in product.axes
    )
    return (
        request.dtype == product.dtype
        and request.unit == product.unit
        and axes == expected_axes
    )


def _binding_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location("local_collection_fragment", *path),
        category=category,
        details=details,
    )


def _runtime_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    category: ProblemCategory = ProblemCategory.PROVIDER_CONTRACT,
    details: Mapping[str, JsonValue] | None = None,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.EXECUTION,
        location=model_location("local_collection_fragment", *path),
        details=details,
    )


__all__ = [
    "BoundLocalCollectionFragment",
    "bind_local_collection_fragment",
    "local_collection_fragment",
]
