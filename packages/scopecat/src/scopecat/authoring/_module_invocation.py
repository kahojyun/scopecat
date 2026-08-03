"""Concrete module invocation handles and instance-owned views."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast, override

from scopecat.authoring._module_results import relocate_module_result
from scopecat.kernel.frozen import FrozenMapping
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.program.bindings import ResourcePort
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
from scopecat.program.products import ProductOutputs, ProductRef
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
    def resource_ports(self) -> tuple[ResourcePort, ...]: ...

    @property
    def _product_outputs_internal(self) -> ProductOutputs: ...


def _empty_resource_bindings() -> FrozenMapping[
    LogicalResourcePortId, LogicalResourcePortId
]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ModuleInvocation[ResultT]:
    module: ModuleHandle
    instance_id: str
    inputs: Mapping[str, ValueRef] = field(default_factory=empty_program_mapping)
    resource_bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId] = field(
        default_factory=_empty_resource_bindings
    )
    _key: InvocationKey = field(
        default_factory=InvocationKey.fresh,
        repr=False,
        compare=False,
    )
    _result: ResultT = field(repr=False, compare=False)

    def __init__(self) -> None:
        msg = "ModuleInvocation is created by calling or instantiating a module"
        raise TypeError(msg)

    @property
    def invocation_key(self) -> InvocationKey:
        """Typed nominal owner used by unresolved module-interface edges."""

        return self._key

    @property
    def result(self) -> ResultT:
        """Return the typed value produced by this explicit occurrence."""

        return self._result

    @property
    def _product_outputs_internal(self) -> ProductOutputs:
        """Return every product visible to compiler projection."""

        relative_ports = self.module.definition.products
        return ProductOutputs(
            {
                port.qualified_id: ProductRef(
                    product_id=port.symbol_id.prefixed(self.instance_id),
                    origin=(self._key, *port.target_origin),
                    _recording=(
                        None
                        if port.recording is None
                        else port.recording.prefixed(self.instance_id)
                    ),
                )
                for port in relative_ports
            }
        )

    @property
    def resources(self) -> ModuleResources:
        """Typed references to this instance's logical resource ports."""

        return ModuleResources(
            _values=FrozenMapping(
                (
                    port.qualified_id,
                    ModuleResource(
                        owner=self._key,
                        port_id=self.resource_bindings.get(
                            port.symbol_id,
                            port.symbol_id.prefixed(self.instance_id),
                        ),
                    ),
                )
                for port in self.module.resource_ports
            )
        )


@dataclass(frozen=True, slots=True)
class ModuleResource:
    """One logical resource as seen from a concrete module invocation."""

    owner: InvocationKey = field(repr=False)
    port_id: LogicalResourcePortId

    @property
    def id(self) -> str:
        return self.port_id.qualified_name


@dataclass(frozen=True, slots=True, repr=False)
class ModuleResources(Mapping[str, ModuleResource]):
    """Read-only attribute and mapping view of invocation resources."""

    _values: Mapping[str, ModuleResource]

    @override
    def __getitem__(self, resource_id: str) -> ModuleResource:
        return self._values[resource_id]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, resource_id: str) -> ModuleResource:
        try:
            return self._values[resource_id]
        except KeyError:
            msg = f"module instance has no resource {resource_id!r}"
            raise AttributeError(msg) from None

    @override
    def __dir__(self) -> list[str]:
        return sorted((*super().__dir__(), *self._values))


def create_module_invocation[ResultT](
    *,
    module: ModuleHandle,
    instance_id: str,
    inputs: Mapping[str, ValueRef],
    resource_bindings: Mapping[LogicalResourcePortId, LogicalResourcePortId],
    result: ResultT,
) -> ModuleInvocation[ResultT]:
    """Close values validated and normalized by ``ExperimentModule``."""

    invocation = cast(
        "ModuleInvocation[ResultT]",
        object.__new__(ModuleInvocation),
    )
    object.__setattr__(invocation, "module", module)
    object.__setattr__(invocation, "instance_id", instance_id)
    object.__setattr__(invocation, "inputs", inputs)
    object.__setattr__(invocation, "resource_bindings", resource_bindings)
    object.__setattr__(invocation, "_key", InvocationKey.fresh())
    object.__setattr__(
        invocation,
        "_result",
        relocate_module_result(
            result,
            product_sources=module._product_outputs_internal.values(),
            product_targets=invocation._product_outputs_internal.values(),
            value_sources=(port.source for port in module.definition.interface.exports),
            value_targets=(
                internal_module_export_value_ref(
                    invocation._key,
                    port.id,
                    port.value_type,
                )
                for port in module.definition.interface.exports
            ),
        ),
    )
    return invocation


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


def module_use_invocation(
    selected: object,
) -> ModuleInvocation[object]:
    if isinstance(selected, ModuleInvocation):
        return selected
    msg = "module composition requires a ModuleInvocation"
    raise TypeError(msg)


def domain_use_call(
    selected: DomainCall | DomainCallProvider | object,
) -> DomainCall:
    if isinstance(selected, DomainCall):
        return selected
    call = getattr(selected, "domain_call", None)
    if isinstance(call, DomainCall):
        return call
    raise TypeError("domain composition requires a DomainCall")
