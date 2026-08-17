"""Validate an effect block against provider-advertised descriptions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    ComputeOperation,
    InvokeOperation,
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
from scopecat.kernel.value_types import Payload
from scopecat.kernel.value_validation import ValueValidationError, validate_literal
from scopecat.records.content import CommandPayload
from scopecat.sdk.instruments.commands import CollectResultRequest
from scopecat.sdk.instruments.contracts import (
    AcquisitionResultSpec,
    InstrumentDescription,
    OperationSpec,
    resolve_implementation_component,
    validate_state_assignments,
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
                        ApplyStateOperation | InvokeOperation | CollectOperation,
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
    payload_schemas = {
        payload_id: payload.schema_id
        for payload_id, payload in available_payloads.items()
    }
    payload_schemas.update(_payload_schemas(tuple(operations)))
    for operation in operations:
        if isinstance(operation, ApplyStateOperation):
            description = descriptions.get(operation.instrument_id)
            if description is None:
                continue
            assignments = [
                target.command_assignment(resource_id=operation.instrument_id)
                for target in operation.targets
            ]
            problems.extend(
                validate_state_assignments(
                    instrument_id=operation.instrument_id,
                    assignments=assignments,
                    description=description,
                )
            )
        elif isinstance(operation, CollectOperation):
            description = descriptions.get(operation.instrument_id)
            if description is None:
                continue
            for request in operation.command.requests:
                result = _matching_result(
                    description,
                    interface_id=request.interface_id,
                    component_path=request.component_path,
                    acquisition_id=request.acquisition_id,
                    result_id=request.result_id,
                )
                if result is None:
                    problems.append(
                        _problem(
                            "instrument_acquisition_result_unsupported",
                            f"instrument {operation.instrument_id} does not "
                            f"support acquisition result {request.result_id!r} "
                            f"under {request.interface_id!r}",
                            "operations",
                            operation.operation_id,
                            "requests",
                            request.id,
                        )
                    )
                    continue
                problems.extend(
                    _validate_result(
                        operation_id=operation.operation_id,
                        instrument_id=operation.instrument_id,
                        request=request,
                        result=result,
                    )
                )
        elif isinstance(operation, InvokeOperation):
            description = descriptions.get(operation.instrument_id)
            if description is None:
                continue
            operation_spec = _matching_operation(
                description,
                interface_id=operation.interface_id,
                component_path=operation.component_path,
                operation_id=operation.operation_id,
            )
            if operation_spec is None:
                problems.append(
                    _problem(
                        "instrument_operation_unsupported",
                        f"instrument {operation.instrument_id} does not support "
                        f"operation {operation.operation_id!r} under "
                        f"{operation.interface_id!r}",
                        "operations",
                        operation.effect_id,
                    )
                )
                continue
            problems.extend(
                _validate_invocation_arguments(
                    operation,
                    operation_spec,
                    payload_schemas=payload_schemas,
                )
            )
    return problems


def _payload_schemas(
    operations: tuple[LocalOperation, ...],
) -> dict[str, str]:
    schemas: dict[str, str] = {}
    for operation in operations:
        if not isinstance(operation, ComputeOperation):
            continue
        if operation.payload_slot is None:
            continue
        slot = operation.payload_slot
        schemas[slot.id] = slot.schema_id
    return schemas


def _matching_result(
    description: InstrumentDescription,
    *,
    interface_id: str,
    component_path: list[str],
    acquisition_id: str,
    result_id: str,
) -> AcquisitionResultSpec | None:
    selected_interface = next(
        (
            interface
            for interface in description.interfaces
            if interface.id == interface_id
        ),
        None,
    )
    if selected_interface is None:
        return None
    component = resolve_implementation_component(
        description,
        selected_interface,
        component_path,
    )
    if component is None:
        return None
    selected_acquisition = next(
        (
            acquisition
            for acquisition in component.acquisitions
            if acquisition.id == acquisition_id
        ),
        None,
    )
    if selected_acquisition is None:
        return None
    return next(
        (result for result in selected_acquisition.results if result.id == result_id),
        None,
    )


def _matching_operation(
    description: InstrumentDescription,
    *,
    interface_id: str,
    component_path: Sequence[str],
    operation_id: str,
) -> OperationSpec | None:
    selected_interface = next(
        (
            interface
            for interface in description.interfaces
            if interface.id == interface_id
        ),
        None,
    )
    if selected_interface is None:
        return None
    component = resolve_implementation_component(
        description,
        selected_interface,
        component_path,
    )
    if component is None:
        return None
    return next(
        (
            operation
            for operation in component.operations
            if operation.id == operation_id
        ),
        None,
    )


def _validate_invocation_arguments(
    invocation: InvokeOperation,
    operation: OperationSpec,
    *,
    payload_schemas: Mapping[str, str],
) -> list[Problem]:
    declared = {argument.id: argument for argument in operation.arguments}
    supplied = {argument.id: argument for argument in invocation.arguments}
    path = ("operations", invocation.effect_id, "arguments")
    problems: list[Problem] = []
    for argument_id in sorted(declared.keys() - supplied.keys()):
        problems.append(
            _problem(
                "instrument_operation_argument_missing",
                f"operation {operation.id!r} requires argument {argument_id!r}",
                *path,
                argument_id,
            )
        )
    for argument_id in sorted(supplied.keys() - declared.keys()):
        problems.append(
            _problem(
                "instrument_operation_argument_unsupported",
                f"operation {operation.id!r} does not accept argument {argument_id!r}",
                *path,
                argument_id,
            )
        )
    for argument_id in sorted(declared.keys() & supplied.keys()):
        value = supplied[argument_id].value.root
        value_type = declared[argument_id].value_type
        atom = value_type.atom
        if isinstance(atom, Payload):
            schema_id = (
                payload_schemas.get(value.payload_id)
                if isinstance(value, PayloadRef)
                else None
            )
            if schema_id != atom.schema_id:
                problems.append(
                    _problem(
                        "instrument_operation_argument_payload_mismatch",
                        f"operation argument {argument_id!r} requires payload "
                        f"{atom.schema_id!r}",
                        *path,
                        argument_id,
                    )
                )
            continue
        try:
            validate_literal(value_type, value)
        except ValueValidationError as error:
            problems.append(
                _problem(
                    "instrument_operation_argument_value_mismatch",
                    f"operation argument {argument_id!r}: {error.reason}",
                    *path,
                    argument_id,
                    *error.path,
                )
            )
    return problems


def _validate_result(
    *,
    operation_id: str,
    instrument_id: str,
    request: CollectResultRequest,
    result: AcquisitionResultSpec,
) -> list[Problem]:
    problems: list[Problem] = []
    path: tuple[LocationPathItem, ...] = (
        "operations",
        operation_id,
        "requests",
        request.id,
    )
    if request.dtype != result.dtype:
        problems.append(
            _problem(
                "instrument_acquisition_result_dtype_mismatch",
                f"instrument {instrument_id} acquisition result "
                f"{result.id} dtype {result.dtype!r} does not match requested "
                f"{request.dtype!r}",
                *path,
                "dtype",
            )
        )
    requested_unit = request.unit
    if requested_unit is not None and (
        result.unit is None or not compatible_units(requested_unit, result.unit)
    ):
        problems.append(
            _problem(
                "instrument_acquisition_result_unit_mismatch",
                f"instrument {instrument_id} acquisition result {result.id} unit "
                f"{result.unit!r} does not satisfy requested "
                f"unit {requested_unit!r}",
                *path,
                "unit",
            )
        )
    dimensions = request.dimensions
    if len(dimensions) != len(result.axes):
        problems.append(
            _problem(
                "instrument_acquisition_result_axes_mismatch",
                f"instrument {instrument_id} acquisition result "
                f"{result.id} axes do not match",
                *path,
                "dimensions",
            )
        )
        return problems
    for index, (requested_axis, declared_axis) in enumerate(
        zip(dimensions, result.axes, strict=True)
    ):
        if (
            requested_axis.id != declared_axis.id
            or requested_axis.kind != declared_axis.kind
            or (
                isinstance(declared_axis.size, int)
                and requested_axis.size != declared_axis.size
            )
        ):
            problems.append(
                _problem(
                    "instrument_acquisition_result_axis_mismatch",
                    f"instrument {instrument_id} acquisition result "
                    f"{result.id} axis "
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
                    "instrument_acquisition_result_axis_unit_mismatch",
                    f"instrument {instrument_id} acquisition result "
                    f"{result.id} axis "
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
