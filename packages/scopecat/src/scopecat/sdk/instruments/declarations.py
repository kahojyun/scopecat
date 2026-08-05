"""Typed Python declarations for instrument interface contracts.

State and result decorators turn ordinary annotated classes into immutable
dataclasses while preserving their authored API for Python type checkers.
:func:`compile_interface` is the explicit boundary that lowers those
declarations to the existing :class:`InterfaceSpec` contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import Field, dataclass, field, fields, is_dataclass
from enum import Enum, auto
from inspect import Parameter, signature
from types import GenericAlias, NoneType, UnionType
from typing import (
    Annotated,
    Literal,
    TypeAliasType,
    TypeVar,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from scopecat.kernel.instrument_members import (
    AcquisitionRef,
    AcquisitionResultRef,
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
from scopecat.measurements.value_spec import (
    MeasurementDType,
    MeasurementVariableRole,
)
from scopecat.program.state import StateBinding
from scopecat.sdk.instruments.contracts import (
    AcquisitionAxisSpec,
    AcquisitionPreconditionSpec,
    AcquisitionResultSpec,
    AcquisitionSpec,
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
    acquisition_precondition as build_acquisition_precondition,
)
from scopecat.sdk.instruments.contracts import (
    acquisition_result as build_acquisition_result,
)
from scopecat.sdk.instruments.contracts import (
    interface as build_interface,
)
from scopecat.sdk.instruments.contracts import operation as build_operation
from scopecat.sdk.instruments.contracts import (
    operation_argument as build_operation_argument,
)

type PropertyAccess = Literal["read_only", "read_write"]
type PreconditionValue = bool | int | float | str | Quantity

_STATE_METADATA = "__scopecat_instrument_state__"
_RESULT_METADATA = "__scopecat_instrument_result__"
_INTERFACE_METADATA = "__scopecat_instrument_interface__"
_ACQUISITION_METADATA = "__scopecat_instrument_acquisition__"
_OPERATION_METADATA = "__scopecat_instrument_operation__"
_STATE_PROJECTION_METADATA = "__scopecat_instrument_state_projection__"
_FIELD_DECLARATION_METADATA = "scopecat.instrument.declaration"


class _NoFieldDefault(Enum):
    TOKEN = auto()


_NO_FIELD_DEFAULT = _NoFieldDefault.TOKEN


class _StateProjectionOmitted(Enum):
    TOKEN = auto()


_STATE_PROJECTION_OMITTED = _StateProjectionOmitted.TOKEN


def _state_projection_repr(self: object) -> str:
    layout = _required_metadata(
        type(self),
        _STATE_PROJECTION_METADATA,
        StateProjectionLayout,
        "instrument state projection",
    )
    arguments: list[str] = []
    for projected_field in layout.fields:
        value = cast("object", getattr(self, projected_field.python_name))
        if value is _STATE_PROJECTION_OMITTED:
            continue
        arguments.append(f"{projected_field.python_name}={value!r}")
    return f"{type(self).__qualname__}({', '.join(arguments)})"


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
    role: MeasurementVariableRole = "observable"
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
class StateFieldReference:
    """A deferred property reference addressed by a typed state field."""

    interface_type: type[object] | None
    state_type: type[object]
    field_name: str


type DeclaredPropertyTarget = PropertyRef | StateFieldReference
type AxisSize = int | str | StateFieldReference | None


@dataclass(frozen=True, slots=True)
class AxisMetadata:
    """One acquisition axis with a fixed, state-owned, or variable size."""

    size: AxisSize
    kind: str | None = None
    unit: str | None = None
    label: str | None = None
    description: str | None = None


type StateMetadata = type[object]


@dataclass(frozen=True, slots=True)
class InterfaceMetadata:
    id: str
    state: StateMetadata | None
    label: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class PreconditionMetadata:
    property: DeclaredPropertyTarget
    value: PreconditionValue
    unavailable_reason: str


@dataclass(frozen=True, slots=True)
class AcquisitionMetadata:
    id: str | None
    axes: tuple[tuple[str, AxisMetadata], ...]
    label: str | None
    description: str | None
    preconditions: tuple[PreconditionMetadata, ...]


@dataclass(frozen=True, slots=True)
class OperationMetadata:
    id: str | None
    label: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class CompiledInterface[InterfaceT]:
    """A typed declaration paired with its lowered instrument contract."""

    interface_type: type[InterfaceT]
    spec: InterfaceSpec
    ref: InterfaceRef


@dataclass(frozen=True, slots=True)
class StateProjectionField:
    """The runtime identity needed to encode one generated state field."""

    python_name: str
    ref: PropertyRef


@dataclass(frozen=True, slots=True)
class DeclaredStateField(StateProjectionField):
    """One concrete state member paired with its compiled property identity."""

    spec: PropertySpec
    annotation: object

    @property
    def property_id(self) -> str:
        return self.ref.property_id


@dataclass(frozen=True, slots=True)
class StateProjectionLayout:
    """The minimal runtime layout carried by a generated state projection."""

    fields: tuple[StateProjectionField, ...]


@dataclass(frozen=True, slots=True)
class DeclaredStateLayout:
    """One compiled flat state schema."""

    fields: tuple[DeclaredStateField, ...]
    source_type: type[object]


@dataclass(frozen=True, slots=True)
class DeclaredOperationArgument:
    """One Python parameter paired with its compiled operation argument."""

    python_name: str
    ref: OperationArgumentRef
    spec: OperationArgumentSpec
    parameter: Parameter
    annotation: object

    @property
    def argument_id(self) -> str:
        return self.ref.argument_id


@dataclass(frozen=True, slots=True)
class DeclaredOperation:
    """One operation method paired with its compiled argument identities."""

    method_name: str
    ref: OperationRef
    spec: OperationSpec
    arguments: tuple[DeclaredOperationArgument, ...]


@dataclass(frozen=True, slots=True)
class DeclaredResultField:
    """One Python result field paired with its compiled wire identity."""

    python_name: str
    ref: AcquisitionResultRef
    spec: AcquisitionResultSpec
    annotation: object

    @property
    def result_id(self) -> str:
        return self.ref.result_id


@dataclass(frozen=True, slots=True)
class DeclaredResultLayout:
    """The complete result schema for one acquisition."""

    result_type: object
    fields: tuple[DeclaredResultField, ...]


@dataclass(frozen=True, slots=True)
class DeclaredAcquisition[ResultT]:
    """Typed acquisition method paired with its complete result layout."""

    method_name: str
    ref: AcquisitionRef
    spec: AcquisitionSpec
    result: DeclaredResultLayout

    @property
    def result_fields(self) -> tuple[DeclaredResultField, ...]:
        """Return every declared result field in declaration order."""

        return self.result.fields


@dataclass(frozen=True, slots=True)
class DeclaredScopeLayout:
    """The root interface capability and its typed declared members."""

    capability_type: type[object]
    ref: InterfaceRef
    spec: InterfaceSpec
    operations: tuple[DeclaredOperation, ...]
    acquisitions: tuple[DeclaredAcquisition[object], ...]


@dataclass(frozen=True, slots=True)
class DeclaredInterfaceLayout[InterfaceT]:
    """The complete Python authoring layout of one compiled interface."""

    compiled: CompiledInterface[InterfaceT]
    root: DeclaredScopeLayout
    state: DeclaredStateLayout | None


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


def member_field[ValueT](
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    access: PropertyAccess = "read_write",
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    choices: Sequence[str] | None = None,
) -> ValueT:  # pyright: ignore[reportInvalidTypeVarUse]
    """Declare one required concrete state field and its instrument metadata.

    Interface state describes a complete driver-facing snapshot, so the Python
    annotation is the concrete ``T``. Generated patch and target carriers add
    omission where live transitions or symbolic effects need sparse updates.
    """

    metadata = {
        _FIELD_DECLARATION_METADATA: member(
            id=id,
            label=label,
            description=description,
            access=access,
            unit=unit,
            minimum=minimum,
            maximum=maximum,
            choices=choices,
        )
    }
    return cast("ValueT", field(metadata=metadata))


def state_projection_field[ValueT]() -> ValueT:  # pyright: ignore[reportInvalidTypeVarUse]
    """Declare an omittable generated state-projection field."""

    return cast("ValueT", field(default=_STATE_PROJECTION_OMITTED))


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


@overload
def state_field(
    state_type: type[object],
    field_name: str,
    /,
) -> StateFieldReference: ...


@overload
def state_field(
    interface_type: type[object],
    state_type: type[object],
    field_name: str,
    /,
) -> StateFieldReference: ...


def state_field(
    interface_or_state_type: type[object],
    state_type_or_field_name: type[object] | str,
    field_name: str | None = None,
    /,
) -> StateFieldReference:
    """Defer a cross-property reference until all declarations are defined."""

    if field_name is None:
        return StateFieldReference(
            interface_type=None,
            state_type=interface_or_state_type,
            field_name=cast("str", state_type_or_field_name),
        )
    return StateFieldReference(
        interface_type=interface_or_state_type,
        state_type=cast("type[object]", state_type_or_field_name),
        field_name=field_name,
    )


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


def result(
    *,
    id: str | None = None,
    role: MeasurementVariableRole = "observable",
    dtype: MeasurementDType | None = None,
    unit: str | None = None,
    axes: Sequence[str] = (),
    label: str | None = None,
    description: str | None = None,
) -> ResultMetadata:
    """Describe one result field while keeping its Python annotation intact."""

    return ResultMetadata(
        id=id,
        role=role,
        dtype=dtype,
        unit=unit,
        axes=tuple(axes),
        label=label,
        description=description,
    )


def result_field[ValueT](
    *,
    default: ValueT | Literal[_NoFieldDefault.TOKEN] = _NO_FIELD_DEFAULT,
    default_factory: Callable[[], ValueT] | Literal[_NoFieldDefault.TOKEN] = (
        _NO_FIELD_DEFAULT
    ),
    id: str | None = None,
    role: MeasurementVariableRole = "observable",
    dtype: MeasurementDType | None = None,
    unit: str | None = None,
    axes: Sequence[str] = (),
    label: str | None = None,
    description: str | None = None,
) -> ValueT:
    """Declare one dataclass acquisition-result field and its metadata."""

    metadata = {
        _FIELD_DECLARATION_METADATA: result(
            id=id,
            role=role,
            dtype=dtype,
            unit=unit,
            axes=axes,
            label=label,
            description=description,
        )
    }
    if default_factory is not _NO_FIELD_DEFAULT:
        if default is not _NO_FIELD_DEFAULT:
            raise ValueError("cannot specify both default and default_factory")
        return field(default_factory=default_factory, metadata=metadata)
    if default is _NO_FIELD_DEFAULT:
        return cast("ValueT", field(metadata=metadata))
    return field(default=default, metadata=metadata)


def axis(
    *,
    size: AxisSize = None,
    kind: str | None = None,
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> AxisMetadata:
    """Declare an acquisition axis; ``None`` means variable length per point."""

    return AxisMetadata(
        size=size,
        kind=kind,
        unit=unit,
        label=label,
        description=description,
    )


@dataclass_transform(
    field_specifiers=(member_field,),
    frozen_default=True,
    kw_only_default=True,
)
def instrument_state[ClassT](cls: type[ClassT], /) -> type[ClassT]:
    """Create an immutable concrete instrument-state schema dataclass.

    Use this for the state a driver can read or report in full. Optionality is
    ordinary domain optionality, not a marker for an omitted device update.
    Sparse generated patch and target types are derived from this schema.
    """

    declared = dataclass(frozen=True, slots=True, kw_only=True)(cls)
    setattr(declared, _STATE_METADATA, True)
    return declared


@dataclass_transform(
    frozen_default=True,
    kw_only_default=True,
)
def instrument_state_projection[ClassT](
    layout: StateProjectionLayout,
    /,
) -> Callable[[type[ClassT]], type[ClassT]]:
    """Create a sparse generated carrier bound to one concrete state layout."""

    def decorate(cls: type[ClassT]) -> type[ClassT]:
        projected = dataclass(frozen=True, slots=True, kw_only=True)(cls)
        setattr(projected, _STATE_PROJECTION_METADATA, layout)
        projected.__repr__ = _state_projection_repr
        return projected

    return decorate


@dataclass_transform(
    field_specifiers=(result_field,),
    frozen_default=True,
    kw_only_default=True,
)
def instrument_result[ClassT](cls: type[ClassT], /) -> type[ClassT]:
    """Create an immutable, slotted acquisition-result dataclass.

    Field roles and axes form one acquisition bundle. Live clients return the
    concrete fields together; symbolic clients preserve the same bundle as
    related dataset products when it is recorded.
    """

    declared = dataclass(frozen=True, slots=True, kw_only=True)(cls)
    setattr(declared, _RESULT_METADATA, True)
    return declared


def instrument_interface[ClassT: type[object]](
    id: str,
    *,
    state: StateMetadata | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Callable[[ClassT], ClassT]:
    """Attach instrument identity to an authored ``Protocol`` or ABC.

    The decorator preserves the Python class. Decorated methods define typed
    operation and acquisition members; ``compile_interface`` is the explicit
    boundary that lowers those declarations to wire and driver contracts.
    """

    declaration = InterfaceMetadata(
        id=id,
        state=state,
        label=label,
        description=description,
    )

    def decorate(cls: ClassT) -> ClassT:
        setattr(cls, _INTERFACE_METADATA, declaration)
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
    """Mark an existing method as a bundled acquisition without wrapping it.

    The method's decorated result type owns variable roles. ``axes`` declares
    dimensions shared by those fields, including sizes derived from state.
    """

    declaration = AcquisitionMetadata(
        id=id,
        axes=() if axes is None else tuple(axes.items()),
        label=label,
        description=description,
        preconditions=tuple(preconditions),
    )

    def decorate(method: Callable[P, ReturnT]) -> Callable[P, ReturnT]:
        setattr(method, _ACQUISITION_METADATA, declaration)
        return method

    return decorate


def compile_interface[InterfaceT](
    interface_type: type[InterfaceT],
) -> CompiledInterface[InterfaceT]:
    """Lower one decorated Python interface class to a typed, fresh contract."""

    declaration = _required_interface_metadata(interface_type)
    properties = [] if declaration.state is None else _compile_state(declaration.state)
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
        operations=operations,
        acquisitions=acquisitions,
        components=(),
    )
    return CompiledInterface(
        interface_type=interface_type,
        spec=spec,
        ref=InterfaceRef(declaration.id),
    )


def declared_interface_ref(interface_type: type[object]) -> InterfaceRef:
    """Return the stable member-ref root for a declared interface class."""

    declaration = _required_interface_metadata(interface_type)
    return InterfaceRef(declaration.id)


def declared_property_ref(
    interface_type: type[object],
    state_type: type[object],
    field_name: str,
) -> PropertyRef:
    """Resolve a state dataclass field to its declared property identity."""

    return declared_interface_ref(interface_type).property(
        _declared_dataclass_field_id(
            state_type,
            field_name,
            metadata_type=MemberMetadata,
            label="state",
        )
    )


def declared_operation_ref(
    interface_type: type[object],
    method_name: str,
) -> OperationRef:
    """Resolve a decorated interface method to its operation identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"declared scope has no method {method_name!r}")
    declaration = _required_metadata(
        method,
        _OPERATION_METADATA,
        OperationMetadata,
        f"declared scope method {method_name!r}",
    )
    return declared_interface_ref(interface_type).operation(
        declaration.id or method_name
    )


def declared_argument_ref(
    interface_type: type[object],
    method_name: str,
    parameter_name: str,
) -> OperationArgumentRef:
    """Resolve one interface operation parameter to its identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"declared scope has no method {method_name!r}")
    _required_metadata(
        method,
        _OPERATION_METADATA,
        OperationMetadata,
        f"declared scope method {method_name!r}",
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
    return declared_operation_ref(
        interface_type,
        method_name,
    ).argument(_declared_operation_argument_id(parameter_name, annotation))


def _declared_operation_argument_id(
    parameter_name: str,
    annotation: object,
) -> str:
    _, metadata = _split_annotation(annotation, ArgumentMetadata)
    return parameter_name if metadata is None or metadata.id is None else metadata.id


def state_projection_assignments(
    projection: object,
) -> dict[PropertyRef, StateBinding]:
    """Encode one generated state projection using explicit field presence."""

    if not is_dataclass(projection):
        raise TypeError("instrument state projection must be a dataclass instance")
    layout = _required_metadata(
        type(projection),
        _STATE_PROJECTION_METADATA,
        StateProjectionLayout,
        "instrument state projection",
    )
    assignments: dict[PropertyRef, StateBinding] = {}
    for projected_field in layout.fields:
        value = cast("object", getattr(projection, projected_field.python_name))
        if value is not _STATE_PROJECTION_OMITTED:
            assignments[projected_field.ref] = cast("StateBinding", value)
    return assignments


def declared_interface_layout[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
    /,
) -> DeclaredInterfaceLayout[InterfaceT]:
    """Project a compiled interface into its complete typed Python member tree."""

    declaration = _required_interface_metadata(compiled.interface_type)
    return DeclaredInterfaceLayout(
        compiled=compiled,
        root=_declared_scope_layout(
            compiled,
        ),
        state=_declared_state_layout(compiled, declaration.state),
    )


def _declared_state_layout[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
    declaration: StateMetadata | None,
) -> DeclaredStateLayout | None:
    if declaration is None:
        return None
    return DeclaredStateLayout(
        source_type=declaration,
        fields=_declared_state_fields(compiled, declaration),
    )


def _declared_state_fields[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
    state_type: type[object],
) -> tuple[DeclaredStateField, ...]:
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(state_type, include_extras=True),
    )
    specs_by_id = {item.id: item for item in compiled.spec.properties}
    declared_fields: list[DeclaredStateField] = []
    for state_member in _instrument_state_fields(state_type):
        annotation = hints.get(state_member.name)
        if annotation is None:
            raise TypeError(f"state field {state_member.name!r} must be annotated")
        concrete_annotation, _ = _split_annotation(annotation, MemberMetadata)
        property_id = _declared_dataclass_field_id(
            state_type,
            state_member.name,
            metadata_type=MemberMetadata,
            label="state",
        )
        declared_fields.append(
            DeclaredStateField(
                python_name=state_member.name,
                ref=compiled.ref.property(property_id),
                spec=specs_by_id[property_id],
                annotation=concrete_annotation,
            )
        )
    return tuple(declared_fields)


def _declared_scope_layout[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
) -> DeclaredScopeLayout:
    operations: list[DeclaredOperation] = []
    acquisitions: list[DeclaredAcquisition[object]] = []
    for method in _declared_members(compiled.interface_type).values():
        operation_declaration = getattr(method, _OPERATION_METADATA, None)
        acquisition_declaration = getattr(method, _ACQUISITION_METADATA, None)
        if isinstance(operation_declaration, OperationMetadata):
            operation_method = cast("Callable[..., None]", method)
            operations.append(
                declared_operation(
                    compiled,
                    operation_method,
                )
            )
        if isinstance(acquisition_declaration, AcquisitionMetadata):
            acquisition_method = cast("Callable[..., object]", method)
            acquisitions.append(
                declared_acquisition(
                    compiled,
                    acquisition_method,
                )
            )
    return DeclaredScopeLayout(
        capability_type=compiled.interface_type,
        ref=compiled.ref,
        spec=compiled.spec,
        operations=tuple(operations),
        acquisitions=tuple(acquisitions),
    )


def declared_operation[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
    method: Callable[..., None],
    /,
) -> DeclaredOperation:
    """Bind a decorated interface method to its compiled argument identities."""

    method_name = next(
        (
            name
            for name, declared_method in _declared_members(
                compiled.interface_type
            ).items()
            if declared_method is method
        ),
        None,
    )
    if method_name is None:
        raise ValueError("operation method does not belong to the compiled interface")
    declaration = _required_metadata(
        method,
        _OPERATION_METADATA,
        OperationMetadata,
        f"interface method {method_name!r}",
    )
    operation_id = declaration.id or method_name
    operation_spec = next(
        item for item in compiled.spec.operations if item.id == operation_id
    )
    operation_ref = compiled.ref.operation(operation_id)
    method_signature = signature(method)
    parameters = tuple(method_signature.parameters.values())[1:]
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(method, include_extras=True),
    )
    specs_by_id = {item.id: item for item in operation_spec.arguments}
    arguments: list[DeclaredOperationArgument] = []
    for parameter in parameters:
        annotation, _ = _split_annotation(
            hints[parameter.name],
            ArgumentMetadata,
        )
        argument_id = _declared_operation_argument_id(
            parameter.name,
            hints[parameter.name],
        )
        arguments.append(
            DeclaredOperationArgument(
                python_name=parameter.name,
                ref=operation_ref.argument(argument_id),
                spec=specs_by_id[argument_id],
                parameter=parameter,
                annotation=annotation,
            )
        )
    return DeclaredOperation(
        method_name=method_name,
        ref=operation_ref,
        spec=operation_spec,
        arguments=tuple(arguments),
    )


def declared_acquisition[InterfaceT, ResultT](
    compiled: CompiledInterface[InterfaceT],
    method: Callable[..., ResultT],
    /,
) -> DeclaredAcquisition[ResultT]:
    """Bind a decorated interface method to its compiled result layout."""

    method_name = next(
        (
            name
            for name, declared_method in _declared_members(
                compiled.interface_type
            ).items()
            if declared_method is method
        ),
        None,
    )
    if method_name is None:
        raise ValueError("acquisition method does not belong to the compiled interface")
    declaration = _required_metadata(
        method,
        _ACQUISITION_METADATA,
        AcquisitionMetadata,
        f"interface method {method_name!r}",
    )
    acquisition_id = declaration.id or method_name
    acquisition_spec = next(
        item for item in compiled.spec.acquisitions if item.id == acquisition_id
    )
    acquisition_ref = compiled.ref.acquisition(acquisition_id)
    result_type = _declared_method_result_type(method, method_name=method_name)
    return DeclaredAcquisition(
        method_name=method_name,
        ref=acquisition_ref,
        spec=acquisition_spec,
        result=_declared_result_layout(
            result_type,
            acquisition_ref=acquisition_ref,
            result_specs=acquisition_spec.results,
        ),
    )


def declared_acquisition_ref(
    interface_type: type[object],
    method_name: str,
) -> AcquisitionRef:
    """Resolve a decorated interface method to its acquisition identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"declared scope has no method {method_name!r}")
    declaration = _required_metadata(
        method,
        _ACQUISITION_METADATA,
        AcquisitionMetadata,
        f"declared scope method {method_name!r}",
    )
    return declared_interface_ref(interface_type).acquisition(
        declaration.id or method_name
    )


def declared_result_ref(
    interface_type: type[object],
    method_name: str,
    field_name: str,
) -> AcquisitionResultRef:
    """Resolve one interface acquisition result field to its identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"declared scope has no method {method_name!r}")
    _required_metadata(
        method,
        _ACQUISITION_METADATA,
        AcquisitionMetadata,
        f"declared scope method {method_name!r}",
    )
    result_type = _declared_method_result_type(
        cast("Callable[..., object]", method),
        method_name=method_name,
    )
    result_id = _optional_declared_dataclass_field_id(
        result_type,
        field_name,
        metadata_type=ResultMetadata,
    )
    if result_id is None:
        raise ValueError(f"acquisition result has no field {field_name!r}")
    return declared_acquisition_ref(
        interface_type,
        method_name,
    ).result(result_id)


def _declared_method_result_type(
    method: Callable[..., object],
    *,
    method_name: str,
) -> object:
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(method, include_extras=True),
    )
    result_type = hints.get("return")
    if result_type is None:
        raise TypeError(
            f"acquisition method {method_name!r} requires a return annotation"
        )
    return result_type


def _declared_result_layout(
    result_type: object,
    *,
    acquisition_ref: AcquisitionRef,
    result_specs: Sequence[AcquisitionResultSpec],
) -> DeclaredResultLayout:
    result_class = get_origin(result_type) or result_type
    if not isinstance(result_class, type) or not is_dataclass(result_class):
        raise TypeError("declared acquisition result must be a dataclass")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(result_class, include_extras=True),
    )
    specs_by_id = {item.id: item for item in result_specs}
    declared_fields = tuple(
        DeclaredResultField(
            python_name=result_field.name,
            ref=acquisition_ref.result(result_id),
            spec=specs_by_id[result_id],
            annotation=_expand_concrete_alias(
                _split_annotation(
                    hints[result_field.name],
                    ResultMetadata,
                )[0]
            ),
        )
        for result_field in fields(result_class)
        if (
            result_id := _declared_dataclass_field_id(
                result_class,
                result_field.name,
                metadata_type=ResultMetadata,
                label="result",
            )
        )
        in specs_by_id
    )
    return DeclaredResultLayout(
        result_type=result_type,
        fields=declared_fields,
    )


def _require_instrument_state(state_type: type[object]) -> None:
    _required_metadata(
        state_type,
        _STATE_METADATA,
        bool,
        "instrument state",
    )
    if not is_dataclass(state_type):
        raise TypeError("instrument state must be a dataclass")


def _instrument_state_fields(
    state_type: type[object],
) -> tuple[Field[object], ...]:
    _require_instrument_state(state_type)
    if not is_dataclass(state_type):
        raise TypeError("instrument state must be a dataclass")
    return fields(state_type)


def _compile_state(state_type: type[object]) -> list[PropertySpec]:
    return _compile_state_fields(state_type)


def _compile_state_fields(
    state_type: type[object],
) -> list[PropertySpec]:
    _require_instrument_state(state_type)
    if not is_dataclass(state_type):
        raise TypeError("instrument state must be a dataclass")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(state_type, include_extras=True),
    )
    state_fields = {state_field.name: state_field for state_field in fields(state_type)}
    properties: list[PropertySpec] = []
    for field_name in state_fields:
        state_field = state_fields[field_name]
        annotation = hints.get(field_name)
        if annotation is None:
            raise TypeError(f"state field {field_name!r} must be annotated")
        base, annotated_metadata = _split_annotation(annotation, MemberMetadata)
        metadata = (
            _declared_field_metadata(state_field, MemberMetadata) or annotated_metadata
        )
        properties.append(
            _compile_property(
                field_name,
                base,
                metadata or MemberMetadata(),
            )
        )
    return properties


def _compile_property(
    field_name: str,
    annotation: object,
    metadata: MemberMetadata,
) -> PropertySpec:
    annotation = _expand_concrete_alias(annotation)
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
        access=metadata.access,
        value_type=Scalar(atom),
    )


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
    annotation = _expand_concrete_alias(annotation)
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
    scope: InterfaceRef,
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
                if isinstance(axis_metadata.size, int) or axis_metadata.size is None
                else (
                    scope.property(axis_metadata.size)
                    if isinstance(axis_metadata.size, str)
                    else _resolve_state_field_reference(
                        axis_metadata.size,
                        scope=scope,
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
    preconditions = _compile_preconditions(declaration.preconditions, scope=scope)
    acquisition_id = declaration.id or method_name
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
    *,
    scope: InterfaceRef,
) -> list[AcquisitionPreconditionSpec]:
    return [
        build_acquisition_precondition(
            _resolve_property_target(declaration.property, scope=scope),
            value=declaration.value,
            unavailable_reason=declaration.unavailable_reason,
        )
        for declaration in declarations
    ]


def _resolve_property_target(
    target: DeclaredPropertyTarget,
    *,
    scope: InterfaceRef,
) -> PropertyRef:
    if isinstance(target, PropertyRef):
        return target
    return _resolve_state_field_reference(target, scope=scope)


def _resolve_state_field_reference(
    target: StateFieldReference,
    *,
    scope: InterfaceRef,
) -> PropertyRef:
    if target.interface_type is not None:
        return declared_property_ref(
            target.interface_type,
            target.state_type,
            target.field_name,
        )
    return scope.property(
        _declared_dataclass_field_id(
            target.state_type,
            target.field_name,
            metadata_type=MemberMetadata,
            label="state",
        )
    )


def _compile_results(
    result_type: object,
    *,
    acquisition_id: str,
    axes: Mapping[str, AcquisitionAxisSpec],
) -> list[AcquisitionResultSpec]:
    result_class = _require_concrete_result_class(
        result_type,
        acquisition_id=acquisition_id,
    )
    if not is_dataclass(result_class):
        raise TypeError("instrument result must be a dataclass")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(result_class, include_extras=True),
    )
    result_fields = {
        result_field.name: result_field for result_field in fields(result_class)
    }
    compiled: list[AcquisitionResultSpec] = []
    for field_name in result_fields:
        result_field = result_fields[field_name]
        annotation = hints.get(result_field.name)
        if annotation is None:
            raise TypeError(f"result field {result_field.name!r} must be annotated")
        base, annotated_metadata = _split_annotation(annotation, ResultMetadata)
        base = _expand_concrete_alias(base)
        if _is_optional_union(base):
            raise TypeError(
                f"acquisition {acquisition_id!r} result field {field_name!r} "
                "cannot be optional; a successful acquisition must provide every "
                "declared result"
            )
        metadata = (
            _declared_field_metadata(result_field, ResultMetadata)
            or annotated_metadata
            or ResultMetadata()
        )
        unknown_axes = set(metadata.axes) - axes.keys()
        if unknown_axes:
            raise ValueError(
                f"result {metadata.id or result_field.name!r} references unknown axes: "
                f"{sorted(unknown_axes)!r}"
            )
        compiled.append(
            build_acquisition_result(
                metadata.id or result_field.name,
                role=metadata.role,
                dtype=metadata.dtype or _infer_result_dtype(base),
                unit=metadata.unit,
                label=metadata.label,
                description=metadata.description,
                axes=[axes[axis_id] for axis_id in metadata.axes],
            )
        )
    return compiled


def _require_concrete_result_class(
    result_type: object,
    *,
    acquisition_id: str,
) -> type[object]:
    result_origin = get_origin(result_type)
    if isinstance(result_origin, type) and getattr(
        result_origin, _RESULT_METADATA, False
    ):
        raise TypeError(
            f"acquisition {acquisition_id!r} cannot return a parameterized "
            "instrument result; instrument result classes must not be generic"
        )
    if not isinstance(result_type, type) or not getattr(
        result_type,
        _RESULT_METADATA,
        False,
    ):
        raise TypeError(
            f"acquisition {acquisition_id!r} must return an instrument result dataclass"
        )
    type_parameters = cast(
        "tuple[object, ...]",
        getattr(result_type, "__type_params__", ()),
    ) or cast(
        "tuple[object, ...]",
        getattr(result_type, "__parameters__", ()),
    )
    if type_parameters:
        raise TypeError(
            f"instrument result {result_type.__qualname__!r} must not be generic"
        )
    return result_type


def _infer_result_dtype(annotation: object) -> MeasurementDType:
    annotation = _expand_concrete_alias(annotation)
    origin = get_origin(annotation)
    if origin in (list, Sequence):
        arguments = cast("tuple[object, ...]", get_args(annotation))
        if not arguments:
            raise TypeError("result collection annotations require an element type")
        annotation = _expand_concrete_alias(arguments[0])
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


def _expand_concrete_alias(annotation: object) -> object:
    """Resolve a concrete PEP 695 alias without changing its value domain."""

    if isinstance(annotation, TypeAliasType):
        parameters = cast(
            "tuple[TypeVar, ...]",
            annotation.__type_params__,
        )
        if parameters:
            return annotation
        return _expand_concrete_alias(cast("object", annotation.__value__))

    origin = get_origin(annotation)
    if not isinstance(origin, TypeAliasType):
        return annotation
    parameters = cast("tuple[TypeVar, ...]", origin.__type_params__)
    arguments = cast("tuple[object, ...]", get_args(annotation))
    if len(parameters) != len(arguments):
        raise TypeError(f"invalid concrete type alias {annotation!r}")
    expanded = _substitute_type_parameters(
        cast("object", origin.__value__),
        dict(zip(parameters, arguments, strict=True)),
    )
    return _expand_concrete_alias(expanded)


def _substitute_type_parameters(
    annotation: object,
    substitutions: Mapping[TypeVar, object],
) -> object:
    if isinstance(annotation, TypeVar):
        return substitutions.get(annotation, annotation)

    origin = get_origin(annotation)
    if origin is None:
        return annotation
    arguments = cast("tuple[object, ...]", get_args(annotation))
    if isinstance(origin, TypeAliasType):
        resolved_arguments = tuple(
            _substitute_type_parameters(item, substitutions) for item in arguments
        )
        applied = origin[
            resolved_arguments[0]
            if len(resolved_arguments) == 1
            else resolved_arguments
        ]
        return _expand_concrete_alias(applied)
    if origin is UnionType:
        resolved = tuple(
            _substitute_type_parameters(item, substitutions) for item in arguments
        )
        union = resolved[0]
        for item in resolved[1:]:
            union = cast("type[object]", union) | cast("type[object]", item)
        return union
    if origin is Annotated:
        return Annotated[
            _substitute_type_parameters(arguments[0], substitutions),
            *arguments[1:],
        ]
    if origin is Literal:
        return annotation

    resolved = tuple(
        _substitute_type_parameters(item, substitutions) for item in arguments
    )
    if resolved == arguments:
        return annotation
    if isinstance(annotation, GenericAlias):
        return GenericAlias(
            cast("type[object]", origin),
            resolved[0] if len(resolved) == 1 else resolved,
        )
    copy_with = getattr(annotation, "copy_with", None)
    if callable(copy_with):
        return cast("Callable[[tuple[object, ...]], object]", copy_with)(resolved)
    raise TypeError(f"unsupported generic concrete alias value {annotation!r}")


def _is_optional_union(annotation: object) -> bool:
    origin = get_origin(annotation)
    is_union = origin is UnionType or (
        getattr(origin, "__module__", None) == "typing"
        and getattr(origin, "__qualname__", None) == "Union"
    )
    return is_union and NoneType in get_args(annotation)


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
    dataclass_fields = {item.name: item for item in fields(dataclass_type)}
    if field_name not in dataclass_fields:
        raise ValueError(f"{label} dataclass has no field {field_name!r}")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(dataclass_type, include_extras=True),
    )
    annotation = hints[field_name]
    _, annotated_metadata = _split_annotation(annotation, metadata_type)
    metadata = (
        _declared_field_metadata(dataclass_fields[field_name], metadata_type)
        or annotated_metadata
    )
    return field_name if metadata is None or metadata.id is None else metadata.id


def _declared_field_metadata[MetadataT: MemberMetadata | ResultMetadata](
    dataclass_field: Field[object],
    metadata_type: type[MetadataT],
) -> MetadataT | None:
    metadata = dataclass_field.metadata.get(_FIELD_DECLARATION_METADATA)
    return metadata if isinstance(metadata, metadata_type) else None


def _required_interface_metadata(
    interface_type: type[object],
) -> InterfaceMetadata:
    return _required_metadata(
        interface_type,
        _INTERFACE_METADATA,
        InterfaceMetadata,
        "instrument interface",
    )


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
    "AcquisitionMetadata",
    "ArgumentMetadata",
    "AxisMetadata",
    "AxisSize",
    "CompiledInterface",
    "DeclaredAcquisition",
    "DeclaredInterfaceLayout",
    "DeclaredOperation",
    "DeclaredOperationArgument",
    "DeclaredPropertyTarget",
    "DeclaredResultField",
    "DeclaredResultLayout",
    "DeclaredScopeLayout",
    "DeclaredStateField",
    "DeclaredStateLayout",
    "InterfaceMetadata",
    "MemberMetadata",
    "OperationMetadata",
    "PreconditionMetadata",
    "PreconditionValue",
    "PropertyAccess",
    "ResultMetadata",
    "StateFieldReference",
    "StateMetadata",
    "StateProjectionField",
    "StateProjectionLayout",
    "acquisition",
    "argument",
    "axis",
    "compile_interface",
    "declared_acquisition",
    "declared_acquisition_ref",
    "declared_argument_ref",
    "declared_interface_layout",
    "declared_interface_ref",
    "declared_operation",
    "declared_operation_ref",
    "declared_property_ref",
    "declared_result_ref",
    "instrument_interface",
    "instrument_result",
    "instrument_state",
    "instrument_state_projection",
    "member",
    "member_field",
    "operation",
    "precondition",
    "result",
    "result_field",
    "state_field",
    "state_projection_assignments",
    "state_projection_field",
]
