"""OO-first glue from declared Python interfaces to the driver protocol."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from inspect import Parameter
from typing import cast

from pydantic import JsonValue

from scopecat.records.measurement import MeasurementAcquisitionValue
from scopecat.sdk.instruments.authoring import (
    DriverAcquisition,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverScalar,
    DriverStatePatch,
    DriverStateReadback,
    DriverStateReadRequest,
    DriverSuccess,
    DriverUnknown,
    state_readback,
)
from scopecat.sdk.instruments.contracts import InstrumentDescription
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    DeclaredInterfaceLayout,
    DeclaredOperation,
    DeclaredStateField,
    compile_interface,
    declared_interface_layout,
)
from scopecat.sdk.instruments.members import (
    AcquisitionRef,
    OperationRef,
    PropertyRef,
)
from scopecat.sdk.problems import ProblemPhase, model_location, problem

_DRIVER_METADATA = "__scopecat_instrument_driver__"


@dataclass(frozen=True, slots=True)
class InstrumentDriverMetadata:
    implementation_id: str
    implementation_version: str
    interfaces: tuple[type[object], ...]
    label: str | None
    description: str | None


def instrument_driver[DriverT: type[object]](
    implementation_id: str,
    implementation_version: str,
    *,
    interfaces: Sequence[type[object]],
    label: str | None = None,
    description: str | None = None,
) -> Callable[[DriverT], DriverT]:
    """Bind an ordinary Python implementation class to declared interfaces."""

    metadata = InstrumentDriverMetadata(
        implementation_id=implementation_id,
        implementation_version=implementation_version,
        interfaces=tuple(interfaces),
        label=label,
        description=description,
    )

    def decorate(cls: DriverT) -> DriverT:
        setattr(cls, _DRIVER_METADATA, metadata)
        setattr(cls, "implementation_id", implementation_id)  # noqa: B010
        setattr(cls, "implementation_version", implementation_version)  # noqa: B010
        return cls

    return decorate


class ObjectInstrumentDriver:
    """Generic driver-protocol adapter for ordinary properties and methods.

    Concrete drivers implement the decorated interface as normal Python OO.
    Override a protocol method only when hardware requires batching, routing,
    or richer failure handling; declaration glue is deliberately not generated.
    """

    instrument_id: str  # pyright: ignore[reportUninitializedInstanceVariable]
    implementation_id: str  # pyright: ignore[reportUninitializedInstanceVariable]
    implementation_version: str  # pyright: ignore[reportUninitializedInstanceVariable]

    def declared_interfaces(self) -> tuple[type[object], ...]:
        return _driver_metadata(type(self)).interfaces

    def describe(self) -> InstrumentDescription:
        metadata = _driver_metadata(type(self))
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=metadata.implementation_id,
            implementation_version=metadata.implementation_version,
            label=metadata.label,
            description=metadata.description,
            interfaces=[
                compile_interface(interface_type).spec
                for interface_type in self.declared_interfaces()
            ],
        )

    def read_state(self, request: DriverStateReadRequest) -> DriverStateReadback:
        properties = _property_bindings(self.declared_interfaces())
        values: dict[PropertyRef, DriverScalar] = {}
        for target in request.targets:
            if not isinstance(target, PropertyRef):
                continue
            binding = properties.get(target)
            if binding is None:
                continue
            values[target] = cast("DriverScalar", getattr(self, binding.python_name))
        return state_readback(request, values)

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverStateReadback | None]:
        properties = _property_bindings(self.declared_interfaces())
        for assignment in request.entries:
            if not isinstance(assignment.target, PropertyRef):
                return _unsupported(
                    self.instrument_id,
                    "state_member",
                    assignment.target.property_id,
                )
            binding = properties.get(assignment.target)
            if binding is None or binding.spec.access != "read_write":
                return _unsupported(
                    self.instrument_id,
                    "state_member",
                    assignment.target.property_id,
                )
            setattr(self, binding.python_name, assignment.value)
        return DriverSuccess(None)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverStateReadback | None]:
        operation = _operation_bindings(self.declared_interfaces()).get(request.target)
        if operation is None:
            return _unsupported(
                self.instrument_id,
                "operation",
                request.target.operation_id,
            )
        outcome = _call_operation(self, operation, request.arguments)
        if isinstance(outcome, DriverSuccess):
            return DriverSuccess(None, metadata=outcome.metadata)
        if outcome is None:
            return DriverSuccess(None)
        return cast("DriverOutcome[DriverStateReadback | None]", outcome)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        acquisition = _acquisition_bindings(self.declared_interfaces()).get(
            request.target
        )
        if acquisition is None:
            return _unsupported(
                self.instrument_id,
                "acquisition",
                request.target.acquisition_id,
            )
        outcome = cast("object", getattr(self, acquisition.method_name)())
        outcome_metadata: dict[str, JsonValue] = {}
        if isinstance(outcome, DriverSuccess):
            result = cast("object", outcome.value)
            outcome_metadata = outcome.metadata
        elif isinstance(outcome, (DriverRejected, DriverUnknown)):
            return outcome
        else:
            result = outcome
        metadata = cast("dict[str, JsonValue]", getattr(result, "metadata", {}))
        values = {
            field.ref: cast(
                "MeasurementAcquisitionValue",
                getattr(result, field.python_name),
            )
            for field in acquisition.result_fields
            if field.ref in request.results
        }
        return DriverSuccess(
            DriverReadback(values=values, metadata=metadata),
            metadata=outcome_metadata,
        )

    def disconnect(self) -> None:
        """Release driver resources; resource-free implementations need no hook."""

    def abort(self) -> None:
        """Best-effort interruption; implementations override when supported."""


def _layouts(
    interfaces: Sequence[type[object]],
) -> tuple[DeclaredInterfaceLayout[object], ...]:
    return tuple(
        declared_interface_layout(compile_interface(interface_type))
        for interface_type in interfaces
    )


def _property_bindings(
    interfaces: Sequence[type[object]],
) -> dict[PropertyRef, DeclaredStateField]:
    return {
        field.ref: field
        for layout in _layouts(interfaces)
        if layout.state is not None
        for field in layout.state.fields
    }


def _operation_bindings(
    interfaces: Sequence[type[object]],
) -> dict[OperationRef, DeclaredOperation]:
    return {
        operation.ref: operation
        for layout in _layouts(interfaces)
        for operation in layout.root.operations
    }


def _acquisition_bindings(
    interfaces: Sequence[type[object]],
) -> dict[AcquisitionRef, DeclaredAcquisition[object]]:
    return {
        acquisition.ref: acquisition
        for layout in _layouts(interfaces)
        for acquisition in layout.root.acquisitions
    }


def _call_operation(
    driver: object,
    operation: DeclaredOperation,
    arguments: Mapping[str, object],
) -> object:
    positional: list[object] = []
    keywords: dict[str, object] = {}
    for argument in operation.arguments:
        value = arguments[argument.argument_id]
        if argument.parameter.kind is Parameter.POSITIONAL_ONLY:
            positional.append(value)
        else:
            keywords[argument.python_name] = value
    method = cast("Callable[..., object]", getattr(driver, operation.method_name))
    return method(*positional, **keywords)


def _driver_metadata(driver_type: type[object]) -> InstrumentDriverMetadata:
    metadata = getattr(driver_type, _DRIVER_METADATA, None)
    if not isinstance(metadata, InstrumentDriverMetadata):
        raise TypeError("object instrument driver is missing @instrument_driver")
    return metadata


def _unsupported(
    instrument_id: str,
    kind: str,
    member_id: str,
) -> DriverRejected:
    return DriverRejected(
        problems=(
            problem(
                f"instrument_{kind}_not_implemented",
                f"{instrument_id} does not implement {member_id}",
                phase=ProblemPhase.EXECUTION,
                location=model_location(f"driver_{kind}", member_id),
            ),
        )
    )


__all__ = [
    "InstrumentDriverMetadata",
    "ObjectInstrumentDriver",
    "instrument_driver",
]
