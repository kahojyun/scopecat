"""Validate a concrete execution program against live driver descriptions."""

from __future__ import annotations

from collections.abc import Mapping

from scopecat._execution.program import (
    ApplyStateStage,
    CollectStage,
    ComputeStage,
    ExecutionProgram,
    ExecutionStage,
)
from scopecat.diagnostics import Diagnostic
from scopecat.instruments.sdk import (
    CollectProductRequest,
    InstrumentDescription,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    ProductDescription,
    validate_state_command,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.state import PayloadRef
from scopecat.units import compatible_units


def validate_execution_program_instruments(
    program: ExecutionProgram,
    *,
    descriptions: Mapping[str, InstrumentDescription],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for instrument_id in program.resource_order:
        if instrument_id not in descriptions:
            diagnostics.append(
                _diagnostic(
                    "missing_instrument_description",
                    f"instrument {instrument_id} did not provide a description",
                    f"instruments.{instrument_id}",
                )
            )
    for point in program.points:
        payloads = _payload_stubs(point.stages)
        for stage in point.stages:
            if isinstance(stage, ApplyStateStage):
                for operation in stage.operations:
                    description = descriptions.get(operation.instrument_id)
                    if description is None:
                        continue
                    fields = [
                        target.command_field(resource_id=operation.instrument_id)
                        for target in operation.targets
                    ]
                    diagnostics.extend(
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
            elif isinstance(stage, CollectStage):
                for operation in stage.operations:
                    description = descriptions.get(operation.instrument_id)
                    if description is None:
                        continue
                    for request in operation.command.requests:
                        product = _find_product(
                            description,
                            capability_id=request.capability_id,
                            product_key=request.id,
                        )
                        if product is None:
                            diagnostics.append(
                                _diagnostic(
                                    "instrument_product_unsupported",
                                    f"instrument {operation.instrument_id} does not "
                                    f"support product {request.id}",
                                    f"operations.{operation.operation_id}.{request.id}",
                                )
                            )
                            continue
                        diagnostics.extend(
                            _validate_product(
                                operation_id=operation.operation_id,
                                instrument_id=operation.instrument_id,
                                request=request,
                                product=product,
                            )
                        )
    return diagnostics


def _payload_stubs(stages: tuple[ExecutionStage, ...]) -> dict[str, CommandPayload]:
    payloads: dict[str, CommandPayload] = {}
    for stage in stages:
        if not isinstance(stage, ComputeStage):
            continue
        for operation in stage.operations:
            if operation.payload_slot is None:
                continue
            slot = operation.payload_slot
            payloads[slot.id] = CommandPayload(
                id=slot.id,
                schema_id=slot.schema_id,
                metadata={"operation_id": operation.operation_id},
                payload=object(),
            )
    return payloads


def _referenced_payloads(
    fields: list[InstrumentStateCommandField],
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


def _find_product(
    description: InstrumentDescription,
    *,
    capability_id: str | None,
    product_key: str,
) -> ProductDescription | None:
    for capability in description.capabilities:
        if capability_id is not None and capability.id != capability_id:
            continue
        for product in capability.products:
            if product.key == product_key:
                return product
    return None


def _validate_product(
    *,
    operation_id: str,
    instrument_id: str,
    request: CollectProductRequest,
    product: ProductDescription,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    path = f"operations.{operation_id}.{request.id}"
    if request.dtype != product.dtype:
        diagnostics.append(
            _diagnostic(
                "instrument_product_dtype_mismatch",
                f"instrument {instrument_id} product {product.key} dtype "
                f"{product.dtype!r} does not match requested "
                f"{request.dtype!r}",
                path,
            )
        )
    requested_unit = request.unit
    if (
        requested_unit is not None
        and product.unit is not None
        and not compatible_units(requested_unit, product.unit)
    ):
        diagnostics.append(
            _diagnostic(
                "instrument_product_unit_mismatch",
                f"instrument {instrument_id} product {product.key} unit "
                f"{product.unit!r} is incompatible with {requested_unit!r}",
                path,
            )
        )
    dimensions = request.dimensions
    if len(dimensions) != len(product.axes):
        diagnostics.append(
            _diagnostic(
                "instrument_product_axes_mismatch",
                f"instrument {instrument_id} product {product.key} axes do not match",
                path,
            )
        )
        return diagnostics
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
            diagnostics.append(
                _diagnostic(
                    "instrument_product_axis_mismatch",
                    f"instrument {instrument_id} product {product.key} axis "
                    f"{declared_axis.id!r} does not match the request",
                    f"{path}.axes.{index}",
                )
            )
    return diagnostics


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = ["validate_execution_program_instruments"]
