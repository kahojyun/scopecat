"""Typed Python declarations for instrument interface contracts.

State members are explicit class attributes: they carry stable identity and
schema metadata, but they do not pretend that hardware I/O is normal Python
attribute access. :func:`compile_interface` lowers those declarations and the
decorated operation/acquisition methods to :class:`InterfaceSpec`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass
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
)

import numpy as np

from scopecat.kernel.instrument_members import (
    AcquisitionRef,
    AcquisitionResultRef,
    ComponentRef,
    DevicePropertyRef,
    DeviceSchemaId,
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
from scopecat.program.measurement_types import (
    MeasurementDType,
    MeasurementVariableRole,
)
from scopecat.program.state import StateBinding
from scopecat.sdk.instruments.contracts import (
    AcquisitionAxisSpec,
    AcquisitionPreconditionSpec,
    AcquisitionResultSpec,
    AcquisitionSpec,
    ComponentSpec,
    InterfaceSpec,
    LinearCoordinatesSpec,
    OperationArgumentSpec,
    OperationSpec,
    PropertySpec,
    StatePropertyRef,
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
from scopecat.sdk.instruments.contracts import component as build_component
from scopecat.sdk.instruments.contracts import (
    interface as build_interface,
)
from scopecat.sdk.instruments.contracts import operation as build_operation
from scopecat.sdk.instruments.contracts import (
    operation_argument as build_operation_argument,
)

type PropertyAccess = Literal["read_only", "write_only", "read_write"]
type PreconditionValue = bool | int | float | str | Quantity

_RESULT_SCHEMA_METADATA = "__scopecat_instrument_result_schema__"
_INTERFACE_METADATA = "__scopecat_instrument_interface__"
_COMPONENT_METADATA = "__scopecat_instrument_component__"
_ACQUISITION_METADATA = "__scopecat_instrument_acquisition__"
_OPERATION_METADATA = "__scopecat_instrument_operation__"
_MEMBER_PROJECTION_METADATA = "__scopecat_instrument_member_projection__"


class _MemberProjectionOmitted(Enum):
    TOKEN = auto()


_MEMBER_PROJECTION_OMITTED = _MemberProjectionOmitted.TOKEN


def _member_projection_repr(self: object) -> str:
    layout = _required_metadata(
        type(self),
        _MEMBER_PROJECTION_METADATA,
        MemberProjectionLayout,
        "instrument member projection",
    )
    arguments: list[str] = []
    for projected_field in layout.fields:
        value = cast("object", getattr(self, projected_field.python_name))
        if value is _MEMBER_PROJECTION_OMITTED:
            continue
        arguments.append(f"{projected_field.python_name}={value!r}")
    return f"{type(self).__qualname__}({', '.join(arguments)})"


@dataclass(frozen=True, slots=True)
class MemberMetadata:
    """Schema metadata carried by one explicit member declaration.

    Read/write access permits commands; baseline restoration remains an
    independent, opt-in lifecycle policy.
    """

    access: PropertyAccess
    id: str | None = None
    label: str | None = None
    description: str | None = None
    capture: bool = True
    restore: bool = False
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class DeviceMemberMetadata(MemberMetadata):
    """Metadata for a model-specific property outside portable interfaces."""

    component_path: tuple[str, ...] = ()


class Member[ValueT]:
    """A portable state-member declaration and driver-binding target.

    The object intentionally has no value-style descriptor behavior. Accessing
    ``SomeInterface.frequency`` returns this declaration object, making I/O
    available only through explicit client or driver operations.
    """

    __slots__ = ("metadata", "owner", "python_name")

    def __init__(self, metadata: MemberMetadata) -> None:
        self.metadata = metadata
        self.owner: type[object] | None = None
        self.python_name: str | None = None

    def __set_name__(self, owner: type[object], name: str) -> None:
        if self.owner is not None and (
            self.owner is not owner or self.python_name != name
        ):
            raise TypeError("instrument member declarations cannot be reused")
        self.owner = owner
        self.python_name = name


class DeviceMember[ValueT](Member[ValueT]):
    """A model-specific state-member declaration owned by a concrete driver."""

    metadata: DeviceMemberMetadata

    def __init__(self, metadata: DeviceMemberMetadata) -> None:
        super().__init__(metadata)


class ResultDeclaration:
    """A scalar or array field in a named acquisition result schema."""

    is_array: bool
    dtype: MeasurementDType
    id: str | None
    role: MeasurementVariableRole
    unit: str | None
    axes: tuple[str, ...]
    label: str | None
    description: str | None
    owner: type[object] | None
    python_name: str | None

    __slots__ = (
        "axes",
        "description",
        "dtype",
        "id",
        "is_array",
        "label",
        "owner",
        "python_name",
        "role",
        "unit",
    )

    def __init__(
        self,
        *,
        is_array: bool,
        dtype: MeasurementDType,
        id: str | None = None,
        role: MeasurementVariableRole = "observable",
        unit: str | None = None,
        axes: tuple[str, ...] = (),
        label: str | None = None,
        description: str | None = None,
    ) -> None:
        self.is_array = is_array
        self.dtype = dtype
        self.id = id
        self.role = role
        self.unit = unit
        self.axes = axes
        self.label = label
        self.description = description
        self.owner = None
        self.python_name = None

    def __set_name__(self, owner: type[object], name: str) -> None:
        if self.owner is not None and (
            self.owner is not owner or self.python_name != name
        ):
            raise TypeError("acquisition result declarations cannot be reused")
        self.owner = owner
        self.python_name = name


@dataclass(frozen=True, slots=True)
class _ResultSchema:
    """Internal ordered fields owned by one named result schema."""

    fields: tuple[ResultDeclaration, ...]


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


type DeclaredPropertyTarget = PropertyRef | Member[object]
type AxisSize = int | str | Member[object] | None


@dataclass(frozen=True, slots=True)
class LinearCoordinatesMetadata:
    """Expected uniformly spaced coordinates derived from instrument state."""

    start: DeclaredPropertyTarget
    stop: DeclaredPropertyTarget
    endpoint: bool = True


@dataclass(frozen=True, slots=True)
class AxisMetadata:
    """One acquisition axis with a fixed, state-owned, or variable size."""

    size: AxisSize
    kind: str | None = None
    unit: str | None = None
    coordinate_result: str | None = None
    coordinates: LinearCoordinatesMetadata | None = None
    label: str | None = None
    description: str | None = None


type ComponentDeclarations = tuple[tuple[str, type[object]], ...]


@dataclass(frozen=True, slots=True)
class InterfaceMetadata:
    id: str
    label: str | None
    description: str | None
    components: ComponentDeclarations


@dataclass(frozen=True, slots=True)
class ComponentMetadata:
    label: str | None
    description: str | None
    components: ComponentDeclarations


@dataclass(frozen=True, slots=True)
class PreconditionMetadata:
    property: DeclaredPropertyTarget
    value: PreconditionValue
    unavailable_reason: str


@dataclass(frozen=True, slots=True)
class AcquisitionMetadata:
    id: str | None
    results: type[object] | None
    axes: tuple[tuple[str, AxisMetadata], ...]
    label: str | None
    description: str | None
    preconditions: tuple[PreconditionMetadata, ...]


class MemberObservation:
    """A named acquisition projection of independently declared state members."""

    __slots__ = ("members", "metadata", "owner", "python_name")

    def __init__(
        self,
        members: tuple[Member[object], ...],
        metadata: AcquisitionMetadata,
    ) -> None:
        self.members = members
        self.metadata = metadata
        self.owner: type[object] | None = None
        self.python_name: str | None = None

    def __set_name__(self, owner: type[object], name: str) -> None:
        if self.owner is not None and (
            self.owner is not owner or self.python_name != name
        ):
            raise TypeError("member observation declarations cannot be reused")
        self.owner = owner
        self.python_name = name


@dataclass(frozen=True, slots=True)
class OperationMetadata:
    id: str | None
    label: str | None
    description: str | None
    invalidates: tuple[DeclaredPropertyTarget, ...]


@dataclass(frozen=True, slots=True)
class CompiledInterface[InterfaceT]:
    """A typed declaration paired with its lowered instrument contract."""

    interface_type: type[InterfaceT]
    spec: InterfaceSpec
    ref: InterfaceRef


@dataclass(frozen=True, slots=True)
class MemberProjectionField:
    """The runtime identity needed to encode one projected property."""

    python_name: str
    ref: PropertyRef


@dataclass(frozen=True, slots=True)
class DeclaredProperty(MemberProjectionField):
    """One Python property paired with its compiled instrument identity."""

    spec: PropertySpec
    annotation: object
    declaration: Member[object]

    @property
    def property_id(self) -> str:
        return self.ref.property_id


@dataclass(frozen=True, slots=True)
class DeclaredDeviceProperty:
    """One concrete-driver property paired with its device-owned identity."""

    python_name: str
    ref: DevicePropertyRef
    spec: PropertySpec
    annotation: object
    declaration: DeviceMember[object]


@dataclass(frozen=True, slots=True)
class MemberProjectionLayout:
    """The minimal runtime layout carried by a generated member projection."""

    fields: tuple[MemberProjectionField, ...]


@dataclass(frozen=True, slots=True)
class DeclaredPropertyLayout:
    """The compiled properties declared directly by one interface."""

    fields: tuple[DeclaredProperty, ...]
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
    source_property: PropertyRef | None = None

    @property
    def result_id(self) -> str:
        return self.ref.result_id


@dataclass(frozen=True, slots=True)
class DeclaredResultLayout:
    """The complete result schema for one acquisition."""

    schema_type: type[object] | None
    type_name: str
    fields: tuple[DeclaredResultField, ...]


@dataclass(frozen=True, slots=True)
class DeclaredAcquisition:
    """An acquisition method paired with its complete result schema."""

    method_name: str
    ref: AcquisitionRef
    spec: AcquisitionSpec
    result: DeclaredResultLayout
    kind: Literal["acquisition", "member_observation"]

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
    acquisitions: tuple[DeclaredAcquisition, ...]


@dataclass(frozen=True, slots=True)
class DeclaredInterfaceLayout[InterfaceT]:
    """The complete Python authoring layout of one compiled interface."""

    compiled: CompiledInterface[InterfaceT]
    root: DeclaredScopeLayout
    properties: DeclaredPropertyLayout | None


def member[ValueT](
    *,
    access: PropertyAccess,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    capture: bool = True,
    restore: bool = False,
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    choices: Sequence[str] | None = None,
) -> Member[ValueT]:
    """Declare one portable member without prescribing its I/O strategy."""

    return Member(
        MemberMetadata(
            id=id,
            label=label,
            description=description,
            access=access,
            capture=capture,
            restore=restore,
            unit=unit,
            minimum=minimum,
            maximum=maximum,
            choices=None if choices is None else tuple(choices),
        )
    )


def write_only_member[ValueT](
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    choices: Sequence[str] | None = None,
) -> Member[ValueT]:
    """Declare acknowledged state that cannot be queried or restored."""

    return member(
        access="write_only",
        id=id,
        label=label,
        description=description,
        capture=False,
        restore=False,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
        choices=choices,
    )


def device_member[ValueT](
    *,
    access: PropertyAccess,
    id: str | None = None,
    component_path: Sequence[str] = (),
    label: str | None = None,
    description: str | None = None,
    capture: bool = True,
    restore: bool = False,
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    choices: Sequence[str] | None = None,
) -> DeviceMember[ValueT]:
    """Declare model-specific background state on a concrete driver class.

    Device members can be captured and explicitly marked restorable without
    claiming a portable interface. Driver methods bind their I/O explicitly.
    """

    return DeviceMember(
        DeviceMemberMetadata(
            id=id,
            component_path=tuple(component_path),
            label=label,
            description=description,
            access=access,
            capture=capture,
            restore=restore,
            unit=unit,
            minimum=minimum,
            maximum=maximum,
            choices=None if choices is None else tuple(choices),
        )
    )


def member_projection_field[ValueT]() -> ValueT:  # pyright: ignore[reportInvalidTypeVarUse]
    """Declare an omittable generated member-projection field."""

    return cast("ValueT", field(default=_MEMBER_PROJECTION_OMITTED))


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


def scalar_result(
    *,
    dtype: MeasurementDType,
    id: str | None = None,
    role: MeasurementVariableRole = "observable",
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> ResultDeclaration:
    """Declare one scalar acquisition result with an explicit wire dtype."""

    return ResultDeclaration(
        is_array=False,
        dtype=dtype,
        id=id,
        role=role,
        unit=unit,
        label=label,
        description=description,
    )


def array_result(
    *,
    dtype: MeasurementDType,
    axes: Sequence[str],
    id: str | None = None,
    role: MeasurementVariableRole = "observable",
    unit: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> ResultDeclaration:
    """Declare one array acquisition result and its ordered acquisition axes."""

    axis_ids = tuple(axes)
    if not axis_ids:
        raise ValueError("array result requires at least one axis")
    if len(set(axis_ids)) != len(axis_ids):
        raise ValueError("array result axes must not contain duplicates")
    return ResultDeclaration(
        is_array=True,
        dtype=dtype,
        id=id,
        role=role,
        unit=unit,
        axes=axis_ids,
        label=label,
        description=description,
    )


def axis(
    *,
    size: AxisSize = None,
    kind: str | None = None,
    unit: str | None = None,
    coordinate_result: str | None = None,
    coordinates: LinearCoordinatesMetadata | None = None,
    label: str | None = None,
    description: str | None = None,
) -> AxisMetadata:
    """Declare an acquisition axis; ``None`` means variable length per point."""

    return AxisMetadata(
        size=size,
        kind=kind,
        unit=unit,
        coordinate_result=coordinate_result,
        coordinates=coordinates,
        label=label,
        description=description,
    )


def linear_coordinates(
    *,
    start: DeclaredPropertyTarget,
    stop: DeclaredPropertyTarget,
    endpoint: bool = True,
) -> LinearCoordinatesMetadata:
    """Declare the expected linear coordinate layout for an acquisition axis."""

    return LinearCoordinatesMetadata(start=start, stop=stop, endpoint=endpoint)


@dataclass_transform(
    frozen_default=True,
    kw_only_default=True,
)
def instrument_member_projection[ClassT](
    layout: MemberProjectionLayout,
    /,
) -> Callable[[type[ClassT]], type[ClassT]]:
    """Create a sparse generated carrier bound to one property layout."""

    def decorate(cls: type[ClassT]) -> type[ClassT]:
        projected = dataclass(frozen=True, slots=True, kw_only=True)(cls)
        setattr(projected, _MEMBER_PROJECTION_METADATA, layout)
        projected.__repr__ = _member_projection_repr
        return projected

    return decorate


def result_schema[ClassT](cls: type[ClassT], /) -> type[ClassT]:
    """Mark a class of explicit result declarations as one acquisition schema.

    The class is a named declaration namespace, not the value returned by a
    driver or client. Generated driver observations and client bundles own the
    corresponding runtime value types.
    """

    type_parameters = cast(
        "tuple[object, ...]",
        getattr(cls, "__type_params__", ()),
    ) or cast(
        "tuple[object, ...]",
        getattr(cls, "__parameters__", ()),
    )
    if type_parameters:
        raise TypeError(f"result schema {cls.__qualname__!r} must not be generic")
    if any(
        isinstance(vars(base).get(_RESULT_SCHEMA_METADATA), _ResultSchema)
        for base in cls.__mro__[1:]
    ):
        raise TypeError(
            f"result schema {cls.__qualname__!r} must not inherit another result schema"
        )
    fields = tuple(
        value
        for value in cast("Mapping[str, object]", vars(cls)).values()
        if isinstance(value, ResultDeclaration)
    )
    if not fields:
        raise TypeError(f"result schema {cls.__qualname__!r} declares no results")
    setattr(cls, _RESULT_SCHEMA_METADATA, _ResultSchema(fields=fields))
    return cls


def instrument_interface[ClassT: type[object]](
    id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    components: Mapping[str, type[object]] | None = None,
) -> Callable[[ClassT], ClassT]:
    """Attach instrument identity to an authored class, ``Protocol``, or ABC.

    The decorator preserves the Python class. Decorated methods define typed
    operation and acquisition members; ``compile_interface`` is the explicit
    boundary that lowers those declarations to wire and driver contracts.
    """

    declaration = InterfaceMetadata(
        id=id,
        label=label,
        description=description,
        components=tuple((components or {}).items()),
    )

    def decorate(cls: ClassT) -> ClassT:
        setattr(cls, _INTERFACE_METADATA, declaration)
        return cls

    return decorate


def instrument_component[ClassT: type[object]](
    *,
    label: str | None = None,
    description: str | None = None,
    components: Mapping[str, type[object]] | None = None,
) -> Callable[[ClassT], ClassT]:
    """Declare one reusable component capability mounted by a parent scope.

    Component ids belong to the parent mapping, so the same declaration can be
    mounted more than once, for example as two identical LO groups.
    """

    declaration = ComponentMetadata(
        label=label,
        description=description,
        components=tuple((components or {}).items()),
    )

    def decorate(cls: ClassT) -> ClassT:
        setattr(cls, _COMPONENT_METADATA, declaration)
        return cls

    return decorate


def operation[**P, ReturnT](
    *,
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
    invalidates: Sequence[DeclaredPropertyTarget] = (),
) -> Callable[[Callable[P, ReturnT]], Callable[P, ReturnT]]:
    """Mark an atomic operation and any state it makes unknowable."""

    declaration = OperationMetadata(
        id=id,
        label=label,
        description=description,
        invalidates=tuple(invalidates),
    )

    def decorate(method: Callable[P, ReturnT]) -> Callable[P, ReturnT]:
        setattr(method, _OPERATION_METADATA, declaration)
        return method

    return decorate


def acquisition[**P](
    *,
    results: type[object],
    id: str | None = None,
    axes: Mapping[str, AxisMetadata] | None = None,
    label: str | None = None,
    description: str | None = None,
    preconditions: Sequence[PreconditionMetadata] = (),
) -> Callable[[Callable[P, None]], Callable[P, None]]:
    """Mark a method as an acquisition with an explicit named result schema."""

    declaration = AcquisitionMetadata(
        id=id,
        results=results,
        axes=() if axes is None else tuple(axes.items()),
        label=label,
        description=description,
        preconditions=tuple(preconditions),
    )

    def decorate(method: Callable[P, None]) -> Callable[P, None]:
        setattr(method, _ACQUISITION_METADATA, declaration)
        return method

    return decorate


def observation(
    *members: Member[object],
    id: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> MemberObservation:
    """Declare a fresh, recordable observation of existing scalar members."""

    if not members:
        raise ValueError("member observation requires at least one member")
    if len(set(members)) != len(members):
        raise ValueError("member observation cannot repeat a member")
    return MemberObservation(
        tuple(members),
        AcquisitionMetadata(
            id=id,
            results=None,
            axes=(),
            label=label,
            description=description,
            preconditions=(),
        ),
    )


def compile_interface[InterfaceT](
    interface_type: type[InterfaceT],
) -> CompiledInterface[InterfaceT]:
    """Lower one decorated Python interface class to a typed, fresh contract."""

    declaration = _required_interface_metadata(interface_type)
    properties = _compile_properties(interface_type)
    scope = InterfaceRef(declaration.id)
    operations, acquisitions = _compile_scope_members(interface_type, scope=scope)
    components = [
        _compile_component(
            component_id,
            component_type,
            scope=scope.component(component_id),
            ancestors=(interface_type,),
        )
        for component_id, component_type in declaration.components
    ]
    spec = build_interface(
        declaration.id,
        label=declaration.label,
        description=declaration.description,
        properties=properties,
        operations=operations,
        acquisitions=acquisitions,
        components=components,
    )
    return CompiledInterface(
        interface_type=interface_type,
        spec=spec,
        ref=scope,
    )


type _DeclaredScopeRef = InterfaceRef | ComponentRef


def _compile_component(
    component_id: str,
    component_type: type[object],
    *,
    scope: ComponentRef,
    ancestors: tuple[type[object], ...],
) -> ComponentSpec:
    if component_type in ancestors:
        chain = " -> ".join(item.__qualname__ for item in (*ancestors, component_type))
        raise TypeError(f"instrument component declarations form a cycle: {chain}")
    declaration = _required_component_metadata(component_type)
    operations, acquisitions = _compile_scope_members(component_type, scope=scope)
    selected_ancestors = (*ancestors, component_type)
    return build_component(
        component_id,
        label=declaration.label,
        description=declaration.description,
        properties=_compile_properties(component_type),
        operations=operations,
        acquisitions=acquisitions,
        components=[
            _compile_component(
                child_id,
                child_type,
                scope=scope.component(child_id),
                ancestors=selected_ancestors,
            )
            for child_id, child_type in declaration.components
        ],
    )


def _compile_scope_members(
    scope_type: type[object],
    *,
    scope: _DeclaredScopeRef,
) -> tuple[list[OperationSpec], list[AcquisitionSpec]]:
    operations: list[OperationSpec] = []
    acquisitions: list[AcquisitionSpec] = []
    for method_name, method in _declared_members(scope_type).items():
        if isinstance(method, MemberObservation):
            acquisitions.append(
                _compile_member_observation(
                    method_name,
                    method,
                    scope_type=scope_type,
                    scope=scope,
                )
            )
            continue
        operation_declaration = getattr(method, _OPERATION_METADATA, None)
        acquisition_declaration = getattr(method, _ACQUISITION_METADATA, None)
        if isinstance(operation_declaration, OperationMetadata) and isinstance(
            acquisition_declaration,
            AcquisitionMetadata,
        ):
            raise TypeError(
                f"instrument method {method_name!r} cannot be both an operation "
                "and an acquisition"
            )
        if isinstance(operation_declaration, OperationMetadata):
            operations.append(
                _compile_operation(
                    method_name,
                    cast("Callable[..., object]", method),
                    operation_declaration,
                    scope=scope,
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
    return operations, acquisitions


def declared_interface_ref(interface_type: type[object]) -> InterfaceRef:
    """Return the stable member-ref root for a declared interface class."""

    declaration = _required_interface_metadata(interface_type)
    return InterfaceRef(declaration.id)


def declared_property_ref(
    interface_type: type[object],
    property_name: str,
    /,
) -> PropertyRef:
    """Resolve a declared property to its stable member identity."""

    declared_property = _declared_properties(interface_type).get(property_name)
    if declared_property is None:
        raise ValueError(f"declared scope has no property {property_name!r}")
    metadata = declared_property.metadata
    property_id = metadata.id or property_name
    return declared_interface_ref(interface_type).property(property_id)


def declared_device_properties(
    driver_type: type[object],
    schema_id: DeviceSchemaId | None,
    /,
) -> tuple[DeclaredDeviceProperty, ...]:
    """Compile device-owned properties declared directly on a driver hierarchy."""

    fields: list[DeclaredDeviceProperty] = []
    for property_name, declaration in _declared_properties(driver_type).items():
        if not isinstance(declaration, DeviceMember):
            continue
        metadata = declaration.metadata
        if schema_id is None:
            raise TypeError(
                f"device property {property_name!r} requires "
                "instrument_driver(device_schema_id=...)"
            )
        annotation, spec = _compile_declared_property(
            driver_type,
            property_name,
            declaration,
        )
        fields.append(
            DeclaredDeviceProperty(
                python_name=property_name,
                ref=DevicePropertyRef(
                    schema_id,
                    metadata.component_path,
                    spec.id,
                ),
                spec=spec,
                annotation=annotation,
                declaration=declaration,
            )
        )
    return tuple(fields)


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


def member_projection_assignments(
    projection: object,
) -> dict[PropertyRef, StateBinding]:
    """Encode one generated member projection using explicit field presence."""

    if not is_dataclass(projection):
        raise TypeError("instrument member projection must be a dataclass instance")
    layout = _required_metadata(
        type(projection),
        _MEMBER_PROJECTION_METADATA,
        MemberProjectionLayout,
        "instrument member projection",
    )
    assignments: dict[PropertyRef, StateBinding] = {}
    for projected_field in layout.fields:
        value = cast("object", getattr(projection, projected_field.python_name))
        if value is not _MEMBER_PROJECTION_OMITTED:
            assignments[projected_field.ref] = cast("StateBinding", value)
    return assignments


def declared_interface_layout[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
    /,
) -> DeclaredInterfaceLayout[InterfaceT]:
    """Project a compiled interface into its complete typed Python member tree."""

    return DeclaredInterfaceLayout(
        compiled=compiled,
        root=_declared_scope_layout(
            compiled,
        ),
        properties=_declared_property_layout(compiled),
    )


def _declared_property_layout[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
) -> DeclaredPropertyLayout | None:
    declared_properties = _declared_properties(compiled.interface_type)
    if not declared_properties:
        return None
    return DeclaredPropertyLayout(
        source_type=compiled.interface_type,
        fields=_declared_property_fields(compiled),
    )


def _declared_property_fields[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
) -> tuple[DeclaredProperty, ...]:
    specs_by_id = {item.id: item for item in compiled.spec.properties}
    declared_fields: list[DeclaredProperty] = []
    for property_name, declaration in _declared_properties(
        compiled.interface_type
    ).items():
        annotation = _declared_member_annotation(
            compiled.interface_type,
            property_name,
            declaration,
        )
        metadata = declaration.metadata
        property_id = metadata.id or property_name
        declared_fields.append(
            DeclaredProperty(
                python_name=property_name,
                ref=compiled.ref.property(property_id),
                spec=specs_by_id[property_id],
                annotation=_expand_concrete_alias(annotation),
                declaration=declaration,
            )
        )
    return tuple(declared_fields)


def _declared_scope_layout[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
) -> DeclaredScopeLayout:
    operations: list[DeclaredOperation] = []
    acquisitions: list[DeclaredAcquisition] = []
    for method in _declared_members(compiled.interface_type).values():
        if isinstance(method, MemberObservation):
            acquisitions.append(declared_acquisition(compiled, method))
            continue
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
            acquisition_method = cast("Callable[..., None]", method)
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


def declared_acquisition[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
    method: Callable[..., None] | MemberObservation,
    /,
) -> DeclaredAcquisition:
    """Bind an acquisition declaration to its compiled result layout."""

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
        raise ValueError("acquisition declaration does not belong to the interface")
    declaration = (
        method.metadata
        if isinstance(method, MemberObservation)
        else _required_metadata(
            method,
            _ACQUISITION_METADATA,
            AcquisitionMetadata,
            f"interface method {method_name!r}",
        )
    )
    acquisition_id = declaration.id or method_name
    acquisition_spec = next(
        item for item in compiled.spec.acquisitions if item.id == acquisition_id
    )
    acquisition_ref = compiled.ref.acquisition(acquisition_id)
    if isinstance(method, MemberObservation):
        result_layout = _declared_member_observation_result_layout(
            compiled,
            method,
            method_name=method_name,
            acquisition_ref=acquisition_ref,
            result_specs=acquisition_spec.results,
        )
        kind: Literal["acquisition", "member_observation"] = "member_observation"
    else:
        result_schema_type = _require_result_schema(
            declaration.results,
            acquisition_id=acquisition_id,
        )[0]
        result_layout = _declared_result_layout(
            result_schema_type,
            acquisition_ref=acquisition_ref,
            result_specs=acquisition_spec.results,
        )
        kind = "acquisition"
    return DeclaredAcquisition(
        method_name=method_name,
        ref=acquisition_ref,
        spec=acquisition_spec,
        result=result_layout,
        kind=kind,
    )


def declared_acquisition_ref(
    interface_type: type[object],
    method_name: str,
) -> AcquisitionRef:
    """Resolve a decorated interface method to its acquisition identity."""

    method = _declared_members(interface_type).get(method_name)
    if method is None:
        raise ValueError(f"declared scope has no method {method_name!r}")
    declaration = (
        method.metadata
        if isinstance(method, MemberObservation)
        else _required_metadata(
            method,
            _ACQUISITION_METADATA,
            AcquisitionMetadata,
            f"declared scope method {method_name!r}",
        )
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
    if isinstance(method, MemberObservation):
        layout = declared_interface_layout(compile_interface(interface_type))
        acquisition = next(
            item for item in layout.root.acquisitions if item.method_name == method_name
        )
        result = next(
            (
                field
                for field in acquisition.result_fields
                if field.python_name == field_name
            ),
            None,
        )
        if result is None:
            raise ValueError(f"acquisition result has no field {field_name!r}")
        return result.ref
    declaration = _required_metadata(
        method,
        _ACQUISITION_METADATA,
        AcquisitionMetadata,
        f"declared scope method {method_name!r}",
    )
    _, schema = _require_result_schema(
        declaration.results,
        acquisition_id=declaration.id or method_name,
    )
    result = next(
        (field for field in schema.fields if field.python_name == field_name),
        None,
    )
    if result is None:
        raise ValueError(f"acquisition result has no field {field_name!r}")
    return declared_acquisition_ref(
        interface_type,
        method_name,
    ).result(result.id or field_name)


def _declared_result_layout(
    result_schema_type: type[object],
    *,
    acquisition_ref: AcquisitionRef,
    result_specs: Sequence[AcquisitionResultSpec],
) -> DeclaredResultLayout:
    _, schema = _require_result_schema(
        result_schema_type,
        acquisition_id=acquisition_ref.acquisition_id,
    )
    specs_by_id = {item.id: item for item in result_specs}
    declared_fields = tuple(
        DeclaredResultField(
            python_name=result_field.python_name,
            ref=acquisition_ref.result(result_id),
            spec=specs_by_id[result_id],
        )
        for result_field in schema.fields
        if result_field.python_name is not None
        and (result_id := result_field.id or result_field.python_name) in specs_by_id
    )
    return DeclaredResultLayout(
        schema_type=result_schema_type,
        type_name=result_schema_type.__name__,
        fields=declared_fields,
    )


def _declared_member_observation_result_layout[InterfaceT](
    compiled: CompiledInterface[InterfaceT],
    declaration: MemberObservation,
    *,
    method_name: str,
    acquisition_ref: AcquisitionRef,
    result_specs: Sequence[AcquisitionResultSpec],
) -> DeclaredResultLayout:
    properties = {
        field.declaration: field for field in _declared_property_fields(compiled)
    }
    specs_by_id = {item.id: item for item in result_specs}
    declared_fields: list[DeclaredResultField] = []
    for member in declaration.members:
        field = properties.get(member)
        if field is None:
            raise TypeError(
                f"member observation {method_name!r} targets a member not declared "
                "by its interface"
            )
        spec = specs_by_id[field.property_id]
        declared_fields.append(
            DeclaredResultField(
                python_name=field.python_name,
                ref=acquisition_ref.result(spec.id),
                spec=spec,
                source_property=field.ref,
            )
        )
    interface_name = compiled.interface_type.__name__.removesuffix("Interface")
    observation_name = "".join(
        segment[:1].upper() + segment[1:]
        for segment in method_name.split("_")
        if segment
    )
    return DeclaredResultLayout(
        schema_type=None,
        type_name=f"{interface_name}{observation_name}Results",
        fields=tuple(declared_fields),
    )


def _compile_properties(scope_type: type[object]) -> list[PropertySpec]:
    properties: list[PropertySpec] = []
    for property_name, declaration in _declared_properties(scope_type).items():
        if isinstance(declaration, DeviceMember):
            raise TypeError(
                f"interface property {property_name!r} cannot use @device_member"
            )
        _, spec = _compile_declared_property(
            scope_type,
            property_name,
            declaration,
        )
        properties.append(spec)
    return properties


def _compile_declared_property(
    scope_type: type[object],
    property_name: str,
    declaration: Member[object],
) -> tuple[object, PropertySpec]:
    annotation = _declared_member_annotation(
        scope_type,
        property_name,
        declaration,
    )
    expanded_annotation = _expand_concrete_alias(annotation)
    return expanded_annotation, _compile_property(
        property_name,
        expanded_annotation,
        declaration.metadata,
    )


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
        capture=metadata.capture,
        restore=metadata.restore,
        value_type=Scalar(atom),
    )


def _compile_operation(
    method_name: str,
    method: Callable[..., object],
    declaration: OperationMetadata,
    *,
    scope: _DeclaredScopeRef,
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
        invalidates=[
            _resolve_property_target(target, scope=scope)
            for target in declaration.invalidates
        ],
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


def _compile_member_observation(
    name: str,
    declaration: MemberObservation,
    *,
    scope_type: type[object],
    scope: _DeclaredScopeRef,
) -> AcquisitionSpec:
    acquisition_id = declaration.metadata.id or name
    declared_members = {
        member: (python_name, member)
        for python_name, member in _declared_properties(scope_type).items()
    }
    results: list[AcquisitionResultSpec] = []
    for member in declaration.members:
        selected = declared_members.get(member)
        if selected is None:
            raise TypeError(
                f"member observation {name!r} targets a member not declared "
                "by its interface scope"
            )
        python_name, selected_member = selected
        annotation, property_spec = _compile_declared_property(
            scope_type,
            python_name,
            selected_member,
        )
        results.append(
            build_acquisition_result(
                property_spec.id,
                dtype=_infer_observation_dtype(annotation),
                unit=selected_member.metadata.unit,
                label=property_spec.label,
                description=property_spec.description,
                source_property=scope.property(property_spec.id),
            )
        )
    return build_acquisition(
        acquisition_id,
        label=declaration.metadata.label,
        description=declaration.metadata.description,
        results=results,
    )


def _compile_acquisition(
    method_name: str,
    method: Callable[..., object],
    declaration: AcquisitionMetadata,
    *,
    scope: _DeclaredScopeRef,
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
    if "return" not in hints or hints["return"] not in (None, NoneType):
        raise TypeError(
            f"acquisition method {method_name!r} must return None; declare its "
            "results with @acquisition(results=...)"
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
                    else _resolve_member_declaration(
                        axis_metadata.size,
                        scope=scope,
                    )
                )
            ),
            kind=axis_metadata.kind,
            unit=axis_metadata.unit,
            coordinate_result=axis_metadata.coordinate_result,
            coordinates=(
                None
                if axis_metadata.coordinates is None
                else LinearCoordinatesSpec(
                    start=_declaration_state_property_ref(
                        _resolve_property_target(
                            axis_metadata.coordinates.start,
                            scope=scope,
                        )
                    ),
                    stop=_declaration_state_property_ref(
                        _resolve_property_target(
                            axis_metadata.coordinates.stop,
                            scope=scope,
                        )
                    ),
                    endpoint=axis_metadata.coordinates.endpoint,
                )
            ),
            label=axis_metadata.label,
            description=axis_metadata.description,
        )
        for axis_id, axis_metadata in declaration.axes
    }
    preconditions = _compile_preconditions(declaration.preconditions, scope=scope)
    acquisition_id = declaration.id or method_name
    results = _compile_results(
        declaration.results,
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
    scope: _DeclaredScopeRef,
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
    scope: _DeclaredScopeRef,
) -> PropertyRef:
    if isinstance(target, PropertyRef):
        return target
    return _resolve_member_declaration(target, scope=scope)


def _declaration_state_property_ref(target: PropertyRef) -> StatePropertyRef:
    return StatePropertyRef(
        interface_id=target.interface_id,
        component_path=list(target.component_path),
        property_id=target.property_id,
    )


def _resolve_member_declaration(
    target: Member[object],
    *,
    scope: _DeclaredScopeRef,
) -> PropertyRef:
    if target.owner is None or target.python_name is None:
        raise TypeError("instrument member declaration is not bound to a class")
    if isinstance(getattr(target.owner, _INTERFACE_METADATA, None), InterfaceMetadata):
        return declared_property_ref(
            target.owner,
            target.python_name,
        )
    return scope.property(target.metadata.id or target.python_name)


def _compile_results(
    result_schema_type: object,
    *,
    acquisition_id: str,
    axes: Mapping[str, AcquisitionAxisSpec],
) -> list[AcquisitionResultSpec]:
    _, schema = _require_result_schema(
        result_schema_type,
        acquisition_id=acquisition_id,
    )
    compiled: list[AcquisitionResultSpec] = []
    for result_field in schema.fields:
        if result_field.python_name is None:
            raise TypeError("acquisition result declaration is not bound to a schema")
        field_name = result_field.python_name
        unknown_axes = set(result_field.axes) - axes.keys()
        if unknown_axes:
            raise ValueError(
                f"result {result_field.id or field_name!r} references unknown axes: "
                f"{sorted(unknown_axes)!r}"
            )
        if result_field.is_array != bool(result_field.axes):
            expected = "at least one axis" if result_field.is_array else "no axes"
            raise TypeError(
                f"acquisition {acquisition_id!r} result field {field_name!r} "
                f"must declare {expected}"
            )
        compiled.append(
            build_acquisition_result(
                result_field.id or field_name,
                role=result_field.role,
                dtype=result_field.dtype,
                unit=result_field.unit,
                label=result_field.label,
                description=result_field.description,
                axes=[axes[axis_id] for axis_id in result_field.axes],
            )
        )
    return compiled


def _require_result_schema(
    result_schema_type: object,
    *,
    acquisition_id: str,
) -> tuple[type[object], _ResultSchema]:
    if not isinstance(result_schema_type, type):
        raise TypeError(
            f"acquisition {acquisition_id!r} requires a class decorated with "
            "@result_schema"
        )
    schema = vars(result_schema_type).get(_RESULT_SCHEMA_METADATA)
    if not isinstance(schema, _ResultSchema):
        raise TypeError(
            f"acquisition {acquisition_id!r} requires a class decorated with "
            "@result_schema"
        )
    return result_schema_type, schema


def _infer_observation_dtype(annotation: object) -> MeasurementDType:
    annotation = _expand_concrete_alias(annotation)
    if annotation is bool or annotation is np.bool_:
        return "bool"
    if annotation is int or annotation is np.int64:
        return "int64"
    if annotation is float or annotation is Quantity or annotation is np.float64:
        return "float64"
    if annotation is complex or annotation is np.complex128:
        return "complex128"
    if annotation is str or annotation is np.str_:
        return "string"
    literal_choices = cast("tuple[object, ...]", get_args(annotation))
    if get_origin(annotation) is Literal and all(
        isinstance(choice, str) for choice in literal_choices
    ):
        return "string"
    raise TypeError(
        f"cannot infer a measurement dtype from member annotation {annotation!r}"
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


def _declared_members(interface_type: type[object]) -> Mapping[str, object]:
    members: dict[str, object] = {}
    for base in reversed(interface_type.__mro__):
        if base is object:
            continue
        members.update(cast("Mapping[str, object]", vars(base)))
    return members


def _declared_properties(
    scope_type: type[object],
) -> Mapping[str, Member[object]]:
    return {
        name: member
        for name, member in _declared_members(scope_type).items()
        if isinstance(member, Member)
    }


def _declared_member_annotation(
    scope_type: type[object],
    property_name: str,
    declaration: Member[object],
) -> object:
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(scope_type, include_extras=True),
    )
    annotation = hints.get(property_name)
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin not in (Member, DeviceMember) or len(arguments) != 1:
        raise TypeError(
            f"declared member {property_name!r} requires a Member[T] or "
            "DeviceMember[T] annotation"
        )
    if isinstance(declaration, DeviceMember) != (origin is DeviceMember):
        raise TypeError(
            f"declared member {property_name!r} annotation does not match its value"
        )
    return cast("tuple[object, ...]", arguments)[0]


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


def _required_interface_metadata(
    interface_type: type[object],
) -> InterfaceMetadata:
    return _required_metadata(
        interface_type,
        _INTERFACE_METADATA,
        InterfaceMetadata,
        "instrument interface",
    )


def _required_component_metadata(
    component_type: type[object],
) -> ComponentMetadata:
    return _required_metadata(
        component_type,
        _COMPONENT_METADATA,
        ComponentMetadata,
        "instrument component",
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
    "ComponentMetadata",
    "DeclaredAcquisition",
    "DeclaredDeviceProperty",
    "DeclaredInterfaceLayout",
    "DeclaredOperation",
    "DeclaredOperationArgument",
    "DeclaredProperty",
    "DeclaredPropertyLayout",
    "DeclaredPropertyTarget",
    "DeclaredResultField",
    "DeclaredResultLayout",
    "DeclaredScopeLayout",
    "DeviceMember",
    "DeviceMemberMetadata",
    "InterfaceMetadata",
    "LinearCoordinatesMetadata",
    "Member",
    "MemberMetadata",
    "MemberObservation",
    "MemberProjectionField",
    "MemberProjectionLayout",
    "OperationMetadata",
    "PreconditionMetadata",
    "PreconditionValue",
    "PropertyAccess",
    "ResultDeclaration",
    "acquisition",
    "argument",
    "array_result",
    "axis",
    "compile_interface",
    "declared_acquisition",
    "declared_acquisition_ref",
    "declared_argument_ref",
    "declared_device_properties",
    "declared_interface_layout",
    "declared_interface_ref",
    "declared_operation",
    "declared_operation_ref",
    "declared_property_ref",
    "declared_result_ref",
    "device_member",
    "instrument_component",
    "instrument_interface",
    "instrument_member_projection",
    "linear_coordinates",
    "member",
    "member_projection_assignments",
    "member_projection_field",
    "observation",
    "operation",
    "precondition",
    "result_schema",
    "scalar_result",
    "write_only_member",
]
