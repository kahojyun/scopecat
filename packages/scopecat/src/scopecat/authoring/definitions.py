"""Function-based experiment definitions lowered to the existing authoring IR."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import NoneType, UnionType
from typing import (
    Annotated,
    TypeAliasType,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from scopecat.authoring._module_handles import (
    ExperimentModule,
    ModuleBuilder,
    ModuleInvocation,
    build_module_ir,
    create_experiment_module_internal,
    module_use_invocation,
)
from scopecat.authoring._products import ProductRef, RecordSelection, record_product
from scopecat.authoring._value_refs import ValueRef, empty_frozen_mapping
from scopecat.authoring.scans import Scan, ScanCenter, ScanValue, build_scan
from scopecat.authoring.templates import (
    ExperimentDefinition,
    ExperimentInvocation,
    ExperimentTemplate,
    create_experiment_definition_internal,
)
from scopecat.authoring.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Record,
    Scalar,
    Series,
    String,
    Table,
    ValueType,
)
from scopecat.authoring.values import MetadataValue, RuntimeInput
from scopecat.authoring.values import input as authoring_input
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.quantity import Quantity as QuantityValue

type DefinitionFunction = Callable[..., object]
type Input[T] = T | ValueRef


def input_ref[T](value: Input[T]) -> ValueRef:
    """View a decorator function input as its symbolic authoring reference.

    ``@module`` and ``@template`` evaluate their Python bodies with symbolic
    values, while ``Input[T]`` also preserves the concrete caller contract.
    Use this helper only when a symbolic-only operation, such as a table
    transform, needs that distinction for static typing.
    """

    return cast("ValueRef", value)


@dataclass(frozen=True, slots=True)
class _DefinitionContract:
    """One decorator function's parsed signature and symbolic arguments."""

    signature: inspect.Signature
    arguments: tuple[tuple[str, ValueRef], ...]

    @property
    def values(self) -> dict[str, ValueRef]:
        return dict(self.arguments)


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentBody:
    """Shared return value for template and scratch definition functions."""

    module: ModuleBuilder = field(default_factory=ModuleBuilder)
    scans: tuple[Scan, ...] = ()
    record_selections: tuple[RecordSelection, ...] = ()

    def scan(
        self,
        target: ValueRef | Scan,
        values: Sequence[ScanValue] = (),
        *,
        unit: str | None = None,
        center: ScanCenter | None = None,
        span: QuantityValue | str | None = None,
        points: int | None = None,
    ) -> ExperimentBody:
        return replace(
            self,
            scans=(
                *self.scans,
                build_scan(
                    target,
                    values,
                    unit=unit,
                    center=center,
                    span=span,
                    points=points,
                ),
            ),
        )

    def record_product(
        self,
        *products: str | ProductRef,
        record_id: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ExperimentBody:
        if record_id is not None and len(products) != 1:
            raise ValueError("record_id can only be used with one product")
        return replace(
            self,
            record_selections=(
                *self.record_selections,
                *(
                    record_product(
                        product,
                        record_id=record_id,
                        metadata=metadata,
                    )
                    for product in products
                ),
            ),
        )

    def records(self, *selections: RecordSelection) -> ExperimentBody:
        return replace(
            self,
            record_selections=(*self.record_selections, *selections),
        )


@dataclass(frozen=True, slots=True, repr=False)
class ScratchDefinition[**P]:
    """A project-neutral experiment factory evaluated for each call."""

    fn: Callable[P, ExperimentBody] = field(repr=False, compare=False)
    _signature: inspect.Signature = field(repr=False, compare=False)
    id: str
    kind: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    @property
    def __wrapped__(self) -> Callable[P, ExperimentBody]:
        return self.fn

    @property
    def __name__(self) -> str:
        return self.fn.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ExperimentInvocation:
        result = self.fn(*args, **kwargs)
        body = _experiment_body(result)
        definition = _close_experiment_body(
            body,
            id=self.id,
            kind=self.kind,
            metadata=self.metadata,
            input_defaults={},
            required_inputs=(),
        )
        return ExperimentInvocation(
            definition=definition,
            inputs=empty_frozen_mapping(),
            scans=(),
        )


@overload
def module[**P](
    definition: Callable[P, ModuleBuilder],
    /,
    *,
    id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule[P]: ...


@overload
def module[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> Callable[[Callable[P, ModuleBuilder]], ExperimentModule[P]]: ...


def module[**P](
    definition: Callable[P, ModuleBuilder] | None = None,
    /,
    *,
    id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentModule[P] | Callable[[Callable[P, ModuleBuilder]], ExperimentModule[P]]:
    """Define a closed module from a Python function."""

    if definition is None:
        return lambda fn: _module_from_function(fn, id=id, metadata=metadata)
    return _module_from_function(definition, id=id, metadata=metadata)


def module_body(
    *,
    id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ModuleBuilder:
    """Start a low-level module body or an ``@module`` return value."""

    return ModuleBuilder(
        id=id,
        metadata=freeze_json_mapping(metadata or {}),
    )


def experiment(*parts: object) -> ExperimentBody:
    """Compose explicit module calls into a template or scratch body."""

    builder = ModuleBuilder()
    for part in parts:
        invocation = _module_invocation(part)
        builder = builder.use(invocation)
    return ExperimentBody(module=builder)


@overload
def template[**P](
    definition: Callable[P, ExperimentBody],
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentTemplate[P]: ...


@overload
def template[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> Callable[[Callable[P, ExperimentBody]], ExperimentTemplate[P]]: ...


def template[**P](
    definition: Callable[P, ExperimentBody] | None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    ExperimentTemplate[P]
    | Callable[[Callable[P, ExperimentBody]], ExperimentTemplate[P]]
):
    """Close a symbolic Python function as an experiment template."""

    def decorate(fn: Callable[P, ExperimentBody]) -> ExperimentTemplate[P]:
        return _template_from_function(
            fn,
            id=id,
            kind=kind,
            metadata=metadata,
        )

    return decorate(definition) if definition is not None else decorate


@overload
def scratch[**P](
    definition: Callable[P, ExperimentBody],
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ScratchDefinition[P]: ...


@overload
def scratch[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> Callable[[Callable[P, ExperimentBody]], ScratchDefinition[P]]: ...


def scratch[**P](
    definition: Callable[P, ExperimentBody] | None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    ScratchDefinition[P] | Callable[[Callable[P, ExperimentBody]], ScratchDefinition[P]]
):
    """Define a project-neutral scratch experiment factory."""

    def decorate(fn: Callable[P, ExperimentBody]) -> ScratchDefinition[P]:
        return ScratchDefinition(
            fn=fn,
            _signature=inspect.signature(fn).replace(
                return_annotation=ExperimentInvocation
            ),
            id=id or _definition_id(fn),
            kind=kind or fn.__name__,
            metadata=freeze_json_mapping(metadata or {}),
        )

    return decorate(definition) if definition is not None else decorate


def _module_from_function[**P](
    fn: Callable[P, ModuleBuilder],
    *,
    id: str | None,
    metadata: Mapping[str, MetadataValue] | None,
) -> ExperimentModule[P]:
    source = cast("DefinitionFunction", fn)
    contract = _definition_contract(source, defaults=False)
    values = contract.values
    result = source(**values)
    body = _module_body(result)
    if body.input_ports:
        raise ValueError("@module function bodies must declare inputs in the signature")
    selected_metadata = dict(metadata or {})
    doc = inspect.getdoc(fn)
    if doc is not None:
        selected_metadata.setdefault("description", doc)
    builder = replace(
        body,
        id=id or _definition_id(fn),
        input_ports=tuple(_input_port(name, value) for name, value in values.items()),
        metadata=freeze_json_mapping({**body.metadata, **selected_metadata}),
    )
    module_ir = build_module_ir(builder)
    return create_experiment_module_internal(
        module_ir,
        definition=fn,
        signature=contract.signature,
    )


def _template_from_function[**P](
    fn: Callable[P, ExperimentBody],
    *,
    id: str | None,
    kind: str | None,
    metadata: Mapping[str, MetadataValue] | None,
) -> ExperimentTemplate[P]:
    source = cast("DefinitionFunction", fn)
    contract = _definition_contract(source, defaults=True)
    signature = contract.signature
    values = contract.values
    body = _experiment_body(source(**values))
    if body.module.input_ports:
        raise ValueError(
            "@template function bodies must declare inputs in the signature"
        )
    selected_body = replace(
        body,
        module=replace(
            body.module,
            input_ports=tuple(
                _input_port(name, value) for name, value in values.items()
            ),
        ),
    )
    defaults = tuple(
        (parameter.name, cast("object", parameter.default))
        for parameter in signature.parameters.values()
    )
    input_defaults = {
        name: cast("RuntimeInput", default)
        for name, default in defaults
        if default is not inspect.Parameter.empty
    }
    required_inputs = tuple(
        name for name, default in defaults if default is inspect.Parameter.empty
    )
    definition = _close_experiment_body(
        selected_body,
        id=id or _definition_id(source),
        kind=kind or source.__name__,
        metadata=metadata,
        input_defaults=input_defaults,
        required_inputs=required_inputs,
    )
    return ExperimentTemplate(
        definition=definition,
        _callable=fn,
        _signature=contract.signature.replace(
            return_annotation=ExperimentInvocation,
        ),
    )


def _close_experiment_body(
    body: ExperimentBody,
    *,
    id: str,
    kind: str,
    metadata: Mapping[str, MetadataValue] | None,
    input_defaults: Mapping[str, RuntimeInput],
    required_inputs: Sequence[str],
) -> ExperimentDefinition:
    module_ir = build_module_ir(body.module, id=f"{id}.module")
    return create_experiment_definition_internal(
        id=id,
        kind=kind,
        module=module_ir,
        record_selections=body.record_selections,
        input_defaults=input_defaults,
        required_inputs=required_inputs,
        default_scans=body.scans,
        metadata=metadata,
    )


def _definition_contract(
    fn: DefinitionFunction,
    *,
    defaults: bool,
) -> _DefinitionContract:
    signature = inspect.signature(fn)
    hints = cast("Mapping[str, object]", get_type_hints(fn, include_extras=True))
    values: dict[str, ValueRef] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        ):
            raise TypeError("definition functions require named parameters")
        default = cast("object", parameter.default)
        if not defaults and default is not inspect.Parameter.empty:
            raise TypeError("module inputs cannot declare Python defaults")
        annotation = hints.get(
            parameter.name,
            cast("object", parameter.annotation),
        )
        values[parameter.name] = authoring_input(
            parameter.name,
            _annotation_value_type(annotation, parameter=parameter.name),
        )
    return _DefinitionContract(signature, tuple(values.items()))


def _annotation_value_type(annotation: object, *, parameter: str) -> ValueType:
    while isinstance(annotation, TypeAliasType):
        annotation = cast("object", annotation.__value__)
    if get_origin(annotation) is Annotated:
        python_type, *metadata = cast("tuple[object, ...]", get_args(annotation))
        declared = tuple(item for item in metadata if _is_value_type(item))
        if len(declared) != 1:
            raise TypeError(
                f"parameter {parameter!r} requires one ValueType in Annotated metadata"
            )
        selected = _as_value_type(declared[0])
        if not _python_annotation_matches(python_type, selected):
            raise TypeError(
                f"parameter {parameter!r} Python annotation is incompatible "
                f"with {selected!r}"
            )
        return selected
    if _is_value_type(annotation):
        return _as_value_type(annotation)
    inferred: dict[object, ValueType] = {
        bool: Scalar(Bool()),
        int: Scalar(Int()),
        float: Scalar(Float()),
        str: Scalar(String()),
        EntityRef: Scalar(Entity()),
        QuantityValue: Scalar(Quantity()),
    }
    selected = inferred.get(annotation)
    if selected is None:
        raise TypeError(
            f"parameter {parameter!r} needs a scalar Python type or Annotated ValueType"
        )
    return selected


def _is_value_type(value: object) -> bool:
    if isinstance(value, Scalar | Series | Table):
        return True
    return isinstance(
        value,
        Bool | Entity | Float | Int | Payload | Quantity | Record | String,
    )


def _as_value_type(value: object) -> ValueType:
    if isinstance(value, Scalar | Series | Table):
        return value
    if isinstance(
        value,
        Bool | Entity | Float | Int | Payload | Quantity | Record | String,
    ):
        return Scalar(value)
    raise AssertionError("value-type metadata was checked before normalization")


def _python_annotation_matches(annotation: object, value_type: ValueType) -> bool:
    if get_origin(annotation) is Input:
        [annotation] = cast("tuple[object, ...]", get_args(annotation))
    origin = get_origin(annotation)
    if origin is UnionType:
        options = cast("tuple[object, ...]", get_args(annotation))
        return all(
            (
                isinstance(value_type, Scalar)
                and value_type.nullable
                and option is NoneType
            )
            or _python_annotation_matches(option, value_type)
            for option in options
        )
    if annotation is object:
        return True
    if isinstance(value_type, Scalar):
        atom = value_type.atom
        if isinstance(atom, Payload | Record) and origin in (dict, Mapping):
            return True
        expected: dict[type[object], tuple[object, ...]] = {
            Bool: (bool,),
            Entity: (str, EntityRef),
            Float: (float,),
            Int: (int,),
            Payload: (dict, Mapping),
            Quantity: (QuantityValue,),
            Record: (dict, Mapping),
            String: (str,),
        }
        return annotation in expected[type(atom)]
    if isinstance(value_type, Series):
        if origin not in (tuple, list, Sequence):
            return False
        item_types = cast("tuple[object, ...]", get_args(annotation))
        if not item_types:
            return False
        return _python_annotation_matches(item_types[0], value_type.item_type)
    if origin not in (tuple, list, Sequence):
        return False
    row_types = cast("tuple[object, ...]", get_args(annotation))
    if not row_types:
        return False
    row_type = row_types[0]
    row_origin = get_origin(row_type)
    return (
        row_origin is dict
        or row_origin is Mapping
        or row_type is dict
        or row_type is Mapping
    )


def _input_port(name: str, value: ValueRef):
    from scopecat.authoring._intents import ModuleInputPort

    return ModuleInputPort(id=name, value_type=value.value_type)


def _module_body(value: object) -> ModuleBuilder:
    if isinstance(value, ModuleBuilder):
        return value
    raise TypeError("@module functions must return module_body()")


def _experiment_body(value: object) -> ExperimentBody:
    if isinstance(value, ExperimentBody):
        return value
    raise TypeError("template and scratch functions must return experiment() bodies")


def _module_invocation(value: object) -> ModuleInvocation:
    if isinstance(value, ExperimentModule):
        return value()
    try:
        return module_use_invocation(value)
    except TypeError as error:
        raise TypeError(
            "experiment() requires explicit module or domain-program calls"
        ) from error


def _definition_id(fn: DefinitionFunction) -> str:
    return f"{fn.__module__}.{fn.__qualname__}"


__all__ = [
    "ExperimentBody",
    "Input",
    "ScratchDefinition",
    "experiment",
    "module",
    "module_body",
    "scratch",
    "template",
]
