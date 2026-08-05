"""Concrete module invocation handles and instance-owned views."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from scopecat.authoring._module_results import relocate_module_result
from scopecat.kernel.frozen import FrozenMapping
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.program.domain import DomainCall
from scopecat.program.identities import InvocationKey
from scopecat.program.input_capture import empty_program_mapping
from scopecat.program.module import (
    ModuleDef,
    ModuleImportBinding,
    ModuleInstance,
    ModuleInstanceLookup,
    ModuleResourceBinding,
)
from scopecat.program.products import ProductRef, ProductRefs
from scopecat.program.value_refs import (
    ValueRef,
    internal_module_export_value_ref,
)


class DomainCallProvider(Protocol):
    """A domain frontend that exposes one native core call."""

    @property
    def domain_call(self) -> DomainCall: ...


class ModuleHandle(Protocol):
    """Structural view required by one concrete module invocation."""

    @property
    def definition(self) -> ModuleDef: ...

    @property
    def _product_refs_internal(self) -> ProductRefs: ...


def _empty_resource_bindings() -> FrozenMapping[
    LogicalResourcePortId, LogicalResourcePortId
]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True, repr=False)
class ModuleInvocation[ResultT]:
    """One occurrence produced by calling or instantiating an experiment module."""

    module: ModuleHandle
    instance_id: str
    _result: ResultT = field(repr=False, compare=False)
    inputs: Mapping[str, ValueRef] = field(default_factory=empty_program_mapping)
    resource_bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId] = field(
        default_factory=_empty_resource_bindings
    )
    _key: InvocationKey = field(
        default_factory=InvocationKey.fresh,
        repr=False,
        compare=False,
    )

    @property
    def invocation_key(self) -> InvocationKey:
        """Typed nominal owner used by unresolved module-interface edges."""

        return self._key

    @property
    def result(self) -> ResultT:
        """Return the typed value produced by this explicit occurrence."""

        return self._result

    @property
    def _product_refs_internal(self) -> ProductRefs:
        """Return every product visible to compiler projection."""

        return _invocation_product_refs(
            self.module,
            instance_id=self.instance_id,
            key=self._key,
        )


def create_module_invocation[ResultT](
    *,
    module: ModuleHandle,
    instance_id: str,
    inputs: Mapping[str, ValueRef],
    resource_bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId],
    result: ResultT,
) -> ModuleInvocation[ResultT]:
    """Close values validated and normalized by ``ExperimentModule``."""

    key = InvocationKey.fresh()
    product_refs = _invocation_product_refs(
        module,
        instance_id=instance_id,
        key=key,
    )
    relocated_result = relocate_module_result(
        result,
        product_sources=module._product_refs_internal.values(),
        product_targets=product_refs.values(),
        value_sources=(port.source for port in module.definition.interface.exports),
        value_targets=(
            internal_module_export_value_ref(
                key,
                port.id,
                port.value_type,
            )
            for port in module.definition.interface.exports
        ),
    )
    return ModuleInvocation(
        module=module,
        instance_id=instance_id,
        _result=relocated_result,
        inputs=inputs,
        resource_bindings=resource_bindings,
        _key=key,
    )


def _invocation_product_refs(
    module: ModuleHandle,
    *,
    instance_id: str,
    key: InvocationKey,
) -> ProductRefs:
    return ProductRefs(
        {
            port.qualified_id: ProductRef.from_export(
                port.projected_by(
                    ModuleInstanceLookup(
                        invocation_key=key,
                        instance_id=instance_id,
                    )
                )
            )
            for port in module.definition.products
        }
    )


def module_instance[ResultT](
    invocation: ModuleInvocation[ResultT],
) -> ModuleInstance:
    bindings = tuple(
        ModuleImportBinding(import_id=import_id, source=source)
        for import_id, source in invocation.inputs.items()
    )
    return ModuleInstance(
        lookup=ModuleInstanceLookup(
            invocation_key=invocation.invocation_key,
            instance_id=invocation.instance_id,
        ),
        module=invocation.module.definition,
        input_bindings=bindings,
        resource_bindings=tuple(
            ModuleResourceBinding(import_id=child_id, source_id=parent_id)
            for child_id, parent_id in invocation.resource_bindings.items()
        ),
    )


def domain_use_call(
    selected: DomainCall | DomainCallProvider | object,
) -> DomainCall:
    if isinstance(selected, DomainCall):
        return selected
    call = getattr(selected, "domain_call", None)
    if isinstance(call, DomainCall):
        return call
    raise TypeError("domain composition requires a DomainCall")
