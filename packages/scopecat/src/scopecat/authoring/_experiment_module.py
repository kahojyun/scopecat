"""Closed module definitions exposed through a Python call contract."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast, overload

from scopecat.authoring._module_invocation import (
    ModuleInvocation,
    create_module_invocation,
)
from scopecat.kernel.frozen import FrozenMapping
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.program.bindings import BindingIntent, InvocationIntent, ResourcePort
from scopecat.program.input_capture import capture_module_inputs
from scopecat.program.module import (
    ModuleDef,
    ModuleEffect,
    ModulePythonImplementation,
    ModuleValueExport,
)
from scopecat.program.operations import ModuleInputPort, ModuleOperationDecl
from scopecat.program.products import ModuleProductDecl, ProductOutputs, ProductRef
from scopecat.program.value_refs import ValueRef, internal_literal_value_ref
from scopecat.program.value_types import ValueType
from scopecat.program.values import MetadataValue, ModuleInput


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ExperimentModule[**P]:
    """One closed module definition with a single Python call contract."""

    _module_def: ModuleDef = field(repr=False)
    _authoring_fn: Callable[P, object] | None = field(
        repr=False,
        compare=False,
    )
    _signature: inspect.Signature = field(repr=False, compare=False)

    def __init__(self) -> None:
        msg = "ExperimentModule is created by @module"
        raise TypeError(msg)

    @property
    def definition(self) -> ModuleDef:
        """Return the explicit immutable definition behind this handle."""

        return self._module_def

    @property
    def id(self) -> str:
        return self._module_def.id

    @property
    def input_ports(self) -> tuple[ModuleInputPort, ...]:
        return self._module_def.interface.imports

    @property
    def output_ports(self) -> tuple[ModuleValueExport, ...]:
        return self._module_def.interface.exports

    @property
    def resource_ports(self) -> tuple[ResourcePort, ...]:
        return self._module_def.interface.resources

    @property
    def bindings(self) -> tuple[BindingIntent, ...]:
        return self._module_def.body.bindings

    @property
    def invocations(self) -> tuple[InvocationIntent, ...]:
        return self._module_def.body.invocations

    @property
    def effects(self) -> tuple[ModuleEffect, ...]:
        return self._module_def.body.effects

    @property
    def operations(self) -> tuple[ModuleOperationDecl, ...]:
        return self._module_def.body.operations

    @property
    def python_implementations(self) -> tuple[ModulePythonImplementation, ...]:
        """Return local implementations stored outside the semantic body."""

        return self._module_def.python_implementations

    @property
    def product_declarations(self) -> tuple[ModuleProductDecl, ...]:
        """Local product declarations consumed by the flattening pass."""

        return self._module_def.body.products

    @property
    def metadata(self) -> Mapping[str, MetadataValue]:
        return self._module_def.metadata

    @property
    def __wrapped__(self) -> Callable[P, object]:
        if self._authoring_fn is None:
            raise AttributeError("__wrapped__")
        return self._authoring_fn

    @property
    def __name__(self) -> str:
        return (
            self._authoring_fn.__name__
            if self._authoring_fn is not None
            else self.id.rsplit(".", maxsplit=1)[-1]
        )

    @property
    def __signature__(self) -> inspect.Signature:
        return self._signature

    def instantiate(
        self,
        instance_id: str,
        mapped_inputs: Mapping[str, ModuleInput] | None = None,
        /,
        *,
        resource_bindings: Mapping[str, str] | None = None,
        **inputs: ModuleInput,
    ) -> ModuleInvocation:
        """Create a hygienic, explicitly named module instance."""

        selected_inputs = dict(mapped_inputs or {})
        selected_inputs.update(inputs)
        return self._invocation(
            instance_id,
            selected_inputs,
            resource_bindings=resource_bindings or {},
        )

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> ModuleInvocation:
        """Create the ordinary single use of this closed definition."""

        bound = self._signature.bind(*args, **kwargs)
        inputs = dict(bound.arguments)
        variadic = next(
            (
                parameter.name
                for parameter in self._signature.parameters.values()
                if parameter.kind is inspect.Parameter.VAR_KEYWORD
            ),
            None,
        )
        if variadic is not None:
            inputs.update(
                cast(
                    "Mapping[str, ModuleInput]",
                    inputs.pop(variadic, {}),
                )
            )
        return self.instantiate(
            self.id.rsplit(".", maxsplit=1)[-1],
            cast("Mapping[str, ModuleInput]", inputs),
        )

    def _invocation(
        self,
        instance_id: str,
        inputs: Mapping[str, ModuleInput],
        *,
        resource_bindings: Mapping[str, str],
    ) -> ModuleInvocation:
        if not instance_id:
            msg = "module instance id must be non-empty"
            raise ValueError(msg)
        try:
            captured_inputs = capture_module_inputs(
                cast("Mapping[str, object]", inputs),
                value_ref_type=ValueRef,
            )
        except (TypeError, ValueError) as error:
            msg = (
                f"module {self.id!r} inputs require typed values or "
                f"closed literal data: {error}"
            )
            raise TypeError(msg) from error
        input_types = {
            port.id: port.value_type for port in self._module_def.interface.imports
        }
        unknown_inputs = sorted(set(inputs) - set(input_types))
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
        normalized_resource_bindings = FrozenMapping(
            (
                logical_resource_port_id(child_id),
                logical_resource_port_id(parent_id),
            )
            for child_id, parent_id in resource_bindings.items()
        )
        declared_resources = {
            port.symbol_id for port in self._module_def.interface.resources
        }
        unknown_resources = sorted(
            item.qualified_name
            for item in set(normalized_resource_bindings) - declared_resources
        )
        if unknown_resources:
            msg = "module instance binds undeclared resources: " + ", ".join(
                unknown_resources
            )
            raise ValueError(msg)
        return create_module_invocation(
            module=self,
            instance_id=instance_id,
            inputs=normalized,
            resource_bindings=normalized_resource_bindings,
        )

    @property
    def products(self) -> ProductOutputs:
        """Typed product references at this module's template boundary."""

        ports = self._module_def.products
        return ProductOutputs(
            {
                port.qualified_id: ProductRef(
                    product_id=port.symbol_id,
                    origin=port.target_origin,
                    recording=port.recording,
                )
                for port in ports
            }
        )


@overload
def create_experiment_module_internal[**P](
    module_def: ModuleDef,
    *,
    definition: Callable[P, object],
    signature: inspect.Signature,
) -> ExperimentModule[P]: ...


@overload
def create_experiment_module_internal(
    module_def: ModuleDef,
    *,
    definition: None = None,
    signature: inspect.Signature,
) -> ExperimentModule[...]: ...


def create_experiment_module_internal(
    module_def: ModuleDef,
    *,
    definition: Callable[..., object] | None = None,
    signature: inspect.Signature,
) -> ExperimentModule[...]:
    """Close one module definition behind its authoring handle."""

    module = object.__new__(ExperimentModule)
    object.__setattr__(module, "_module_def", module_def)
    object.__setattr__(module, "_authoring_fn", definition)
    object.__setattr__(
        module,
        "_signature",
        signature.replace(return_annotation=ModuleInvocation),
    )
    return module


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
