"""Validate instrument readbacks and normalize effect receipts."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, JsonValue

from scopecat.execution.local.program import CollectOperation
from scopecat.kernel.content_identity import (
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.measurements.contracts import (
    MeasurementValueContractIssueCode,
    measurement_value_contract_issues,
)
from scopecat.records.execution_journal import CollectionChunk, CollectionChunkReceipt
from scopecat.records.instrument import InstrumentReadback
from scopecat.sdk.instruments.contracts import (
    ActionReceipt,
    ApplyReceipt,
    CollectReceipt,
)


def validate_readback(
    operation: CollectOperation,
    readback: InstrumentReadback,
) -> list[Problem]:
    problems: list[Problem] = []
    requests = {request.id: request for request in operation.command.requests}
    for product_id in sorted(set(requests) - set(readback.values)):
        problems.append(
            _readback_problem(
                "instrument_missing_product",
                f"instrument {operation.instrument_id} did not return "
                f"requested product {product_id}",
                product_id,
            )
        )
    for product_id in sorted(set(readback.values) - set(requests)):
        problems.append(
            _readback_problem(
                "instrument_unexpected_product",
                f"instrument {operation.instrument_id} returned unexpected "
                f"product {product_id}",
                product_id,
            )
        )
    for product_id in sorted(set(requests) & set(readback.values)):
        request = requests[product_id]
        value = readback.values[product_id]
        expected_shape = [axis.size for axis in request.dimensions]
        for issue in measurement_value_contract_issues(
            value,
            expected_dtype=request.dtype,
            expected_unit=request.unit,
            expected_shape=expected_shape,
        ):
            if issue.code is MeasurementValueContractIssueCode.DTYPE_MISMATCH:
                problems.append(
                    _readback_problem(
                        "instrument_readback_dtype_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"returned {issue.actual}, expected {issue.expected}",
                        product_id,
                        "dtype",
                    )
                )
            elif issue.code is MeasurementValueContractIssueCode.UNIT_MISMATCH:
                problems.append(
                    _readback_problem(
                        "instrument_readback_unit_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"returned unit {issue.actual!r}, expected "
                        f"{issue.expected!r}-compatible units",
                        product_id,
                        "unit",
                    )
                )
            elif issue.code is MeasurementValueContractIssueCode.SHAPE_MISMATCH:
                actual_shape = list(cast("tuple[int, ...]", issue.actual))
                expected_contract_shape = list(cast("tuple[int, ...]", issue.expected))
                problems.append(
                    _readback_problem(
                        "instrument_readback_shape_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"returned shape {actual_shape}, "
                        f"expected {expected_contract_shape}",
                        product_id,
                        "shape",
                    )
                )
            elif (
                issue.code is MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH
            ):
                value_path = ".".join(str(item) for item in issue.path)
                problems.append(
                    _readback_problem(
                        "instrument_readback_shape_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"array {value_path} has structure {issue.actual!r}, "
                        f"expected {issue.expected!r}",
                        product_id,
                        *issue.path,
                    )
                )
            else:
                value_path = ".".join(str(item) for item in issue.path)
                problems.append(
                    _readback_problem(
                        "instrument_readback_value_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"value {value_path} violates {issue.code.value}: expected "
                        f"{issue.expected!r}, got {issue.actual!r}",
                        product_id,
                        *issue.path,
                    )
                )
    return problems


def command_evidence(command: BaseModel) -> dict[str, JsonValue]:
    envelope = command.model_dump(mode="json")
    return {
        "command": envelope,
        "command_content_hash": stable_content_hash(envelope),
    }


def apply_receipt_evidence(receipt: ApplyReceipt) -> dict[str, JsonValue]:
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def action_receipt_evidence(receipt: ActionReceipt) -> dict[str, JsonValue]:
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def collect_receipt_evidence(receipt: CollectReceipt) -> dict[str, JsonValue]:
    if receipt.status == "collected":
        return {
            "receipt_status": receipt.status,
            **({"receipt_metadata": receipt.metadata} if receipt.metadata else {}),
        }
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def validate_collection_chunk_receipt(
    value: object,
    *,
    chunk: CollectionChunk,
) -> CollectionChunkReceipt:
    if not isinstance(value, CollectionChunkReceipt):
        msg = (
            "collection repository must return CollectionChunkReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    receipt = CollectionChunkReceipt.model_validate(value.model_dump(mode="json"))
    if (
        receipt.operation_id != chunk.operation_id
        or receipt.content_hash != chunk.content_hash
    ):
        msg = "collection receipt does not cover its exact committed chunk"
        raise ValueError(msg)
    return receipt


def normalize_apply_receipt(value: object) -> ApplyReceipt:
    if not isinstance(value, ApplyReceipt):
        msg = (
            "instrument apply_state must return ApplyReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return ApplyReceipt.model_validate(value.model_dump(mode="json"))


def normalize_action_receipt(value: object) -> ActionReceipt:
    if not isinstance(value, ActionReceipt):
        msg = (
            "instrument action must return ActionReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return ActionReceipt.model_validate(value.model_dump(mode="json"))


def normalize_collect_receipt(value: object) -> CollectReceipt:
    if not isinstance(value, CollectReceipt):
        msg = (
            "instrument collect must return CollectReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return CollectReceipt.model_validate(value.model_dump(mode="json"))


def _readback_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument_readback", "values", *path),
    )
