"""Closed module definitions exposed through a Python call contract."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

from scopecat.authoring._module_invocation import (
    ModuleInvocation,
    create_module_invocation,
)
from scopecat.authoring._module_results import relocate_module_result
from scopecat.kernel.frozen import FrozenMapping
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.program.input_capture import capture_module_inputs, empty_program_mapping
from scopecat.program.module import ModuleDef
from scopecat.program.products import ProductRef, ProductRefs
from scopecat.program.value_refs import ValueRef, internal_literal_value_ref
from scopecat.program.value_types import ValueType
from scopecat.program.values import MetadataValue, ModuleInput

type _ModuleBuilder[ResultT] = Callable[
    [str, Mapping[str, object]],
    ModuleInvocation[ResultT],
]


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentModule[ResultT, **P]:
    """Typed module handle; structural arguments specialize it on invocation."""

    _module_def: ModuleDef | None = field(repr=False)
    _authoring_fn: Callable[P, ResultT] = field(
        repr=False,
        compare=False,
    )
    _signature: inspect.Signature = field(repr=False, compare=False)
    _result: ResultT = field(repr=False, compare=False)
    _id: str
    _metadata: Mapping[str, MetadataValue] = field(repr=False)
    _builder: _ModuleBuilder[ResultT] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _implicit_inputs: Mapping[str, ModuleInput] = field(
        default_factory=empty_program_mapping,
        repr=False,
        compare=False,
    )

    @property
    def definition(self) -> ModuleDef:
        """Return the explicit immutable definition behind this handle."""

        if self._module_def is None:
            raise TypeError(
                "structurally parameterized modules have no single definition; "
                "inspect invocation.module.definition instead"
            )
        return self._module_def

    @property
    def id(self) -> str:
        return self._id

    @property
    def metadata(self) -> Mapping[str, MetadataValue]:
        return self._metadata

    @property
    def __wrapped__(self) -> Callable[P, ResultT]:
        return self._authoring_fn

    @property
    def __name__(self) -> str:
        return self._authoring_fn.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def instantiate(
        self,
        instance_id: str,
        mapped_inputs: Mapping[str, ModuleInput] | None = None,
        /,
        **inputs: ModuleInput,
    ) -> ModuleInvocation[ResultT]:
        """Create a hygienic, explicitly named module instance."""

        if self._module_def is None:
            raise TypeError(
                "structurally parameterized modules require typed arguments; "
                "use call(instance_id, ...)"
            )
        selected_inputs = dict(mapped_inputs or {})
        selected_inputs.update(inputs)
        return self._invocation(
            instance_id,
            selected_inputs,
        )

    def call(
        self,
        instance_id: str,
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> ModuleInvocation[ResultT]:
        """Create an explicitly named occurrence through the typed signature."""

        bound = self._signature.bind(*args, **kwargs)
        return self._build(instance_id, bound.arguments)

    def __call__(
        self,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> ModuleInvocation[ResultT]:
        """Create the ordinary single use of this module."""

        bound = self._signature.bind(*args, **kwargs)
        return self._build(
            self.id.rsplit(".", maxsplit=1)[-1],
            bound.arguments,
        )

    def _build(
        self,
        instance_id: str,
        arguments: Mapping[str, object],
    ) -> ModuleInvocation[ResultT]:
        if self._builder is not None:
            return self._builder(instance_id, arguments)
        return self._invocation(
            instance_id,
            cast("Mapping[str, ModuleInput]", arguments),
        )

    def _invocation(
        self,
        instance_id: str,
        inputs: Mapping[str, ModuleInput],
    ) -> ModuleInvocation[ResultT]:
        if not instance_id:
            msg = "module instance id must be non-empty"
            raise ValueError(msg)
        module_def = self._module_def
        if module_def is None:
            raise TypeError("parametric module must be specialized before invocation")
        private_overrides = sorted(set(inputs) & set(self._implicit_inputs))
        if private_overrides:
            rendered = ", ".join(repr(input_id) for input_id in private_overrides)
            raise ValueError(f"module private inputs cannot be overridden: {rendered}")
        selected_inputs = dict(self._implicit_inputs)
        selected_inputs.update(inputs)
        try:
            captured_inputs = capture_module_inputs(
                cast("Mapping[str, object]", selected_inputs),
                value_ref_type=ValueRef,
            )
        except (TypeError, ValueError) as error:
            msg = (
                f"module {self.id!r} inputs require typed values or "
                f"closed literal data: {error}"
            )
            raise TypeError(msg) from error
        input_types = {
            port.id: port.value_type for port in module_def.interface.imports
        }
        unknown_inputs = sorted(set(selected_inputs) - set(input_types))
        if unknown_inputs:
            unknown = ", ".join(repr(input_id) for input_id in unknown_inputs)
            msg = f"module {self.id!r} received undeclared inputs: {unknown}"
            raise ValueError(msg)
        normalized = FrozenMapping(
            (
                input_id,
                _module_input_value_ref(
                    value,
                    input_id=input_id,
                    value_type=input_types[input_id],
                ),
            )
            for input_id, value in captured_inputs.items()
        )
        missing_inputs = sorted(set(input_types) - set(normalized))
        if missing_inputs:
            missing = ", ".join(repr(input_id) for input_id in missing_inputs)
            msg = f"module instance {instance_id!r} must connect all inputs: {missing}"
            raise ValueError(msg)
        return create_module_invocation(
            module=self,
            instance_id=instance_id,
            inputs=normalized,
            result=self._result,
        )

    @property
    def _product_refs_internal(self) -> ProductRefs:
        """Return every product visible to compiler projection."""

        return _definition_product_refs(self.definition)


def create_experiment_module_internal[ResultT, **P](
    module_def: ModuleDef,
    *,
    definition: Callable[P, ResultT],
    signature: inspect.Signature,
    result: ResultT,
    implicit_inputs: Mapping[str, ModuleInput] | None = None,
) -> ExperimentModule[ResultT, P]:
    """Close one module definition behind its authoring handle."""

    definition_products = _definition_product_refs(module_def)
    value_exports = module_def.interface.exports
    relocated_result = relocate_module_result(
        result,
        product_sources=definition_products.values(),
        product_targets=definition_products.values(),
        value_sources=(export.source for export in value_exports),
        value_targets=(export.source for export in value_exports),
    )
    return ExperimentModule(
        _module_def=module_def,
        _authoring_fn=definition,
        _signature=signature.replace(return_annotation=ModuleInvocation),
        _result=relocated_result,
        _id=module_def.id,
        _metadata=module_def.metadata,
        _implicit_inputs=dict(implicit_inputs or {}),
    )


def create_parametric_experiment_module_internal[ResultT, **P](
    *,
    id: str,
    metadata: Mapping[str, MetadataValue],
    definition: Callable[P, ResultT],
    signature: inspect.Signature,
    builder: _ModuleBuilder[ResultT],
) -> ExperimentModule[ResultT, P]:
    """Create a module factory whose structural arguments close each use."""

    return ExperimentModule(
        _module_def=None,
        _authoring_fn=definition,
        _signature=signature.replace(return_annotation=ModuleInvocation),
        _result=cast("ResultT", None),
        _id=id,
        _metadata=metadata,
        _builder=builder,
    )


def _definition_product_refs(module_def: ModuleDef) -> ProductRefs:
    return ProductRefs(
        {
            port.qualified_id: ProductRef.from_export(port)
            for port in module_def.products
        }
    )


def _module_input_value_ref(
    value: object,
    *,
    input_id: str,
    value_type: ValueType,
) -> ValueRef:
    path = ("inputs", input_id)
    if isinstance(value, ValueRef):
        require_assignable(value.value_type, value_type, path=path)
        return value
    return internal_literal_value_ref(value, value_type, path=path)
