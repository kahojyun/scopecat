"""Explicit hierarchical IR for reusable authoring modules.

The public builder and invocation objects are authoring handles.  ``ModuleIR``
is the immutable definition they elaborate into: its interface declares the
values and logical resources visible at the boundary, while its body retains
child instances and local intents until the dedicated elaboration pass lowers
the hierarchy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

from scopecat._product_identity import ProductId
from scopecat._resource_identity import LogicalResourcePortId
from scopecat._value_type_compatibility import require_assignable
from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
)
from scopecat.authoring._frozen_values import empty_frozen_mapping
from scopecat.authoring._intents import (
    ExperimentStateIntent,
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.authoring._record_intents import (
    ModuleProductPort,
    RecordIntent,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_transform_value_ref,
    internal_value_ref_input_id,
    internal_value_ref_module_export,
    internal_value_ref_operation_id,
    internal_value_ref_operation_origin,
    internal_value_ref_unbound_input_ids,
)
from scopecat.authoring.value_types import ValueType
from scopecat.authoring.values import (
    ComputeDeclarationKey,
    ComputeFunction,
    MetadataValue,
    RouteRef,
)
from scopecat.errors import CheckFailed
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)


@dataclass(frozen=True, slots=True)
class InvocationKey:
    """Nominal identity of one explicit authoring invocation.

    Instance names are structural names inside a parent module and therefore
    are not sufficient to distinguish a reference obtained from a foreign
    invocation with the same spelling.  This typed key exists only while
    authoring edges are associated with their selected instance.
    """

    value: UUID

    @classmethod
    def fresh(cls) -> InvocationKey:
        return cls(uuid4())


@dataclass(frozen=True, slots=True)
class ModuleInstanceLookup:
    """Information used to resolve an invocation-owned interface edge."""

    invocation_key: InvocationKey
    instance_id: str

    def __post_init__(self) -> None:
        if not self.instance_id:
            msg = "module instance id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ModuleValueExport:
    """One named projection from a module boundary to an authored value."""

    id: str
    source: ValueRef

    def __post_init__(self) -> None:
        if not self.id:
            msg = "module output ids must be non-empty"
            raise ValueError(msg)

    @property
    def value_type(self) -> ValueType:
        """The export type is derived from its source, never duplicated."""

        return self.source.value_type


@dataclass(frozen=True, slots=True)
class ModuleProductExport:
    """Interface projection to one product declaration in the module body."""

    symbol_id: ProductId
    target_id: ProductId
    target_origin: tuple[object, ...] = field(repr=False, compare=False)

    @classmethod
    def from_declaration(cls, product: ModuleProductPort) -> ModuleProductExport:
        symbol_id = product.product_id
        return cls(
            symbol_id=symbol_id,
            target_id=symbol_id,
            target_origin=product.origin,
        )

    def projected_by(self, instance: ModuleInstanceLookup) -> ModuleProductExport:
        return ModuleProductExport(
            symbol_id=self.symbol_id.prefixed(instance.instance_id),
            target_id=self.target_id.prefixed(instance.instance_id),
            target_origin=(instance.invocation_key, *self.target_origin),
        )

    @property
    def id(self) -> str:
        return self.symbol_id.local_id

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol_id.scope

    @property
    def qualified_id(self) -> str:
        return self.symbol_id.qualified_name


@dataclass(frozen=True, slots=True)
class ModuleImportBinding:
    """A closed edge from one child import to a typed parent value."""

    import_id: str
    source: ValueRef

    def __post_init__(self) -> None:
        if not self.import_id:
            msg = "module input binding id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ModuleInterfaceIR:
    imports: tuple[ModuleInputPort, ...] = ()
    exports: tuple[ModuleValueExport, ...] = ()
    resources: tuple[ResourcePort, ...] = ()
    products: tuple[ModuleProductExport, ...] = ()

    def __post_init__(self) -> None:
        _require_unique("module import", tuple(item.id for item in self.imports))
        _require_unique("module export", tuple(item.id for item in self.exports))
        _require_unique(
            "module resource",
            tuple(item.symbol_id for item in self.resources),
        )
        _require_unique(
            "module product",
            tuple(item.qualified_id for item in self.products),
        )


@dataclass(frozen=True, slots=True)
class ModuleInstanceIR:
    lookup: ModuleInstanceLookup
    module: ModuleIR
    input_bindings: tuple[ModuleImportBinding, ...]

    @property
    def instance_id(self) -> str:
        return self.lookup.instance_id

    @property
    def invocation_key(self) -> InvocationKey:
        return self.lookup.invocation_key

    def __post_init__(self) -> None:
        imports = {item.id: item for item in self.module.interface.imports}
        bindings = {item.import_id: item for item in self.input_bindings}
        _require_unique(
            "module input binding",
            tuple(item.import_id for item in self.input_bindings),
        )
        unknown = sorted(set(bindings) - set(imports))
        if unknown:
            msg = "module instance binds undeclared imports: " + ", ".join(unknown)
            raise ValueError(msg)
        missing = sorted(set(imports) - set(bindings))
        if missing:
            msg = "module instance has unbound imports: " + ", ".join(missing)
            raise ValueError(msg)
        for import_id, binding in bindings.items():
            require_assignable(
                binding.source.value_type,
                imports[import_id].value_type,
                path=("instances", self.instance_id, "inputs", import_id),
            )


@dataclass(frozen=True, slots=True)
class ModulePythonImplementation:
    """Local Python implementation kept outside a module's semantic body."""

    declaration_key: ComputeDeclarationKey
    fn: ComputeFunction = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self.fn):
            msg = "module Python implementation must be callable"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class ModuleBodyIR:
    instances: tuple[ModuleInstanceIR, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    state: tuple[ExperimentStateIntent, ...] = ()
    operations: tuple[ModuleOperationDecl, ...] = ()
    records: tuple[RecordIntent, ...] = ()
    products: tuple[ModuleProductPort, ...] = ()

    def __post_init__(self) -> None:
        _require_unique(
            "module instance",
            tuple(item.instance_id for item in self.instances),
        )
        _require_unique(
            "module invocation",
            tuple(item.invocation_key for item in self.instances),
        )
        _require_unique(
            "module operation",
            tuple(item.operation_id for item in self.operations),
        )
        _require_unique(
            "module operation declaration",
            tuple(item.declaration_key for item in self.operations),
        )


@dataclass(frozen=True, slots=True)
class ModuleIR:
    id: str
    interface: ModuleInterfaceIR
    body: ModuleBodyIR
    python_implementations: tuple[ModulePythonImplementation, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "module id must be non-empty"
            raise ValueError(msg)
        _require_operation_implementations(self)
        problems = _module_closure_problems(self)
        if problems:
            raise CheckFailed(problems)


def _module_closure_problems(module: ModuleIR) -> list[Problem]:
    """Check lexical closure while every declaration boundary is still visible."""

    problems: list[Problem] = []
    seen: set[tuple[str, str]] = set()
    imports = {item.id: item for item in module.interface.imports}
    operations = {item.operation_id: item for item in module.body.operations}
    instances = {item.invocation_key: item for item in module.body.instances}

    def add_problem(
        code: str,
        subject: str,
        *,
        category: ProblemCategory,
        message: str,
    ) -> None:
        key = (code, subject)
        if key in seen:
            return
        seen.add(key)
        problems.append(
            blocking_problem(
                code=code,
                category=category,
                phase=ProblemPhase.AUTHORING,
                message=message,
                location=model_location("module", module.id, subject),
            )
        )

    for value in _module_lexical_value_refs(module):
        for input_id in internal_value_ref_unbound_input_ids(value):
            if input_id not in imports:
                add_problem(
                    "module_input_undeclared",
                    input_id,
                    category=ProblemCategory.NOT_FOUND,
                    message=(
                        f"module {module.id!r} uses undeclared input {input_id!r}"
                    ),
                )

        def check_leaf(leaf: ValueRef) -> ValueRef:
            input_id = internal_value_ref_input_id(leaf)
            if input_id is not None:
                declared = imports.get(input_id)
                if declared is not None and leaf.value_type != declared.value_type:
                    add_problem(
                        "module_input_type_mismatch",
                        input_id,
                        category=ProblemCategory.INVALID_INPUT,
                        message=(
                            f"module input {input_id!r} is used with a value type "
                            "different from its interface declaration"
                        ),
                    )

            operation_id = internal_value_ref_operation_id(leaf)
            if operation_id is not None:
                operation = operations.get(operation_id)
                if operation is None or internal_value_ref_operation_origin(leaf) != (
                    *operation.instance_path,
                    operation.declaration_key,
                ):
                    add_problem(
                        "module_compute_foreign_definition",
                        operation_id.qualified_name,
                        category=ProblemCategory.NOT_FOUND,
                        message=(
                            f"module {module.id!r} uses compute "
                            f"{operation_id.qualified_name!r} that it does not define"
                        ),
                    )

            selected_export = internal_value_ref_module_export(leaf)
            if selected_export is None:
                return leaf
            invocation_key, export_id = selected_export
            instance = instances.get(invocation_key)
            if instance is None:
                add_problem(
                    "module_export_foreign_instance",
                    export_id,
                    category=ProblemCategory.INVALID_INPUT,
                    message=(
                        f"module export {export_id!r} belongs to an instance "
                        f"outside module {module.id!r}"
                    ),
                )
                return leaf
            exports = {
                export.id: export for export in instance.module.interface.exports
            }
            export = exports.get(export_id)
            if export is None:
                add_problem(
                    "module_export_unknown",
                    f"{instance.instance_id}/{export_id}",
                    category=ProblemCategory.NOT_FOUND,
                    message=(
                        f"module instance {instance.instance_id!r} has no "
                        f"export {export_id!r}"
                    ),
                )
            elif leaf.value_type != export.value_type:
                add_problem(
                    "module_export_type_mismatch",
                    f"{instance.instance_id}/{export_id}",
                    category=ProblemCategory.INVALID_INPUT,
                    message=(
                        f"module export {instance.instance_id!r}/{export_id!r} "
                        "does not preserve its declared value type"
                    ),
                )
            return leaf

        internal_transform_value_ref(value, check_leaf)

    declared_resources = {port.symbol_id for port in module.interface.resources}
    for resource_id in _module_resource_uses(module):
        if resource_id not in declared_resources:
            add_problem(
                "module_resource_undeclared",
                resource_id.qualified_name,
                category=ProblemCategory.NOT_FOUND,
                message=(
                    f"module {module.id!r} uses undeclared resource "
                    f"{resource_id.qualified_name!r}"
                ),
            )

    expected_products = {
        export.symbol_id: export
        for export in (
            *(
                product.projected_by(instance.lookup)
                for instance in module.body.instances
                for product in instance.module.interface.products
            ),
            *(
                ModuleProductExport.from_declaration(product)
                for product in module.body.products
            ),
        )
    }
    for product in module.interface.products:
        expected = expected_products.get(product.symbol_id)
        if (
            expected is None
            or product.target_id != expected.target_id
            or product.target_origin != expected.target_origin
        ):
            add_problem(
                "module_product_projection_invalid",
                product.qualified_id,
                category=ProblemCategory.INVALID_INPUT,
                message=(
                    f"module product {product.qualified_id!r} is not a valid "
                    "projection of a body declaration"
                ),
            )
    if set(expected_products) != {
        product.symbol_id for product in module.interface.products
    }:
        add_problem(
            "module_product_projection_incomplete",
            "products",
            category=ProblemCategory.INVALID_INPUT,
            message=f"module {module.id!r} does not expose its body products exactly",
        )
    return problems


def _module_lexical_value_refs(module: ModuleIR) -> tuple[ValueRef, ...]:
    roots: list[object] = []
    roots.extend(export.source for export in module.interface.exports)
    roots.extend(
        source
        for port in module.interface.resources
        for source in port.selector.entity_inputs
    )
    roots.extend(
        binding.source
        for instance in module.body.instances
        for binding in instance.input_bindings
    )
    roots.extend(binding.value for binding in module.body.bindings)
    for intent in module.body.state:
        roots.extend(
            (intent.relation, intent.resource, intent.value, *intent.route_entities)
        )
    roots.extend(
        value
        for operation in module.body.operations
        for _name, value in operation.inputs
    )
    roots.extend(axis.size for record in module.body.records for axis in record.axes)
    roots.extend(axis.size for product in module.body.products for axis in product.axes)
    return tuple(
        value for root in roots for value in _nested_value_refs(root, seen=frozenset())
    )


def _nested_value_refs(
    value: object,
    *,
    seen: frozenset[int],
) -> tuple[ValueRef, ...]:
    if isinstance(value, ValueRef):
        return (value,)
    if isinstance(value, Mapping):
        selected = cast("Mapping[object, object]", value)
        marker = id(selected)
        if marker in seen:
            return ()
        nested_seen = seen | {marker}
        return tuple(
            item
            for nested in selected.values()
            for item in _nested_value_refs(nested, seen=nested_seen)
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        selected = cast("Sequence[object]", value)
        marker = id(selected)
        if marker in seen:
            return ()
        nested_seen = seen | {marker}
        return tuple(
            item
            for nested in selected
            for item in _nested_value_refs(nested, seen=nested_seen)
        )
    return ()


def _module_resource_uses(module: ModuleIR) -> tuple[LogicalResourcePortId, ...]:
    selected: list[LogicalResourcePortId] = []
    selected.extend(binding.port_id for binding in module.body.bindings)
    selected.extend(
        intent.resource_port
        for intent in module.body.state
        if intent.resource_port is not None
    )
    selected.extend(
        value.port_id
        for operation in module.body.operations
        for _name, value in operation.inputs
        if isinstance(value, RouteRef)
    )
    selected.extend(
        record.resource_port_id
        for record in module.body.records
        if record.resource_port_id is not None
    )
    selected.extend(
        product.resource_port_id
        for product in module.body.products
        if product.resource_port_id is not None
    )
    return tuple(selected)


def _require_unique(label: str, values: tuple[object, ...]) -> None:
    duplicates = [value for value in dict.fromkeys(values) if values.count(value) > 1]
    if duplicates:
        msg = f"duplicate {label} ids: " + ", ".join(repr(item) for item in duplicates)
        raise ValueError(msg)


def _require_operation_implementations(module: ModuleIR) -> None:
    operation_keys = {item.declaration_key for item in module.body.operations}
    implementation_keys = tuple(
        item.declaration_key for item in module.python_implementations
    )
    _require_unique("module Python implementation", implementation_keys)
    missing = operation_keys - set(implementation_keys)
    orphaned = set(implementation_keys) - operation_keys
    if missing:
        msg = "module operations are missing Python implementations"
        raise ValueError(msg)
    if orphaned:
        msg = "module Python implementations reference unknown operations"
        raise ValueError(msg)


__all__ = [
    "InvocationKey",
    "ModuleBodyIR",
    "ModuleIR",
    "ModuleImportBinding",
    "ModuleInstanceIR",
    "ModuleInstanceLookup",
    "ModuleInterfaceIR",
    "ModuleProductExport",
    "ModulePythonImplementation",
    "ModuleValueExport",
]
