"""Explicit hierarchical definitions for reusable modules.

The public contexts and invocation objects are authoring handles. ``ModuleDef``
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

from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.program.bindings import (
    BindingIntent,
    EnsureStateIntent,
    InvocationIntent,
    ResourcePort,
)
from scopecat.program.domain import DomainExecution
from scopecat.program.identities import (
    ComputeDeclarationKey,
    InvocationKey,
)
from scopecat.program.input_capture import empty_program_mapping
from scopecat.program.measurements import MeasurementPostprocessor
from scopecat.program.operations import (
    ModuleInputPort,
    ModuleOperationDecl,
)
from scopecat.program.products import (
    ModuleProductDecl,
    ProductRecording,
    ProductRef,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_input_id,
    internal_value_ref_module_export,
    internal_value_ref_operation_id,
    internal_value_ref_operation_origin,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
)
from scopecat.program.value_transforms import (
    internal_transform_value_ref,
    internal_value_ref_unbound_input_ids,
)
from scopecat.program.value_types import ValueType
from scopecat.program.values import (
    ComputeFunction,
    MetadataValue,
)


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
            msg = "module value export ids must be non-empty"
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
    recording: ProductRecording | None = None

    @classmethod
    def from_declaration(cls, product: ModuleProductDecl) -> ModuleProductExport:
        symbol_id = product.product_id
        return cls(
            symbol_id=symbol_id,
            target_id=symbol_id,
            target_origin=product.origin,
            recording=product.recording,
        )

    def projected_by(self, instance: ModuleInstanceLookup) -> ModuleProductExport:
        return ModuleProductExport(
            symbol_id=self.symbol_id.prefixed(instance.instance_id),
            target_id=self.target_id.prefixed(instance.instance_id),
            target_origin=(instance.invocation_key, *self.target_origin),
            recording=(
                None
                if self.recording is None
                else self.recording.prefixed(instance.instance_id)
            ),
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
class ModuleInterface:
    imports: tuple[ModuleInputPort, ...] = ()
    exports: tuple[ModuleValueExport, ...] = ()
    resources: tuple[ResourcePort, ...] = ()

    def __post_init__(self) -> None:
        _require_unique("module import", tuple(item.id for item in self.imports))
        _require_unique("module export", tuple(item.id for item in self.exports))
        _require_unique(
            "module resource",
            tuple(item.symbol_id for item in self.resources),
        )


@dataclass(frozen=True, slots=True)
class ModuleInstance:
    lookup: ModuleInstanceLookup
    module: ModuleDef
    input_bindings: tuple[ModuleImportBinding, ...]
    resource_bindings: tuple[ModuleResourceBinding, ...] = ()

    @property
    def instance_id(self) -> str:
        return self.lookup.instance_id

    @property
    def invocation_key(self) -> InvocationKey:
        return self.lookup.invocation_key


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
class ModuleAcquireResult:
    """Map one hardware acquisition result to a logical product."""

    product: ProductRef
    result_id: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_program_mapping)

    def __post_init__(self) -> None:
        if not self.result_id:
            raise ValueError("module acquisition result id must be non-empty")
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ModuleAcquireEffect:
    """Realize selected products at this exact effect position.

    Acquisition is an ordered effect because triggering or reading hardware is
    observable execution. Product shape remains a declaration and durable
    recording remains template policy, so neither is encoded in this effect.
    """

    id: str
    resource_port_id: LogicalResourcePortId
    interface_id: InterfaceId
    component_path: tuple[str, ...]
    acquisition_id: str
    results: tuple[ModuleAcquireResult, ...]

    def __post_init__(self) -> None:
        if not self.id or not self.results:
            raise ValueError("module acquire requires an id and results")
        if not self.acquisition_id or any(
            not component for component in self.component_path
        ):
            raise ValueError("module acquisition and component ids must be non-empty")
        product_ids = tuple(result.product.product_id for result in self.results)
        _require_unique("module acquire product", product_ids)
        _require_unique(
            "module acquisition result",
            tuple(result.result_id for result in self.results),
        )


type ModuleEffect = (
    ModuleInstance
    | BindingIntent
    | EnsureStateIntent
    | InvocationIntent
    | DomainExecution
    | ModuleAcquireEffect
)


@dataclass(frozen=True, slots=True)
class ModuleBody:
    """A closed effect sequence with derived child and product views."""

    effects: tuple[ModuleEffect, ...] = ()
    operations: tuple[ModuleOperationDecl, ...] = ()
    measurement_postprocessors: tuple[MeasurementPostprocessor, ...] = ()
    products: tuple[ModuleProductDecl, ...] = ()

    def __post_init__(self) -> None:
        _require_unique(
            "module instance",
            tuple(item.instance_id for item in self.child_instances),
        )
        _require_unique(
            "module invocation",
            tuple(item.invocation_key for item in self.child_instances),
        )
        _require_unique(
            "module operation",
            tuple(item.operation_id for item in self.operations),
        )
        _require_unique(
            "module operation declaration",
            tuple(item.declaration_key for item in self.operations),
        )
        _require_unique(
            "module domain execution",
            tuple(item.id for item in self.domain_executions),
        )
        _require_unique(
            "module acquisition",
            tuple(item.id for item in self.acquisitions),
        )
        _require_unique(
            "module invocation effect",
            tuple(item.id for item in self.invocations),
        )
        _require_unique(
            "module measurement postprocessor",
            tuple(item.symbol_id for item in self.measurement_postprocessors),
        )
        local_product_origins = {
            product.product_id: product.origin for product in self.products
        }
        projected_product_origins = {
            product.symbol_id: product.target_origin
            for instance in self.child_instances
            for product in (
                child.projected_by(instance.lookup)
                for child in instance.module.products
            )
        }
        visible_product_origins = {
            **projected_product_origins,
            **local_product_origins,
        }
        for postprocessor in self.measurement_postprocessors:
            _require_postprocessor_product(
                postprocessor,
                direction="input",
                role="input",
                selected_id=postprocessor.input_binding,
                origin=postprocessor.input_product_origin,
                local_product_origins=local_product_origins,
                allowed_product_origins=visible_product_origins,
            )
            output_origins = dict(postprocessor.output_product_origins)
            for role, selected_id in postprocessor.output_bindings:
                _require_postprocessor_product(
                    postprocessor,
                    direction="output",
                    role=role,
                    selected_id=selected_id,
                    origin=output_origins.get(role),
                    local_product_origins=local_product_origins,
                    allowed_product_origins=local_product_origins,
                )

    @property
    def child_instances(self) -> tuple[ModuleInstance, ...]:
        """Derive children so effects remain the sole ordering authority."""

        return tuple(
            effect for effect in self.effects if isinstance(effect, ModuleInstance)
        )

    @property
    def exposed_products(self) -> tuple[ModuleProductExport, ...]:
        """Project products from the declarations that actually own them."""

        return (
            *(
                product.projected_by(instance.lookup)
                for instance in self.child_instances
                for product in instance.module.products
            ),
            *(
                ModuleProductExport.from_declaration(product)
                for product in self.products
            ),
        )

    @property
    def bindings(self) -> tuple[BindingIntent, ...]:
        return tuple(
            binding
            for effect in self.effects
            for binding in (
                (effect,)
                if isinstance(effect, BindingIntent)
                else effect.assignments
                if isinstance(effect, EnsureStateIntent)
                else ()
            )
        )

    @property
    def domain_executions(self) -> tuple[DomainExecution, ...]:
        return tuple(
            effect for effect in self.effects if isinstance(effect, DomainExecution)
        )

    @property
    def invocations(self) -> tuple[InvocationIntent, ...]:
        return tuple(
            effect for effect in self.effects if isinstance(effect, InvocationIntent)
        )

    @property
    def acquisitions(self) -> tuple[ModuleAcquireEffect, ...]:
        return tuple(
            effect for effect in self.effects if isinstance(effect, ModuleAcquireEffect)
        )


@dataclass(frozen=True, slots=True)
class ModuleDef:
    id: str
    interface: ModuleInterface
    body: ModuleBody
    python_implementations: tuple[ModulePythonImplementation, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_program_mapping)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "module id must be non-empty"
            raise ValueError(msg)
        _require_unique(
            "module product",
            tuple(item.qualified_id for item in self.products),
        )
        problems = _module_closure_problems(self)
        if problems:
            raise CheckFailed(problems)

    @property
    def products(self) -> tuple[ModuleProductExport, ...]:
        return self.body.exposed_products


class _ModuleProblemAdder(Protocol):
    def __call__(
        self,
        code: str,
        subject: str,
        *,
        message: str,
    ) -> None: ...


def _module_closure_problems(module: ModuleDef) -> list[Problem]:
    """Check lexical closure while every declaration boundary is still visible."""

    problems: list[Problem] = []
    seen: set[tuple[str, str]] = set()
    imports = {item.id: item for item in module.interface.imports}
    operations = {item.operation_id: item for item in module.body.operations}
    instances = {item.invocation_key: item for item in module.body.child_instances}

    def add_problem(
        code: str,
        subject: str,
        *,
        message: str,
    ) -> None:
        key = (code, subject)
        if key in seen:
            return
        seen.add(key)
        problems.append(
            problem(
                code=code,
                phase=ProblemPhase.AUTHORING,
                message=message,
                location=model_location("module", module.id, subject),
            )
        )

    for value in _module_lexical_value_refs(module):
        if internal_value_ref_point_dependencies(value):
            add_problem(
                "module_point_dependency_free",
                "point_dependencies",
                message=(
                    f"module {module.id!r} cannot depend on experiment coordinates; "
                    "declare a typed module input instead"
                ),
            )
        if internal_value_ref_parameter_contracts(value):
            add_problem(
                "module_parameter_dependency_free",
                "parameter_dependencies",
                message=(
                    f"module {module.id!r} cannot depend on experiment parameters; "
                    "declare a typed module input instead"
                ),
            )
        for input_id in internal_value_ref_unbound_input_ids(value):
            if input_id not in imports:
                add_problem(
                    "module_input_undeclared",
                    input_id,
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
                    "module_result_foreign_instance",
                    export_id,
                    message=(
                        f"module result {export_id!r} belongs to an instance "
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
                    "module_result_unknown",
                    f"{instance.instance_id}/{export_id}",
                    message=(
                        f"module instance {instance.instance_id!r} has no "
                        f"result {export_id!r}"
                    ),
                )
            elif leaf.value_type != export.value_type:
                add_problem(
                    "module_result_type_mismatch",
                    f"{instance.instance_id}/{export_id}",
                    message=(
                        f"module result {instance.instance_id!r}/{export_id!r} "
                        "does not preserve its declared value type"
                    ),
                )
            return leaf

        internal_transform_value_ref(value, check_leaf)

    _check_module_resources(module, add_problem)
    _check_module_products(module, add_problem)
    return problems


def _check_module_resources(
    module: ModuleDef,
    add_problem: _ModuleProblemAdder,
) -> None:
    declared = {port.symbol_id for port in module.interface.resources}
    parent_ports = {port.symbol_id: port for port in module.interface.resources}
    for instance in module.body.child_instances:
        child_ports = {
            port.symbol_id: port for port in instance.module.interface.resources
        }
        for binding in instance.resource_bindings:
            parent_port = parent_ports.get(binding.source_id)
            if parent_port is None:
                add_problem(
                    "module_resource_binding_undeclared",
                    f"{instance.instance_id}/{binding.source_id.qualified_name}",
                    message=(
                        f"module instance {instance.instance_id!r} binds to "
                        f"undeclared parent resource "
                        f"{binding.source_id.qualified_name!r}"
                    ),
                )
                continue
            child_port = child_ports[binding.import_id]
            missing_interfaces = sorted(
                set(child_port.selector.interfaces)
                - set(parent_port.selector.interfaces)
            )
            if missing_interfaces:
                add_problem(
                    "module_resource_binding_interface_mismatch",
                    f"{instance.instance_id}/{binding.import_id.qualified_name}",
                    message=(
                        f"parent resource {binding.source_id.qualified_name!r} "
                        "does not provide child interfaces: "
                        + ", ".join(missing_interfaces)
                    ),
                )
    for resource_id in _module_resource_uses(module):
        if resource_id not in declared:
            add_problem(
                "module_resource_undeclared",
                resource_id.qualified_name,
                message=(
                    f"module {module.id!r} uses undeclared resource "
                    f"{resource_id.qualified_name!r}"
                ),
            )


def _check_module_products(
    module: ModuleDef,
    add_problem: _ModuleProblemAdder,
) -> None:
    expected_products = {export.symbol_id: export for export in module.products}
    product_origins = {
        product_id: export.target_origin
        for product_id, export in expected_products.items()
    }
    for acquire in module.body.acquisitions:
        for acquired in acquire.results:
            product = acquired.product
            expected_origin = product_origins.get(product.product_id)
            if expected_origin != product.origin:
                add_problem(
                    "module_acquire_product_invalid",
                    f"{acquire.id}/{product.product_id.qualified_name}",
                    message=(
                        f"module acquisition {acquire.id!r} references product "
                        f"{product.product_id.qualified_name!r} outside this module"
                    ),
                )
    for execution in module.body.domain_executions:
        for result_id, product in execution.result_bindings:
            expected_origin = product_origins.get(product.product_id)
            if expected_origin is None:
                add_problem(
                    "domain_execution_product_unknown",
                    f"{execution.id}/{result_id}",
                    message=(
                        f"domain result {result_id!r} binds unknown product "
                        f"{product.id!r}"
                    ),
                )
            elif product.origin != expected_origin:
                add_problem(
                    "domain_execution_product_foreign_instance",
                    f"{execution.id}/{result_id}",
                    message=(
                        f"domain result {result_id!r} binds product {product.id!r} "
                        "from another module instance"
                    ),
                )


def _module_lexical_value_refs(module: ModuleDef) -> tuple[ValueRef, ...]:
    roots: list[object] = []
    roots.extend(export.source for export in module.interface.exports)
    roots.extend(
        source
        for port in module.interface.resources
        for source in port.selector.entity_inputs
    )
    roots.extend(
        binding.source
        for instance in module.body.child_instances
        for binding in instance.input_bindings
    )
    roots.extend(binding.value for binding in module.body.bindings)
    roots.extend(
        argument.value
        for invocation in module.body.invocations
        for argument in invocation.arguments
    )
    roots.extend(
        value
        for execution in module.body.domain_executions
        for _name, value in (
            *execution.input_bindings,
            *execution.compiler_input_bindings,
        )
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


def _module_resource_uses(module: ModuleDef) -> tuple[LogicalResourcePortId, ...]:
    selected: list[LogicalResourcePortId] = []
    selected.extend(binding.port_id for binding in module.body.bindings)
    selected.extend(invocation.port_id for invocation in module.body.invocations)
    selected.extend(acquire.resource_port_id for acquire in module.body.acquisitions)
    return tuple(selected)


def _require_unique(label: str, values: tuple[object, ...]) -> None:
    duplicates = [value for value in dict.fromkeys(values) if values.count(value) > 1]
    if duplicates:
        msg = f"duplicate {label} ids: " + ", ".join(repr(item) for item in duplicates)
        raise ValueError(msg)


def _require_postprocessor_product(
    postprocessor: MeasurementPostprocessor,
    *,
    direction: str,
    role: str,
    selected_id: ProductId,
    origin: tuple[object, ...] | None,
    local_product_origins: Mapping[ProductId, tuple[object, ...]],
    allowed_product_origins: Mapping[ProductId, tuple[object, ...]],
) -> None:
    if origin is None:
        if selected_id not in local_product_origins:
            raise ValueError(
                f"measurement postprocessor {postprocessor.id!r} {direction} "
                f"{role!r} references undeclared local product "
                f"{selected_id.qualified_name!r}"
            )
        return
    expected_origin = allowed_product_origins.get(selected_id)
    if expected_origin is None:
        location = (
            "outside this module"
            if direction == "input"
            else "outside this module's local products"
        )
        raise ValueError(
            f"measurement postprocessor {postprocessor.id!r} {direction} {role!r} "
            f"references product {selected_id.qualified_name!r} {location}"
        )
    if origin != expected_origin:
        raise ValueError(
            f"measurement postprocessor {postprocessor.id!r} {direction} {role!r} "
            f"references product {selected_id.qualified_name!r} from another "
            "module instance"
        )
