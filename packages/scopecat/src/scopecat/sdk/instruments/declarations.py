"""Typed Python declarations for instrument interface contracts.

The decorators in this module only attach declaration metadata. They leave the
decorated dataclasses and methods unchanged so Python type checkers continue to
see the authored API. :func:`compile_interface` is the explicit boundary that
lowers those declarations to the existing :class:`InterfaceSpec` contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from inspect import Parameter, signature
from types import NoneType, UnionType
from typing import (
    Annotated,
    Literal,
    TypeAliasType,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from scopecat.kernel.instrument_members import (
    AcquisitionRef,
    AcquisitionResultRef,
    ComponentRef,
    InterfaceRef,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Bool as BoolType
from scopecat.kernel.value_types import Float as FloatType
from scopecat.kernel.value_types import Int as IntType
from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_types import String as StringType
from scopecat.measurements.results import MeasurementDType
from scopecat.program.state import StateBinding
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments.contracts import (
    AcquisitionAxisSpec,
    AcquisitionPreconditionSpec,
    AcquisitionResultSpec,
    AcquisitionSpec,
    ComponentSpec,
    DiscriminatedState,
    InterfaceSpec,
    OperationArgumentSpec,
    OperationSpec,
    PropertySpec,
)
from scopecat.sdk.instruments.contracts import (
    acquisition as build_acquisition,
)
from scopecat.sdk.instruments.contracts import (
    acquisition_axis as build_acquisition_axis,
)
from scopecat.sdk.instruments.contracts import (
    acquisition_case as build_acquisition_case,
)
from scopecat.sdk.instruments.contracts import (
    acquisition_precondition as build_acquisition_precondition,
)
from scopecat.sdk.instruments.contracts import (
    acquisition_result as build_acquisition_result,
)
from scopecat.sdk.instruments.contracts import component as build_component
from scopecat.sdk.instruments.contracts import (
    discriminated_state as build_discriminated_state,
)
from scopecat.sdk.instruments.contracts import (
    interface as build_interface,
)
from scopecat.sdk.instruments.contracts import operation as build_operation
from scopecat.sdk.instruments.contracts import (
    operation_argument as build_operation_argument,
)
from scopecat.sdk.instruments.contracts import state_case as build_state_case
from scopecat.sdk.instruments.contracts import (
    state_discriminated_acquisition as build_state_discriminated_acquisition,
)

type PropertyAccess = Literal["read_only", "write_only", "read_write"]
type PreconditionValue = bool | int | float | str | Quantity

_STATE_METADATA = "__scopecat_instrument_state__"
_OBSERVED_STATE_METADATA = "__scopecat_instrument_observed_state__"
_RESULT_METADATA = "__scopecat_instrument_result__"
_INTERFACE_METADATA = "__scopecat_instrument_interface__"
_ACQUISITION_METADATA = "__scopecat_instrument_acquisition__"
_OPERATION_METADATA = "__scopecat_instrument_operation__"
_STATE_INTERFACES_METADATA = "__scopecat_instrument_state_interfaces__"
_STATE_BINDINGS_METADATA = "__scopecat_instrument_state_bindings__"


@dataclass(frozen=True, slots=True)
class MemberMetadata:
    """Metadata that cannot be inferred from a state field annotation."""

    id: str | None = None
    label: str | None = None
    description: str | None = None
    access: PropertyAccess = "read_write"
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ResultMetadata:
    """Metadata for one field of a decorated acquisition result dataclass."""

    id: str | None = None
    dtype: MeasurementDType | None = None
    unit: str | None = None
    axes: tuple[str, ...] = ()
    label: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ArgumentMetadata:
    """Metadata for one typed atomic-operation parameter."""

    id: str | None = None
    label: str | None = None
    description: str | None = None
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    payload_schema_id: str | None = None


@dataclass(frozen=True, slots=True)
class ComponentMetadata:
    """One named occurrence of a nested typed capability."""

    id: str | None = None
    label: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class StateFieldReference:
    """A deferred property reference addressed by a typed state field."""

    state_type: type[object]
    field_name: str


@dataclass(frozen=True, slots=True)
class DiscriminatorReference:
    """A deferred reference to one declared interface's state discriminator."""

    interface_type: type[object]


type DeclaredPropertyTarget = PropertyRef | StateFieldReference | DiscriminatorReference
type AxisSize = int | str | StateFieldReference


@dataclass(frozen=True, slots=True)
class AxisMetadata:
    """One acquisition axis, with either a fixed or state-owned size."""

    size: AxisSize
    kind: str | None = None
    unit: str | None = None
    label: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class StateCaseMetadata:
    value: str
    state_type: type[object]
    fields: tuple[str, ...]
    required_on_entry: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscriminatedStateMetadata:
    discriminator: MemberMetadata
    common_state: type[object]
    cases: tuple[StateCaseMetadata, ...]


type StateMetadata = type[object] | DiscriminatedStateMetadata


@dataclass(frozen=True, slots=True)
class InterfaceMetadata:
    id: str
    state: StateMetadata | None
    observed_state: type[object] | None
    label: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class PreconditionMetadata:
    property: DeclaredPropertyTarget
    value: PreconditionValue
    unavailable_reason: str


@dataclass(frozen=True, slots=True)
class AcquisitionCaseMetadata:
    value: str
    result_type: type[object]
    preconditions: tuple[PreconditionMetadata, ...]


@dataclass(frozen=True, slots=True)
class AcquisitionMetadata:
    id: str | None
    axes: tuple[tuple[str, AxisMetadata], ...]
    label: str | None
    description: str | None
    preconditions: tuple[PreconditionMetadata, ...]
    discriminator: DeclaredPropertyTarget | None
    cases: tuple[AcquisitionCaseMetadata, ...]


@dataclass(frozen=True, slots=True)
class OperationMetadata:
    id: str | None
    label: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class StateBindingsMetadata:
    fields: tuple[tuple[str, PropertyRef], ...]
    constants: tuple[tuple[PropertyRef, StateBinding], ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledInterface[InterfaceT]:
    """A typed declaration paired with its lowered instrument contract."""

    interface_type: type[InterfaceT]
    spec: InterfaceSpec
    ref: InterfaceRef

    def fresh_spec(self) -> InterfaceSpec:
        """Return a deep copy safe for consumers that normalize Pydantic models."""

        return self.spec.model_copy(deep=True)


@dataclass(frozen=True, slots=True)
class CompiledStateTarget:
    """Internal desired-state adapter produced from a declared dataclass."""

    assignments: Mapping[PropertyRef, StateBinding]

    def target_assignments(self) -> Mapping[PropertyRef, StateBinding]:
        return self.assignments


def member(
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    access: PropertyAccess = "read_write",
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    choices: Sequence[str] | None = None,
) -> MemberMetadata:
    """Describe one state field while keeping its Python annotation intact."""

    return MemberMetadata(
        id=id,
        label=label,
        description=description,
        access=access,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
        choices=None if choices is None else tuple(choices),
    )


def argument(
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    choices: Sequence[str] | None = None,
    payload_schema_id: str | None = None,
) -> ArgumentMetadata:
    """Describe an atomic-operation parameter through ``Annotated`` metadata."""

    return ArgumentMetadata(
        id=id,
        label=label,
        description=description,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
        choices=None if choices is None else tuple(choices),
        payload_schema_id=payload_schema_id,
    )


def component(
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> ComponentMetadata:
    """Attach a typed nested capability to a Protocol/ABC attribute."""

    return ComponentMetadata(id=id, label=label, description=description)


def state_case(
    value: str,
    state_type: type[object],
    *,
    fields: Sequence[str],
    required_on_entry: Sequence[str] = (),
) -> StateCaseMetadata:
    """Declare the state fields available for one discriminator value."""

    return StateCaseMetadata(
        value=value,
        state_type=state_type,
        fields=tuple(fields),
        required_on_entry=tuple(required_on_entry),
    )


def discriminated_state(
    discriminator: MemberMetadata,
    *,
    common: type[object],
    cases: Sequence[StateCaseMetadata],
) -> DiscriminatedStateMetadata:
    """Describe a persistent state partition without changing its dataclasses."""

    if discriminator.id is None:
        raise ValueError("state discriminator member requires an explicit id")
    return DiscriminatedStateMetadata(
        discriminator=discriminator,
        common_state=common,
        cases=tuple(cases),
    )


def state_field(
    state_type: type[object],
    field_name: str,
) -> StateFieldReference:
    """Defer a cross-property reference until all declarations are defined."""

    return StateFieldReference(state_type=state_type, field_name=field_name)


def interface_discriminator(
    interface_type: type[object],
) -> DiscriminatorReference:
    """Refer to another declared interface's state discriminator."""

    return DiscriminatorReference(interface_type=interface_type)


def precondition(
    property: DeclaredPropertyTarget,
    *,
    value: PreconditionValue,
    unavailable_reason: str,
) -> PreconditionMetadata:
    """Declare one public state value required before an acquisition."""

    return PreconditionMetadata(
        property=property,
        value=value,
        unavailable_reason=unavailable_reason,
    )


def acquisition_case(
    value: str,
    result_type: type[object],
    *,
    preconditions: Sequence[PreconditionMetadata] = (),
) -> AcquisitionCaseMetadata:
    """Declare one result shape selected by an acquisition discriminator."""

    return AcquisitionCaseMetadata(
        value=value,
        result_type=result_type,
        preconditions=tuple(preconditions),
    )


def result(
    *,
    id: str | None = None,
    dtype: MeasurementDType | None = None,
    unit: str | None = None,
    axes: Sequence[str] = (),
    label: str | None = None,
    description: str | None = None,
) -> ResultMetadata:
    """Describe one result field while keeping its Python annotation intact."""

    return ResultMetadata(
        id=id,
        dtype=dtype,
        unit=unit,
        axes=tuple(axes),
        label=label,
        description=description,
    )


def axis(
    *,
    size: AxisSize,
    kind: str | None = None,
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> AxisMetadata:
    """Declare a fixed-size axis or name the state property owning its size."""

    return AxisMetadata(
        size=size,
        kind=kind,
        unit=unit,
        label=label,
        description=description,
    )


def instrument_state[ClassT: type[object]](cls: ClassT) -> ClassT:
    """Mark an existing dataclass as interface state without replacing it."""

    setattr(cls, _STATE_METADATA, True)
    return cls


def instrument_observed_state[ClassT: type[object]](cls: ClassT) -> ClassT:
    """Mark a readback dataclass whose fields cannot be used as desired state."""

    setattr(cls, _OBSERVED_STATE_METADATA, True)
    return cls


def instrument_result[ClassT: type[object]](cls: ClassT) -> ClassT:
    """Mark an existing dataclass as acquisition results without replacing it."""

    setattr(cls, _RESULT_METADATA, True)
    return cls


def instrument_interface[ClassT: type[object]](
    id: str,
    *,
    state: StateMetadata | None = None,
    observed_state: type[object] | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Callable[[ClassT], ClassT]:
    """Attach stable interface identity and state metadata to a typed class."""

    declaration = InterfaceMetadata(
        id=id,
        state=state,
        observed_state=observed_state,
        label=label,
        description=description,
    )

    def decorate(cls: ClassT) -> ClassT:
        setattr(cls, _INTERFACE_METADATA, declaration)
        if isinstance(state, DiscriminatedStateMetadata):
            _bind_discriminated_state(id, state)
        elif state is not None:
            _bind_flat_state(id, state)
        if observed_state is not None:
            _bind_observed_state(id, observed_state)
        return cls

    return decorate


def operation[**P, ReturnT](
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Callable[[Callable[P, ReturnT]], Callable[P, ReturnT]]:
    """Mark a typed method as an atomic instrument operation."""

    declaration = OperationMetadata(
        id=id,
        label=label,
        description=description,
    )

    def decorate(method: Callable[P, ReturnT]) -> Callable[P, ReturnT]:
        setattr(method, _OPERATION_METADATA, declaration)
        return method

    return decorate


def acquisition[**P, ReturnT](
    *,
    id: str | None = None,
    axes: Mapping[str, AxisMetadata] | None = None,
    label: str | None = None,
    description: str | None = None,
    preconditions: Sequence[PreconditionMetadata] = (),
) -> Callable[[Callable[P, ReturnT]], Callable[P, ReturnT]]:
    """Mark an existing method as a fixed acquisition without wrapping it."""

    declaration = AcquisitionMetadata(
        id=id,
        axes=() if axes is None else tuple(axes.items()),
        label=label,
        description=description,
        preconditions=tuple(preconditions),
        discriminator=None,
        cases=(),
    )

    def decorate(method: Callable[P, ReturnT]) -> Callable[P, ReturnT]:
        setattr(method, _ACQUISITION_METADATA, declaration)
        return method

    return decorate


def state_discriminated_acquisition[**P, ReturnT](
    discriminator: DeclaredPropertyTarget,
    *,
    cases: Sequence[AcquisitionCaseMetadata],
    id: str | None = None,
    axes: Mapping[str, AxisMetadata] | None = None,
    label: str | None = None,
    description: str | None = None,
    preconditions: Sequence[PreconditionMetadata] = (),
) -> Callable[[Callable[P, ReturnT]], Callable[P, ReturnT]]:
    """Mark a method whose result schema follows a persistent state value."""

    declaration = AcquisitionMetadata(
        id=id,
        axes=() if axes is None else tuple(axes.items()),
        label=label,
        description=description,
        preconditions=tuple(preconditions),
        discriminator=discriminator,
        cases=tuple(cases),
    )

    def decorate(method: Callable[P, ReturnT]) -> Callable[P, ReturnT]:
        setattr(method, _ACQUISITION_METADATA, declaration)
        return method

    return decorate


def compile_interface[InterfaceT](
    interface_type: type[InterfaceT],
) -> CompiledInterface[InterfaceT]:
    """Lower one decorated Python interface class to a typed, fresh contract."""

    declaration = _required_metadata(
        interface_type,
        _INTERFACE_METADATA,
        InterfaceMetadata,
        "instrument interface",
    )
    properties: list[PropertySpec] = []
    compiled_state: DiscriminatedState | None = None
    if isinstance(declaration.state, DiscriminatedStateMetadata):
        if declaration.observed_state is not None:
            raise ValueError(
                "observed state cannot currently be combined with discriminated state"
            )
        compiled_state = _compile_discriminated_state(declaration.state)
    elif declaration.state is not None:
        properties = _compile_state(declaration.state)
    if declaration.observed_state is not None:
        properties.extend(_compile_observed_state(declaration.observed_state))
    scope = InterfaceRef(declaration.id)
    operations: list[OperationSpec] = []
    acquisitions: list[AcquisitionSpec] = []
    for method_name, method in _declared_members(interface_type).items():
        operation_declaration = getattr(method, _OPERATION_METADATA, None)
        acquisition_declaration = getattr(method, _ACQUISITION_METADATA, None)
        if isinstance(operation_declaration, OperationMetadata) and isinstance(
            acquisition_declaration,
            AcquisitionMetadata,
        ):
            raise TypeError(
                f"interface method {method_name!r} cannot be both an operation "
                "and an acquisition"
            )
        if isinstance(operation_declaration, OperationMetadata):
            operations.append(
                _compile_operation(
                    method_name,
                    cast("Callable[..., object]", method),
                    operation_declaration,
                )
            )
        if not isinstance(acquisition_declaration, AcquisitionMetadata):
            continue
        acquisitions.append(
            _compile_acquisition(
                method_name,
                cast("Callable[..., object]", method),
                acquisition_declaration,
                scope=scope,
            )
        )
    spec = build_interface(
        declaration.id,
        label=declaration.label,
        description=declaration.description,
        properties=properties,
        state=compiled_state,
        operations=operations,
        acquisitions=acquisitions,
        components=_compile_components(interface_type, scope=scope),
    )
    return CompiledInterface(
        interface_type=interface_type,
        spec=spec,
        ref=InterfaceRef(declaration.id),
    )


def declared_interface_ref(interface_type: type[object]) -> InterfaceRef:
    """Return the stable member-ref root for a declared interface class."""

    declaration = _required_metadata(
        interface_type,
        _INTERFACE_METADATA,
        InterfaceMetadata,
        "instrument interface",
    )
    return InterfaceRef(declaration.id)


def declared_property_ref(
    state_type: type[object],
    field_name: str,
) -> PropertyRef:
    """Resolve a state dataclass field to its declared property identity."""

    interface_ids = cast(
        "tuple[str, ...]",
        getattr(state_type, _STATE_INTERFACES_METADATA, ()),
    )
    if len(interface_ids) != 1:
        raise ValueError(
            "state property refs require the state type to belong to exactly "
            "one declared interface"
        )
    return InterfaceRef(interface_ids[0]).property(
        _declared_dataclass_field_id(
            state_type,
            field_name,
            metadata_type=MemberMetadata,
            label="state",
        )
    )


def declared_discriminator_ref(interface_type: type[object]) -> PropertyRef:
    """Return the persistent discriminator of a declared interface."""

    declaration = _required_metadata(
        interface_type,
        _INTERFACE_METADATA,
        InterfaceMetadata,
        "instrument interface",
    )
    if not isinstance(declaration.state, DiscriminatedStateMetadata):
        raise ValueError("interface does not declare discriminated state")
    discriminator_id = declaration.state.discriminator.id
    if discriminator_id is None:
        raise ValueError("state discriminator member requires an explicit id")
    return InterfaceRef(declaration.id).property(discriminator_id)


def declared_component_ref(
    interface_type: type[object],
    attribute_name: str,
    *nested_attribute_names: str,
) -> ComponentRef:
    """Resolve typed component attribute names to a stable component path."""

    scope: InterfaceRef | ComponentRef = declared_interface_ref(interface_type)
    capability_type = interface_type
    for selected_name in (attribute_name, *nested_attribute_names):
        capability_type, declaration = _declared_component(
            capability_type,
            selected_name,
        )
        scope = scope.component(declaration.id or selected_name)
    if not isinstance(scope, ComponentRef):
        raise AssertionError("declared component resolution produced an interface ref")
    return scope


def declared_operation_ref(
    interface_type: type[object],
    method_name: str,
) -> OperationRef:
    """Resolve a decorated method to its atomic-operation identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"interface has no method {method_name!r}")
    declaration = _required_metadata(
        method,
        _OPERATION_METADATA,
        OperationMetadata,
        f"interface method {method_name!r}",
    )
    return declared_interface_ref(interface_type).operation(
        declaration.id or method_name
    )


def declared_argument_ref(
    interface_type: type[object],
    method_name: str,
    parameter_name: str,
) -> OperationArgumentRef:
    """Resolve one typed operation parameter to its stable argument identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"interface has no method {method_name!r}")
    _required_metadata(
        method,
        _OPERATION_METADATA,
        OperationMetadata,
        f"interface method {method_name!r}",
    )
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(cast("Callable[..., object]", method), include_extras=True),
    )
    annotation = hints.get(parameter_name)
    if (
        annotation is None
        or parameter_name
        not in signature(cast("Callable[..., object]", method)).parameters
    ):
        raise ValueError(
            f"operation method {method_name!r} has no annotated parameter "
            f"{parameter_name!r}"
        )
    _, metadata = _split_annotation(annotation, ArgumentMetadata)
    return declared_operation_ref(interface_type, method_name).argument(
        parameter_name if metadata is None or metadata.id is None else metadata.id
    )


def declared_state_assignments(state: object) -> dict[PropertyRef, StateBinding]:
    """Encode one decorated state dataclass without injecting instance methods."""

    state_type = type(state)
    _required_metadata(
        state_type,
        _STATE_METADATA,
        bool,
        "instrument state",
    )
    if not is_dataclass(state):
        raise TypeError("instrument state must be a dataclass instance")
    bindings = _required_metadata(
        state_type,
        _STATE_BINDINGS_METADATA,
        StateBindingsMetadata,
        "instrument state binding",
    )
    assignments = dict(bindings.constants)
    for field_name, property_ref in bindings.fields:
        value = cast("object", getattr(state, field_name))
        if value is not None:
            assignments[property_ref] = cast(
                "StateBinding",
                value,
            )
    return assignments


def declared_state_target(state: object) -> CompiledStateTarget:
    """Adapt a declared dataclass to the existing ``DesiredState`` protocol."""

    return CompiledStateTarget(declared_state_assignments(state))


def declared_acquisition_ref(
    interface_type: type[object],
    method_name: str,
) -> AcquisitionRef:
    """Resolve a decorated method to its acquisition identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"interface has no method {method_name!r}")
    declaration = _required_metadata(
        method,
        _ACQUISITION_METADATA,
        AcquisitionMetadata,
        f"interface method {method_name!r}",
    )
    return declared_interface_ref(interface_type).acquisition(
        declaration.id or method_name
    )


def declared_result_ref(
    interface_type: type[object],
    method_name: str,
    field_name: str,
) -> AcquisitionResultRef:
    """Resolve a result dataclass field to its acquisition result identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"interface has no method {method_name!r}")
    declaration = _required_metadata(
        method,
        _ACQUISITION_METADATA,
        AcquisitionMetadata,
        f"interface method {method_name!r}",
    )
    if declaration.cases:
        result_types = tuple(case.result_type for case in declaration.cases)
    else:
        hints = cast(
            "Mapping[str, object]",
            get_type_hints(
                cast("Callable[..., object]", method),
                include_extras=True,
            ),
        )
        result_type = hints.get("return")
        if result_type is None:
            raise TypeError(
                f"acquisition method {method_name!r} requires a return annotation"
            )
        result_types = (result_type,)
    result_ids = tuple(
        result_id
        for result_type in result_types
        if (
            result_id := _optional_declared_dataclass_field_id(
                result_type,
                field_name,
                metadata_type=ResultMetadata,
            )
        )
        is not None
    )
    if len(result_ids) != 1:
        raise ValueError(
            f"acquisition result field {field_name!r} must resolve exactly once"
        )
    [result_id] = result_ids
    return declared_acquisition_ref(interface_type, method_name).result(result_id)


def _bind_flat_state(interface_id: str, state_type: type[object]) -> None:
    _require_instrument_state(state_type)
    if not is_dataclass(state_type):
        raise TypeError("instrument state must be a dataclass")
    bindings = tuple(
        (
            state_field.name,
            InterfaceRef(interface_id).property(
                _declared_dataclass_field_id(
                    state_type,
                    state_field.name,
                    metadata_type=MemberMetadata,
                    label="state",
                )
            ),
        )
        for state_field in fields(state_type)
    )
    _attach_state_bindings(
        state_type,
        interface_id=interface_id,
        bindings=StateBindingsMetadata(bindings),
    )


def _bind_observed_state(interface_id: str, state_type: type[object]) -> None:
    _require_instrument_observed_state(state_type)
    if not is_dataclass(state_type):
        raise TypeError("instrument observed state must be a dataclass")
    if getattr(state_type, _STATE_METADATA, False):
        raise TypeError("observed state cannot also be declared as desired state")
    for observed_field in fields(state_type):
        _declared_dataclass_field_id(
            state_type,
            observed_field.name,
            metadata_type=MemberMetadata,
            label="observed state",
        )
    _attach_state_interface(state_type, interface_id=interface_id)


def _bind_discriminated_state(
    interface_id: str,
    declaration: DiscriminatedStateMetadata,
) -> None:
    discriminator_id = declaration.discriminator.id
    if discriminator_id is None:
        raise ValueError("state discriminator member requires an explicit id")
    discriminator_ref = InterfaceRef(interface_id).property(discriminator_id)
    _bind_flat_state(interface_id, declaration.common_state)
    common_bindings = _required_metadata(
        declaration.common_state,
        _STATE_BINDINGS_METADATA,
        StateBindingsMetadata,
        "instrument state binding",
    )
    common_by_field = dict(common_bindings.fields)

    for case in declaration.cases:
        _require_instrument_state(case.state_type)
        if not is_dataclass(case.state_type):
            raise TypeError("instrument state must be a dataclass")
        selected = set(case.fields)
        case_bindings: list[tuple[str, PropertyRef]] = []
        for state_field in fields(case.state_type):
            if state_field.name in selected:
                property_id = _declared_dataclass_field_id(
                    case.state_type,
                    state_field.name,
                    metadata_type=MemberMetadata,
                    label="state",
                )
                property_ref = InterfaceRef(interface_id).property(property_id)
            else:
                try:
                    property_ref = common_by_field[state_field.name]
                except KeyError:
                    raise ValueError(
                        f"state case {case.value!r} field {state_field.name!r} "
                        "is neither case-specific nor common"
                    ) from None
            case_bindings.append((state_field.name, property_ref))
        if selected - {name for name, _ in case_bindings}:
            raise ValueError(
                f"state case {case.value!r} references unknown fields: "
                f"{sorted(selected - {name for name, _ in case_bindings})!r}"
            )
        _attach_state_bindings(
            case.state_type,
            interface_id=interface_id,
            bindings=StateBindingsMetadata(
                fields=tuple(case_bindings),
                constants=((discriminator_ref, case.value),),
            ),
        )


def _attach_state_bindings(
    state_type: type[object],
    *,
    interface_id: str,
    bindings: StateBindingsMetadata,
) -> None:
    _attach_state_interface(state_type, interface_id=interface_id)
    existing = getattr(state_type, _STATE_BINDINGS_METADATA, None)
    if existing is not None and existing != bindings:
        raise ValueError("one declared state type cannot have multiple bindings")
    setattr(state_type, _STATE_BINDINGS_METADATA, bindings)


def _attach_state_interface(
    state_type: type[object],
    *,
    interface_id: str,
) -> None:
    interface_ids = cast(
        "tuple[str, ...]",
        getattr(state_type, _STATE_INTERFACES_METADATA, ()),
    )
    if interface_ids and interface_ids != (interface_id,):
        raise ValueError("one declared state type cannot belong to multiple interfaces")
    setattr(state_type, _STATE_INTERFACES_METADATA, (interface_id,))


def _require_instrument_state(state_type: type[object]) -> None:
    _required_metadata(
        state_type,
        _STATE_METADATA,
        bool,
        "instrument state",
    )
    if not is_dataclass(state_type):
        raise TypeError("instrument state must be a dataclass")


def _require_instrument_observed_state(state_type: type[object]) -> None:
    _required_metadata(
        state_type,
        _OBSERVED_STATE_METADATA,
        bool,
        "instrument observed state",
    )
    if not is_dataclass(state_type):
        raise TypeError("instrument observed state must be a dataclass")


def _compile_state(state_type: type[object]) -> list[PropertySpec]:
    return _compile_state_fields(state_type, selected_fields=None)


def _compile_observed_state(state_type: type[object]) -> list[PropertySpec]:
    _require_instrument_observed_state(state_type)
    return _compile_state_fields(
        state_type,
        selected_fields=None,
        observed=True,
    )


def _compile_state_fields(
    state_type: type[object],
    *,
    selected_fields: Sequence[str] | None,
    observed: bool = False,
) -> list[PropertySpec]:
    if observed:
        _require_instrument_observed_state(state_type)
    else:
        _require_instrument_state(state_type)
    if not is_dataclass(state_type):
        raise TypeError("instrument state must be a dataclass")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(state_type, include_extras=True),
    )
    state_fields = {state_field.name: state_field for state_field in fields(state_type)}
    field_names = (
        tuple(state_fields) if selected_fields is None else tuple(selected_fields)
    )
    unknown = set(field_names) - state_fields.keys()
    if unknown:
        raise ValueError(
            f"state declaration references unknown fields: {sorted(unknown)!r}"
        )
    properties: list[PropertySpec] = []
    for field_name in field_names:
        annotation = hints.get(field_name)
        if annotation is None:
            raise TypeError(f"state field {field_name!r} must be annotated")
        base, metadata = _split_annotation(annotation, MemberMetadata)
        properties.append(
            _compile_property(
                field_name,
                base,
                metadata or MemberMetadata(),
                access="read_only" if observed else None,
            )
        )
    return properties


def _compile_discriminated_state(
    declaration: DiscriminatedStateMetadata,
) -> DiscriminatedState:
    discriminator = declaration.discriminator
    if discriminator.id is None:
        raise ValueError("state discriminator member requires an explicit id")
    return build_discriminated_state(
        _compile_property(discriminator.id, str, discriminator),
        common_properties=_compile_state(declaration.common_state),
        cases=tuple(
            build_state_case(
                case.value,
                properties=_compile_state_fields(
                    case.state_type,
                    selected_fields=case.fields,
                ),
                required_on_entry_property_ids=tuple(
                    _declared_dataclass_field_id(
                        case.state_type,
                        field_name,
                        metadata_type=MemberMetadata,
                        label="state",
                    )
                    for field_name in case.required_on_entry
                ),
            )
            for case in declaration.cases
        ),
    )


def _compile_property(
    field_name: str,
    annotation: object,
    metadata: MemberMetadata,
    *,
    access: PropertyAccess | None = None,
) -> PropertySpec:
    annotation = _strip_state_wrappers(annotation)
    property_id = metadata.id or field_name
    origin = get_origin(annotation)
    if annotation is bool:
        _require_member_metadata(metadata, property_id, allowed=())
        atom = BoolType()
    elif annotation is int:
        _require_member_metadata(
            metadata,
            property_id,
            allowed=("minimum", "maximum"),
        )
        atom = IntType(
            minimum=_integer_bound(metadata.minimum, property_id, "minimum"),
            maximum=_integer_bound(metadata.maximum, property_id, "maximum"),
        )
    elif annotation is float:
        _require_member_metadata(
            metadata,
            property_id,
            allowed=("minimum", "maximum"),
        )
        atom = FloatType(
            minimum=metadata.minimum,
            maximum=metadata.maximum,
        )
    elif annotation is str:
        _require_member_metadata(metadata, property_id, allowed=("choices",))
        atom = StringType(choices=metadata.choices)
    elif origin is Literal:
        _require_member_metadata(metadata, property_id, allowed=())
        choices = cast("tuple[object, ...]", get_args(annotation))
        if not choices or any(not isinstance(choice, str) for choice in choices):
            raise TypeError(
                f"property {property_id!r} Literal choices must all be strings"
            )
        atom = StringType(choices=cast("tuple[str, ...]", choices))
    elif annotation is Quantity:
        _require_member_metadata(
            metadata,
            property_id,
            allowed=("unit", "minimum", "maximum"),
        )
        if metadata.unit is None:
            raise TypeError(
                f"quantity property {property_id!r} requires member(unit=...)"
            )
        atom = QuantityType(
            unit=metadata.unit,
            minimum=metadata.minimum,
            maximum=metadata.maximum,
        )
    else:
        raise TypeError(
            f"property {property_id!r} uses unsupported annotation {annotation!r}"
        )
    return PropertySpec(
        id=property_id,
        label=metadata.label,
        description=metadata.description,
        access=metadata.access if access is None else access,
        value_type=Scalar(atom),
    )


def _compile_components(
    capability_type: type[object],
    *,
    scope: InterfaceRef | ComponentRef,
) -> list[ComponentSpec]:
    components: list[ComponentSpec] = []
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(capability_type, include_extras=True),
    )
    for attribute_name, annotation in hints.items():
        nested_type, declaration = _split_annotation(annotation, ComponentMetadata)
        if declaration is None:
            continue
        if not isinstance(nested_type, type):
            raise TypeError(
                f"component attribute {attribute_name!r} must name a capability type"
            )
        component_id = declaration.id or attribute_name
        component_scope = scope.component(component_id)
        operations: list[OperationSpec] = []
        acquisitions: list[AcquisitionSpec] = []
        for method_name, method in _declared_members(nested_type).items():
            operation_declaration = getattr(method, _OPERATION_METADATA, None)
            acquisition_declaration = getattr(method, _ACQUISITION_METADATA, None)
            if isinstance(operation_declaration, OperationMetadata) and isinstance(
                acquisition_declaration,
                AcquisitionMetadata,
            ):
                raise TypeError(
                    f"component method {method_name!r} cannot be both an operation "
                    "and an acquisition"
                )
            if isinstance(operation_declaration, OperationMetadata):
                operations.append(
                    _compile_operation(
                        method_name,
                        cast("Callable[..., object]", method),
                        operation_declaration,
                    )
                )
            if isinstance(acquisition_declaration, AcquisitionMetadata):
                acquisitions.append(
                    _compile_acquisition(
                        method_name,
                        cast("Callable[..., object]", method),
                        acquisition_declaration,
                        scope=component_scope,
                    )
                )
        components.append(
            build_component(
                component_id,
                label=declaration.label,
                description=declaration.description,
                operations=operations,
                acquisitions=acquisitions,
                components=_compile_components(nested_type, scope=component_scope),
            )
        )
    return components


def _declared_component(
    capability_type: type[object],
    attribute_name: str,
) -> tuple[type[object], ComponentMetadata]:
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(capability_type, include_extras=True),
    )
    annotation = hints.get(attribute_name)
    if annotation is None:
        raise ValueError(f"capability has no component attribute {attribute_name!r}")
    nested_type, declaration = _split_annotation(annotation, ComponentMetadata)
    if declaration is None:
        raise ValueError(
            f"capability attribute {attribute_name!r} is not a declared component"
        )
    if not isinstance(nested_type, type):
        raise TypeError(
            f"component attribute {attribute_name!r} must name a capability type"
        )
    return nested_type, declaration


def _compile_operation(
    method_name: str,
    method: Callable[..., object],
    declaration: OperationMetadata,
) -> OperationSpec:
    parameters = tuple(signature(method).parameters.values())
    if (
        not parameters
        or parameters[0].name != "self"
        or parameters[0].kind
        not in (
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        )
    ):
        raise TypeError(f"operation method {method_name!r} must begin with self")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(method, include_extras=True),
    )
    if "return" not in hints or hints["return"] not in (None, NoneType):
        raise TypeError(f"operation method {method_name!r} must return None")
    arguments: list[OperationArgumentSpec] = []
    for parameter in parameters[1:]:
        if parameter.kind not in (
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
            Parameter.KEYWORD_ONLY,
        ):
            raise TypeError(
                f"operation method {method_name!r} cannot use variadic parameters"
            )
        if parameter.default is not Parameter.empty:  # pyright: ignore[reportAny]
            raise TypeError(
                f"operation parameter {parameter.name!r} cannot have a default"
            )
        annotation = hints.get(parameter.name)
        if annotation is None:
            raise TypeError(f"operation parameter {parameter.name!r} must be annotated")
        base, metadata = _split_annotation(annotation, ArgumentMetadata)
        arguments.append(
            _compile_operation_argument(
                parameter.name,
                base,
                metadata or ArgumentMetadata(),
            )
        )
    return build_operation(
        declaration.id or method_name,
        label=declaration.label,
        description=declaration.description,
        arguments=arguments,
    )


def _compile_operation_argument(
    parameter_name: str,
    annotation: object,
    metadata: ArgumentMetadata,
) -> OperationArgumentSpec:
    argument_id = metadata.id or parameter_name
    origin = get_origin(annotation)
    if metadata.payload_schema_id is not None:
        unsupported = any(
            value is not None
            for value in (
                metadata.unit,
                metadata.minimum,
                metadata.maximum,
                metadata.choices,
            )
        )
        if unsupported:
            raise TypeError(
                f"payload argument {argument_id!r} cannot use scalar constraints"
            )
        atom = PayloadType(schema_id=metadata.payload_schema_id)
    elif annotation is bool:
        _require_argument_metadata(metadata, argument_id, allowed=())
        atom = BoolType()
    elif annotation is int:
        _require_argument_metadata(
            metadata,
            argument_id,
            allowed=("minimum", "maximum"),
        )
        atom = IntType(
            minimum=_integer_bound(metadata.minimum, argument_id, "minimum"),
            maximum=_integer_bound(metadata.maximum, argument_id, "maximum"),
        )
    elif annotation is float:
        _require_argument_metadata(
            metadata,
            argument_id,
            allowed=("minimum", "maximum"),
        )
        atom = FloatType(minimum=metadata.minimum, maximum=metadata.maximum)
    elif annotation is str:
        _require_argument_metadata(metadata, argument_id, allowed=("choices",))
        atom = StringType(choices=metadata.choices)
    elif origin is Literal:
        _require_argument_metadata(metadata, argument_id, allowed=())
        choices = cast("tuple[object, ...]", get_args(annotation))
        if not choices or any(not isinstance(choice, str) for choice in choices):
            raise TypeError(
                f"operation argument {argument_id!r} Literal choices must all "
                "be strings"
            )
        atom = StringType(choices=cast("tuple[str, ...]", choices))
    elif annotation is Quantity:
        _require_argument_metadata(
            metadata,
            argument_id,
            allowed=("unit", "minimum", "maximum"),
        )
        if metadata.unit is None:
            raise TypeError(
                f"quantity argument {argument_id!r} requires argument(unit=...)"
            )
        atom = QuantityType(
            unit=metadata.unit,
            minimum=metadata.minimum,
            maximum=metadata.maximum,
        )
    else:
        raise TypeError(
            f"operation argument {argument_id!r} uses unsupported annotation "
            f"{annotation!r}; set argument(payload_schema_id=...) for payloads"
        )
    return build_operation_argument(
        argument_id,
        value_type=Scalar(atom),
        label=metadata.label,
        description=metadata.description,
    )


def _compile_acquisition(
    method_name: str,
    method: Callable[..., object],
    declaration: AcquisitionMetadata,
    *,
    scope: InterfaceRef | ComponentRef,
) -> AcquisitionSpec:
    parameters = tuple(signature(method).parameters.values())
    if (
        len(parameters) != 1
        or parameters[0].name != "self"
        or parameters[0].kind
        not in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    ):
        raise TypeError(f"acquisition method {method_name!r} must accept only self")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(method, include_extras=True),
    )
    result_type = hints.get("return")
    if result_type is None:
        raise TypeError(
            f"acquisition method {method_name!r} requires a return annotation"
        )
    axes = {
        axis_id: build_acquisition_axis(
            axis_id,
            size=(
                axis_metadata.size
                if isinstance(axis_metadata.size, int)
                else (
                    scope.property(axis_metadata.size)
                    if isinstance(axis_metadata.size, str)
                    else declared_property_ref(
                        axis_metadata.size.state_type,
                        axis_metadata.size.field_name,
                    )
                )
            ),
            kind=axis_metadata.kind,
            unit=axis_metadata.unit,
            label=axis_metadata.label,
            description=axis_metadata.description,
        )
        for axis_id, axis_metadata in declaration.axes
    }
    preconditions = _compile_preconditions(declaration.preconditions)
    acquisition_id = declaration.id or method_name
    if declaration.discriminator is not None:
        if not declaration.cases:
            raise ValueError(
                f"state-discriminated acquisition {acquisition_id!r} requires cases"
            )
        return build_state_discriminated_acquisition(
            acquisition_id,
            label=declaration.label,
            description=declaration.description,
            discriminator=_resolve_property_target(declaration.discriminator),
            preconditions=preconditions,
            cases=tuple(
                build_acquisition_case(
                    case.value,
                    results=_compile_results(
                        case.result_type,
                        acquisition_id=acquisition_id,
                        axes=axes,
                    ),
                    preconditions=_compile_preconditions(case.preconditions),
                )
                for case in declaration.cases
            ),
        )
    results = _compile_results(
        result_type,
        acquisition_id=acquisition_id,
        axes=axes,
    )
    return build_acquisition(
        acquisition_id,
        label=declaration.label,
        description=declaration.description,
        results=results,
        preconditions=preconditions,
    )


def _compile_preconditions(
    declarations: Sequence[PreconditionMetadata],
) -> list[AcquisitionPreconditionSpec]:
    return [
        build_acquisition_precondition(
            _resolve_property_target(declaration.property),
            value=declaration.value,
            unavailable_reason=declaration.unavailable_reason,
        )
        for declaration in declarations
    ]


def _resolve_property_target(target: DeclaredPropertyTarget) -> PropertyRef:
    if isinstance(target, PropertyRef):
        return target
    if isinstance(target, StateFieldReference):
        return declared_property_ref(target.state_type, target.field_name)
    return declared_discriminator_ref(target.interface_type)


def _compile_results(
    result_type: object,
    *,
    acquisition_id: str,
    axes: Mapping[str, AcquisitionAxisSpec],
) -> list[AcquisitionResultSpec]:
    result_class = get_origin(result_type) or result_type
    if not isinstance(result_class, type) or not getattr(
        result_class,
        _RESULT_METADATA,
        False,
    ):
        raise TypeError(
            f"acquisition {acquisition_id!r} must return an instrument result dataclass"
        )
    if not is_dataclass(result_class):
        raise TypeError("instrument result must be a dataclass")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(result_class, include_extras=True),
    )
    compiled: list[AcquisitionResultSpec] = []
    for result_field in fields(result_class):
        annotation = hints.get(result_field.name)
        if annotation is None:
            raise TypeError(f"result field {result_field.name!r} must be annotated")
        base, metadata = _split_annotation(annotation, ResultMetadata)
        metadata = metadata or ResultMetadata()
        unknown_axes = set(metadata.axes) - axes.keys()
        if unknown_axes:
            raise ValueError(
                f"result {metadata.id or result_field.name!r} references unknown axes: "
                f"{sorted(unknown_axes)!r}"
            )
        compiled.append(
            build_acquisition_result(
                metadata.id or result_field.name,
                dtype=metadata.dtype or _infer_result_dtype(base),
                unit=metadata.unit,
                label=metadata.label,
                description=metadata.description,
                axes=[axes[axis_id] for axis_id in metadata.axes],
            )
        )
    return compiled


def _infer_result_dtype(annotation: object) -> MeasurementDType:
    annotation = _strip_optional(annotation)
    origin = get_origin(annotation)
    if origin in (list, Sequence):
        arguments = cast("tuple[object, ...]", get_args(annotation))
        if not arguments:
            raise TypeError("result collection annotations require an element type")
        annotation = arguments[0]
    if annotation is bool:
        return "bool"
    if annotation is int:
        return "int64"
    if annotation is float or annotation is Quantity:
        return "float64"
    if annotation is complex:
        return "complex128"
    if annotation is str:
        return "string"
    raise TypeError(
        f"cannot infer a measurement dtype from {annotation!r}; set result(dtype=...)"
    )


def _split_annotation[MetadataT](
    annotation: object,
    metadata_type: type[MetadataT],
) -> tuple[object, MetadataT | None]:
    if get_origin(annotation) is not Annotated:
        return annotation, None
    base, *extras = cast("tuple[object, ...]", get_args(annotation))
    metadata = [item for item in extras if isinstance(item, metadata_type)]
    if len(metadata) > 1:
        raise TypeError(f"annotation contains multiple {metadata_type.__name__} values")
    return base, metadata[0] if metadata else None


def _strip_optional(annotation: object) -> object:
    if get_origin(annotation) is not UnionType:
        return annotation
    arguments = cast("tuple[object, ...]", get_args(annotation))
    if NoneType not in arguments:
        return annotation
    remaining = tuple(item for item in arguments if item is not NoneType)
    if len(remaining) != 1:
        raise TypeError(f"unsupported union annotation {annotation!r}")
    return remaining[0]


def _strip_state_wrappers(annotation: object) -> object:
    """Remove sparse ``None`` and the known symbolic ``ValueRef`` branch."""

    arguments = (
        cast("tuple[object, ...]", get_args(annotation))
        if get_origin(annotation) is UnionType
        else (annotation,)
    )
    remaining = tuple(
        item for item in arguments if item is not NoneType and item is not ValueRef
    )
    if len(remaining) != 1:
        raise TypeError(f"unsupported state union annotation {annotation!r}")
    selected = remaining[0]
    if isinstance(selected, TypeAliasType):
        return _strip_state_wrappers(getattr(selected, "__value__", None))
    alias = get_origin(selected)
    if not isinstance(alias, TypeAliasType):
        return selected

    alias_value = getattr(alias, "__value__", None)
    alias_parameters = cast(
        "tuple[object, ...]",
        getattr(alias, "__type_params__", ()),
    )
    alias_arguments = cast("tuple[object, ...]", get_args(selected))
    value_arguments = cast("tuple[object, ...]", get_args(alias_value))
    if (
        len(alias_parameters) == 1
        and len(alias_arguments) == 1
        and alias_parameters[0] in value_arguments
        and ValueRef in value_arguments
    ):
        return _strip_state_wrappers(alias_arguments[0])
    raise TypeError(f"unsupported state type alias {selected!r}")


def _declared_members(interface_type: type[object]) -> Mapping[str, object]:
    members: dict[str, object] = {}
    for base in reversed(interface_type.__mro__):
        if base is object:
            continue
        members.update(cast("Mapping[str, object]", vars(base)))
    return members


def _integer_bound(
    value: float | None,
    property_id: str,
    label: str,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"integer property {property_id!r} {label} must be an integer")
    return value


def _require_member_metadata(
    metadata: MemberMetadata,
    property_id: str,
    *,
    allowed: tuple[str, ...],
) -> None:
    values = {
        "unit": metadata.unit,
        "minimum": metadata.minimum,
        "maximum": metadata.maximum,
        "choices": metadata.choices,
    }
    unsupported = [
        name
        for name, value in values.items()
        if value is not None and name not in allowed
    ]
    if unsupported:
        raise TypeError(
            f"property {property_id!r} does not support metadata: "
            f"{', '.join(unsupported)}"
        )


def _require_argument_metadata(
    metadata: ArgumentMetadata,
    argument_id: str,
    *,
    allowed: tuple[str, ...],
) -> None:
    values = {
        "unit": metadata.unit,
        "minimum": metadata.minimum,
        "maximum": metadata.maximum,
        "choices": metadata.choices,
        "payload_schema_id": metadata.payload_schema_id,
    }
    unsupported = [
        name
        for name, value in values.items()
        if value is not None and name not in allowed
    ]
    if unsupported:
        raise TypeError(
            f"operation argument {argument_id!r} does not support metadata: "
            f"{', '.join(unsupported)}"
        )


def _optional_declared_dataclass_field_id[MetadataT: MemberMetadata | ResultMetadata](
    dataclass_annotation: object,
    field_name: str,
    *,
    metadata_type: type[MetadataT],
) -> str | None:
    dataclass_type = get_origin(dataclass_annotation) or dataclass_annotation
    if not isinstance(dataclass_type, type) or not is_dataclass(dataclass_type):
        raise TypeError("declared result must be a dataclass")
    if field_name not in {item.name for item in fields(dataclass_type)}:
        return None
    return _declared_dataclass_field_id(
        dataclass_type,
        field_name,
        metadata_type=metadata_type,
        label="result",
    )


def _declared_dataclass_field_id[MetadataT: MemberMetadata | ResultMetadata](
    dataclass_type: type[object],
    field_name: str,
    *,
    metadata_type: type[MetadataT],
    label: str,
) -> str:
    if not is_dataclass(dataclass_type):
        raise TypeError(f"declared {label} must be a dataclass")
    if field_name not in {item.name for item in fields(dataclass_type)}:
        raise ValueError(f"{label} dataclass has no field {field_name!r}")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(dataclass_type, include_extras=True),
    )
    annotation = hints[field_name]
    _, metadata = _split_annotation(annotation, metadata_type)
    return field_name if metadata is None or metadata.id is None else metadata.id


def _required_metadata[MetadataT](
    target: object,
    attribute: str,
    metadata_type: type[MetadataT],
    label: str,
) -> MetadataT:
    metadata = getattr(target, attribute, None)
    if not isinstance(metadata, metadata_type):
        raise TypeError(f"{label} is missing its decorator")
    return metadata


__all__ = [
    "AcquisitionCaseMetadata",
    "AcquisitionMetadata",
    "ArgumentMetadata",
    "AxisMetadata",
    "AxisSize",
    "CompiledInterface",
    "CompiledStateTarget",
    "ComponentMetadata",
    "DeclaredPropertyTarget",
    "DiscriminatedStateMetadata",
    "DiscriminatorReference",
    "InterfaceMetadata",
    "MemberMetadata",
    "OperationMetadata",
    "PreconditionMetadata",
    "PreconditionValue",
    "PropertyAccess",
    "ResultMetadata",
    "StateCaseMetadata",
    "StateFieldReference",
    "StateMetadata",
    "acquisition",
    "acquisition_case",
    "argument",
    "axis",
    "compile_interface",
    "component",
    "declared_acquisition_ref",
    "declared_argument_ref",
    "declared_component_ref",
    "declared_discriminator_ref",
    "declared_interface_ref",
    "declared_operation_ref",
    "declared_property_ref",
    "declared_result_ref",
    "declared_state_assignments",
    "declared_state_target",
    "discriminated_state",
    "instrument_interface",
    "instrument_observed_state",
    "instrument_result",
    "instrument_state",
    "interface_discriminator",
    "member",
    "operation",
    "precondition",
    "result",
    "state_case",
    "state_discriminated_acquisition",
    "state_field",
]
