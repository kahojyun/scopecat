"""Resolve module-local export edges before hierarchy localization."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from scopecat.compiler.frontend.module_scoping import (
    DefinitionEffect,
    scope_value_ref,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.kernel.symbols import SymbolId
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
    ResourceSelector,
)
from scopecat.program.domain import DomainExecution
from scopecat.program.identities import InvocationKey
from scopecat.program.logical import AcquireEffect, AcquireId, AcquireResult
from scopecat.program.module import (
    ModuleAcquireEffect,
    ModuleBody,
    ModuleInterface,
    ModulePythonImplementation,
)
from scopecat.program.operations import ModuleOperationDecl
from scopecat.program.products import ModuleProductDecl, localize_product_input_refs
from scopecat.program.value_refs import (
    ValueRef,
    internal_require_resolved_value_ref,
    internal_value_ref_module_export,
)
from scopecat.program.value_transforms import internal_transform_value_ref


class HierarchyRoot(Protocol):
    """Structural program container accepted by hierarchy elaboration."""

    @property
    def interface(self) -> ModuleInterface: ...

    @property
    def body(self) -> ModuleBody: ...

    @property
    def python_implementations(
        self,
    ) -> tuple[ModulePythonImplementation, ...]: ...


class ModuleValueResolver:
    """Resolve explicit instance-export edges within one module boundary."""

    def __init__(self, module: HierarchyRoot) -> None:
        self._instances = {
            instance.invocation_key: instance
            for instance in module.body.child_instances
        }
        self._exports: dict[tuple[InvocationKey, str], ValueRef] = {}
        self._active: set[tuple[InvocationKey, str]] = set()

    def resolve(self, value: ValueRef) -> ValueRef:
        return internal_transform_value_ref(value, self._resolve_leaf)

    def _resolve_leaf(self, value: ValueRef) -> ValueRef:
        selected = internal_value_ref_module_export(value)
        if selected is None:
            return value
        return self._resolve_export(*selected)

    def _resolve_export(
        self,
        invocation_key: InvocationKey,
        export_id: str,
    ) -> ValueRef:
        cache_key = (invocation_key, export_id)
        cached = self._exports.get(cache_key)
        if cached is not None:
            return cached
        if cache_key in self._active:
            raise CheckFailed(
                [
                    problem(
                        code="module_result_cycle",
                        phase=ProblemPhase.AUTHORING,
                        message=f"module result {export_id!r} forms a cycle",
                        location=model_location("module", "results", export_id),
                    )
                ]
            )
        instance = self._instances.get(invocation_key)
        if instance is None:
            raise CheckFailed(
                [
                    problem(
                        code="module_result_foreign_instance",
                        phase=ProblemPhase.AUTHORING,
                        message=(
                            f"module result {export_id!r} belongs to an instance "
                            "that is not part of this module"
                        ),
                        location=model_location("module", "results", export_id),
                    )
                ]
            )
        exports = {export.id: export for export in instance.module.interface.exports}
        export = exports.get(export_id)
        if export is None:
            raise CheckFailed(
                [
                    problem(
                        code="module_result_unknown",
                        phase=ProblemPhase.AUTHORING,
                        message=(
                            f"module instance {instance.instance_id!r} has no "
                            f"result {export_id!r}"
                        ),
                        location=model_location("module", "results", export_id),
                    )
                ]
            )

        self._active.add(cache_key)
        try:
            child_resolver = ModuleValueResolver(instance.module)
            local_source = child_resolver.resolve(export.source)
            local_inputs = {
                binding.import_id: self.resolve(binding.source)
                for binding in instance.input_bindings
            }
            localized = scope_value_ref(
                local_source,
                local_inputs,
                scope=(instance.instance_id,),
                origin=(instance.invocation_key,),
            )
            resolved = self.resolve(localized)
            internal_require_resolved_value_ref(
                resolved,
                context=f"module result {export_id!r}",
            )
            self._exports[cache_key] = resolved
            return resolved
        finally:
            self._active.remove(cache_key)


def lower_module_effect(
    effect: (
        BindingIntent
        | EnsureStateIntent
        | InvocationIntent
        | DomainExecution
        | ModuleAcquireEffect
    ),
    *,
    resolver: ModuleValueResolver,
) -> DefinitionEffect:
    if isinstance(effect, BindingIntent):
        return resolve_binding(effect, resolver=resolver)
    if isinstance(effect, EnsureStateIntent):
        return replace(
            effect,
            assignments=tuple(
                resolve_binding(assignment, resolver=resolver)
                for assignment in effect.assignments
            ),
        )
    if isinstance(effect, InvocationIntent):
        return resolve_invocation(effect, resolver=resolver)
    if isinstance(effect, DomainExecution):
        return resolve_domain_execution(effect, resolver=resolver)
    return AcquireEffect(
        id=AcquireId(SymbolId(local_id=effect.id)),
        resource_port_id=effect.resource_port_id,
        interface_id=effect.interface_id,
        component_path=effect.component_path,
        acquisition_id=effect.acquisition_id,
        results=tuple(
            AcquireResult(
                product_id=result.product.product_id,
                result_id=result.result_id,
                metadata=result.metadata,
            )
            for result in effect.results
        ),
    )


def resolve_resource_port(
    port: ResourcePort,
    *,
    resolver: ModuleValueResolver,
) -> ResourcePort:
    return replace(
        port,
        selector=ResourceSelector(
            interfaces=port.selector.interfaces,
            entity_inputs=tuple(
                resolver.resolve(value) for value in port.selector.entity_inputs
            ),
            role=port.selector.role,
        ),
    )


def resolve_operation(
    operation: ModuleOperationDecl,
    *,
    resolver: ModuleValueResolver,
) -> ModuleOperationDecl:
    return replace(
        operation,
        inputs=tuple(
            (
                name,
                resolver.resolve(value) if isinstance(value, ValueRef) else value,
            )
            for name, value in operation.inputs
        ),
    )


def resolve_product(
    product: ModuleProductDecl,
    *,
    resolver: ModuleValueResolver,
) -> ModuleProductDecl:
    return localize_product_input_refs(
        product,
        {},
        localize_value_ref=lambda value, _inputs: resolver.resolve(value),
    )


def resolve_binding(
    binding: BindingIntent,
    *,
    resolver: ModuleValueResolver,
) -> BindingIntent:
    return replace(
        binding,
        value=(
            resolver.resolve(binding.value)
            if isinstance(binding.value, ValueRef)
            else binding.value
        ),
    )


def resolve_invocation(
    invocation: InvocationIntent,
    *,
    resolver: ModuleValueResolver,
) -> InvocationIntent:
    return replace(
        invocation,
        arguments=tuple(
            replace(
                argument,
                value=(
                    resolver.resolve(argument.value)
                    if isinstance(argument.value, ValueRef)
                    else argument.value
                ),
            )
            for argument in invocation.arguments
        ),
    )


def resolve_domain_execution(
    execution: DomainExecution,
    *,
    resolver: ModuleValueResolver,
) -> DomainExecution:
    return replace(
        execution,
        input_bindings=tuple(
            (
                name,
                resolver.resolve(value) if isinstance(value, ValueRef) else value,
            )
            for name, value in execution.input_bindings
        ),
        compiler_input_bindings=tuple(
            (
                name,
                resolver.resolve(value) if isinstance(value, ValueRef) else value,
            )
            for name, value in execution.compiler_input_bindings
        ),
    )
