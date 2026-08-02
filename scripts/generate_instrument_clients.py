"""Generate typed first-party instrument surfaces from declared interfaces."""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
import types
import typing
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, TypeAliasType, TypeVar, cast, get_args, get_origin

from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    DeclaredInterfaceLayout,
    DeclaredOperation,
    DeclaredScopeLayout,
    DeclaredStateLayout,
    compile_interface,
    declared_bundle_interfaces,
    declared_interface_layout,
)
from scopecat_instruments.interface_declarations import (
    DCSourceInterface,
    DCSourceMonitorInterface,
    NetworkSweepInterface,
    ReferenceSource,
    RFOutputInterface,
    SParameter,
    TemperatureReadoutInterface,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTS_PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "scopecat-instruments"
OUTPUT = INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "clients.py"
MEMBERS_OUTPUT = (
    INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "members.py"
)
INTERFACES_OUTPUT = (
    INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "interfaces.py"
)
STATES_OUTPUT = INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "states.py"
FIXTURE_IMPORT_ROOT = INSTRUMENTS_PACKAGE_ROOT / "tests"
FIXTURE_OUTPUT = FIXTURE_IMPORT_ROOT / "generated_client_fixture.py"
FIXTURE_MEMBERS_OUTPUT = FIXTURE_IMPORT_ROOT / "generated_member_catalog_fixture.py"
FIXTURE_INTERFACES_OUTPUT = (
    FIXTURE_IMPORT_ROOT / "generated_interface_catalog_fixture.py"
)
FIXTURE_STATES_OUTPUT = FIXTURE_IMPORT_ROOT / "generated_state_catalog_fixture.py"
_TYPING_UNION_ORIGIN: object = typing.Union  # pyright: ignore[reportDeprecated]
_FACADE_PARAMETER_NAMES = frozenset({"instrument_id", "resource_id", "for_"})


class ClientGenerationError(ValueError):
    """A declaration uses a feature the typed client surface cannot represent."""


@dataclass(frozen=True, slots=True)
class ClientSurface:
    """Non-structural inputs that a Python interface declaration cannot carry."""

    interface_type: type[object]
    public_name_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class BundleClientSurface:
    """One typed client surface composed from an instrument bundle."""

    bundle_type: type[object]
    facade_flag: str | None = None


type GenerationSurface = ClientSurface | BundleClientSurface


def _type_identity(interface_type: type[object]) -> str:
    return f"{interface_type.__module__}.{interface_type.__qualname__}"


def clients_for(
    interface_type: type[object],
    /,
    *,
    public_name_overrides: tuple[tuple[str, str], ...] = (),
) -> ClientSurface:
    """Select one decorated interface for typed client generation."""

    return ClientSurface(
        interface_type=interface_type,
        public_name_overrides=public_name_overrides,
    )


def clients_for_bundle(
    bundle_type: type[object],
    /,
    *,
    facade_flag: str | None = None,
) -> BundleClientSurface:
    """Select one declared bundle for typed client generation."""

    return BundleClientSurface(
        bundle_type=bundle_type,
        facade_flag=facade_flag,
    )


def _surface_interface_types(
    surfaces: tuple[GenerationSurface, ...],
) -> tuple[type[object], ...]:
    """Flatten selected interfaces in declaration order without duplicates."""

    selected: list[type[object]] = []
    seen: set[type[object]] = set()
    for surface in surfaces:
        interface_types = (
            declared_bundle_interfaces(surface.bundle_type)
            if isinstance(surface, BundleClientSurface)
            else (surface.interface_type,)
        )
        for interface_type in interface_types:
            if interface_type in seen:
                continue
            seen.add(interface_type)
            selected.append(interface_type)
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class GenerationTarget:
    """One independently importable generated module and its declarations."""

    output: Path
    surfaces: tuple[GenerationSurface, ...]


@dataclass(frozen=True, slots=True)
class CatalogTarget:
    """Public projections generated from a closed set of declared interfaces."""

    members_output: Path
    interfaces_output: Path
    states_output: Path
    interface_types: tuple[type[object], ...]
    public_types: tuple[object, ...] = ()


class _Options(argparse.Namespace):
    check: bool = False


class _FixtureDeclarations(Protocol):
    CatalogProjectionInterface: type[object]
    ComponentOperationInterface: type[object]


_PRODUCTION_SURFACES: tuple[GenerationSurface, ...] = (
    clients_for(
        TemperatureReadoutInterface,
        public_name_overrides=(("sample.readback", "TemperatureReadback"),),
    ),
    clients_for(RFOutputInterface),
    clients_for(DCSourceInterface),
    clients_for_bundle(DCSourceMonitorInterface, facade_flag="monitor"),
    clients_for(NetworkSweepInterface),
)

PRODUCTION_TARGET = GenerationTarget(
    output=OUTPUT,
    surfaces=_PRODUCTION_SURFACES,
)

PRODUCTION_CATALOG_TARGET = CatalogTarget(
    members_output=MEMBERS_OUTPUT,
    interfaces_output=INTERFACES_OUTPUT,
    states_output=STATES_OUTPUT,
    interface_types=_surface_interface_types(_PRODUCTION_SURFACES),
    public_types=(ReferenceSource, SParameter),
)


def _fixture_target() -> GenerationTarget:
    declarations = _fixture_declarations()
    return GenerationTarget(
        output=FIXTURE_OUTPUT,
        surfaces=(clients_for(declarations.ComponentOperationInterface),),
    )


def _fixture_catalog_target() -> CatalogTarget:
    declarations = _fixture_declarations()
    return CatalogTarget(
        members_output=FIXTURE_MEMBERS_OUTPUT,
        interfaces_output=FIXTURE_INTERFACES_OUTPUT,
        states_output=FIXTURE_STATES_OUTPUT,
        interface_types=(declarations.CatalogProjectionInterface,),
    )


def _fixture_declarations() -> _FixtureDeclarations:
    import_root = str(FIXTURE_IMPORT_ROOT)
    if import_root not in sys.path:
        sys.path.insert(0, import_root)
    return cast(
        "_FixtureDeclarations",
        cast("object", import_module("client_codegen_fixture_declarations")),
    )


def _generation_targets() -> tuple[GenerationTarget, ...]:
    return (PRODUCTION_TARGET, _fixture_target())


def _catalog_targets() -> tuple[CatalogTarget, ...]:
    return (PRODUCTION_CATALOG_TARGET, _fixture_catalog_target())


@dataclass(frozen=True, slots=True)
class _OperationArgumentModel:
    python_name: str
    kind: str
    concrete_annotation: str
    symbolic_annotation: str


@dataclass(frozen=True, slots=True)
class _OperationModel:
    method_name: str
    descriptor_name: str
    arguments: tuple[_OperationArgumentModel, ...]


@dataclass(frozen=True, slots=True)
class _AcquisitionModel:
    method_name: str
    descriptor_name: str
    result_type_name: str
    result_type_arguments: int
    readback_name: str
    products_name: str


@dataclass(frozen=True, slots=True)
class _ScopeModel:
    python_path: tuple[str, ...]
    class_stem: str
    operations: tuple[_OperationModel, ...]
    acquisitions: tuple[_AcquisitionModel, ...]
    components: tuple[_ScopeModel, ...]

    @property
    def is_root(self) -> bool:
        return not self.python_path

    @property
    def python_name(self) -> str:
        return self.python_path[-1]

    @property
    def live_client_name(self) -> str:
        return f"{self.class_stem}Client"

    @property
    def symbolic_client_name(self) -> str:
        return f"Symbolic{self.class_stem}Client"

    @property
    def symbolic_group_name(self) -> str:
        return f"Symbolic{self.class_stem}Group"


@dataclass(frozen=True, slots=True)
class _InterfaceConstituentModel:
    interface_identity: str
    interface_type_name: str
    constant_prefix: str
    layout: DeclaredInterfaceLayout[object]
    observation_type_name: str | None

    @property
    def ref_name(self) -> str:
        return f"_{self.constant_prefix}_REF"

    @property
    def layout_name(self) -> str:
        return f"_{self.constant_prefix}_LAYOUT"

    @property
    def observation_descriptor_name(self) -> str | None:
        if self.observation_type_name is None:
            return None
        return f"_{self.constant_prefix}_OBSERVATION_DECLARATION"

    @property
    def needs_layout(self) -> bool:
        return self.layout.observed_state is not None or any(
            scope.operations or scope.acquisitions
            for scope in _walk_declared_scopes(self.layout.root)
        )


@dataclass(frozen=True, slots=True)
class _InterfaceModel:
    interface_identity: str
    stem: str
    factory_name: str
    generate_family: bool
    observation_type_name: str | None
    live_state_type_names: tuple[str, ...]
    symbolic_state_type_names: tuple[str, ...]
    group_state_type_names: tuple[str, ...]
    constituents: tuple[_InterfaceConstituentModel, ...]
    root: _ScopeModel

    @property
    def live_state_type_name(self) -> str | None:
        if not self.live_state_type_names:
            return None
        if len(self.live_state_type_names) == 1:
            return self.live_state_type_names[0]
        return self.live_state_alias_name

    @property
    def symbolic_state_type_name(self) -> str | None:
        if not self.symbolic_state_type_names:
            return None
        if len(self.symbolic_state_type_names) == 1:
            return self.symbolic_state_type_names[0]
        return self.symbolic_state_alias_name

    @property
    def group_state_type_name(self) -> str | None:
        if not self.group_state_type_names:
            return None
        if len(self.group_state_type_names) == 1:
            return self.group_state_type_names[0]
        return self.group_state_alias_name

    @property
    def live_state_alias_name(self) -> str:
        return f"_{self.stem}Patch"

    @property
    def symbolic_state_alias_name(self) -> str:
        return f"_{self.stem}Target"

    @property
    def group_state_alias_name(self) -> str:
        return f"_{self.stem}GroupTarget"

    @property
    def live_client_name(self) -> str:
        return self.root.live_client_name

    @property
    def symbolic_client_name(self) -> str:
        return self.root.symbolic_client_name

    @property
    def symbolic_group_name(self) -> str:
        return self.root.symbolic_group_name

    @property
    def ref_names(self) -> tuple[str, ...]:
        return tuple(constituent.ref_name for constituent in self.constituents)

    @property
    def requires_expression(self) -> str:
        return _render_tuple(self.ref_names)

    @property
    def observation_descriptor_name(self) -> str | None:
        descriptors = tuple(
            descriptor
            for constituent in self.constituents
            if (descriptor := constituent.observation_descriptor_name) is not None
        )
        if not descriptors:
            return None
        if len(descriptors) != 1:
            raise AssertionError("generated model has multiple observation descriptors")
        return descriptors[0]

    @property
    def needs_layout(self) -> bool:
        return any(constituent.needs_layout for constituent in self.constituents)


@dataclass(frozen=True, slots=True)
class _BundleFlagFacadeModel:
    factory_name: str
    flag_name: str
    base: _InterfaceModel
    bundle: _InterfaceModel


@dataclass(frozen=True, slots=True)
class _CatalogInterfaceModel:
    interface_type: type[object]
    interface_identity: str
    interface_type_name: str
    constant_prefix: str
    factory_name: str
    root: DeclaredScopeLayout
    states: tuple[DeclaredStateLayout, ...]
    observed_state_type: type[object] | None


@dataclass(frozen=True, slots=True)
class _StateProjectionNames:
    patch: str
    target: str
    group_target: str


def _state_projection_names(layout: DeclaredStateLayout) -> _StateProjectionNames:
    source_name = layout.source_type.__name__
    stem = source_name.removesuffix("State") or source_name
    return _StateProjectionNames(
        patch=f"{stem}Patch",
        target=f"{stem}Target",
        group_target=f"{stem}GroupTarget",
    )


def _state_projection_module(interface_type: type[object]) -> str:
    package, separator, _ = interface_type.__module__.rpartition(".")
    if not separator:
        raise ClientGenerationError(
            "generated state clients require interface declarations in a package"
        )
    return f"{package}.states"


def _register_state_projection_types(
    renderer: _AnnotationRenderer,
    interface_type: type[object],
    layouts: tuple[DeclaredStateLayout, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    names = tuple(_state_projection_names(layout) for layout in layouts)
    if names:
        imported = renderer.imports.setdefault(
            _state_projection_module(interface_type),
            set(),
        )
        imported.update(
            name
            for projection_names in names
            for name in (
                projection_names.patch,
                projection_names.target,
                projection_names.group_target,
            )
        )
    return (
        tuple(item.patch for item in names),
        tuple(item.target for item in names),
        tuple(item.group_target for item in names),
    )


@dataclass(frozen=True, slots=True)
class _MemberProjection:
    name: str
    expression: str
    owner: str


class _AnnotationRenderer:
    """Render resolved catalog annotations and collect their direct imports."""

    def __init__(self) -> None:
        self.imports: dict[str, set[str]] = {}

    def reference(self, annotation: type[object]) -> str:
        return self._reference(annotation)

    def render(self, annotation: object) -> str:
        return self._render(annotation, substitutions={})

    def _render(
        self,
        annotation: object,
        *,
        substitutions: dict[TypeVar, object],
    ) -> str:
        if isinstance(annotation, TypeVar):
            return self._render(
                substitutions[annotation],
                substitutions=substitutions,
            )
        if isinstance(annotation, TypeAliasType):
            return self._render(
                cast("object", annotation.__value__),
                substitutions=substitutions,
            )

        origin = cast("object | None", get_origin(annotation))
        arguments = cast("tuple[object, ...]", get_args(annotation))
        if isinstance(origin, TypeAliasType):
            alias_substitutions = dict(substitutions)
            parameters = cast("tuple[TypeVar, ...]", origin.__type_params__)
            alias_substitutions.update(zip(parameters, arguments, strict=True))
            return self._render(
                cast("object", origin.__value__),
                substitutions=alias_substitutions,
            )
        if origin is types.UnionType or origin is _TYPING_UNION_ORIGIN:
            return " | ".join(
                self._render(argument, substitutions=substitutions)
                for argument in arguments
            )
        if origin is typing.Annotated:
            return self._render(arguments[0], substitutions=substitutions)
        if origin is typing.Literal:
            self.imports.setdefault("typing", set()).add("Literal")
            return (
                "Literal["
                + ", ".join(
                    _string_literal(item) if isinstance(item, str) else repr(item)
                    for item in arguments
                )
                + "]"
            )
        if origin is not None:
            rendered_origin = self._render(origin, substitutions=substitutions)
            rendered_arguments = ", ".join(
                self._render(argument, substitutions=substitutions)
                for argument in arguments
            )
            return f"{rendered_origin}[{rendered_arguments}]"
        if annotation is None or annotation is types.NoneType:
            return "None"
        if isinstance(annotation, type):
            return self._reference(annotation)
        raise ClientGenerationError(
            f"cannot render resolved operation annotation {annotation!r}"
        )

    def _reference(self, annotation: type[object]) -> str:
        if annotation.__module__ == "builtins":
            return annotation.__qualname__
        module = annotation.__module__
        name = annotation.__qualname__
        if module == "scopecat.program.value_refs" and name == "ValueRef":
            module = "scopecat.authoring"
        if "." in name:
            raise ClientGenerationError(
                f"cannot import nested annotation type {module}.{name}"
            )
        self.imports.setdefault(module, set()).add(name)
        return name


def render_catalog_target(target: CatalogTarget) -> tuple[tuple[Path, str], ...]:
    """Render every public projection owned by one interface catalog."""

    models = _catalog_models(target.interface_types)
    return (
        (target.members_output, _render_members_module(models)),
        (target.interfaces_output, _render_interfaces_module(models)),
        (
            target.states_output,
            _render_states_module(models, public_types=target.public_types),
        ),
    )


def _catalog_models(
    interface_types: tuple[type[object], ...],
) -> tuple[_CatalogInterfaceModel, ...]:
    if not interface_types:
        raise ClientGenerationError("an interface catalog requires a declaration")
    models: list[_CatalogInterfaceModel] = []
    seen_identities: set[str] = set()
    for interface_type in interface_types:
        compiled = compile_interface(interface_type)
        layout = declared_interface_layout(compiled)
        identity = f"{interface_type.__module__}.{interface_type.__qualname__}"
        if identity in seen_identities:
            raise ClientGenerationError(
                f"interface catalog repeats declaration {identity}"
            )
        seen_identities.add(identity)
        interface_name = interface_type.__name__
        stem = interface_name.removesuffix("Interface")
        models.append(
            _CatalogInterfaceModel(
                interface_type=interface_type,
                interface_identity=identity,
                interface_type_name=interface_name,
                constant_prefix=_snake_case(stem).upper(),
                factory_name=f"{_snake_case(stem)}_interface",
                root=layout.root,
                states=layout.states,
                observed_state_type=(
                    None
                    if layout.observed_state is None
                    else layout.observed_state.state_type
                ),
            )
        )
    return tuple(models)


def _render_members_module(models: tuple[_CatalogInterfaceModel, ...]) -> str:
    projections = tuple(
        projection
        for model in models
        for projection in _interface_member_projections(model)
    )
    _validate_member_projections(projections)
    imports: dict[str, set[str]] = {
        "scopecat.sdk.instruments.declarations": {"declared_interface_ref"},
    }
    for model in models:
        imports.setdefault(model.interface_type.__module__, set()).add(
            model.interface_type_name
        )
    declarations = "".join(
        _render_member_projection(projection) for projection in projections
    )
    return (
        _generated_module_header(
            "Typed identities generated from the declared instrument interfaces."
        )
        + _render_import_block(imports)
        + "\n"
        + declarations
        + _render_all(tuple(projection.name for projection in projections))
    )


def _interface_member_projections(
    model: _CatalogInterfaceModel,
) -> tuple[_MemberProjection, ...]:
    root_name = model.constant_prefix
    projections = [
        _MemberProjection(
            name=root_name,
            expression=f"declared_interface_ref({model.interface_type_name})",
            owner=f"{model.interface_identity} interface",
        )
    ]
    _append_scope_member_projections(
        projections,
        model.root,
        scope_name=root_name,
        owner_prefix=model.interface_identity,
    )
    return tuple(projections)


def _append_scope_member_projections(
    projections: list[_MemberProjection],
    scope: DeclaredScopeLayout,
    *,
    scope_name: str,
    owner_prefix: str,
) -> None:
    scope_path = ".".join(scope.python_path) or "<root>"
    for property_spec in scope.spec.properties:
        name = _join_constant_name(scope_name, property_spec.id)
        projections.append(
            _MemberProjection(
                name=name,
                expression=(
                    f"{scope_name}.property({_string_literal(property_spec.id)})"
                ),
                owner=f"{owner_prefix} scope {scope_path} property {property_spec.id}",
            )
        )
    for operation in scope.operations:
        operation_name = _join_constant_name(
            scope_name,
            operation.ref.operation_id,
        )
        projections.append(
            _MemberProjection(
                name=operation_name,
                expression=(
                    f"{scope_name}.operation("
                    f"{_string_literal(operation.ref.operation_id)})"
                ),
                owner=(
                    f"{owner_prefix} scope {scope_path} operation "
                    f"{operation.method_name}"
                ),
            )
        )
        for argument in operation.arguments:
            argument_name = _join_constant_name(
                operation_name,
                argument.ref.argument_id,
            )
            projections.append(
                _MemberProjection(
                    name=argument_name,
                    expression=(
                        f"{operation_name}.argument("
                        f"{_string_literal(argument.ref.argument_id)})"
                    ),
                    owner=(
                        f"{owner_prefix} scope {scope_path} operation "
                        f"{operation.method_name} argument {argument.python_name}"
                    ),
                )
            )
    for acquisition in scope.acquisitions:
        acquisition_name = _join_constant_name(
            scope_name,
            acquisition.method_name,
        )
        if acquisition_name == scope_name:
            acquisition_name = f"{scope_name}_ACQUISITION"
        projections.append(
            _MemberProjection(
                name=acquisition_name,
                expression=(
                    f"{scope_name}.acquisition("
                    f"{_string_literal(acquisition.ref.acquisition_id)})"
                ),
                owner=(
                    f"{owner_prefix} scope {scope_path} acquisition "
                    f"{acquisition.method_name}"
                ),
            )
        )
        seen_results: set[object] = set()
        for result_field in acquisition.result_fields:
            if result_field.ref in seen_results:
                continue
            seen_results.add(result_field.ref)
            result_name = (
                f"{_join_constant_name(scope_name, result_field.python_name)}_RESULT"
            )
            projections.append(
                _MemberProjection(
                    name=result_name,
                    expression=(
                        f"{acquisition_name}.result("
                        f"{_string_literal(result_field.result_id)})"
                    ),
                    owner=(
                        f"{owner_prefix} scope {scope_path} acquisition "
                        f"{acquisition.method_name} result {result_field.python_name}"
                    ),
                )
            )
    for component in scope.components:
        component_id = component.spec.id
        component_name = _join_constant_name(scope_name, component_id)
        component_path = ".".join(component.python_path)
        projections.append(
            _MemberProjection(
                name=component_name,
                expression=f"{scope_name}.component({_string_literal(component_id)})",
                owner=f"{owner_prefix} component {component_path}",
            )
        )
        _append_scope_member_projections(
            projections,
            component,
            scope_name=component_name,
            owner_prefix=owner_prefix,
        )


def _validate_member_projections(
    projections: tuple[_MemberProjection, ...],
) -> None:
    owners_by_name: dict[str, list[str]] = {}
    for projection in projections:
        owners_by_name.setdefault(projection.name, []).append(projection.owner)
    collisions = {
        name: owners for name, owners in owners_by_name.items() if len(owners) > 1
    }
    if not collisions:
        return
    details = "; ".join(
        f"{name}: {' vs '.join(owners)}" for name, owners in sorted(collisions.items())
    )
    raise ClientGenerationError(f"generated catalog symbol collisions: {details}")


def _render_member_projection(projection: _MemberProjection) -> str:
    compact = f"{projection.name} = {projection.expression}\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    receiver, separator, invocation = projection.expression.rpartition(".")
    if not separator:
        return f"{projection.name} = (\n    {projection.expression}\n)\n"
    method, separator, argument = invocation.partition("(")
    if not separator or not argument.endswith(")"):
        raise ClientGenerationError(
            f"cannot wrap generated member expression {projection.expression!r}"
        )
    call_prefix = f"{projection.name} = {receiver}.{method}("
    if len(call_prefix) <= 88:
        return f"{call_prefix}\n    {argument[:-1]},\n)\n"
    return (
        f"{projection.name} = (\n"
        f"    {receiver}.{method}(\n"
        f"        {argument[:-1]},\n"
        "    )\n"
        ")\n"
    )


def _render_interfaces_module(models: tuple[_CatalogInterfaceModel, ...]) -> str:
    owners_by_name: dict[str, list[str]] = {}
    imports: dict[str, set[str]] = {
        "scopecat.sdk.instruments": {"InterfaceSpec"},
        "scopecat.sdk.instruments.declarations": {"compile_interface"},
    }
    declarations: list[str] = []
    for model in models:
        owners_by_name.setdefault(model.factory_name, []).append(
            model.interface_identity
        )
        imports.setdefault(model.interface_type.__module__, set()).add(
            model.interface_type_name
        )
        declarations.append(
            "\n\n"
            f"def {model.factory_name}() -> InterfaceSpec:\n"
            f"    return compile_interface({model.interface_type_name}).fresh_spec()\n"
        )
    collisions = {
        name: owners for name, owners in owners_by_name.items() if len(owners) > 1
    }
    if collisions:
        details = "; ".join(
            f"{name}: {' vs '.join(owners)}"
            for name, owners in sorted(collisions.items())
        )
        raise ClientGenerationError(
            f"generated interface factory collisions: {details}"
        )
    return (
        _generated_module_header(
            "Vendor-neutral interface factories generated from Python declarations."
        )
        + _render_import_block(imports)
        + "".join(declarations)
        + "\n"
        + _render_all(tuple(model.factory_name for model in models))
    )


def _render_states_module(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    public_types: tuple[object, ...],
) -> str:
    renderer = _AnnotationRenderer()
    imports: dict[str, set[str]] = {}
    exports_by_name: dict[str, str] = {}
    declarations: list[str] = []
    seen_sources: dict[type[object], DeclaredStateLayout] = {}

    for candidate in (
        *(
            model.observed_state_type
            for model in models
            if model.observed_state_type is not None
        ),
        *public_types,
    ):
        module, name = _public_type_location(candidate)
        owner = f"{module}.{name}"
        existing = exports_by_name.get(name)
        if existing is not None and existing != owner:
            raise ClientGenerationError(
                f"generated state export collision {name}: {existing} vs {owner}"
            )
        exports_by_name[name] = owner
        imports.setdefault(module, set()).add(f"{name} as {name}")

    has_states = any(model.states for model in models)
    if has_states:
        imports["scopecat.authoring"] = {"PerEntity", "ValueRef"}
        imports["scopecat.sdk.instruments.declarations"] = {
            "compile_interface",
            "declared_interface_layout",
            "instrument_state_projection",
            "state_projection_field",
        }

    for model in models:
        if not model.states:
            continue
        imports.setdefault(model.interface_type.__module__, set()).add(
            model.interface_type_name
        )
        layouts_name = f"_{model.constant_prefix}_STATE_LAYOUTS"
        declarations.append(
            ("\n\n" if declarations else "\n")
            + f"{layouts_name} = declared_interface_layout(\n"
            f"    compile_interface({model.interface_type_name})\n"
            ").states\n"
        )
        for index, layout in enumerate(model.states):
            existing_layout = seen_sources.get(layout.source_type)
            if existing_layout is not None:
                if existing_layout != layout:
                    raise ClientGenerationError(
                        "one state schema produced inconsistent projection layouts: "
                        f"{layout.source_type.__module__}."
                        f"{layout.source_type.__qualname__}"
                    )
                continue
            seen_sources[layout.source_type] = layout
            names = _state_projection_names(layout)
            owner = f"{layout.source_type.__module__}.{layout.source_type.__qualname__}"
            for name in (names.patch, names.target, names.group_target):
                existing = exports_by_name.get(name)
                if existing is not None:
                    raise ClientGenerationError(
                        f"generated state export collision {name}: "
                        f"{existing} vs {owner}"
                    )
                exports_by_name[name] = owner
            layout_expression = f"{layouts_name}[{index}]"
            declarations.extend(
                (
                    _render_state_projection(
                        names.patch,
                        layout,
                        layout_expression=layout_expression,
                        renderer=renderer,
                        projection="live",
                    ),
                    _render_state_projection(
                        names.target,
                        layout,
                        layout_expression=layout_expression,
                        renderer=renderer,
                        projection="symbolic",
                    ),
                    _render_state_projection(
                        names.group_target,
                        layout,
                        layout_expression=layout_expression,
                        renderer=renderer,
                        projection="group",
                    ),
                )
            )

    for module, names in renderer.imports.items():
        imports.setdefault(module, set()).update(names)
    import_block = _render_import_block(imports) if imports else ""
    return (
        _generated_module_header(
            "Typed state projections generated from instrument interfaces."
        )
        + import_block
        + "".join(declarations)
        + ("\n" if declarations else "")
        + _render_all(tuple(exports_by_name))
    )


def _render_state_projection(
    name: str,
    layout: DeclaredStateLayout,
    *,
    layout_expression: str,
    renderer: _AnnotationRenderer,
    projection: str,
) -> str:
    required = frozenset(layout.required_fields)
    fields: list[str] = []
    for declared_field in layout.fields:
        concrete = renderer.render(declared_field.annotation)
        if projection == "live":
            annotation = concrete
        elif projection == "symbolic":
            annotation = f"{concrete} | ValueRef"
        elif projection == "group":
            annotation = f"{concrete} | ValueRef | PerEntity[{concrete} | ValueRef]"
        else:
            raise AssertionError(f"unknown state projection {projection!r}")
        fields.append(
            _render_state_projection_field(
                declared_field.python_name,
                annotation,
                required=declared_field.python_name in required,
            )
        )
    body = "".join(fields) or "    pass\n"
    return (
        f"\n\n@instrument_state_projection({layout_expression})\nclass {name}:\n{body}"
    )


def _render_state_projection_field(
    name: str,
    annotation: str,
    *,
    required: bool,
) -> str:
    default = "" if required else " = state_projection_field()"
    compact = f"    {name}: {annotation}{default}\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    if not required:
        wrapped_default = f"    {name}: {annotation} = (\n"
        if len(wrapped_default.rstrip("\n")) <= 88:
            return wrapped_default + "        state_projection_field()\n    )\n"

    branches = _split_top_level_union(annotation)
    if len(branches) == 1:
        return compact
    lines = [f"    {name}: (\n", f"        {branches[0]}\n"]
    lines.extend(f"        | {branch}\n" for branch in branches[1:])
    lines.append("    )")
    if not required:
        lines.append(" = state_projection_field()")
    lines.append("\n")
    return "".join(lines)


def _split_top_level_union(annotation: str) -> tuple[str, ...]:
    branches: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(annotation):
        character = annotation[index]
        if character in "[({":
            depth += 1
        elif character in "])}":
            depth -= 1
        elif depth == 0 and annotation.startswith(" | ", index):
            branches.append(annotation[start:index])
            index += 2
            start = index + 1
        index += 1
    branches.append(annotation[start:])
    return tuple(branches)


def render_generation_target(target: GenerationTarget) -> str:
    """Render one configured generated module."""

    return render_client_module(target.surfaces)


def render_client_module(
    surfaces: tuple[GenerationSurface, ...],
) -> str:
    """Render an independently importable module for selected declarations."""

    renderer = _AnnotationRenderer()
    suppressed_families = _facade_base_identities(surfaces)
    models = tuple(
        _generation_model(
            surface,
            renderer=renderer,
            suppressed_families=suppressed_families,
        )
        for surface in surfaces
    )
    if not models:
        raise ClientGenerationError("a generated client module requires a declaration")
    facade_models = _bundle_flag_facade_models(surfaces, models=models)
    _validate_generated_symbols(models, facades=facade_models)

    sections = [
        _render_header(models, facades=facade_models, renderer=renderer),
        _render_interface_refs(models),
        _render_descriptors(models),
    ]
    for model in models:
        sections.extend(
            (
                _render_state_alias(model),
                _render_result_types(model),
                _render_live_scopes(model),
                _render_symbolic_scopes(model),
                _render_symbolic_group_scopes(model),
                _render_family(model),
            )
        )
    sections.append(_render_bundle_flag_facades(facade_models))
    sections.append(_render_exports(models, facades=facade_models))
    return "".join(sections)


def _generation_model(
    surface: GenerationSurface,
    *,
    renderer: _AnnotationRenderer,
    suppressed_families: frozenset[str],
) -> _InterfaceModel:
    if isinstance(surface, BundleClientSurface):
        return _bundle_model(surface, renderer=renderer)
    return _interface_model(
        surface,
        renderer=renderer,
        generate_family=_type_identity(surface.interface_type)
        not in suppressed_families,
    )


def _interface_model(
    surface: ClientSurface,
    *,
    renderer: _AnnotationRenderer,
    generate_family: bool,
) -> _InterfaceModel:
    constituent = _constituent_model(surface.interface_type, renderer=renderer)
    layout = constituent.layout
    interface_name = surface.interface_type.__name__
    stem = interface_name.removesuffix("Interface")
    overrides = dict(surface.public_name_overrides)
    observation_type_name = (
        None
        if layout.observed_state is None
        else renderer.reference(layout.observed_state.state_type)
    )
    root = _scope_model(
        layout.root,
        interface_stem=stem,
        constant_prefix=constituent.constant_prefix,
        overrides=overrides,
        renderer=renderer,
    )
    live_states, symbolic_states, group_states = _register_state_projection_types(
        renderer,
        surface.interface_type,
        layout.states,
    )
    return _InterfaceModel(
        interface_identity=(
            f"{surface.interface_type.__module__}.{surface.interface_type.__qualname__}"
        ),
        stem=stem,
        factory_name=overrides.get("factory", _snake_case(stem)),
        generate_family=generate_family,
        observation_type_name=observation_type_name,
        live_state_type_names=live_states,
        symbolic_state_type_names=symbolic_states,
        group_state_type_names=group_states,
        constituents=(constituent,),
        root=root,
    )


def _bundle_model(
    surface: BundleClientSurface,
    *,
    renderer: _AnnotationRenderer,
) -> _InterfaceModel:
    bundle_type = surface.bundle_type
    bundle_identity = f"{bundle_type.__module__}.{bundle_type.__qualname__}"
    constituents = tuple(
        _constituent_model(interface_type, renderer=renderer)
        for interface_type in declared_bundle_interfaces(bundle_type)
    )
    for constituent in constituents:
        if constituent.layout.root.components:
            raise ClientGenerationError(
                f"generated bundle {bundle_identity} only supports root members; "
                f"constituent {constituent.interface_identity} declares components"
            )

    owners_by_method: dict[str, list[str]] = {}
    for constituent in constituents:
        for operation in constituent.layout.root.operations:
            owners_by_method.setdefault(operation.method_name, []).append(
                f"{constituent.interface_identity} operation"
            )
        for acquisition in constituent.layout.root.acquisitions:
            owners_by_method.setdefault(acquisition.method_name, []).append(
                f"{constituent.interface_identity} acquisition"
            )
    method_collisions = {
        name: owners for name, owners in owners_by_method.items() if len(owners) > 1
    }
    if method_collisions:
        details = "; ".join(
            f"{name}: {' vs '.join(owners)}"
            for name, owners in sorted(method_collisions.items())
        )
        raise ClientGenerationError(
            f"generated bundle method collisions for {bundle_identity}: {details}"
        )

    observed_constituents = tuple(
        constituent
        for constituent in constituents
        if constituent.observation_type_name is not None
    )
    if len(observed_constituents) > 1:
        rendered = ", ".join(
            constituent.interface_identity for constituent in observed_constituents
        )
        raise ClientGenerationError(
            f"generated bundle {bundle_identity} has multiple observed states: "
            f"{rendered}"
        )

    bundle_name = bundle_type.__name__
    stem = bundle_name.removesuffix("Interface")
    scopes = tuple(
        _scope_model(
            constituent.layout.root,
            interface_stem=stem,
            constant_prefix=constituent.constant_prefix,
            overrides={},
            renderer=renderer,
        )
        for constituent in constituents
    )
    root = _ScopeModel(
        python_path=(),
        class_stem=stem,
        operations=tuple(
            operation for scope in scopes for operation in scope.operations
        ),
        acquisitions=tuple(
            acquisition for scope in scopes for acquisition in scope.acquisitions
        ),
        components=(),
    )
    state_layouts: list[DeclaredStateLayout] = []
    live_states: list[str] = []
    symbolic_states: list[str] = []
    group_states: list[str] = []
    for constituent in constituents:
        new_layouts = tuple(
            layout
            for layout in constituent.layout.states
            if all(layout.source_type is not item.source_type for item in state_layouts)
        )
        state_layouts.extend(new_layouts)
        registered = _register_state_projection_types(
            renderer,
            constituent.layout.compiled.interface_type,
            new_layouts,
        )
        live_states.extend(registered[0])
        symbolic_states.extend(registered[1])
        group_states.extend(registered[2])
    return _InterfaceModel(
        interface_identity=bundle_identity,
        stem=stem,
        factory_name=_snake_case(stem),
        generate_family=False,
        observation_type_name=(
            None
            if not observed_constituents
            else observed_constituents[0].observation_type_name
        ),
        live_state_type_names=tuple(live_states),
        symbolic_state_type_names=tuple(symbolic_states),
        group_state_type_names=tuple(group_states),
        constituents=constituents,
        root=root,
    )


def _constituent_model(
    interface_type: type[object],
    *,
    renderer: _AnnotationRenderer,
) -> _InterfaceConstituentModel:
    compiled = compile_interface(interface_type)
    layout = declared_interface_layout(compiled)
    interface_name = interface_type.__name__
    observation_type_name = (
        None
        if layout.observed_state is None
        else renderer.reference(layout.observed_state.state_type)
    )
    return _InterfaceConstituentModel(
        interface_identity=f"{interface_type.__module__}.{interface_type.__qualname__}",
        interface_type_name=renderer.reference(interface_type),
        constant_prefix=_snake_case(interface_name.removesuffix("Interface")).upper(),
        layout=layout,
        observation_type_name=observation_type_name,
    )


def _facade_base_identities(
    surfaces: tuple[GenerationSurface, ...],
) -> frozenset[str]:
    identities: set[str] = set()
    for surface in surfaces:
        if not isinstance(surface, BundleClientSurface):
            continue
        if surface.facade_flag is None:
            continue
        bundle_identity = _type_identity(surface.bundle_type)
        constituent_types = declared_bundle_interfaces(surface.bundle_type)
        if len(constituent_types) != 2:
            raise ClientGenerationError(
                f"bundle facade {bundle_identity} requires exactly two interfaces"
            )
        identities.add(_type_identity(constituent_types[0]))
    return frozenset(identities)


def _bundle_flag_facade_models(
    surfaces: tuple[GenerationSurface, ...],
    *,
    models: tuple[_InterfaceModel, ...],
) -> tuple[_BundleFlagFacadeModel, ...]:
    models_by_identity = {model.interface_identity: model for model in models}
    resolved: list[_BundleFlagFacadeModel] = []
    for surface in surfaces:
        if not isinstance(surface, BundleClientSurface):
            continue
        flag_name = surface.facade_flag
        if flag_name is None:
            continue
        if not flag_name.isidentifier() or keyword.iskeyword(flag_name):
            raise ClientGenerationError(
                f"bundle facade flag must be a Python identifier: {flag_name!r}"
            )
        if flag_name in _FACADE_PARAMETER_NAMES:
            raise ClientGenerationError(
                f"bundle facade flag reserves factory parameter {flag_name!r}"
            )
        bundle_type = surface.bundle_type
        bundle_identity = _type_identity(bundle_type)
        constituent_types = declared_bundle_interfaces(bundle_type)
        if len(constituent_types) != 2:
            raise AssertionError(
                "facade constituent count was validated before modeling"
            )
        base_type, _ = constituent_types
        base_identity = _type_identity(base_type)
        base = models_by_identity.get(base_identity)
        if base is None or len(base.constituents) != 1:
            raise ClientGenerationError(
                f"bundle facade {bundle_identity} requires its first constituent "
                f"{base_identity} as a generated base surface"
            )
        bundle = models_by_identity.get(bundle_identity)
        if bundle is None or tuple(
            constituent.interface_identity for constituent in bundle.constituents
        ) != tuple(
            _type_identity(interface_type) for interface_type in constituent_types
        ):
            raise ClientGenerationError(
                f"bundle facade {bundle_identity} requires a generated bundle surface"
            )
        resolved.append(
            _BundleFlagFacadeModel(
                factory_name=base.factory_name,
                flag_name=flag_name,
                base=base,
                bundle=bundle,
            )
        )
    return tuple(resolved)


def _validate_generated_symbols(
    models: tuple[_InterfaceModel, ...],
    *,
    facades: tuple[_BundleFlagFacadeModel, ...] = (),
) -> None:
    owners_by_symbol: dict[str, list[str]] = {}

    def register(symbol: str, owner: str) -> None:
        owners_by_symbol.setdefault(symbol, []).append(owner)

    for constituent in _unique_constituents(models):
        declaration = constituent.interface_identity
        register(constituent.ref_name, f"{declaration} interface ref")
        if constituent.needs_layout:
            register(constituent.layout_name, f"{declaration} layout")
        if constituent.observation_descriptor_name is not None:
            register(
                constituent.observation_descriptor_name,
                f"{declaration} observation",
            )
        for scope in _walk_declared_scopes(constituent.layout.root):
            path = ".".join(scope.python_path) or "<root>"
            scope_owner = f"{declaration} scope {path}"
            for operation in scope.operations:
                register(
                    _descriptor_name(
                        constituent.constant_prefix,
                        scope.python_path,
                        operation.method_name,
                    ),
                    f"{scope_owner} operation {operation.method_name}",
                )
            for acquisition in scope.acquisitions:
                register(
                    _descriptor_name(
                        constituent.constant_prefix,
                        scope.python_path,
                        acquisition.method_name,
                    ),
                    f"{scope_owner} acquisition {acquisition.method_name}",
                )

    for model in models:
        declaration = model.interface_identity
        for type_names, alias_name, projection in (
            (
                model.live_state_type_names,
                model.live_state_alias_name,
                "live patch",
            ),
            (
                model.symbolic_state_type_names,
                model.symbolic_state_alias_name,
                "symbolic target",
            ),
            (
                model.group_state_type_names,
                model.group_state_alias_name,
                "group target",
            ),
        ):
            if len(type_names) > 1:
                register(alias_name, f"{declaration} {projection} union")
        if model.generate_family:
            register(model.factory_name, f"{declaration} factory")
        for scope in _walk_scopes(model.root):
            path = ".".join(scope.python_path) or "<root>"
            scope_owner = f"{declaration} scope {path}"
            register(scope.live_client_name, f"{scope_owner} live client")
            register(scope.symbolic_client_name, f"{scope_owner} symbolic client")
            register(scope.symbolic_group_name, f"{scope_owner} symbolic group")
            for acquisition in scope.acquisitions:
                acquisition_owner = (
                    f"{scope_owner} acquisition {acquisition.method_name}"
                )
                register(
                    acquisition.readback_name,
                    f"{acquisition_owner} live results",
                )
                register(
                    acquisition.products_name,
                    f"{acquisition_owner} symbolic results",
                )

    for facade in facades:
        register(
            facade.factory_name,
            f"{facade.bundle.interface_identity} boolean facade",
        )

    collisions = {
        symbol: owners for symbol, owners in owners_by_symbol.items() if len(owners) > 1
    }
    if not collisions:
        return
    details = "; ".join(
        f"{symbol}: {' vs '.join(owners)}"
        for symbol, owners in sorted(collisions.items())
    )
    raise ClientGenerationError(f"generated symbol collisions: {details}")


def _scope_model(
    scope: DeclaredScopeLayout,
    *,
    interface_stem: str,
    constant_prefix: str,
    overrides: dict[str, str],
    renderer: _AnnotationRenderer,
) -> _ScopeModel:
    class_stem = interface_stem + "".join(
        _pascal_case(name) for name in scope.python_path
    )
    operations = tuple(
        _operation_model(
            operation,
            python_path=scope.python_path,
            constant_prefix=constant_prefix,
            renderer=renderer,
        )
        for operation in scope.operations
    )
    acquisitions = tuple(
        _acquisition_model(
            acquisition,
            python_path=scope.python_path,
            constant_prefix=constant_prefix,
            overrides=overrides,
            renderer=renderer,
        )
        for acquisition in scope.acquisitions
    )
    components = tuple(
        _scope_model(
            component,
            interface_stem=interface_stem,
            constant_prefix=constant_prefix,
            overrides=overrides,
            renderer=renderer,
        )
        for component in scope.components
    )
    return _ScopeModel(
        python_path=scope.python_path,
        class_stem=class_stem,
        operations=operations,
        acquisitions=acquisitions,
        components=components,
    )


def _operation_model(
    operation: DeclaredOperation[...],
    *,
    python_path: tuple[str, ...],
    constant_prefix: str,
    renderer: _AnnotationRenderer,
) -> _OperationModel:
    arguments: list[_OperationArgumentModel] = []
    for argument in operation.arguments:
        if argument.python_name == "effect_id":
            qualified_method = ".".join((*python_path, operation.method_name))
            raise ClientGenerationError(
                "generated symbolic clients reserve operation parameter "
                f"{qualified_method}.effect_id"
            )
        if isinstance(argument.spec.value_type.atom, PayloadType):
            qualified_method = ".".join((*python_path, operation.method_name))
            raise ClientGenerationError(
                "generated clients do not support payload operation argument "
                f"{qualified_method}.{argument.python_name}"
            )
        concrete_annotation = renderer.render(argument.annotation)
        arguments.append(
            _OperationArgumentModel(
                python_name=argument.python_name,
                kind=argument.parameter.kind.name,
                concrete_annotation=concrete_annotation,
                symbolic_annotation=f"{concrete_annotation} | ValueRef",
            )
        )
    return _OperationModel(
        method_name=operation.method_name,
        descriptor_name=_descriptor_name(
            constant_prefix,
            python_path,
            operation.method_name,
        ),
        arguments=tuple(arguments),
    )


def _acquisition_model(
    acquisition: DeclaredAcquisition[object],
    *,
    python_path: tuple[str, ...],
    constant_prefix: str,
    overrides: dict[str, str],
    renderer: _AnnotationRenderer,
) -> _AcquisitionModel:
    result_alias = acquisition.layouts[0].result_type
    result_type = cast("type[object]", get_origin(result_alias) or result_alias)
    result_type_name = renderer.reference(result_type)
    result_stem = result_type_name.removesuffix("Results")
    method_name = acquisition.method_name
    override_prefix = ".".join((*python_path, method_name))
    return _AcquisitionModel(
        method_name=method_name,
        descriptor_name=_descriptor_name(
            constant_prefix,
            python_path,
            method_name,
        ),
        result_type_name=result_type_name,
        result_type_arguments=len(get_args(result_alias)),
        readback_name=overrides.get(
            f"{override_prefix}.readback",
            f"{result_stem}Readback",
        ),
        products_name=overrides.get(
            f"{override_prefix}.products",
            f"{result_stem}Products",
        ),
    )


def _render_header(
    models: tuple[_InterfaceModel, ...],
    *,
    facades: tuple[_BundleFlagFacadeModel, ...],
    renderer: _AnnotationRenderer,
) -> str:
    scopes = tuple(scope for model in models for scope in _walk_scopes(model.root))
    has_components = any(not scope.is_root for scope in scopes)
    has_operations = any(scope.operations for scope in scopes)
    has_acquisitions = any(scope.acquisitions for scope in scopes)
    has_observations = any(model.observation_type_name for model in models)
    has_state = any(model.live_state_type_name is not None for model in models)
    has_plain_root = any(model.live_state_type_name is None for model in models)

    imports: dict[str, set[str]] = {
        "scopecat.authoring": {"EachEntity", "OneEntity"},
        "scopecat_instruments._symbolic_runtime": {"SymbolicInstrumentRecorder"},
    }
    if facades:
        imports["typing"] = {"Literal", "overload"}
        imports["scopecat.api._instruments"] = {"InstrumentRef", "instrument"}
        imports["scopecat.authoring"].add("EntitySelection")
    if any(model.generate_family for model in models):
        imports["scopecat_instruments._family_runtime"] = {"InstrumentFamily"}
    imports["scopecat.sdk.instruments.declarations"] = {"declared_interface_ref"}
    if any(model.needs_layout for model in models):
        imports["scopecat.sdk.instruments.declarations"].update(
            {"compile_interface", "declared_interface_layout"}
        )
    if has_plain_root:
        imports["scopecat_instruments._client_runtime"] = {"InstrumentClientBase"}
        imports["scopecat_instruments._symbolic_runtime"].update(
            {
                "SymbolicInstrumentClientBase",
                "SymbolicInstrumentGroupBase",
            }
        )
    if has_state:
        imports.setdefault("scopecat_instruments._client_runtime", set()).add(
            "DeclaredStateClientBase"
        )
        imports["scopecat_instruments._symbolic_runtime"].update(
            {
                "DeclaredStateSymbolicClientBase",
                "DeclaredStateSymbolicGroupBase",
            }
        )
    if has_operations or has_acquisitions:
        imports["scopecat.authoring"].add("PerEntity")
    if has_operations:
        imports["scopecat.authoring"].add("ValueRef")
    if has_acquisitions:
        imports["dataclasses"] = {"dataclass", "field"}
        imports["scopecat.authoring"].add("ProductRef")
        imports["scopecat.records.measurement"] = {"MeasurementValue"}
        imports["scopecat.sdk.instruments"] = {"CollectReceipt"}
    if has_operations:
        imports.setdefault("scopecat.sdk.instruments", set()).add("InvokeReceipt")
    if has_observations:
        imports.setdefault("typing", set()).add("cast")
        imports["scopecat.sdk.instruments.declarations"].add("DeclaredObservedState")
    if has_components:
        imports["scopecat_instruments._client_runtime"].add(
            "InstrumentComponentClientBase"
        )
        imports["scopecat_instruments._symbolic_runtime"].update(
            {
                "SymbolicInstrumentComponentClientBase",
                "SymbolicInstrumentComponentGroupBase",
            }
        )
    for module, names in renderer.imports.items():
        imports.setdefault(module, set()).update(names)

    return (
        "# This file was auto-generated by scripts/generate_instrument_clients.py.\n"
        "# Do not make direct changes to the file.\n"
        '"""Typed live and symbolic clients generated from interface declarations."""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        f"{_render_import_block(imports)}"
    )


def _render_from_import(module: str, names: set[str]) -> str:
    bare_names = {name for name in names if " as " not in name}
    aliases = names - bare_names
    rendered = _render_bare_from_import(module, bare_names) if bare_names else ""
    return rendered + "".join(
        f"from {module} import (\n    {alias},\n)\n"
        for alias in sorted(aliases, key=str.casefold)
    )


def _render_bare_from_import(module: str, names: set[str]) -> str:
    ordered = sorted(names, key=_import_name_key)
    compact = f"from {module} import {', '.join(ordered)}\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return (
        f"from {module} import (\n"
        + "".join(f"    {name},\n" for name in ordered)
        + ")\n"
    )


def _render_import_block(imports: dict[str, set[str]]) -> str:
    standard_modules = {"dataclasses", "typing"}
    external_modules = {module for module in imports if module.startswith("scopecat.")}
    local_modules = imports.keys() - standard_modules - external_modules
    standard_imports = "".join(
        _render_from_import(module, imports[module])
        for module in sorted(standard_modules & imports.keys())
    )
    external_imports = "".join(
        _render_from_import(module, imports[module])
        for module in sorted(external_modules)
    )
    local_imports = "".join(
        _render_from_import(module, imports[module]) for module in sorted(local_modules)
    )
    return (
        f"{standard_imports}"
        f"{'\n' if standard_imports and external_imports else ''}"
        f"{external_imports}"
        f"{'\n' if (standard_imports or external_imports) and local_imports else ''}"
        f"{local_imports}"
    )


def _generated_module_header(description: str) -> str:
    return (
        "# This file was auto-generated by scripts/generate_instrument_clients.py.\n"
        "# Do not make direct changes to the file.\n"
        f'"""{description}"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
    )


def _render_all(exports: tuple[str, ...]) -> str:
    return (
        "\n__all__ = [\n"
        + "".join(f'    "{name}",\n' for name in sorted(exports))
        + "]\n"
    )


def _public_type_location(value: object) -> tuple[str, str]:
    if isinstance(value, TypeAliasType):
        module = cast("str", value.__module__)
        name = value.__name__
    elif isinstance(value, type):
        module = value.__module__
        name = value.__qualname__
    else:
        raise ClientGenerationError(f"cannot re-export public type {value!r}")
    if "." in name:
        raise ClientGenerationError(
            f"cannot re-export nested public type {module}.{name}"
        )
    return module, name


def _import_name_key(name: str) -> tuple[int, str]:
    if name.isupper():
        return (0, name)
    if name[0].isupper():
        return (1, name)
    return (2, name)


def _render_state_alias(model: _InterfaceModel) -> str:
    return "".join(
        _render_type_union(alias_name, type_names)
        for alias_name, type_names in (
            (model.live_state_alias_name, model.live_state_type_names),
            (model.symbolic_state_alias_name, model.symbolic_state_type_names),
            (model.group_state_alias_name, model.group_state_type_names),
        )
        if len(type_names) > 1
    )


def _render_type_union(alias_name: str, type_names: tuple[str, ...]) -> str:
    union = " | ".join(type_names)
    compact = f"type {alias_name} = {union}\n"
    if len(compact.rstrip("\n")) <= 88:
        return "\n\n" + compact
    if len(f"    {union}") <= 88:
        return f"\n\ntype {alias_name} = (\n    {union}\n)\n"
    return (
        f"\n\ntype {alias_name} = (\n"
        + "\n".join(
            f"    {'| ' if index else ''}{state_type}"
            for index, state_type in enumerate(type_names)
        )
        + "\n)\n"
    )


def _render_interface_refs(models: tuple[_InterfaceModel, ...]) -> str:
    return "".join(
        f"\n{constituent.ref_name} = declared_interface_ref("
        f"{constituent.interface_type_name})\n"
        for constituent in _unique_constituents(models)
    )


def _render_descriptors(models: tuple[_InterfaceModel, ...]) -> str:
    return "".join(
        _render_constituent_descriptors(constituent)
        for constituent in _unique_constituents(models)
    )


def _render_constituent_descriptors(
    constituent: _InterfaceConstituentModel,
) -> str:
    if not constituent.needs_layout:
        return ""
    compact_layout = (
        f"{constituent.layout_name} = declared_interface_layout("
        f"compile_interface({constituent.interface_type_name}))\n"
    )
    sections = ["\n"]
    if len(compact_layout.rstrip("\n")) <= 88:
        sections.append(compact_layout)
    else:
        sections.extend(
            (
                f"{constituent.layout_name} = declared_interface_layout(\n",
                f"    compile_interface({constituent.interface_type_name})\n",
                ")\n",
            )
        )
    if constituent.observation_type_name is not None:
        observation_name = constituent.observation_descriptor_name
        if observation_name is None:
            raise AssertionError("observed constituent requires a descriptor name")
        sections.extend(
            (
                f"{observation_name} = cast(\n",
                f'    "DeclaredObservedState[{constituent.observation_type_name}]",\n',
                f"    {constituent.layout_name}.observed_state,\n",
                ")\n",
            )
        )
    _append_declared_scope_descriptors(
        sections,
        constituent.layout.root,
        scope_expression=f"{constituent.layout_name}.root",
        constant_prefix=constituent.constant_prefix,
    )
    return "".join(sections)


def _append_declared_scope_descriptors(
    sections: list[str],
    scope: DeclaredScopeLayout,
    *,
    scope_expression: str,
    constant_prefix: str,
) -> None:
    sections.extend(
        _render_descriptor_assignment(
            _descriptor_name(
                constant_prefix,
                scope.python_path,
                operation.method_name,
            ),
            scope_expression,
            collection="operations",
            index=index,
        )
        for index, operation in enumerate(scope.operations)
    )
    sections.extend(
        _render_descriptor_assignment(
            _descriptor_name(
                constant_prefix,
                scope.python_path,
                acquisition.method_name,
            ),
            scope_expression,
            collection="acquisitions",
            index=index,
        )
        for index, acquisition in enumerate(scope.acquisitions)
    )
    for index, component in enumerate(scope.components):
        _append_declared_scope_descriptors(
            sections,
            component,
            scope_expression=f"{scope_expression}.components[{index}]",
            constant_prefix=constant_prefix,
        )


def _render_result_types(model: _InterfaceModel) -> str:
    sections: list[str] = []
    for scope in _walk_scopes(model.root):
        for item in scope.acquisitions:
            live_arguments = _type_arguments(
                "MeasurementValue | None",
                count=item.result_type_arguments,
            )
            product_arguments = _type_arguments(
                "ProductRef",
                count=item.result_type_arguments,
            )
            readback_declaration = _render_inherited_class_declaration(
                item.readback_name,
                f"{item.result_type_name}{live_arguments}",
            )
            products_declaration = _render_inherited_class_declaration(
                item.products_name,
                f"{item.result_type_name}{product_arguments}",
            )
            sections.append(
                "\n\n"
                "@dataclass(frozen=True, slots=True)\n"
                f"{readback_declaration}"
                f'    """Named {item.method_name} results plus their effect '
                'receipt."""\n'
                "\n"
                "    receipt: CollectReceipt = field(repr=False)\n"
                "\n\n"
                "@dataclass(frozen=True, slots=True)\n"
                f"{products_declaration}"
                f'    """Typed logical products produced by '
                f'{item.method_name}."""\n'
            )
    return "".join(sections)


def _render_inherited_class_declaration(name: str, base: str) -> str:
    compact = f"class {name}({base}):\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return f"class {name}(\n    {base}\n):\n"


def _render_live_scopes(model: _InterfaceModel) -> str:
    return "".join(
        _render_live_scope(model, scope) for scope in _walk_scopes_postorder(model.root)
    )


def _render_live_scope(model: _InterfaceModel, scope: _ScopeModel) -> str:
    if scope.is_root:
        base = (
            "InstrumentClientBase"
            if model.live_state_type_name is None
            else f"DeclaredStateClientBase[{model.live_state_type_name}]"
        )
    else:
        base = "InstrumentComponentClientBase"
    body: list[str] = []
    if scope.is_root and model.observation_type_name is not None:
        observation_name = model.observation_descriptor_name
        if observation_name is None:
            raise AssertionError("observed model requires a descriptor name")
        body.extend(
            (
                f"    def observation(self) -> {model.observation_type_name}:\n",
                f"        return {observation_name}.decode(\n",
                "            self._session.observed_state(self.instrument_id)\n",
                "        )\n",
                "\n",
                "    def refresh_observation(self) -> "
                f"{model.observation_type_name}:\n",
                f"        return {observation_name}.decode(\n",
                "            self._session.read_state(self.instrument_id)\n",
                "        )\n",
            )
        )
    for operation in scope.operations:
        _append_member_separator(body)
        body.append(_render_live_operation(operation))
    for acquisition in scope.acquisitions:
        _append_member_separator(body)
        body.append(_render_live_acquisition(acquisition))
    for component in scope.components:
        _append_member_separator(body)
        owner = "self" if scope.is_root else "self._owner"
        body.append(
            "    @property\n"
            f"    def {component.python_name}(self) -> "
            f"{component.live_client_name}:\n"
            f"        return {component.live_client_name}({owner})\n"
        )
    if not body:
        body.append("    pass\n")
    return (
        "\n\n"
        f"class {scope.live_client_name}({base}):\n" + "".join(body).rstrip("\n") + "\n"
    )


def _render_live_operation(operation: _OperationModel) -> str:
    signature = _render_operation_signature(
        operation,
        annotation="concrete_annotation",
        return_annotation="InvokeReceipt",
    )
    call = _render_declared_call(
        operation,
        receiver="self._invoke_declared",
        leading_arguments=(operation.descriptor_name,),
        returns=True,
    )
    return signature + call


def _render_live_acquisition(acquisition: _AcquisitionModel) -> str:
    return (
        f"    def {acquisition.method_name}(self) -> {acquisition.readback_name}:\n"
        "        return self._collect_declared(\n"
        f"            {acquisition.descriptor_name},\n"
        f"            {acquisition.readback_name},\n"
        "        )\n"
    )


def _render_symbolic_scopes(model: _InterfaceModel) -> str:
    return "".join(
        _render_symbolic_scope(model, scope)
        for scope in _walk_scopes_postorder(model.root)
    )


def _render_symbolic_scope(model: _InterfaceModel, scope: _ScopeModel) -> str:
    if scope.is_root:
        base = (
            "SymbolicInstrumentClientBase"
            if model.symbolic_state_type_name is None
            else f"DeclaredStateSymbolicClientBase[{model.symbolic_state_type_name}]"
        )
    else:
        base = "SymbolicInstrumentComponentClientBase"
    body: list[str] = ["    __slots__ = ()\n"]
    if scope.is_root:
        body.extend(
            (
                "\n",
                "    def __init__(\n",
                "        self,\n",
                "        recorder: SymbolicInstrumentRecorder,\n",
                "        resource_id: str,\n",
                "        *,\n",
                "        for_: OneEntity | None = None,\n",
                "    ) -> None:\n",
                "        super().__init__(\n",
                "            recorder,\n",
                "            resource_id,\n",
                f"            requires={model.requires_expression},\n",
                "            for_=for_,\n",
                "        )\n",
            )
        )
    for operation in scope.operations:
        _append_member_separator(body)
        body.append(_render_symbolic_operation(operation))
    for acquisition in scope.acquisitions:
        _append_member_separator(body)
        body.append(_render_symbolic_acquisition(acquisition))
    for component in scope.components:
        _append_member_separator(body)
        owner = "self" if scope.is_root else "self._owner"
        body.append(
            "    @property\n"
            f"    def {component.python_name}(self) -> "
            f"{component.symbolic_client_name}:\n"
            f"        return {component.symbolic_client_name}({owner})\n"
        )
    declaration = f"class {scope.symbolic_client_name}({base}):\n"
    if len(declaration.rstrip("\n")) > 88:
        declaration = f"class {scope.symbolic_client_name}(\n    {base}\n):\n"
    return f"\n\n{declaration}" + "".join(body).rstrip("\n") + "\n"


def _render_symbolic_operation(operation: _OperationModel) -> str:
    signature = _render_operation_signature(
        operation,
        annotation="symbolic_annotation",
        return_annotation="None",
        effect_id=True,
    )
    call = _render_declared_call(
        operation,
        receiver="self._invoke_declared",
        leading_arguments=(operation.descriptor_name, "effect_id"),
        returns=False,
    )
    return signature + call


def _render_symbolic_acquisition(acquisition: _AcquisitionModel) -> str:
    return (
        f"    def {acquisition.method_name}(\n"
        "        self,\n"
        "        *,\n"
        "        id: str | None = None,\n"
        f"    ) -> {acquisition.products_name}:\n"
        "        return self._acquire_declared(\n"
        f"            {acquisition.descriptor_name},\n"
        f"            {acquisition.products_name},\n"
        "            id=id,\n"
        "        )\n"
    )


def _render_symbolic_group_scopes(model: _InterfaceModel) -> str:
    return "".join(
        _render_symbolic_group_scope(model, scope)
        for scope in _walk_scopes_postorder(model.root)
    )


def _render_symbolic_group_scope(
    model: _InterfaceModel,
    scope: _ScopeModel,
) -> str:
    if scope.is_root:
        base = (
            f"SymbolicInstrumentGroupBase[{scope.symbolic_client_name}]"
            if model.symbolic_state_type_name is None
            else "DeclaredStateSymbolicGroupBase["
            f"{model.symbolic_state_type_name}, "
            f"{model.group_state_type_name}, {scope.symbolic_client_name}]"
        )
    else:
        base = f"SymbolicInstrumentComponentGroupBase[{scope.symbolic_client_name}]"
    body: list[str] = ["    __slots__ = ()\n"]
    if scope.is_root:
        body.extend(
            (
                "\n",
                "    def __init__(\n",
                "        self,\n",
                "        recorder: SymbolicInstrumentRecorder,\n",
                "        resource_id: str,\n",
                "        *,\n",
                "        for_: EachEntity,\n",
                "    ) -> None:\n",
                "        super().__init__(\n",
                "            recorder,\n",
                "            resource_id,\n",
                "            for_=for_,\n",
                f"            client_factory={scope.symbolic_client_name},\n",
                "        )\n",
            )
        )
    for operation in scope.operations:
        _append_member_separator(body)
        body.append(_render_group_operation(operation))
    for acquisition in scope.acquisitions:
        _append_member_separator(body)
        body.append(_render_group_acquisition(acquisition))
    for component in scope.components:
        _append_member_separator(body)
        body.append(
            "    @property\n"
            f"    def {component.python_name}(self) -> "
            f"{component.symbolic_group_name}:\n"
            f"        return {component.symbolic_group_name}(\n"
            "            self._entities,\n"
            "            self._clients.map("
            f"lambda client: client.{component.python_name}),\n"
            "        )\n"
        )
    return (
        "\n\n"
        f"class {scope.symbolic_group_name}(\n"
        f"{_render_group_base(base)}"
        "):\n" + "".join(body).rstrip("\n") + "\n"
    )


def _render_group_base(base: str) -> str:
    if len(f"    {base}") <= 88:
        return f"    {base}\n"
    origin, separator, arguments = base.partition("[")
    if not separator or not arguments.endswith("]"):
        return f"    {base}\n"
    type_arguments = _split_top_level_arguments(arguments[:-1])
    compact_arguments = ", ".join(type_arguments)
    if len(f"        {compact_arguments}") <= 88:
        rendered_arguments = f"        {compact_arguments}\n"
    else:
        rendered_arguments = "".join(
            f"        {argument},\n" for argument in type_arguments
        )
    return f"    {origin}[\n{rendered_arguments}    ]\n"


def _split_top_level_arguments(arguments: str) -> tuple[str, ...]:
    items: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(arguments):
        if character in "[({":
            depth += 1
        elif character in "])}":
            depth -= 1
        elif character == "," and depth == 0:
            items.append(arguments[start:index].strip())
            start = index + 1
    items.append(arguments[start:].strip())
    return tuple(items)


def _render_group_operation(operation: _OperationModel) -> str:
    signature = _render_operation_signature(
        operation,
        annotation="symbolic_annotation",
        return_annotation="None",
        effect_id=True,
        per_entity=True,
    )
    body = [
        f"        _{argument.python_name}_by_entity = "
        f"self._align({argument.python_name})\n"
        for argument in operation.arguments
    ]
    body.append("        for entity in self._entities:\n")
    call_arguments: list[str] = []
    for argument in operation.arguments:
        value = f"_{argument.python_name}_by_entity[entity]"
        if argument.kind == "KEYWORD_ONLY":
            call_arguments.append(f"                {argument.python_name}={value},\n")
        else:
            call_arguments.append(f"                {value},\n")
    call_arguments.append("                effect_id=effect_id,\n")
    body.extend(
        (
            f"            self._clients[entity].{operation.method_name}(\n",
            *call_arguments,
            "            )\n",
        )
    )
    return signature + "".join(body)


def _render_group_acquisition(acquisition: _AcquisitionModel) -> str:
    return (
        f"    def {acquisition.method_name}(\n"
        "        self,\n"
        "        *,\n"
        "        id: str | None = None,\n"
        f"    ) -> PerEntity[{acquisition.products_name}]:\n"
        "        return self._clients.map("
        f"lambda client: client.{acquisition.method_name}(id=id))\n"
    )


def _render_operation_signature(
    operation: _OperationModel,
    *,
    annotation: str,
    return_annotation: str,
    effect_id: bool = False,
    per_entity: bool = False,
) -> str:
    lines = [f"    def {operation.method_name}(\n", "        self,\n"]
    previous_kind: str | None = None
    for index, argument in enumerate(operation.arguments):
        if argument.kind == "KEYWORD_ONLY" and previous_kind != "KEYWORD_ONLY":
            lines.append("        *,\n")
        rendered_annotation = cast("str", getattr(argument, annotation))
        if per_entity:
            rendered_annotation = (
                f"{rendered_annotation} | PerEntity[{rendered_annotation}]"
            )
        lines.append(f"        {argument.python_name}: {rendered_annotation},\n")
        if argument.kind == "POSITIONAL_ONLY" and (
            index == len(operation.arguments) - 1
            or operation.arguments[index + 1].kind != "POSITIONAL_ONLY"
        ):
            lines.append("        /,\n")
        previous_kind = argument.kind
    if effect_id:
        if not any(argument.kind == "KEYWORD_ONLY" for argument in operation.arguments):
            lines.append("        *,\n")
        lines.append("        effect_id: str | None = None,\n")
    lines.append(f"    ) -> {return_annotation}:\n")
    return "".join(lines)


def _render_declared_call(
    operation: _OperationModel,
    *,
    receiver: str,
    leading_arguments: tuple[str, ...],
    returns: bool,
) -> str:
    prefix = "return " if returns else ""
    lines = [f"        {prefix}{receiver}(\n"]
    lines.extend(f"            {argument},\n" for argument in leading_arguments)
    for argument in operation.arguments:
        if argument.kind == "KEYWORD_ONLY":
            lines.append(
                f"            {argument.python_name}={argument.python_name},\n"
            )
        else:
            lines.append(f"            {argument.python_name},\n")
    lines.append("        )\n")
    return "".join(lines)


def _render_family(model: _InterfaceModel) -> str:
    if not model.generate_family:
        return ""
    return (
        "\n\n"
        f"{model.factory_name}: InstrumentFamily[\n"
        f"    {model.live_client_name},\n"
        f"    {model.symbolic_client_name},\n"
        f"    {model.symbolic_group_name},\n"
        "] = InstrumentFamily(\n"
        f"    {model.live_client_name},\n"
        f"    {model.symbolic_client_name},\n"
        f"    {model.symbolic_group_name},\n"
        f"    requires={model.requires_expression},\n"
        ")\n"
    )


def _render_bundle_flag_facades(
    facades: tuple[_BundleFlagFacadeModel, ...],
) -> str:
    rendered = "".join(_render_bundle_flag_facade(facade) for facade in facades)
    return rendered + ("\n" if rendered else "")


def _render_bundle_flag_facade(facade: _BundleFlagFacadeModel) -> str:
    name = facade.factory_name
    flag = facade.flag_name
    base = facade.base
    bundle = facade.bundle
    base_live = f"InstrumentRef[{base.live_client_name}]"
    bundle_live = f"InstrumentRef[{bundle.live_client_name}]"
    return (
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: str,\n"
        "    *,\n"
        f"    {flag}: Literal[False] = False,\n"
        f") -> {base_live}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: str,\n"
        "    *,\n"
        f"    {flag}: Literal[True],\n"
        f") -> {bundle_live}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: str,\n"
        "    *,\n"
        f"    {flag}: bool,\n"
        f") -> {base_live} | {bundle_live}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: SymbolicInstrumentRecorder,\n"
        "    resource_id: str,\n"
        "    *,\n"
        "    for_: EachEntity,\n"
        f"    {flag}: Literal[False] = False,\n"
        f") -> {base.symbolic_group_name}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: SymbolicInstrumentRecorder,\n"
        "    resource_id: str,\n"
        "    *,\n"
        "    for_: EachEntity,\n"
        f"    {flag}: Literal[True],\n"
        f") -> {bundle.symbolic_group_name}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: SymbolicInstrumentRecorder,\n"
        "    resource_id: str,\n"
        "    *,\n"
        "    for_: EachEntity,\n"
        f"    {flag}: bool,\n"
        f") -> {base.symbolic_group_name} | {bundle.symbolic_group_name}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: SymbolicInstrumentRecorder,\n"
        "    resource_id: str,\n"
        "    *,\n"
        "    for_: OneEntity | None = None,\n"
        f"    {flag}: Literal[False] = False,\n"
        f") -> {base.symbolic_client_name}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: SymbolicInstrumentRecorder,\n"
        "    resource_id: str,\n"
        "    *,\n"
        "    for_: OneEntity | None = None,\n"
        f"    {flag}: Literal[True],\n"
        f") -> {bundle.symbolic_client_name}: ...\n"
        "\n\n@overload\n"
        f"def {name}(\n"
        "    instrument_id: SymbolicInstrumentRecorder,\n"
        "    resource_id: str,\n"
        "    *,\n"
        "    for_: OneEntity | None = None,\n"
        f"    {flag}: bool,\n"
        f") -> {base.symbolic_client_name} | {bundle.symbolic_client_name}: ...\n"
        "\n\n"
        f"def {name}(\n"
        "    instrument_id: str | SymbolicInstrumentRecorder,\n"
        "    resource_id: str | None = None,\n"
        "    *,\n"
        "    for_: EntitySelection | None = None,\n"
        f"    {flag}: bool = False,\n"
        ") -> (\n"
        f"    {base_live}\n"
        f"    | {bundle_live}\n"
        f"    | {base.symbolic_client_name}\n"
        f"    | {base.symbolic_group_name}\n"
        f"    | {bundle.symbolic_client_name}\n"
        f"    | {bundle.symbolic_group_name}\n"
        "):\n"
        "    if isinstance(instrument_id, str):\n"
        "        if resource_id is not None or for_ is not None:\n"
        '            raise TypeError("live instrument clients only accept an '
        'instrument id")\n'
        f"        if {flag}:\n"
        "            return instrument(\n"
        "                instrument_id,\n"
        f"                {bundle.live_client_name},\n"
        f"                requires={bundle.requires_expression},\n"
        "            )\n"
        "        return instrument(\n"
        "            instrument_id,\n"
        f"            {base.live_client_name},\n"
        f"            requires={base.requires_expression},\n"
        "        )\n"
        "    if resource_id is None:\n"
        '        raise TypeError("symbolic instrument clients require a logical '
        'resource id")\n'
        "    if isinstance(for_, EachEntity):\n"
        f"        if {flag}:\n"
        f"            return {bundle.symbolic_group_name}(\n"
        "                instrument_id,\n"
        "                resource_id,\n"
        "                for_=for_,\n"
        "            )\n"
        f"        return {base.symbolic_group_name}(\n"
        "            instrument_id,\n"
        "            resource_id,\n"
        "            for_=for_,\n"
        "        )\n"
        f"    if {flag}:\n"
        f"        return {bundle.symbolic_client_name}(\n"
        "            instrument_id,\n"
        "            resource_id,\n"
        "            for_=for_,\n"
        "        )\n"
        f"    return {base.symbolic_client_name}(\n"
        "        instrument_id,\n"
        "        resource_id,\n"
        "        for_=for_,\n"
        "    )\n"
    )


def _render_exports(
    models: tuple[_InterfaceModel, ...],
    *,
    facades: tuple[_BundleFlagFacadeModel, ...] = (),
) -> str:
    exports = {"SymbolicInstrumentRecorder"}
    for model in models:
        if model.generate_family:
            exports.add(model.factory_name)
        for scope in _walk_scopes(model.root):
            exports.update(
                {
                    scope.live_client_name,
                    scope.symbolic_client_name,
                    scope.symbolic_group_name,
                }
            )
            for acquisition in scope.acquisitions:
                exports.update({acquisition.products_name, acquisition.readback_name})
    exports.update(facade.factory_name for facade in facades)
    return (
        "\n__all__ = [\n"
        + "".join(f'    "{name}",\n' for name in sorted(exports))
        + "]\n"
    )


def _walk_scopes(root: _ScopeModel) -> tuple[_ScopeModel, ...]:
    return (
        root,
        *(child for component in root.components for child in _walk_scopes(component)),
    )


def _walk_scopes_postorder(root: _ScopeModel) -> tuple[_ScopeModel, ...]:
    return (
        *(
            child
            for component in root.components
            for child in _walk_scopes_postorder(component)
        ),
        root,
    )


def _walk_declared_scopes(root: DeclaredScopeLayout) -> tuple[DeclaredScopeLayout, ...]:
    return (
        root,
        *(
            child
            for component in root.components
            for child in _walk_declared_scopes(component)
        ),
    )


def _unique_constituents(
    models: tuple[_InterfaceModel, ...],
) -> tuple[_InterfaceConstituentModel, ...]:
    constituents_by_identity: dict[str, _InterfaceConstituentModel] = {}
    for model in models:
        for constituent in model.constituents:
            existing = constituents_by_identity.get(constituent.interface_identity)
            if existing is not None:
                if (
                    existing.interface_type_name != constituent.interface_type_name
                    or existing.constant_prefix != constituent.constant_prefix
                ):
                    raise ClientGenerationError(
                        "inconsistent generated constituent model for "
                        f"{constituent.interface_identity}"
                    )
                continue
            constituents_by_identity[constituent.interface_identity] = constituent
    return tuple(constituents_by_identity.values())


def _render_tuple(values: tuple[str, ...]) -> str:
    if not values:
        return "()"
    trailing_comma = "," if len(values) == 1 else ""
    return f"({', '.join(values)}{trailing_comma})"


def _render_descriptor_assignment(
    descriptor_name: str,
    scope_expression: str,
    *,
    collection: str,
    index: int,
) -> str:
    expression = f"{scope_expression}.{collection}[{index}]"
    compact = f"{descriptor_name} = {expression}\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    if ".components[" in scope_expression:
        return f"{descriptor_name} = (\n    {expression}\n)\n"
    return f"{descriptor_name} = {scope_expression}.{collection}[\n    {index}\n]\n"


def _descriptor_name(
    constant_prefix: str,
    python_path: tuple[str, ...],
    method_name: str,
) -> str:
    segments = (constant_prefix, *python_path, method_name, "DECLARATION")
    return "_" + "_".join(_constant_segment(segment) for segment in segments)


def _constant_segment(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()


def _string_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _join_constant_name(prefix: str, segment: str) -> str:
    prefix_parts = prefix.split("_")
    segment_parts = _constant_segment(segment).split("_")
    overlap = 0
    for count in range(1, min(len(prefix_parts), len(segment_parts)) + 1):
        if prefix_parts[-count:] == segment_parts[:count]:
            overlap = count
    return "_".join((*prefix_parts, *segment_parts[overlap:]))


def _append_member_separator(body: list[str]) -> None:
    if body and body[-1] != "\n":
        body.append("\n")


def _type_arguments(annotation: str, *, count: int) -> str:
    if count == 0:
        return ""
    return f"[{', '.join(annotation for _ in range(count))}]"


def _pascal_case(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]+|_", name))


def _snake_case(name: str) -> str:
    words = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", words).lower()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when any committed generated source is stale",
    )
    options = _Options()
    parser.parse_args(argv, namespace=options)
    rendered = (
        *(
            (target.output, render_generation_target(target))
            for target in _generation_targets()
        ),
        *(
            rendered_source
            for target in _catalog_targets()
            for rendered_source in render_catalog_target(target)
        ),
    )
    if options.check:
        stale = tuple(
            output
            for output, source in rendered
            if (output.read_text(encoding="utf-8") if output.is_file() else "")
            != source
        )
        if stale:
            rendered_paths = ", ".join(
                str(path.relative_to(REPOSITORY_ROOT)) for path in stale
            )
            print(
                "generated instrument sources are stale "
                f"({rendered_paths}); run "
                "`uv run python scripts/generate_instrument_clients.py`",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return
    for output, source in rendered:
        output.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
