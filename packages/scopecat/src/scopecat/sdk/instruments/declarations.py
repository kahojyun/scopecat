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
    InterfaceRef,
    PropertyRef,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Bool as BoolType
from scopecat.kernel.value_types import Float as FloatType
from scopecat.kernel.value_types import Int as IntType
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.kernel.value_types import String as StringType
from scopecat.measurements.results import MeasurementDType
from scopecat.program.state import StateBinding
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments.contracts import (
    AcquisitionAxisSpec,
    AcquisitionResultSpec,
    AcquisitionSpec,
    FixedAcquisitionSpec,
    InterfaceSpec,
    PropertySpec,
)
from scopecat.sdk.instruments.contracts import (
    acquisition as build_acquisition,
)
from scopecat.sdk.instruments.contracts import (
    acquisition_axis as build_acquisition_axis,
)
from scopecat.sdk.instruments.contracts import (
    acquisition_result as build_acquisition_result,
)
from scopecat.sdk.instruments.contracts import (
    interface as build_interface,
)

type PropertyAccess = Literal["read_only", "write_only", "read_write"]
type AxisSize = int | str

_STATE_METADATA = "__scopecat_instrument_state__"
_RESULT_METADATA = "__scopecat_instrument_result__"
_INTERFACE_METADATA = "__scopecat_instrument_interface__"
_ACQUISITION_METADATA = "__scopecat_instrument_acquisition__"
_STATE_INTERFACES_METADATA = "__scopecat_instrument_state_interfaces__"


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
class AxisMetadata:
    """One acquisition axis, with either a fixed or state-owned size."""

    size: AxisSize
    kind: str | None = None
    unit: str | None = None
    label: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class InterfaceMetadata:
    id: str
    state: type[object] | None
    label: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionMetadata:
    id: str | None
    axes: tuple[tuple[str, AxisMetadata], ...]
    label: str | None
    description: str | None


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


def instrument_result[ClassT: type[object]](cls: ClassT) -> ClassT:
    """Mark an existing dataclass as acquisition results without replacing it."""

    setattr(cls, _RESULT_METADATA, True)
    return cls


def instrument_interface[ClassT: type[object]](
    id: str,
    *,
    state: type[object] | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Callable[[ClassT], ClassT]:
    """Attach stable interface identity and state metadata to a typed class."""

    declaration = InterfaceMetadata(
        id=id,
        state=state,
        label=label,
        description=description,
    )

    def decorate(cls: ClassT) -> ClassT:
        setattr(cls, _INTERFACE_METADATA, declaration)
        if state is not None:
            interface_ids = cast(
                "tuple[str, ...]",
                getattr(state, _STATE_INTERFACES_METADATA, ()),
            )
            if id not in interface_ids:
                setattr(state, _STATE_INTERFACES_METADATA, (*interface_ids, id))
        return cls

    return decorate


def acquisition[**P, ReturnT](
    *,
    id: str | None = None,
    axes: Mapping[str, AxisMetadata] | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Callable[[Callable[P, ReturnT]], Callable[P, ReturnT]]:
    """Mark an existing method as a fixed acquisition without wrapping it."""

    declaration = AcquisitionMetadata(
        id=id,
        axes=() if axes is None else tuple(axes.items()),
        label=label,
        description=description,
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
    properties = [] if declaration.state is None else _compile_state(declaration.state)
    acquisitions: list[AcquisitionSpec] = []
    for method_name, method in _declared_members(interface_type).items():
        acquisition_declaration = getattr(method, _ACQUISITION_METADATA, None)
        if not isinstance(acquisition_declaration, AcquisitionMetadata):
            continue
        acquisitions.append(
            _compile_acquisition(
                method_name,
                cast("Callable[..., object]", method),
                acquisition_declaration,
                interface_id=declaration.id,
            )
        )
    spec = build_interface(
        declaration.id,
        label=declaration.label,
        description=declaration.description,
        properties=properties,
        acquisitions=acquisitions,
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
    assignments: dict[PropertyRef, StateBinding] = {}
    for state_field in fields(state):
        value = cast("object", getattr(state, state_field.name))
        if value is not None:
            assignments[declared_property_ref(state_type, state_field.name)] = cast(
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
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(cast("Callable[..., object]", method), include_extras=True),
    )
    result_type = hints.get("return")
    if result_type is None:
        raise TypeError(
            f"acquisition method {method_name!r} requires a return annotation"
        )
    result_class = get_origin(result_type) or result_type
    if not isinstance(result_class, type):
        raise TypeError(f"acquisition method {method_name!r} has invalid result type")
    result_id = _declared_dataclass_field_id(
        result_class,
        field_name,
        metadata_type=ResultMetadata,
        label="result",
    )
    return declared_acquisition_ref(interface_type, method_name).result(result_id)


def _compile_state(state_type: type[object]) -> list[PropertySpec]:
    _required_metadata(
        state_type,
        _STATE_METADATA,
        bool,
        "instrument state",
    )
    if not is_dataclass(state_type):
        raise TypeError("instrument state must be a dataclass")
    hints = cast(
        "Mapping[str, object]",
        get_type_hints(state_type, include_extras=True),
    )
    properties: list[PropertySpec] = []
    for state_field in fields(state_type):
        annotation = hints.get(state_field.name)
        if annotation is None:
            raise TypeError(f"state field {state_field.name!r} must be annotated")
        base, metadata = _split_annotation(annotation, MemberMetadata)
        properties.append(
            _compile_property(
                state_field.name,
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
        access=metadata.access,
        value_type=Scalar(atom),
    )


def _compile_acquisition(
    method_name: str,
    method: Callable[..., object],
    declaration: AcquisitionMetadata,
    *,
    interface_id: str,
) -> FixedAcquisitionSpec:
    parameters = tuple(signature(method).parameters.values())
    if (
        len(parameters) != 1
        or parameters[0].name != "self"
        or parameters[0].kind
        not in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    ):
        raise TypeError(
            f"fixed acquisition method {method_name!r} must accept only self"
        )
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
                else InterfaceRef(interface_id).property(axis_metadata.size)
            ),
            kind=axis_metadata.kind,
            unit=axis_metadata.unit,
            label=axis_metadata.label,
            description=axis_metadata.description,
        )
        for axis_id, axis_metadata in declaration.axes
    }
    results = _compile_results(
        result_type,
        acquisition_id=declaration.id or method_name,
        axes=axes,
    )
    return build_acquisition(
        declaration.id or method_name,
        label=declaration.label,
        description=declaration.description,
        results=results,
    )


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
    return cast("Mapping[str, object]", vars(interface_type))


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
    "AcquisitionMetadata",
    "AxisMetadata",
    "AxisSize",
    "CompiledInterface",
    "CompiledStateTarget",
    "InterfaceMetadata",
    "MemberMetadata",
    "PropertyAccess",
    "ResultMetadata",
    "acquisition",
    "axis",
    "compile_interface",
    "declared_acquisition_ref",
    "declared_interface_ref",
    "declared_property_ref",
    "declared_result_ref",
    "declared_state_assignments",
    "declared_state_target",
    "instrument_interface",
    "instrument_result",
    "instrument_state",
    "member",
    "result",
]
