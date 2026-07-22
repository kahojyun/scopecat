"""Explicit hierarchical IR for reusable authoring modules.

The public builder and invocation objects are authoring handles.  ``ModuleIR``
is the immutable definition they elaborate into: its interface declares the
values and logical resources visible at the boundary, while its body retains
child instances and local intents until the dedicated elaboration pass lowers
the hierarchy. Imports, definitions, uses, and exports remain distinct so
instantiation can alpha-rename private identities without changing producer
identity.

Reusable modules own typed dataflow, resources, and available products.
Templates own workflow policy such as exposed defaults, scans, and durable
record selection; that policy must not leak into a reusable module instance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast
from uuid import UUID, uuid4

from scopecat.authoring._binding_intents import (
    ExperimentBindingIntent,
    ResourcePort,
)
from scopecat.authoring._frozen_values import empty_frozen_mapping
from scopecat.authoring._intents import (
    ExperimentStateIntent,
    ModuleActionDecl,
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.authoring._products import (
    ModuleProductDecl,
    ProductRef,
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
from scopecat.authoring.domain import DomainExecution
from scopecat.authoring.measurements import MeasurementTransform
from scopecat.authoring.value_types import ValueType
from scopecat.authoring.values import (
    ComputeDeclarationKey,
    ComputeFunction,
    MetadataValue,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.value_type_compatibility import require_assignable


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
    def from_declaration(cls, product: ModuleProductDecl) -> ModuleProductExport:
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
class ModuleResourceBinding:
    """Bind one child resource import to a resource port of its parent."""

    import_id: LogicalResourcePortId
    source_id: LogicalResourcePortId


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
    resource_bindings: tuple[ModuleResourceBinding, ...] = ()

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
        resource_imports = {
            item.symbol_id: item for item in self.module.interface.resources
        }
        resource_bindings = {item.import_id: item for item in self.resource_bindings}
        _require_unique(
            "module resource binding",
            tuple(item.import_id for item in self.resource_bindings),
        )
        unknown_resources = sorted(
            item.qualified_name
            for item in set(resource_bindings) - set(resource_imports)
        )
        if unknown_resources:
            msg = "module instance binds undeclared resources: " + ", ".join(
                unknown_resources
            )
            raise ValueError(msg)


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
class ModuleInstanceEffect:
    """Inline one child module's procedure at this position."""

    invocation_key: InvocationKey


@dataclass(frozen=True, slots=True)
class ModuleBindingEffect:
    """Apply one desired-state binding at this position."""

    intent: ExperimentBindingIntent


@dataclass(frozen=True, slots=True)
class ModuleStateEffect:
    """Apply one row-scoped desired-state region at this position."""

    intent: ExperimentStateIntent


@dataclass(frozen=True, slots=True)
class ModuleActionEffect:
    """Deliver one receipt-bearing instrument action at this position."""

    intent: ModuleActionDecl


@dataclass(frozen=True, slots=True)
class ModuleDomainEffect:
    """Invoke one opaque domain program at this position."""

    execution: DomainExecution


@dataclass(frozen=True, slots=True)
class ModuleAcquireProduct:
    """One product realized by an authored acquisition effect."""

    product: ProductRef
    provider_key: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        if not self.provider_key:
            raise ValueError("module acquired product provider key must be non-empty")
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ModuleAcquireEffect:
    """Realize selected products at this exact procedure position.

    Acquisition is an ordered effect because triggering or reading hardware is
    observable execution. Product shape remains a declaration and durable
    recording remains template policy, so neither is encoded in this effect.
    """

    id: str
    resource_port_id: LogicalResourcePortId
    capability_id: str
    products: tuple[ModuleAcquireProduct, ...]

    def __post_init__(self) -> None:
        if not self.id or not self.products:
            raise ValueError("module acquire requires an id and products")
        if not self.capability_id:
            raise ValueError("module acquire capability must be non-empty")
        product_ids = tuple(product.product.product_id for product in self.products)
        _require_unique("module acquire product", product_ids)
        _require_unique(
            "module acquire provider key",
            tuple(product.provider_key for product in self.products),
        )


type ModuleEffectIR = (
    ModuleInstanceEffect
    | ModuleBindingEffect
    | ModuleStateEffect
    | ModuleActionEffect
    | ModuleDomainEffect
    | ModuleAcquireEffect
)


@dataclass(frozen=True, slots=True)
class ModuleBodyIR:
    instances: tuple[ModuleInstanceIR, ...] = ()
    procedure: tuple[ModuleEffectIR, ...] = ()
    operations: tuple[ModuleOperationDecl, ...] = ()
    measurement_transforms: tuple[MeasurementTransform, ...] = ()
    products: tuple[ModuleProductDecl, ...] = ()

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
        _require_unique("module action", tuple(item.action_id for item in self.actions))
        _require_unique(
            "module domain execution",
            tuple(item.id for item in self.domain_executions),
        )
        _require_unique(
            "module acquisition",
            tuple(item.id for item in self.acquisitions),
        )
        invocation_keys = tuple(
            effect.invocation_key
            for effect in self.procedure
            if isinstance(effect, ModuleInstanceEffect)
        )
        _require_unique("module procedure invocation", invocation_keys)
        declared_invocations = {item.invocation_key for item in self.instances}
        if set(invocation_keys) != declared_invocations:
            msg = "module procedure must contain every child invocation exactly once"
            raise ValueError(msg)
        _require_unique(
            "module measurement transform",
            tuple(item.symbol_id for item in self.measurement_transforms),
        )
        local_product_origins = {
            product.product_id: product.origin for product in self.products
        }
        projected_product_origins = {
            product.symbol_id: product.target_origin
            for instance in self.instances
            for product in (
                child.projected_by(instance.lookup)
                for child in instance.module.interface.products
            )
        }
        visible_product_origins = {
            **projected_product_origins,
            **local_product_origins,
        }
        for transform in self.measurement_transforms:
            for direction, bindings, origins, allowed_products in (
                (
                    "input",
                    transform.input_bindings,
                    transform.input_product_origins,
                    visible_product_origins,
                ),
                (
                    "output",
                    transform.output_bindings,
                    transform.output_product_origins,
                    local_product_origins,
                ),
            ):
                _require_transform_products(
                    transform,
                    direction=direction,
                    bindings=bindings,
                    binding_origins=origins,
                    local_product_origins=local_product_origins,
                    allowed_product_origins=allowed_products,
                )

    @property
    def bindings(self) -> tuple[ExperimentBindingIntent, ...]:
        return tuple(
            effect.intent
            for effect in self.procedure
            if isinstance(effect, ModuleBindingEffect)
        )

    @property
    def state(self) -> tuple[ExperimentStateIntent, ...]:
        return tuple(
            effect.intent
            for effect in self.procedure
            if isinstance(effect, ModuleStateEffect)
        )

    @property
    def actions(self) -> tuple[ModuleActionDecl, ...]:
        return tuple(
            effect.intent
            for effect in self.procedure
            if isinstance(effect, ModuleActionEffect)
        )

    @property
    def domain_executions(self) -> tuple[DomainExecution, ...]:
        return tuple(
            effect.execution
            for effect in self.procedure
            if isinstance(effect, ModuleDomainEffect)
        )

    @property
    def acquisitions(self) -> tuple[ModuleAcquireEffect, ...]:
        return tuple(
            effect
            for effect in self.procedure
            if isinstance(effect, ModuleAcquireEffect)
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


class _ModuleProblemAdder(Protocol):
    def __call__(
        self,
        code: str,
        subject: str,
        *,
        category: ProblemCategory,
        message: str,
    ) -> None: ...


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

    _check_module_resources(module, add_problem)
    _check_module_products(module, add_problem)
    return problems


def _check_module_resources(
    module: ModuleIR,
    add_problem: _ModuleProblemAdder,
) -> None:
    declared = {port.symbol_id for port in module.interface.resources}
    parent_ports = {port.symbol_id: port for port in module.interface.resources}
    for instance in module.body.instances:
        child_ports = {
            port.symbol_id: port for port in instance.module.interface.resources
        }
        for binding in instance.resource_bindings:
            parent_port = parent_ports.get(binding.source_id)
            if parent_port is None:
                add_problem(
                    "module_resource_binding_undeclared",
                    f"{instance.instance_id}/{binding.source_id.qualified_name}",
                    category=ProblemCategory.NOT_FOUND,
                    message=(
                        f"module instance {instance.instance_id!r} binds to "
                        f"undeclared parent resource "
                        f"{binding.source_id.qualified_name!r}"
                    ),
                )
                continue
            child_port = child_ports[binding.import_id]
            missing_capabilities = sorted(
                set(child_port.selector.capabilities)
                - set(parent_port.selector.capabilities)
            )
            if missing_capabilities:
                add_problem(
                    "module_resource_binding_capability_mismatch",
                    f"{instance.instance_id}/{binding.import_id.qualified_name}",
                    category=ProblemCategory.INVALID_INPUT,
                    message=(
                        f"parent resource {binding.source_id.qualified_name!r} "
                        "does not provide child capabilities: "
                        + ", ".join(missing_capabilities)
                    ),
                )
    for resource_id in _module_resource_uses(module):
        if resource_id not in declared:
            add_problem(
                "module_resource_undeclared",
                resource_id.qualified_name,
                category=ProblemCategory.NOT_FOUND,
                message=(
                    f"module {module.id!r} uses undeclared resource "
                    f"{resource_id.qualified_name!r}"
                ),
            )


def _check_module_products(
    module: ModuleIR,
    add_problem: _ModuleProblemAdder,
) -> None:
    resource_ports = {port.symbol_id: port for port in module.interface.resources}
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
    product_origins = {
        product_id: export.target_origin
        for product_id, export in expected_products.items()
    }
    for acquire in module.body.acquisitions:
        for acquired in acquire.products:
            product = acquired.product
            expected_origin = product_origins.get(product.product_id)
            if expected_origin != product.origin:
                add_problem(
                    "module_acquire_product_invalid",
                    f"{acquire.id}/{product.product_id.qualified_name}",
                    category=ProblemCategory.NOT_FOUND,
                    message=(
                        f"module acquisition {acquire.id!r} references product "
                        f"{product.product_id.qualified_name!r} outside this module"
                    ),
                )
    for execution in module.body.domain_executions:
        required_resources = {
            port.id: port for port in execution.program.resource_ports
        }
        for role, resource_id in execution.resource_bindings:
            port = resource_ports.get(resource_id)
            if port is None:
                continue
            missing_capabilities = sorted(
                set(required_resources[role].capabilities)
                - set(port.selector.capabilities)
            )
            if missing_capabilities:
                add_problem(
                    "domain_resource_capability_mismatch",
                    f"{execution.id}/{role}",
                    category=ProblemCategory.INVALID_INPUT,
                    message=(
                        f"domain resource role {role!r} requires capabilities: "
                        + ", ".join(missing_capabilities)
                    ),
                )
        for result_id, product in execution.result_bindings:
            expected_origin = product_origins.get(product.product_id)
            if expected_origin is None:
                add_problem(
                    "domain_execution_product_unknown",
                    f"{execution.id}/{result_id}",
                    category=ProblemCategory.NOT_FOUND,
                    message=(
                        f"domain result {result_id!r} binds unknown product "
                        f"{product.id!r}"
                    ),
                )
            elif product.origin != expected_origin:
                add_problem(
                    "domain_execution_product_foreign_instance",
                    f"{execution.id}/{result_id}",
                    category=ProblemCategory.INVALID_INPUT,
                    message=(
                        f"domain result {result_id!r} binds product {product.id!r} "
                        "from another module instance"
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
        roots.extend((intent.relation, intent.value, *intent.target_entities))
    roots.extend(
        value for action in module.body.actions for _name, value in action.fields
    )
    roots.extend(
        value
        for execution in module.body.domain_executions
        for _name, value in execution.input_bindings
    )
    roots.extend(
        value
        for operation in module.body.operations
        for _name, value in operation.inputs
    )
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
        selected = value
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
    selected.extend(intent.resource_port for intent in module.body.state)
    selected.extend(action.resource_port_id for action in module.body.actions)
    selected.extend(acquire.resource_port_id for acquire in module.body.acquisitions)
    selected.extend(
        resource_id
        for execution in module.body.domain_executions
        for _role, resource_id in execution.resource_bindings
    )
    return tuple(selected)


def _require_unique(label: str, values: tuple[object, ...]) -> None:
    duplicates = [value for value in dict.fromkeys(values) if values.count(value) > 1]
    if duplicates:
        msg = f"duplicate {label} ids: " + ", ".join(repr(item) for item in duplicates)
        raise ValueError(msg)


def _require_transform_products(
    transform: MeasurementTransform,
    *,
    direction: str,
    bindings: tuple[tuple[str, ProductId], ...],
    binding_origins: tuple[tuple[str, tuple[object, ...]], ...],
    local_product_origins: Mapping[ProductId, tuple[object, ...]],
    allowed_product_origins: Mapping[ProductId, tuple[object, ...]],
) -> None:
    origins_by_role = dict(binding_origins)
    for role, selected_id in bindings:
        if role not in origins_by_role:
            if selected_id not in local_product_origins:
                raise ValueError(
                    f"measurement transform {transform.id!r} {direction} "
                    f"{role!r} references undeclared local product "
                    f"{selected_id.qualified_name!r}"
                )
            continue
        expected_origin = allowed_product_origins.get(selected_id)
        if expected_origin is None:
            location = (
                "outside this module"
                if direction == "input"
                else "outside this module's local products"
            )
            raise ValueError(
                f"measurement transform {transform.id!r} {direction} {role!r} "
                f"references product {selected_id.qualified_name!r} {location}"
            )
        if origins_by_role[role] != expected_origin:
            raise ValueError(
                f"measurement transform {transform.id!r} {direction} {role!r} "
                f"references product {selected_id.qualified_name!r} from another "
                "module instance"
            )


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
