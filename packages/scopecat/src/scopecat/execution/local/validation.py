"""Validate a local effect block against live driver descriptions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    ComputeOperation,
    LocalOperation,
)
from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.state import PayloadRef
from scopecat.kernel.units import compatible_units
from scopecat.records.artifact import CommandPayload
from scopecat.sdk.instruments.contracts import (
    CollectProductRequest,
    InstrumentDescription,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    ProductDescription,
    validate_state_command,
)


def validate_local_effect_block_instruments(
    *,
    resource_order: Sequence[str],
    operations: Sequence[LocalOperation],
    descriptions: Mapping[str, InstrumentDescription],
    available_payloads: Mapping[str, CommandPayload],
) -> list[Problem]:
    problems: list[Problem] = []
    required_instruments = tuple(
        dict.fromkeys(
            (
                *resource_order,
                *(
                    operation.instrument_id
                    for operation in operations
                    if isinstance(
                        operation,
                        ApplyStateOperation | CollectOperation,
                    )
                ),
            )
        )
    )
    for instrument_id in required_instruments:
        if instrument_id not in descriptions:
            problems.append(
                _problem(
                    "missing_instrument_description",
                    f"instrument {instrument_id} did not provide a description",
                    "instruments",
                    instrument_id,
                    "description",
                )
            )
    payloads = {**available_payloads, **_payload_stubs(tuple(operations))}
    for operation in operations:
        if isinstance(operation, ApplyStateOperation):
            description = descriptions.get(operation.instrument_id)
            if description is None:
                continue
            fields = [
                target.command_field(resource_id=operation.instrument_id)
                for target in operation.targets
            ]
            problems.extend(
                validate_state_command(
                    command=InstrumentStateCommand(
                        operation_id=operation.operation_id,
                        instrument_id=operation.instrument_id,
                        fields=fields,
                        payloads=_referenced_payloads(fields, payloads),
                    ),
                    description=description,
                    payloads=payloads,
                )
            )
        elif isinstance(operation, CollectOperation):
            description = descriptions.get(operation.instrument_id)
            if description is None:
                continue
            for request in operation.command.requests:
                product = _matching_product(
                    description,
                    capability_id=request.capability_id,
                    product_key=request.id,
                )
                if product is None:
                    problems.append(
                        _problem(
                            "instrument_product_unsupported",
                            f"instrument {operation.instrument_id} does not "
                            f"support product {request.id} under capability "
                            f"{request.capability_id!r}",
                            "operations",
                            operation.operation_id,
                            "requests",
                            request.id,
                        )
                    )
                    continue
                problems.extend(
                    _validate_product(
                        operation_id=operation.operation_id,
                        instrument_id=operation.instrument_id,
                        request=request,
                        product=product,
                    )
                )
    return problems


def _payload_stubs(
    operations: tuple[LocalOperation, ...],
) -> dict[str, CommandPayload]:
    payloads: dict[str, CommandPayload] = {}
    for operation in operations:
        if not isinstance(operation, ComputeOperation):
            continue
        if operation.payload_slot is None:
            continue
        slot = operation.payload_slot
        payloads[slot.id] = CommandPayload(
            id=slot.id,
            schema_id=slot.schema_id,
            operation_id=operation.operation_id,
            payload=object(),
        )
    return payloads


def _referenced_payloads(
    fields: Sequence[InstrumentStateCommandField],
    payloads: Mapping[str, CommandPayload],
) -> dict[str, CommandPayload]:
    selected: dict[str, CommandPayload] = {}
    for field in fields:
        value = field.value.root
        if not isinstance(value, PayloadRef):
            continue
        payload = payloads.get(value.payload_id)
        if payload is not None:
            selected[payload.id] = payload
    return selected


def _matching_product(
    description: InstrumentDescription,
    *,
    capability_id: str,
    product_key: str,
) -> ProductDescription | None:
    selected_capability = next(
        (
            capability
            for capability in description.capabilities
            if capability.id == capability_id
        ),
        None,
    )
    if selected_capability is None:
        return None
    return next(
        (
            product
            for product in selected_capability.products
            if product.key == product_key
        ),
        None,
    )


def _validate_product(
    *,
    operation_id: str,
    instrument_id: str,
    request: CollectProductRequest,
    product: ProductDescription,
) -> list[Problem]:
    problems: list[Problem] = []
    path: tuple[LocationPathItem, ...] = (
        "operations",
        operation_id,
        "requests",
        request.id,
    )
    if request.dtype != product.dtype:
        problems.append(
            _problem(
                "instrument_product_dtype_mismatch",
                f"instrument {instrument_id} product {product.key} dtype "
                f"{product.dtype!r} does not match requested "
                f"{request.dtype!r}",
                *path,
                "dtype",
            )
        )
    requested_unit = request.unit
    if requested_unit is not None and (
        product.unit is None or not compatible_units(requested_unit, product.unit)
    ):
        problems.append(
            _problem(
                "instrument_product_unit_mismatch",
                f"instrument {instrument_id} product {product.key} unit "
                f"{product.unit!r} does not satisfy requested "
                f"unit {requested_unit!r}",
                *path,
                "unit",
            )
        )
    dimensions = request.dimensions
    if len(dimensions) != len(product.axes):
        problems.append(
            _problem(
                "instrument_product_axes_mismatch",
                f"instrument {instrument_id} product {product.key} axes do not match",
                *path,
                "dimensions",
            )
        )
        return problems
    for index, (requested_axis, declared_axis) in enumerate(
        zip(dimensions, product.axes, strict=True)
    ):
        if (
            requested_axis.id != declared_axis.id
            or requested_axis.kind != declared_axis.kind
            or (
                declared_axis.size is not None
                and requested_axis.size != declared_axis.size
            )
        ):
            problems.append(
                _problem(
                    "instrument_product_axis_mismatch",
                    f"instrument {instrument_id} product {product.key} axis "
                    f"{declared_axis.id!r} does not match the request",
                    *path,
                    "axes",
                    index,
                )
            )
        requested_axis_unit = requested_axis.unit
        if requested_axis_unit is not None and (
            declared_axis.unit is None
            or not compatible_units(requested_axis_unit, declared_axis.unit)
        ):
            problems.append(
                _problem(
                    "instrument_product_axis_unit_mismatch",
                    f"instrument {instrument_id} product {product.key} axis "
                    f"{requested_axis.id!r} unit {declared_axis.unit!r} does not "
                    f"satisfy requested unit {requested_axis_unit!r}",
                    *path,
                    "axes",
                    index,
                    "unit",
                )
            )
    return problems


def _problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=model_location("execution_program", *path),
    )
