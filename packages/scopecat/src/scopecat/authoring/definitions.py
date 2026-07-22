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
    override,
)

from scopecat.authoring._frozen_values import empty_frozen_mapping
from scopecat.authoring._module_construction import (
    build_module_from_builder,
    module_use_invocation,
)
from scopecat.authoring._module_handles import (
    ExperimentModule,
    ModuleBuilder,
    ModuleCall,
    ModuleInvocation,
)
from scopecat.authoring._products import ProductRef, RecordSelection, record_product
from scopecat.authoring._validation import validate_template_definition
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.scans import Scan, ScanCenter, ScanValue, build_scan
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
    InputDescription,
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
from scopecat.authoring.values import MetadataValue, ModuleInput, RuntimeInput
from scopecat.authoring.values import input as authoring_input
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity as QuantityValue

type DefinitionFunction = Callable[..., object]
type Input[T] = T | ValueRef
type ModuleBodyResult = (
    ModuleBuilder
    | ExperimentModule
    | ModuleInvocation
    | ModuleCall
    | Sequence[ModuleInvocation | ModuleCall]
    | None
)


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
    inputs: tuple[InputDescription, ...] = ()

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

    def describe_input(
        self,
        id: str,  # noqa: A002
        *,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ExperimentBody:
        """Add presentation metadata to an input declared in the signature."""

        selected = InputDescription(
            id=id,
            label=label,
            description=description,
            metadata=metadata or {},
        )
        return replace(self, inputs=(*self.inputs, selected))


class ModuleDefinition[**P](ExperimentModule):
    """A closed module retaining its Python definition's call contract."""

    __slots__ = ("_contract", "_definition", "_signature")

    _contract: _DefinitionContract
    _definition: Callable[P, ModuleBodyResult]
    _signature: inspect.Signature

    def __init__(
        self,
        module: ExperimentModule,
        definition: Callable[P, ModuleBodyResult],
        contract: _DefinitionContract,
    ) -> None:
        super().__init__(_ir=module.ir)
        self._definition = definition
        self._contract = contract
        self._signature = contract.signature.replace(return_annotation=ModuleInvocation)

    @property
    def __wrapped__(self) -> Callable[P, ModuleBodyResult]:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    @override
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ModuleInvocation:
        bound = self._contract.signature.bind(*args, **kwargs)
        return self.instantiate(
            self.id.rsplit(".", maxsplit=1)[-1],
            cast("Mapping[str, ModuleInput]", bound.arguments),
        )


class TemplateDefinition[**P](ExperimentTemplate):
    """A closed template retaining its Python definition's call contract."""

    __slots__ = ("_contract", "_definition", "_signature")

    _contract: _DefinitionContract
    _definition: Callable[P, ExperimentBody]
    _signature: inspect.Signature

    def __init__(
        self,
        template: ExperimentTemplate,
        definition: Callable[P, ExperimentBody],
        contract: _DefinitionContract,
    ) -> None:
        super().__init__(
            id=template.id,
            kind=template.kind,
            module=template.module,
            record_selections=template.record_selections,
            inputs=template.inputs,
            default_scans=template.default_scans,
            label=template.label,
            description=template.description,
            metadata=template.metadata,
        )
        self._definition = definition
        self._contract = contract
        self._signature = contract.signature.replace(
            return_annotation=ExperimentInvocation
        )

    @property
    def __wrapped__(self) -> Callable[P, ExperimentBody]:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    @override
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ExperimentInvocation:
        bound = self._contract.signature.bind(*args, **kwargs)
        return self.bind(**cast("dict[str, RuntimeInput]", dict(bound.arguments)))


@dataclass(frozen=True, slots=True, repr=False)
class ScratchDefinition[**P]:
    """A workspace-neutral experiment factory evaluated for each call."""

    fn: Callable[P, ExperimentBody] = field(repr=False, compare=False)
    _signature: inspect.Signature = field(repr=False, compare=False)
    id: str
    kind: str
    label: str | None = None
    description: str | None = None
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
        template = _close_experiment_body(
            body,
            id=self.id,
            kind=self.kind,
            label=self.label,
            description=self.description,
            metadata=self.metadata,
        )
        return template.bind()


@overload
def module[**P](
    definition: Callable[P, ModuleBodyResult],
    /,
    *,
    id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ModuleDefinition[P]: ...


@overload
def module[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> Callable[[Callable[P, ModuleBodyResult]], ModuleDefinition[P]]: ...


def module[**P](
    definition: Callable[P, ModuleBodyResult] | None = None,
    /,
    *,
    id: str | None = None,  # noqa: A002
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    ModuleDefinition[P] | Callable[[Callable[P, ModuleBodyResult]], ModuleDefinition[P]]
):
    """Define a closed module from a Python function."""

    if definition is None:
        return lambda fn: _module_from_function(fn, id=id, metadata=metadata)
    return _module_from_function(definition, id=id, metadata=metadata)


def module_body(
    *,
    id: str | None = None,  # noqa: A002
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
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> TemplateDefinition[P]: ...


@overload
def template[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> Callable[[Callable[P, ExperimentBody]], TemplateDefinition[P]]: ...


def template[**P](
    definition: Callable[P, ExperimentBody] | None = None,
    /,
    *,
    id: str | None = None,  # noqa: A002
    kind: str | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    TemplateDefinition[P]
    | Callable[[Callable[P, ExperimentBody]], TemplateDefinition[P]]
):
    """Close a symbolic Python function as an experiment template."""

    def decorate(fn: Callable[P, ExperimentBody]) -> TemplateDefinition[P]:
        return _template_from_function(
            fn,
            id=id,
            kind=kind,
            label=label,
            description=description,
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
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ScratchDefinition[P]: ...


@overload
def scratch[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> Callable[[Callable[P, ExperimentBody]], ScratchDefinition[P]]: ...


def scratch[**P](
    definition: Callable[P, ExperimentBody] | None = None,
    /,
    *,
    id: str | None = None,  # noqa: A002
    kind: str | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    ScratchDefinition[P] | Callable[[Callable[P, ExperimentBody]], ScratchDefinition[P]]
):
    """Define a workspace-neutral scratch experiment factory."""

    def decorate(fn: Callable[P, ExperimentBody]) -> ScratchDefinition[P]:
        return ScratchDefinition(
            fn=fn,
            _signature=inspect.signature(fn).replace(
                return_annotation=ExperimentInvocation
            ),
            id=id or _definition_id(fn),
            kind=kind or fn.__name__,
            label=label,
            description=description or inspect.getdoc(fn),
            metadata=freeze_json_mapping(metadata or {}),
        )

    return decorate(definition) if definition is not None else decorate


def _module_from_function[**P](
    fn: Callable[P, ModuleBodyResult],
    *,
    id: str | None,  # noqa: A002
    metadata: Mapping[str, MetadataValue] | None,
) -> ModuleDefinition[P]:
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
    return ModuleDefinition(build_module_from_builder(builder), fn, contract)


def _template_from_function[**P](
    fn: Callable[P, ExperimentBody],
    *,
    id: str | None,  # noqa: A002
    kind: str | None,
    label: str | None,
    description: str | None,
    metadata: Mapping[str, MetadataValue] | None,
) -> TemplateDefinition[P]:
    source = cast("DefinitionFunction", fn)
    contract = _definition_contract(source, defaults=True)
    signature = contract.signature
    values = contract.values
    body = _experiment_body(source(**values))
    if body.module.input_ports:
        raise ValueError(
            "@template function bodies must declare inputs in the signature"
        )
    inferred_inputs = tuple(
        _input_description(parameter) for parameter in signature.parameters.values()
    )
    descriptions_by_id = {item.id: item for item in body.inputs}
    if len(descriptions_by_id) != len(body.inputs):
        duplicates = sorted(
            input_id
            for input_id in descriptions_by_id
            if sum(item.id == input_id for item in body.inputs) > 1
        )
        rendered = ", ".join(repr(item) for item in duplicates)
        raise ValueError(f"template inputs are declared twice: {rendered}")
    inferred_ids = {item.id for item in inferred_inputs}
    unknown_descriptions = sorted(set(descriptions_by_id) - inferred_ids)
    if unknown_descriptions:
        rendered = ", ".join(repr(item) for item in unknown_descriptions)
        raise ValueError(
            f"template input descriptions require signature ports: {rendered}"
        )
    selected_inputs = tuple(
        _merge_input_description(item, descriptions_by_id.get(item.id))
        for item in inferred_inputs
    )
    selected_body = replace(
        body,
        module=replace(
            body.module,
            input_ports=tuple(
                _input_port(name, value) for name, value in values.items()
            ),
        ),
        inputs=selected_inputs,
    )
    return TemplateDefinition(
        _close_experiment_body(
            selected_body,
            id=id or _definition_id(source),
            kind=kind or source.__name__,
            label=label,
            description=description or inspect.getdoc(source),
            metadata=metadata,
        ),
        fn,
        contract,
    )


def _close_experiment_body(
    body: ExperimentBody,
    *,
    id: str,  # noqa: A002
    kind: str,
    label: str | None,
    description: str | None,
    metadata: Mapping[str, MetadataValue] | None,
) -> ExperimentTemplate:
    module_handle = body.module.build(id=f"{id}.module")
    template_handle = ExperimentTemplate(
        id=id,
        kind=kind,
        module=module_handle,
        record_selections=body.record_selections,
        inputs=body.inputs,
        default_scans=body.scans,
        label=label,
        description=description,
        metadata=freeze_json_mapping(metadata or {}),
    )
    validate_template_definition(
        module=template_handle.module,
        inputs=template_handle.inputs,
        default_scans=template_handle.default_scans,
        record_selections=template_handle.record_selections,
    )
    return template_handle


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


def _input_description(parameter: inspect.Parameter) -> InputDescription:
    default = cast("object", parameter.default)
    if default is inspect.Parameter.empty:
        return InputDescription(id=parameter.name)
    return InputDescription(
        id=parameter.name,
        default=cast("RuntimeInput", default),
    )


def _merge_input_description(
    inferred: InputDescription,
    declared: InputDescription | None,
) -> InputDescription:
    if declared is None:
        return inferred
    return replace(
        inferred,
        label=declared.label,
        description=declared.description,
        metadata=freeze_json_mapping({**inferred.metadata, **declared.metadata}),
    )


def _module_body(value: ModuleBodyResult | object) -> ModuleBuilder:
    if value is None:
        return ModuleBuilder()
    if isinstance(value, ModuleBuilder):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        invocations: list[ModuleInvocation] = []
        for item in cast("Sequence[object]", value):
            try:
                invocation = module_use_invocation(item)
            except TypeError:
                break
            invocations.append(invocation)
        else:
            return ModuleBuilder().use(*invocations)
    try:
        return ModuleBuilder().use(_module_invocation(cast("object", value)))
    except TypeError:
        pass
    raise TypeError(
        "@module functions must return a module body, module call, or module calls"
    )


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
    "ModuleDefinition",
    "ScratchDefinition",
    "TemplateDefinition",
    "experiment",
    "module",
    "module_body",
    "scratch",
    "template",
]
