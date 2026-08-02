"""Function-based module and experiment definitions."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import UnionType
from typing import (
    Annotated,
    Concatenate,
    Protocol,
    TypeAliasType,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from scopecat.authoring._experiment_module import (
    ExperimentModule,
    create_experiment_module_internal,
)
from scopecat.authoring._module_context import (
    DefinitionResource,
    ModuleContext,
    build_ensure_state_intent,
)
from scopecat.authoring._module_invocation import (
    DomainCallProvider,
    ModuleInvocation,
    domain_use_call,
    module_use_invocation,
)
from scopecat.authoring.entity_parameters import PerEntity
from scopecat.authoring.finalization import Finalizable
from scopecat.authoring.scans import Scan
from scopecat.authoring.templates import (
    ExperimentTemplate,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.instrument_members import (
    AcquisitionResultRef,
    InterfaceRef,
    OperationArgumentRef,
    OperationRef,
    PropertyRef,
)
from scopecat.kernel.product_identity import parse_product_id
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.measurements.postprocessor_contract import MeasurementPostprocessorKernel
from scopecat.measurements.results import MeasurementDType
from scopecat.program.bindings import BindingIntent
from scopecat.program.definitions import (
    ExperimentDef,
    ExperimentInvocation,
    create_experiment_def,
)
from scopecat.program.domain import DomainCall
from scopecat.program.input_capture import empty_program_mapping
from scopecat.program.operations import ModuleInputPort
from scopecat.program.products import (
    ProductAxis,
    ProductRecording,
    ProductRef,
    RecordSelection,
    record_coordinate,
    record_product,
)
from scopecat.program.state import DesiredState, StateBinding
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
)
from scopecat.program.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Scalar,
    String,
    Table,
    ValueType,
)
from scopecat.program.values import (
    ComputeFunction,
    ComputeInput,
    MetadataValue,
    RuntimeInput,
)
from scopecat.program.values import input as authoring_input

# pyright: reportPrivateUsage=false

type DefinitionFunction = Callable[..., object]
type Input[T] = T | ValueRef


class _RecordableProducts(Protocol):
    """Internal structural hook implemented by generated result bundles."""

    def _recording_products(self) -> tuple[ProductRef, ...]: ...


type RecordProductInput = (
    ProductRef | _RecordableProducts | PerEntity[ProductRef | _RecordableProducts]
)


def input_ref[T](value: Input[T]) -> ValueRef:
    """View a decorator function input as its symbolic authoring reference.

    ``@module`` and ``@template`` evaluate their Python bodies with symbolic
    values, while ``Input[T]`` also preserves the concrete caller contract.
    Use this helper only when a symbolic-only operation, such as a table
    transform, needs that distinction for static typing.
    """

    return cast("ValueRef", value)


def _expand_record_products(
    products: Sequence[RecordProductInput],
) -> tuple[ProductRef, ...]:
    selected: list[ProductRef] = []
    for product in products:
        if isinstance(product, PerEntity):
            for value in product.values():
                _append_record_product(selected, value)
            continue
        _append_record_product(selected, product)
    return tuple(selected)


def _append_record_product(
    selected: list[ProductRef],
    product: ProductRef | _RecordableProducts,
) -> None:
    if isinstance(product, ProductRef):
        selected.append(product)
        return
    selected.extend(product._recording_products())


def _recording_role_is_coordinate(product: ProductRef) -> bool:
    return product._recording_role == "coordinate"


def _record_namespace_segments(namespace: str) -> tuple[str, ...]:
    if not namespace:
        raise ValueError("record namespace must be non-empty")
    namespace_id = parse_product_id(namespace)
    return (*namespace_id.scope, namespace_id.local_id)


def _namespaced_record_id(
    product: ProductRef,
    namespace: tuple[str, ...],
) -> str:
    return product.product_id.prefixed(*namespace).qualified_name


def _recording_group_id(
    product: ProductRef,
    namespace: tuple[str, ...],
) -> str | None:
    if product._recording is None:
        return None
    return product._recording.occurrence.prefixed(*namespace).qualified_name


@dataclass(frozen=True, slots=True)
class _DefinitionContract:
    """One decorator function's parsed signature and symbolic arguments."""

    signature: inspect.Signature
    arguments: tuple[tuple[str, ValueRef], ...]

    @property
    def values(self) -> dict[str, ValueRef]:
        return dict(self.arguments)


class ExperimentContext:
    """Explicit recorder injected into one template or scratch definition."""

    __slots__ = (
        "_final_state_bindings",
        "_program",
        "_record_selections",
        "_scans",
    )

    def __init__(self) -> None:
        self._program = ModuleContext()
        self._scans: list[Scan] = []
        self._record_selections: list[RecordSelection] = []
        self._final_state_bindings: list[BindingIntent] = []

    def close_definition_internal(
        self,
        *,
        id: str,
        kind: str,
        metadata: Mapping[str, MetadataValue] | None,
        input_ports: Sequence[ModuleInputPort] = (),
        input_defaults: Mapping[str, RuntimeInput],
        required_inputs: Sequence[str],
    ) -> ExperimentDef:
        """Freeze this context directly as one experiment definition."""

        interface, body, python_implementations = (
            self._program.close_experiment_parts_internal(
                input_ports=input_ports,
            )
        )
        return create_experiment_def(
            id=id,
            kind=kind,
            interface=interface,
            body=body,
            python_implementations=python_implementations,
            record_selections=self._record_selections,
            input_defaults=input_defaults,
            required_inputs=required_inputs,
            default_scans=self._scans,
            final_state_bindings=self._final_state_bindings,
            metadata=metadata,
        )

    @overload
    def run(self, part: ExperimentModule[...]) -> ModuleInvocation: ...

    @overload
    def run(self, part: ModuleInvocation) -> ModuleInvocation: ...

    @overload
    def run(self, part: DomainCall) -> DomainCall: ...

    @overload
    def run[T: DomainCallProvider](self, part: T) -> T: ...

    def run(
        self,
        part: object,
    ) -> object:
        """Append one module or domain occurrence to the root experiment."""

        if isinstance(part, DomainCall) or isinstance(
            getattr(part, "domain_call", None),
            DomainCall,
        ):
            call = domain_use_call(part)
            self._program.append_domain_call_internal(call)
            return part
        invocation = _module_invocation(part)
        self._program.append_invocation_internal(invocation)
        return invocation

    def _resource(
        self,
        id: str,
        *,
        requires: Sequence[InterfaceRef] = (),
        for_entities: Sequence[ValueRef] = (),
    ) -> DefinitionResource:
        """Declare a logical resource for a generated symbolic client."""

        return self._program._resource(
            id,
            requires=requires,
            for_entities=for_entities,
        )

    def _bind_property(
        self,
        resource: DefinitionResource,
        property: PropertyRef,
        *,
        value: StateBinding,
    ) -> None:
        """Bind a property for an internal authoring extension."""

        self._program._bind_property(resource, property, value=value)

    def _ensure(
        self,
        resource: DefinitionResource,
        target: DesiredState,
    ) -> None:
        """Declare a target state for a generated symbolic client."""

        self._program._ensure(resource, target)

    def _invoke(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        operation: OperationRef,
        arguments: Mapping[OperationArgumentRef, StateBinding | None] | None = None,
    ) -> None:
        """Append an operation for a generated symbolic client."""

        self._program._invoke(
            id,
            resource=resource,
            operation=operation,
            arguments=arguments,
        )

    def _product(
        self,
        id: str,
        *,
        scope: Sequence[str] = (),
        unit: str | None = "ratio",
        dtype: MeasurementDType = "float64",
        axes: Sequence[ProductAxis] = (),
        recording: ProductRecording | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ProductRef:
        """Declare a logical product for a generated acquisition or producer."""

        return self._program._product(
            id,
            scope=scope,
            unit=unit,
            dtype=dtype,
            axes=axes,
            recording=recording,
            metadata=metadata,
        )

    def _acquire(
        self,
        id: str,
        *,
        resource: DefinitionResource,
        results: Mapping[AcquisitionResultRef, ProductRef],
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        """Map acquisition results for a generated symbolic client."""

        self._program._acquire(
            id,
            resource=resource,
            results=results,
            metadata=metadata,
        )

    def compute(
        self,
        id: str,
        *,
        fn: ComputeFunction,
        inputs: Mapping[str, ComputeInput] | None = None,
        output_type: Scalar,
    ) -> ValueRef:
        """Declare one experiment-owned compute node and return its result."""

        return self._program.compute(
            id,
            fn=fn,
            inputs=inputs,
            output_type=output_type,
        )

    def _postprocess(
        self,
        id: str,
        *,
        input: ProductRef,
        outputs: Mapping[str, ProductRef],
        kernel: MeasurementPostprocessorKernel,
    ) -> None:
        """Register a typed producer's point-local measurement calculation."""

        self._program._postprocess(
            id,
            input=input,
            outputs=outputs,
            kernel=kernel,
        )

    def scan(self, *scans: Scan) -> None:
        """Declare the experiment's default point-domain scans."""

        self._scans.extend(scans)

    def record(
        self,
        *products: RecordProductInput,
        record_id: str | None = None,
        namespace: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        """Select typed product references under an optional output prefix."""

        if record_id is not None and namespace is not None:
            raise ValueError("record_id and namespace cannot be used together")
        namespace_segments = (
            () if namespace is None else _record_namespace_segments(namespace)
        )
        selected_products = _expand_record_products(products)
        if record_id is not None and len(selected_products) != 1:
            raise ValueError("record_id can only be used with one product")
        self._record_selections.extend(
            (
                record_coordinate
                if _recording_role_is_coordinate(product)
                else record_product
            )(
                product,
                record_id=(
                    _namespaced_record_id(product, namespace_segments)
                    if namespace_segments
                    else record_id
                ),
                recording_group_id=(
                    _recording_group_id(product, namespace_segments)
                    if namespace_segments
                    else None
                ),
                metadata=metadata,
            )
            for product in selected_products
        )

    def finalize[StateT](
        self,
        resource: Finalizable[StateT],
        target: StateT,
    ) -> None:
        """Declare typed state after normal experiment completion."""

        for logical_resource, desired_state in resource.finalization_targets(target):
            self._append_finalization_target(logical_resource, desired_state)

    def _append_finalization_target(
        self,
        resource: DefinitionResource,
        target: DesiredState,
    ) -> None:
        """Validate and append one normalized final-state target."""

        self._program.require_owned_resource_internal(resource)
        intent = build_ensure_state_intent(resource.port_id, target)
        for assignment in intent.assignments:
            value = assignment.value
            if not isinstance(value, ValueRef):
                continue
            if internal_value_ref_requires_execution(value):
                raise ValueError(
                    "experiment final_state cannot depend on point-local compute"
                )
            if internal_value_ref_point_dependencies(value):
                raise ValueError(
                    "experiment final_state cannot depend on scan coordinates"
                )
        self._final_state_bindings.extend(intent.assignments)


@dataclass(frozen=True, slots=True, repr=False)
class ScratchDefinition[**P]:
    """A project-neutral experiment factory evaluated for each call."""

    fn: Callable[Concatenate[ExperimentContext, P], None] = field(
        repr=False,
        compare=False,
    )
    _signature: inspect.Signature = field(repr=False, compare=False)
    id: str
    kind: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_program_mapping)

    @property
    def __wrapped__(self) -> Callable[Concatenate[ExperimentContext, P], None]:
        return self.fn

    @property
    def __name__(self) -> str:
        return self.fn.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ExperimentInvocation:
        context = ExperimentContext()
        result = self.fn(context, *args, **kwargs)
        _require_definition_none(result, kind="scratch")
        definition = context.close_definition_internal(
            id=self.id,
            kind=self.kind,
            metadata=self.metadata,
            input_defaults={},
            required_inputs=(),
        )
        return ExperimentInvocation(
            definition=definition,
            inputs=empty_program_mapping(),
            scans=(),
        )


@overload
def module[**P](
    definition: Callable[Concatenate[ModuleContext, P], None],
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
) -> Callable[
    [Callable[Concatenate[ModuleContext, P], None]],
    ExperimentModule[P],
]: ...


def module[**P](
    definition: Callable[Concatenate[ModuleContext, P], None] | None = None,
    /,
    *,
    id: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    ExperimentModule[P]
    | Callable[
        [Callable[Concatenate[ModuleContext, P], None]],
        ExperimentModule[P],
    ]
):
    """Define a closed module from a Python function."""

    if definition is None:
        return lambda fn: _module_from_function(fn, id=id, metadata=metadata)
    return _module_from_function(definition, id=id, metadata=metadata)


@overload
def template[**P](
    definition: Callable[Concatenate[ExperimentContext, P], None],
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
) -> Callable[
    [Callable[Concatenate[ExperimentContext, P], None]],
    ExperimentTemplate[P],
]: ...


def template[**P](
    definition: Callable[Concatenate[ExperimentContext, P], None] | None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    ExperimentTemplate[P]
    | Callable[
        [Callable[Concatenate[ExperimentContext, P], None]],
        ExperimentTemplate[P],
    ]
):
    """Close a symbolic Python function as an experiment template."""

    def decorate(
        fn: Callable[Concatenate[ExperimentContext, P], None],
    ) -> ExperimentTemplate[P]:
        return _template_from_function(
            fn,
            id=id,
            kind=kind,
            metadata=metadata,
        )

    return decorate(definition) if definition is not None else decorate


@overload
def scratch[**P](
    definition: Callable[Concatenate[ExperimentContext, P], None],
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
) -> Callable[
    [Callable[Concatenate[ExperimentContext, P], None]],
    ScratchDefinition[P],
]: ...


def scratch[**P](
    definition: Callable[Concatenate[ExperimentContext, P], None] | None = None,
    /,
    *,
    id: str | None = None,
    kind: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> (
    ScratchDefinition[P]
    | Callable[
        [Callable[Concatenate[ExperimentContext, P], None]],
        ScratchDefinition[P],
    ]
):
    """Define a project-neutral scratch experiment factory."""

    def decorate(
        fn: Callable[Concatenate[ExperimentContext, P], None],
    ) -> ScratchDefinition[P]:
        signature = _context_signature(fn, ExperimentContext)
        return ScratchDefinition(
            fn=fn,
            _signature=signature.replace(return_annotation=ExperimentInvocation),
            id=id or _definition_id(fn),
            kind=kind or fn.__name__,
            metadata=freeze_json_mapping(metadata or {}),
        )

    return decorate(definition) if definition is not None else decorate


def _module_from_function[**P](
    fn: Callable[Concatenate[ModuleContext, P], None],
    *,
    id: str | None,
    metadata: Mapping[str, MetadataValue] | None,
) -> ExperimentModule[P]:
    source = cast("DefinitionFunction", fn)
    contract = _definition_contract(
        source,
        defaults=False,
        context_type=ModuleContext,
    )
    values = contract.values
    context = ModuleContext()
    result = source(context, **values)
    _require_definition_none(result, kind="module")
    selected_metadata = dict(metadata or {})
    doc = inspect.getdoc(fn)
    if doc is not None:
        selected_metadata.setdefault("description", doc)
    module_def = context.close_definition_internal(
        id=id or _definition_id(fn),
        input_ports=tuple(_input_port(name, value) for name, value in values.items()),
        metadata=selected_metadata,
    )
    return create_experiment_module_internal(
        module_def,
        definition=cast("Callable[P, object]", fn),
        signature=contract.signature,
    )


def _template_from_function[**P](
    fn: Callable[Concatenate[ExperimentContext, P], None],
    *,
    id: str | None,
    kind: str | None,
    metadata: Mapping[str, MetadataValue] | None,
) -> ExperimentTemplate[P]:
    source = cast("DefinitionFunction", fn)
    contract = _definition_contract(
        source,
        defaults=True,
        context_type=ExperimentContext,
    )
    signature = contract.signature
    values = contract.values
    context = ExperimentContext()
    result = source(context, **values)
    _require_definition_none(result, kind="template")
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
    definition = context.close_definition_internal(
        id=id or _definition_id(source),
        kind=kind or source.__name__,
        metadata=metadata,
        input_ports=tuple(_input_port(name, value) for name, value in values.items()),
        input_defaults=input_defaults,
        required_inputs=required_inputs,
    )
    return ExperimentTemplate(
        definition=definition,
        _callable=cast("Callable[P, object]", fn),
        _signature=contract.signature.replace(
            return_annotation=ExperimentInvocation,
        ),
    )


def _definition_contract(
    fn: DefinitionFunction,
    *,
    defaults: bool,
    context_type: type[object],
) -> _DefinitionContract:
    signature = _context_signature(fn, context_type)
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


def _context_signature(
    fn: DefinitionFunction,
    context_type: type[object],
) -> inspect.Signature:
    signature = inspect.signature(fn)
    parameters = tuple(signature.parameters.values())
    if not parameters:
        raise TypeError(
            f"definition function requires a leading {context_type.__name__} parameter"
        )
    context = parameters[0]
    hints = cast("Mapping[str, object]", get_type_hints(fn, include_extras=True))
    annotation = hints.get(context.name, cast("object", context.annotation))
    if annotation is not context_type:
        raise TypeError(
            f"first definition parameter must be annotated as {context_type.__name__}"
        )
    if context.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD:
        raise TypeError("definition context must be the first positional parameter")
    return signature.replace(parameters=parameters[1:])


def _require_definition_none(value: object, *, kind: str) -> None:
    if value is not None:
        raise TypeError(f"@{kind} definition functions must return None")


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
    if isinstance(value, Scalar | Table):
        return True
    return isinstance(
        value,
        Bool | Entity | Float | Int | Payload | Quantity | String,
    )


def _as_value_type(value: object) -> ValueType:
    if isinstance(value, Scalar | Table):
        return value
    if isinstance(
        value,
        Bool | Entity | Float | Int | Payload | Quantity | String,
    ):
        return Scalar(value)
    raise AssertionError("value-type metadata was checked before normalization")


def _python_annotation_matches(annotation: object, value_type: ValueType) -> bool:
    if get_origin(annotation) is Input:
        [annotation] = cast("tuple[object, ...]", get_args(annotation))
    origin = get_origin(annotation)
    if origin is UnionType:
        return all(
            _python_annotation_matches(option, value_type)
            for option in cast("tuple[object, ...]", get_args(annotation))
        )
    if annotation is object:
        return True
    if isinstance(value_type, Scalar):
        atom = value_type.atom
        if isinstance(atom, Payload) and origin in (dict, Mapping):
            return True
        expected: dict[type[object], tuple[object, ...]] = {
            Bool: (bool,),
            Entity: (str, EntityRef),
            Float: (float,),
            Int: (int,),
            Payload: (dict, Mapping),
            Quantity: (QuantityValue,),
            String: (str,),
        }
        return annotation in expected[type(atom)]
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


def _input_port(name: str, value: ValueRef) -> ModuleInputPort:
    return ModuleInputPort(id=name, value_type=value.value_type)


def _module_invocation(value: object) -> ModuleInvocation:
    if isinstance(value, ExperimentModule):
        return value()
    try:
        return module_use_invocation(value)
    except TypeError as error:
        raise TypeError(
            "ExperimentContext.run() requires a module or domain call"
        ) from error


def _definition_id(fn: DefinitionFunction) -> str:
    return f"{fn.__module__}.{fn.__qualname__}"


__all__ = [
    "ExperimentContext",
    "Input",
    "ScratchDefinition",
    "input_ref",
    "module",
    "scratch",
    "template",
]
