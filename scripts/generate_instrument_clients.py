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
from dataclasses import fields as dataclass_fields
from importlib import import_module
from pathlib import Path
from typing import Protocol, TypeAliasType, TypeVar, cast, get_args, get_origin

from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.sdk.instruments import (
    AcquisitionAxisSpec,
    AcquisitionRef,
    ComponentRef,
    InterfaceSpec,
    OperationRef,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    DeclaredInterfaceLayout,
    DeclaredObservedState,
    DeclaredOperation,
    DeclaredResultField,
    DeclaredResultLayout,
    DeclaredScopeLayout,
    DeclaredStateLayout,
    compile_interface,
    declared_bundle_interfaces,
    declared_interface_layout,
)
from scopecat_instruments.package_manifest import (
    PACKAGE_MANIFEST,
    BundleSurfaceRegistration,
    SurfaceRegistration,
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
DRIVER_STATES_OUTPUT = (
    INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "driver_states.py"
)
DRIVER_HANDLERS_OUTPUT = (
    INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "driver_handlers.py"
)
PACKAGE_EXPORTS_OUTPUT = (
    INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "__init__.py"
)
FIXTURE_IMPORT_ROOT = INSTRUMENTS_PACKAGE_ROOT / "tests"
FIXTURE_OUTPUT = FIXTURE_IMPORT_ROOT / "generated_client_fixture.py"
FIXTURE_MEMBERS_OUTPUT = FIXTURE_IMPORT_ROOT / "generated_member_catalog_fixture.py"
FIXTURE_INTERFACES_OUTPUT = (
    FIXTURE_IMPORT_ROOT / "generated_interface_catalog_fixture.py"
)
FIXTURE_STATES_OUTPUT = FIXTURE_IMPORT_ROOT / "generated_state_catalog_fixture.py"
FIXTURE_DRIVER_STATES_OUTPUT = (
    FIXTURE_IMPORT_ROOT / "generated_driver_state_catalog_fixture.py"
)
FIXTURE_DRIVER_HANDLERS_OUTPUT = (
    FIXTURE_IMPORT_ROOT / "generated_driver_handler_fixture.py"
)
PRODUCTION_STATE_PROJECTION_MODULE = "scopecat_instruments.states"
FIXTURE_STATE_PROJECTION_MODULE = "generated_state_catalog_fixture"
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
    state_projection_module: str


@dataclass(frozen=True, slots=True)
class CatalogTarget:
    """Public projections generated from a closed set of declared interfaces."""

    members_output: Path
    interfaces_output: Path
    states_output: Path
    driver_states_output: Path
    members_module: str
    interface_types: tuple[type[object], ...]
    public_types: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class DriverHandlerTarget:
    """One generated typed driver-adapter module."""

    output: Path
    surfaces: tuple[GenerationSurface, ...]
    members_module: str
    driver_states_module: str


@dataclass(frozen=True, slots=True)
class PackageExportsTarget:
    """Lazy package exports derived from generated client and state surfaces."""

    output: Path
    client_target: GenerationTarget
    catalog_target: CatalogTarget
    client_module: str
    states_module: str
    static_exports: tuple[tuple[str, str], ...] = ()


class _DeclarationCache:
    """Compile each interface declaration at most once per generator run."""

    def __init__(self) -> None:
        self._layouts: dict[type[object], DeclaredInterfaceLayout[object]] = {}

    def layout(
        self,
        interface_type: type[object],
        /,
    ) -> DeclaredInterfaceLayout[object]:
        selected = self._layouts.get(interface_type)
        if selected is None:
            selected = declared_interface_layout(compile_interface(interface_type))
            self._layouts[interface_type] = selected
        return selected


class _Options(argparse.Namespace):
    check: bool = False


class _FixtureDeclarations(Protocol):
    CatalogProjectionInterface: type[object]
    ComponentOperationInterface: type[object]
    DriverFixedAcquisitionInterface: type[object]
    DriverMonitorInterface: type[object]
    DriverMonitorBundle: type[object]
    DriverSourceInterface: type[object]
    LiteralOperationInterface: type[object]
    PayloadOperationInterface: type[object]


def _manifest_surface(registration: SurfaceRegistration, /) -> GenerationSurface:
    if isinstance(registration, BundleSurfaceRegistration):
        return clients_for_bundle(
            registration.bundle_type,
            facade_flag=registration.facade_flag,
        )
    return clients_for(
        registration.interface_type,
        public_name_overrides=registration.public_name_overrides,
    )


_PRODUCTION_SURFACES = tuple(
    _manifest_surface(registration) for registration in PACKAGE_MANIFEST.surfaces
)

PRODUCTION_TARGET = GenerationTarget(
    output=OUTPUT,
    surfaces=_PRODUCTION_SURFACES,
    state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
)

PRODUCTION_CATALOG_TARGET = CatalogTarget(
    members_output=MEMBERS_OUTPUT,
    interfaces_output=INTERFACES_OUTPUT,
    states_output=STATES_OUTPUT,
    driver_states_output=DRIVER_STATES_OUTPUT,
    members_module="scopecat_instruments.members",
    interface_types=_surface_interface_types(_PRODUCTION_SURFACES),
    public_types=PACKAGE_MANIFEST.public_types,
)

PRODUCTION_DRIVER_HANDLER_TARGET = DriverHandlerTarget(
    output=DRIVER_HANDLERS_OUTPUT,
    surfaces=_PRODUCTION_SURFACES,
    members_module="scopecat_instruments.members",
    driver_states_module="scopecat_instruments.driver_states",
)

PRODUCTION_PACKAGE_EXPORTS_TARGET = PackageExportsTarget(
    output=PACKAGE_EXPORTS_OUTPUT,
    client_target=PRODUCTION_TARGET,
    catalog_target=PRODUCTION_CATALOG_TARGET,
    client_module="scopecat_instruments.clients",
    states_module="scopecat_instruments.states",
    static_exports=(("ConfiguredInstrumentProvider", "scopecat_instruments.provider"),),
)


def _fixture_target() -> GenerationTarget:
    declarations = _fixture_declarations()
    return GenerationTarget(
        output=FIXTURE_OUTPUT,
        surfaces=(clients_for(declarations.ComponentOperationInterface),),
        state_projection_module=FIXTURE_STATE_PROJECTION_MODULE,
    )


def _fixture_catalog_target() -> CatalogTarget:
    declarations = _fixture_declarations()
    handler_surfaces = _fixture_driver_handler_surfaces(declarations)
    return CatalogTarget(
        members_output=FIXTURE_MEMBERS_OUTPUT,
        interfaces_output=FIXTURE_INTERFACES_OUTPUT,
        states_output=FIXTURE_STATES_OUTPUT,
        driver_states_output=FIXTURE_DRIVER_STATES_OUTPUT,
        members_module="generated_member_catalog_fixture",
        interface_types=(
            declarations.CatalogProjectionInterface,
            *_surface_interface_types(handler_surfaces),
        ),
    )


def _fixture_driver_handler_surfaces(
    declarations: _FixtureDeclarations,
) -> tuple[GenerationSurface, ...]:
    return (
        clients_for(declarations.ComponentOperationInterface),
        clients_for(declarations.LiteralOperationInterface),
        clients_for(declarations.PayloadOperationInterface),
        clients_for(declarations.DriverFixedAcquisitionInterface),
        clients_for(declarations.DriverSourceInterface),
        clients_for_bundle(declarations.DriverMonitorBundle, facade_flag="monitor"),
    )


def _fixture_driver_handler_target() -> DriverHandlerTarget:
    declarations = _fixture_declarations()
    return DriverHandlerTarget(
        output=FIXTURE_DRIVER_HANDLERS_OUTPUT,
        surfaces=_fixture_driver_handler_surfaces(declarations),
        members_module="generated_member_catalog_fixture",
        driver_states_module="generated_driver_state_catalog_fixture",
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


def _driver_handler_targets() -> tuple[DriverHandlerTarget, ...]:
    return (PRODUCTION_DRIVER_HANDLER_TARGET, _fixture_driver_handler_target())


def _package_exports_targets() -> tuple[PackageExportsTarget, ...]:
    return (PRODUCTION_PACKAGE_EXPORTS_TARGET,)


@dataclass(frozen=True, slots=True)
class _OperationArgumentModel:
    python_name: str
    argument_id: str
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
class _StateKeywordFieldModel:
    python_name: str
    concrete_annotation: str
    symbolic_annotation: str
    group_annotation: str


@dataclass(frozen=True, slots=True)
class _StateKeywordModel:
    patch_type_name: str
    target_type_name: str
    group_target_type_name: str
    fields: tuple[_StateKeywordFieldModel, ...]


@dataclass(frozen=True, slots=True)
class _InterfaceConstituentModel:
    interface_identity: str
    interface_id: str
    constant_prefix: str
    layout: DeclaredInterfaceLayout[object]
    observation_type_name: str | None

    @property
    def ref_name(self) -> str:
        return f"_{self.constant_prefix}_REF"

    @property
    def observation_descriptor_name(self) -> str | None:
        if self.observation_type_name is None:
            return None
        return f"_{self.constant_prefix}_OBSERVATION_DECLARATION"


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
    keyword_state: _StateKeywordModel | None
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
    spec: InterfaceSpec
    root: DeclaredScopeLayout
    states: tuple[DeclaredStateLayout, ...]
    observed_state: DeclaredObservedState[object] | None

    @property
    def observed_state_type(self) -> type[object] | None:
        return None if self.observed_state is None else self.observed_state.state_type


@dataclass(frozen=True, slots=True)
class _StateProjectionNames:
    patch: str
    target: str
    group_target: str


@dataclass(frozen=True, slots=True)
class _DriverPatchField:
    property_id: str
    annotation: object


@dataclass(frozen=True, slots=True)
class _DriverHandlerConstituent:
    interface_type: type[object]
    stem: str
    constant_prefix: str
    field_name: str
    layout: DeclaredInterfaceLayout[object]
    optional: bool


@dataclass(frozen=True, slots=True)
class _DriverHandlerSurface:
    stem: str
    flag_name: str | None
    constituents: tuple[_DriverHandlerConstituent, ...]


@dataclass(frozen=True, slots=True)
class _DriverAcquisitionField:
    python_name: str
    member_name: str


@dataclass(frozen=True, slots=True)
class _DriverAcquisitionModel:
    hook_name: str
    member_name: str
    type_stem: str
    fields: tuple[_DriverAcquisitionField, ...]
    optional: bool


@dataclass(frozen=True, slots=True)
class _DriverOperationModel:
    declaration: DeclaredOperation
    hook_name: str
    member_name: str
    optional: bool


def _state_projection_names(layout: DeclaredStateLayout) -> _StateProjectionNames:
    stem = layout.projection_stem
    return _StateProjectionNames(
        patch=f"{stem}Patch",
        target=f"{stem}Target",
        group_target=f"{stem}GroupTarget",
    )


def _register_state_projection_types(
    renderer: _AnnotationRenderer,
    layouts: tuple[DeclaredStateLayout, ...],
    *,
    state_projection_module: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    names = tuple(_state_projection_names(layout) for layout in layouts)
    if names:
        imported = renderer.imports.setdefault(
            state_projection_module,
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


def _state_keyword_model(
    layouts: tuple[DeclaredStateLayout, ...],
    *,
    renderer: _AnnotationRenderer,
) -> _StateKeywordModel | None:
    """Describe the unambiguous keyword surface for one flat state schema."""

    if len(layouts) != 1:
        return None
    layout = layouts[0]
    if layout.required_fields or layout.constants:
        return None
    names = _state_projection_names(layout)
    fields: list[_StateKeywordFieldModel] = []
    for field in layout.fields:
        concrete = renderer.render(field.annotation)
        symbolic = f"{concrete} | ValueRef"
        fields.append(
            _StateKeywordFieldModel(
                python_name=field.python_name,
                concrete_annotation=concrete,
                symbolic_annotation=symbolic,
                group_annotation=f"{symbolic} | PerEntity[{symbolic}]",
            )
        )
    return _StateKeywordModel(
        patch_type_name=names.patch,
        target_type_name=names.target,
        group_target_type_name=names.group_target,
        fields=tuple(fields),
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


def render_catalog_target(
    target: CatalogTarget,
    *,
    declaration_cache: _DeclarationCache | None = None,
) -> tuple[tuple[Path, str], ...]:
    """Render every public projection owned by one interface catalog."""

    cache = declaration_cache or _DeclarationCache()
    models = _catalog_models(target.interface_types, declaration_cache=cache)
    return (
        (target.members_output, _render_members_module(models)),
        (target.interfaces_output, _render_interfaces_module(models)),
        (
            target.states_output,
            _render_states_module(
                models,
                public_types=target.public_types,
                members_module=target.members_module,
            ),
        ),
        (
            target.driver_states_output,
            _render_driver_states_module(models, members_module=target.members_module),
        ),
    )


def _catalog_models(
    interface_types: tuple[type[object], ...],
    *,
    declaration_cache: _DeclarationCache,
) -> tuple[_CatalogInterfaceModel, ...]:
    if not interface_types:
        raise ClientGenerationError("an interface catalog requires a declaration")
    models: list[_CatalogInterfaceModel] = []
    seen_identities: set[str] = set()
    for interface_type in interface_types:
        layout = declaration_cache.layout(interface_type)
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
                spec=layout.compiled.spec,
                root=layout.root,
                states=layout.states,
                observed_state=layout.observed_state,
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
        "scopecat.sdk.instruments": {"InterfaceRef"},
    }
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
            expression=f"InterfaceRef({_string_literal(model.root.ref.interface_id)})",
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
    }
    declarations: list[str] = []
    for model in models:
        owners_by_name.setdefault(model.factory_name, []).append(
            model.interface_identity
        )
        spec_json_name = f"_{model.constant_prefix}_SPEC_JSON"
        declarations.append(
            f"{spec_json_name} = (\n"
            f"{_render_string_literal_lines(model.spec.model_dump_json(), indent=4)}"
            ")\n"
            "\n\n"
            f"def {model.factory_name}() -> InterfaceSpec:\n"
            f"    return InterfaceSpec.model_validate_json({spec_json_name})\n"
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
        + "\n"
        + "\n\n".join(declarations)
        + "\n"
        + _render_all(tuple(model.factory_name for model in models))
    )


def _unique_state_layouts(
    models: tuple[_CatalogInterfaceModel, ...],
) -> tuple[tuple[_CatalogInterfaceModel, DeclaredStateLayout], ...]:
    selected: list[tuple[_CatalogInterfaceModel, DeclaredStateLayout]] = []
    seen_sources: dict[type[object], DeclaredStateLayout] = {}
    for model in models:
        for layout in model.states:
            existing = seen_sources.get(layout.source_type)
            if existing is not None:
                if existing != layout:
                    raise ClientGenerationError(
                        "one state schema produced inconsistent projection layouts: "
                        f"{layout.source_type.__module__}."
                        f"{layout.source_type.__qualname__}"
                    )
                continue
            seen_sources[layout.source_type] = layout
            selected.append((model, layout))
    return tuple(selected)


def _state_export_owners(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    public_types: tuple[object, ...],
    state_layouts: tuple[tuple[_CatalogInterfaceModel, DeclaredStateLayout], ...],
) -> dict[str, str]:
    exports_by_name: dict[str, str] = {}
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

    for _, layout in state_layouts:
        owner = f"{layout.source_type.__module__}.{layout.source_type.__qualname__}"
        names = _state_projection_names(layout)
        for name in (names.patch, names.target, names.group_target):
            existing = exports_by_name.get(name)
            if existing is not None:
                raise ClientGenerationError(
                    f"generated state export collision {name}: {existing} vs {owner}"
                )
            exports_by_name[name] = owner
    return exports_by_name


def _render_states_module(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    public_types: tuple[object, ...],
    members_module: str,
) -> str:
    renderer = _AnnotationRenderer()
    imports: dict[str, set[str]] = {}
    declarations: list[str] = []
    member_imports: set[str] = set()
    state_layouts = _unique_state_layouts(models)
    exports_by_name = _state_export_owners(
        models,
        public_types=public_types,
        state_layouts=state_layouts,
    )

    for candidate in (
        *(
            model.observed_state_type
            for model in models
            if model.observed_state_type is not None
        ),
        *public_types,
    ):
        module, name = _public_type_location(candidate)
        imports.setdefault(module, set()).add(f"{name} as {name}")

    if state_layouts:
        imports["scopecat.authoring"] = {"PerEntity", "ValueRef"}
        imports["scopecat.sdk.instruments.declarations"] = {
            "StateProjectionField",
            "StateProjectionLayout",
            "instrument_state_projection",
            "state_projection_field",
        }

    for model, layout in state_layouts:
        names = _state_projection_names(layout)
        layout_expression = _state_projection_layout_name(names)
        declarations.append(
            _render_state_projection_layout(
                layout_expression,
                layout,
                constant_prefix=model.constant_prefix,
                member_imports=member_imports,
            )
        )
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
    if member_imports:
        imports[members_module] = member_imports
    import_block = _render_import_block(imports) if imports else ""
    declaration_block = "".join(declarations)
    if import_block:
        declaration_block = declaration_block.removeprefix("\n")
    return (
        _generated_module_header(
            "Typed state projections generated from instrument interfaces."
        )
        + import_block
        + declaration_block
        + ("\n" if declarations else "")
        + _render_all(tuple(exports_by_name))
    )


def _render_driver_states_module(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    members_module: str,
) -> str:
    renderer = _AnnotationRenderer()
    imports: dict[str, set[str]] = {
        "collections.abc": {"Mapping"},
        "pydantic": {"JsonValue"},
        "scopecat.sdk.instruments": {
            "DriverScalar",
            "DriverState",
            "DriverStatePatch",
            "PropertyRef",
        },
        "typing": {"TypedDict", "cast"},
    }
    member_imports: set[str] = set()
    declarations: list[str] = []
    exports: list[str] = ["encode_driver_state"]
    encoder_owners: dict[str, str] = {}

    for model in models:
        patch_fields = _driver_patch_fields(model)
        if patch_fields:
            patch_name = _driver_patch_name(model)
            decoder_name = _driver_patch_decoder_name(model)
            exports.extend((patch_name, decoder_name))
            rendered_fields = tuple(
                (field.property_id, renderer.render(field.annotation))
                for field in patch_fields
            )
            declarations.append(_render_driver_patch_type(patch_name, rendered_fields))
            declarations.append(
                _render_driver_patch_decoder(
                    model,
                    patch_name=patch_name,
                    decoder_name=decoder_name,
                    fields=rendered_fields,
                    member_imports=member_imports,
                )
            )

        for layout in model.states:
            if layout.role == "common":
                continue
            encoder_name = _state_encoder_name(layout.source_type)
            owner = _type_identity(layout.source_type)
            existing_owner = encoder_owners.get(encoder_name)
            if existing_owner is not None:
                if existing_owner != owner:
                    raise ClientGenerationError(
                        f"generated driver state encoder collision {encoder_name}: "
                        f"{existing_owner} vs {owner}"
                    )
                continue
            encoder_owners[encoder_name] = owner
            exports.append(encoder_name)
            source_type_name = renderer.reference(layout.source_type)
            declarations.append(
                _render_exact_state_encoder(
                    layout,
                    constant_prefix=model.constant_prefix,
                    encoder_name=encoder_name,
                    source_type_name=source_type_name,
                    member_imports=member_imports,
                )
            )

        if model.observed_state is not None:
            observation = model.observed_state
            encoder_name = _observation_encoder_name(observation.state_type)
            owner = _type_identity(observation.state_type)
            existing_owner = encoder_owners.get(encoder_name)
            if existing_owner is not None:
                if existing_owner != owner:
                    raise ClientGenerationError(
                        f"generated driver state encoder collision {encoder_name}: "
                        f"{existing_owner} vs {owner}"
                    )
            else:
                encoder_owners[encoder_name] = owner
                exports.append(encoder_name)
                observation_type_name = renderer.reference(observation.state_type)
                declarations.append(
                    _render_observation_encoder(
                        observation,
                        constant_prefix=model.constant_prefix,
                        encoder_name=encoder_name,
                        observation_type_name=observation_type_name,
                        member_imports=member_imports,
                    )
                )

    imports[members_module] = member_imports
    for module, names in renderer.imports.items():
        imports.setdefault(module, set()).update(names)
    return (
        _generated_module_header(
            "Typed driver state codecs generated from instrument interfaces."
        )
        + _render_driver_import_block(imports)
        + "".join(declarations)
        + _render_encode_driver_state()
        + "\n"
        + _render_all(tuple(exports))
    )


def render_driver_handler_target(
    target: DriverHandlerTarget,
    *,
    declaration_cache: _DeclarationCache | None = None,
) -> str:
    """Render typed ABC adapters for selected driver-facing surfaces."""

    cache = declaration_cache or _DeclarationCache()
    surfaces = tuple(
        _driver_handler_surface(item, declaration_cache=cache)
        for item in target.surfaces
    )
    if not surfaces:
        raise ClientGenerationError("a driver handler module requires a surface")
    return _render_driver_handlers_module(
        surfaces,
        members_module=target.members_module,
        driver_states_module=target.driver_states_module,
    )


def _driver_handler_surface(
    surface: GenerationSurface,
    *,
    declaration_cache: _DeclarationCache,
) -> _DriverHandlerSurface:
    if isinstance(surface, BundleClientSurface):
        interface_types = declared_bundle_interfaces(surface.bundle_type)
        stem = surface.bundle_type.__name__.removesuffix("Interface")
        flag_name = surface.facade_flag
        if flag_name is not None and len(interface_types) != 2:
            raise ClientGenerationError(
                "optional driver bundle adapters require exactly two interfaces"
            )
    else:
        interface_types = (surface.interface_type,)
        stem = surface.interface_type.__name__.removesuffix("Interface")
        flag_name = None
    constituents = tuple(
        _DriverHandlerConstituent(
            interface_type=interface_type,
            stem=(interface_stem := interface_type.__name__.removesuffix("Interface")),
            constant_prefix=_snake_case(interface_stem).upper(),
            field_name=_snake_case(interface_stem),
            layout=declaration_cache.layout(interface_type),
            optional=flag_name is not None and index > 0,
        )
        for index, interface_type in enumerate(interface_types)
    )
    return _DriverHandlerSurface(
        stem=stem,
        flag_name=flag_name,
        constituents=constituents,
    )


def _render_driver_handlers_module(
    surfaces: tuple[_DriverHandlerSurface, ...],
    *,
    members_module: str,
    driver_states_module: str,
) -> str:
    renderer = _AnnotationRenderer()
    operations = tuple(
        operation
        for surface in surfaces
        for constituent in surface.constituents
        for scope in _walk_declared_scopes(constituent.layout.root)
        for operation in scope.operations
    )
    has_operation_arguments = any(operation.arguments for operation in operations)
    has_payload_arguments = any(
        isinstance(argument.spec.value_type.atom, PayloadType)
        for operation in operations
        for argument in operation.arguments
    )
    imports: dict[str, set[str]] = {
        "abc": {"ABC", "abstractmethod"},
        "collections.abc": {"Mapping"},
        "dataclasses": {"dataclass", "field"},
        "pydantic": {"JsonValue"},
        "scopecat.records.measurement": {"MeasurementValue"},
        "scopecat.sdk.instruments": {
            "AcquisitionResultRef",
            "DriverAcquisition",
            "DriverOperation",
            "DriverOutcome",
            "DriverReadback",
            "DriverRejected",
            "DriverScalar",
            "DriverState",
            "DriverStatePatch",
            "DriverSuccess",
            "PropertyRef",
        },
        "scopecat.sdk.problems": {"ProblemPhase", "model_location", "problem"},
        "typing": {"Literal", "TypedDict"},
    }
    if has_operation_arguments:
        imports["typing"].add("cast")
    if has_payload_arguments:
        imports["scopecat.sdk.instruments"].add("DriverPayload")
    member_imports: set[str] = set()
    driver_state_imports: set[str] = {"encode_driver_state"}
    declarations: list[str] = []
    exports: list[str] = []

    acquisition_models: dict[object, _DriverAcquisitionModel] = {}
    for surface in surfaces:
        for constituent in surface.constituents:
            for scope in _walk_declared_scopes(constituent.layout.root):
                for acquisition in scope.acquisitions:
                    if acquisition.ref in acquisition_models:
                        continue
                    model = _driver_acquisition_model(
                        constituent,
                        scope,
                        acquisition,
                        member_imports=member_imports,
                    )
                    acquisition_models[acquisition.ref] = model
                    declarations.append(_render_driver_acquisition_types(model))
                    exports.extend(
                        (
                            f"{model.type_stem}DriverReadback",
                            f"{model.type_stem}DriverResultName",
                            f"{model.type_stem}DriverValues",
                        )
                    )

    for surface in surfaces:
        rendered, surface_exports = _render_driver_adapter(
            surface,
            renderer=renderer,
            member_imports=member_imports,
            driver_state_imports=driver_state_imports,
            acquisition_models=acquisition_models,
            imports=imports,
        )
        declarations.append(rendered)
        exports.extend(surface_exports)

    imports[members_module] = member_imports
    imports[driver_states_module] = driver_state_imports
    for module, names in renderer.imports.items():
        imports.setdefault(module, set()).update(names)
    return (
        _generated_module_header(
            "Typed driver adapters generated from instrument interfaces."
        )
        + _render_driver_import_block(imports)
        + _render_driver_unsupported_helper()
        + "".join(declarations)
        + "\n"
        + _render_all(tuple(dict.fromkeys(exports)))
    )


def _driver_acquisition_model(
    constituent: _DriverHandlerConstituent,
    scope: DeclaredScopeLayout,
    acquisition: DeclaredAcquisition[object],
    *,
    member_imports: set[str],
) -> _DriverAcquisitionModel:
    scope_name = _driver_scope_constant_name(constituent.constant_prefix, scope)
    member_name = _join_constant_name(scope_name, acquisition.method_name)
    if member_name == scope_name:
        member_name = f"{scope_name}_ACQUISITION"
    member_imports.add(member_name)
    fields: list[_DriverAcquisitionField] = []
    seen_refs: set[object] = set()
    for declared_field in acquisition.result_fields:
        if declared_field.ref in seen_refs:
            continue
        seen_refs.add(declared_field.ref)
        result_name = (
            f"{_join_constant_name(scope_name, declared_field.python_name)}_RESULT"
        )
        member_imports.add(result_name)
        fields.append(
            _DriverAcquisitionField(
                python_name=declared_field.python_name,
                member_name=result_name,
            )
        )
    type_stem = (
        constituent.stem
        + "".join(_pascal_case(item) for item in scope.python_path)
        + _pascal_case(acquisition.method_name)
    )
    return _DriverAcquisitionModel(
        hook_name=_driver_hook_name(scope.python_path, acquisition.method_name),
        member_name=member_name,
        type_stem=type_stem,
        fields=tuple(fields),
        optional=constituent.optional,
    )


def _render_driver_acquisition_types(model: _DriverAcquisitionModel) -> str:
    result_type = f"{model.type_stem}DriverResultName"
    values_type = f"{model.type_stem}DriverValues"
    readback_type = f"{model.type_stem}DriverReadback"
    literal = (
        "Literal["
        + ", ".join(_string_literal(field.python_name) for field in model.fields)
        + "]"
    )
    values = "".join(
        f"    {field.python_name}: MeasurementValue\n" for field in model.fields
    )
    return (
        f"\n\ntype {result_type} = {literal}\n"
        f"\n\nclass {values_type}(TypedDict, total=False):\n"
        f"{values}"
        "\n\n@dataclass(frozen=True, slots=True)\n"
        f"class {readback_type}:\n"
        f"    values: {values_type}\n"
        "    metadata: dict[str, JsonValue] = field(default_factory=dict)\n"
    )


def _render_driver_adapter(
    surface: _DriverHandlerSurface,
    *,
    renderer: _AnnotationRenderer,
    member_imports: set[str],
    driver_state_imports: set[str],
    acquisition_models: dict[object, _DriverAcquisitionModel],
    imports: dict[str, set[str]],
) -> tuple[str, tuple[str, ...]]:
    class_name = f"{surface.stem}DriverAdapter"
    snapshot_name = f"{surface.stem}DriverSnapshot"
    patch_name = f"{surface.stem}DriverPatch"
    snapshot_fields = _driver_snapshot_fields(
        surface,
        imports=imports,
        driver_state_imports=driver_state_imports,
    )
    state_constituents = tuple(
        constituent
        for constituent in surface.constituents
        if _driver_writable_state_layouts(constituent.layout.states)
    )
    operation_models = tuple(
        _driver_operation_model(
            constituent,
            scope,
            operation,
            member_imports=member_imports,
        )
        for constituent in surface.constituents
        for scope in _walk_declared_scopes(constituent.layout.root)
        for operation in scope.operations
    )
    selected_acquisitions = tuple(
        acquisition_models[acquisition.ref]
        for constituent in surface.constituents
        for scope in _walk_declared_scopes(constituent.layout.root)
        for acquisition in scope.acquisitions
    )

    declarations: list[str] = []
    exports: list[str] = [class_name]
    if snapshot_fields:
        declarations.append(
            "\n\n@dataclass(frozen=True, slots=True, kw_only=True)\n"
            f"class {snapshot_name}:\n"
            + "".join(
                f"    {name}: {annotation}\n"
                for name, annotation, _constituent, _kind in snapshot_fields
            )
            + "    metadata: dict[str, JsonValue] = field(default_factory=dict)\n"
        )
        exports.append(snapshot_name)
    if len(state_constituents) > 1:
        declarations.append(
            "\n\n@dataclass(frozen=True, slots=True)\n"
            f"class {patch_name}:\n"
            + "".join(
                f"    {constituent.field_name}: {constituent.stem}DriverPatch\n"
                for constituent in state_constituents
            )
        )
        exports.append(patch_name)

    body: list[str] = [f"\n\nclass {class_name}(ABC):\n", "    instrument_id: str\n"]
    if surface.flag_name is not None:
        private_flag = f"_driver_{surface.flag_name}_enabled"
        body.extend(
            (
                "\n",
                f"    def __init__(self, *, {surface.flag_name}: bool) -> None:\n",
                f"        self.{private_flag} = {surface.flag_name}\n",
            )
        )

    if snapshot_fields:
        read_hook = f"read_{_snake_case(surface.stem)}_state"
        body.extend(
            (
                "\n",
                "    @abstractmethod\n",
                f"    def {read_hook}(self) -> {snapshot_name}: ...\n",
            )
        )
    if state_constituents:
        apply_hook = f"apply_{_snake_case(surface.stem)}_state"
        hook_patch = (
            patch_name
            if len(state_constituents) > 1
            else f"{state_constituents[0].stem}DriverPatch"
        )
        body.extend(
            (
                "\n",
                "    @abstractmethod\n",
                f"    def {apply_hook}(\n",
                "        self,\n",
                f"        patch: {hook_patch},\n",
                "        /,\n",
                "    ) -> DriverOutcome[None]: ...\n",
            )
        )
    for operation in operation_models:
        body.append(_render_driver_operation_hook(operation, renderer=renderer))
    for acquisition in selected_acquisitions:
        body.append(_render_driver_acquisition_hook(acquisition))

    body.append(
        _render_adapter_read_state(
            surface,
            snapshot_fields=snapshot_fields,
        )
    )
    body.append(
        _render_adapter_apply_state(
            surface,
            state_constituents=state_constituents,
            patch_name=patch_name,
        )
    )
    body.append(_render_adapter_invoke(surface, operation_models, renderer=renderer))
    body.append(_render_adapter_collect(surface, selected_acquisitions))
    declarations.append("".join(body))
    return "".join(declarations), tuple(exports)


def _driver_snapshot_fields(
    surface: _DriverHandlerSurface,
    *,
    imports: dict[str, set[str]],
    driver_state_imports: set[str],
) -> tuple[tuple[str, str, _DriverHandlerConstituent, str], ...]:
    selected: list[tuple[str, str, _DriverHandlerConstituent, str]] = []
    is_bundle = len(surface.constituents) > 1
    for constituent in surface.constituents:
        state_layouts = _driver_writable_state_layouts(constituent.layout.states)
        if state_layouts:
            annotation = _driver_state_annotation(
                constituent,
                state_layouts,
                imports=imports,
            )
            if constituent.optional:
                annotation = f"{annotation} | None"
            field_name = constituent.field_name if is_bundle else "state"
            selected.append((field_name, annotation, constituent, "state"))
            driver_state_imports.add(f"decode_{_snake_case(constituent.stem)}_patch")
            driver_state_imports.add(f"{constituent.stem}DriverPatch")
            for layout in state_layouts:
                driver_state_imports.add(_state_encoder_name(layout.source_type))
            for layout in state_layouts[:-1]:
                imports.setdefault(layout.source_type.__module__, set()).add(
                    layout.source_type.__name__
                )
        observation = constituent.layout.observed_state
        if observation is not None:
            if is_bundle:
                field_name = (
                    f"{constituent.field_name}_observation"
                    if state_layouts
                    else constituent.field_name
                )
            else:
                field_name = "observation"
            annotation = observation.state_type.__name__
            if constituent.optional:
                annotation = f"{annotation} | None"
            selected.append((field_name, annotation, constituent, "observation"))
            imports.setdefault(observation.state_type.__module__, set()).add(
                observation.state_type.__name__
            )
            driver_state_imports.add(_observation_encoder_name(observation.state_type))
    return tuple(selected)


def _driver_writable_state_layouts(
    layouts: tuple[DeclaredStateLayout, ...],
) -> tuple[DeclaredStateLayout, ...]:
    return tuple(layout for layout in layouts if layout.role != "common")


def _driver_state_annotation(
    constituent: _DriverHandlerConstituent,
    layouts: tuple[DeclaredStateLayout, ...],
    *,
    imports: dict[str, set[str]],
) -> str:
    if len(layouts) == 1:
        state_type = layouts[0].source_type
        imports.setdefault(state_type.__module__, set()).add(state_type.__name__)
        return state_type.__name__
    alias_name = f"{constituent.stem}State"
    declaration_module = import_module(constituent.interface_type.__module__)
    if hasattr(declaration_module, alias_name):
        imports.setdefault(constituent.interface_type.__module__, set()).add(alias_name)
        return alias_name
    names: list[str] = []
    for layout in layouts:
        state_type = layout.source_type
        imports.setdefault(state_type.__module__, set()).add(state_type.__name__)
        names.append(state_type.__name__)
    return " | ".join(names)


def _driver_operation_model(
    constituent: _DriverHandlerConstituent,
    scope: DeclaredScopeLayout,
    operation: DeclaredOperation,
    *,
    member_imports: set[str],
) -> _DriverOperationModel:
    scope_name = _driver_scope_constant_name(constituent.constant_prefix, scope)
    member_name = _join_constant_name(scope_name, operation.ref.operation_id)
    member_imports.add(member_name)
    return _DriverOperationModel(
        declaration=operation,
        hook_name=_driver_hook_name(scope.python_path, operation.method_name),
        member_name=member_name,
        optional=constituent.optional,
    )


def _driver_scope_constant_name(
    constant_prefix: str,
    scope: DeclaredScopeLayout,
) -> str:
    selected = constant_prefix
    component_path = (
        scope.ref.component_path if isinstance(scope.ref, ComponentRef) else ()
    )
    for component_id in component_path:
        selected = _join_constant_name(selected, component_id)
    return selected


def _driver_hook_name(python_path: tuple[str, ...], method_name: str) -> str:
    return "handle_" + "_".join((*python_path, method_name))


def _render_driver_unsupported_helper() -> str:
    return (
        "\n\ndef _unsupported_driver_request(\n"
        "    instrument_id: str,\n"
        "    kind: str,\n"
        "    member_id: str,\n"
        ") -> DriverRejected:\n"
        "    return DriverRejected(\n"
        "        problems=(\n"
        "            problem(\n"
        '                f"instrument_{kind}_not_implemented",\n'
        '                f"{instrument_id} does not implement {member_id}",\n'
        "                phase=ProblemPhase.EXECUTION,\n"
        '                location=model_location(f"driver_{kind}", member_id),\n'
        "            ),\n"
        "        )\n"
        "    )\n"
    )


def _render_driver_operation_hook(
    model: _DriverOperationModel,
    *,
    renderer: _AnnotationRenderer,
) -> str:
    arguments = model.declaration.arguments
    lines = [
        "\n",
        "    @abstractmethod\n",
        f"    def {model.hook_name}(\n",
        "        self,\n",
    ]
    previous_kind: str | None = None
    for index, argument in enumerate(arguments):
        kind = argument.parameter.kind.name
        if kind == "KEYWORD_ONLY" and previous_kind != "KEYWORD_ONLY":
            lines.append("        *,\n")
        lines.append(
            f"        {argument.python_name}: {renderer.render(argument.annotation)},\n"
        )
        if kind == "POSITIONAL_ONLY" and (
            index == len(arguments) - 1
            or arguments[index + 1].parameter.kind.name != "POSITIONAL_ONLY"
        ):
            lines.append("        /,\n")
        previous_kind = kind
    lines.append("    ) -> DriverOutcome[None]: ...\n")
    return "".join(lines)


def _render_driver_acquisition_hook(model: _DriverAcquisitionModel) -> str:
    return (
        "\n"
        "    @abstractmethod\n"
        f"    def {model.hook_name}(\n"
        "        self,\n"
        f"        requested: frozenset[{model.type_stem}DriverResultName],\n"
        "        /,\n"
        f"    ) -> DriverOutcome[{model.type_stem}DriverReadback]: ...\n"
    )


def _render_adapter_read_state(
    surface: _DriverHandlerSurface,
    *,
    snapshot_fields: tuple[tuple[str, str, _DriverHandlerConstituent, str], ...],
) -> str:
    lines = ["\n", "    def read_state(self) -> DriverState:\n"]
    if not snapshot_fields:
        lines.append("        return encode_driver_state()\n")
        return "".join(lines)

    read_hook = f"read_{_snake_case(surface.stem)}_state"
    lines.extend(
        (
            f"        snapshot = self.{read_hook}()\n",
            "        encoded: list[Mapping[PropertyRef, DriverScalar]] = []\n",
        )
    )
    for field_name, _annotation, constituent, kind in snapshot_fields:
        value = f"snapshot.{field_name}"
        if kind == "observation":
            encoder = _observation_encoder_name(
                cast(
                    "DeclaredObservedState[object]",
                    constituent.layout.observed_state,
                ).state_type
            )
            if constituent.optional:
                flag = cast("str", surface.flag_name)
                lines.extend(
                    (
                        f"        if self._driver_{flag}_enabled and "
                        f"{value} is not None:\n",
                        f"            encoded.append({encoder}({value}))\n",
                    )
                )
            else:
                lines.append(f"        encoded.append({encoder}({value}))\n")
            continue

        layouts = _driver_writable_state_layouts(constituent.layout.states)
        indent = "        "
        if constituent.optional:
            flag = cast("str", surface.flag_name)
            lines.append(
                f"        if self._driver_{flag}_enabled and {value} is not None:\n"
            )
            indent = "            "
        if len(layouts) == 1:
            lines.append(
                f"{indent}encoded.append("
                f"{_state_encoder_name(layouts[0].source_type)}({value}))\n"
            )
            continue
        for index, layout in enumerate(layouts):
            if index == len(layouts) - 1:
                lines.extend(
                    (
                        f"{indent}else:\n",
                        f"{indent}    encoded.append("
                        f"{_state_encoder_name(layout.source_type)}({value}))\n",
                    )
                )
                continue
            keyword = "if" if index == 0 else "elif"
            lines.extend(
                (
                    f"{indent}{keyword} isinstance({value}, "
                    f"{layout.source_type.__name__}):\n",
                    f"{indent}    encoded.append("
                    f"{_state_encoder_name(layout.source_type)}({value}))\n",
                )
            )
    lines.append(
        "        return encode_driver_state(*encoded, metadata=snapshot.metadata)\n"
    )
    return "".join(lines)


def _render_adapter_apply_state(
    surface: _DriverHandlerSurface,
    *,
    state_constituents: tuple[_DriverHandlerConstituent, ...],
    patch_name: str,
) -> str:
    lines = [
        "\n",
        "    def apply_state(\n",
        "        self,\n",
        "        request: DriverStatePatch,\n",
        "    ) -> DriverOutcome[DriverState | None]:\n",
    ]
    if not state_constituents:
        lines.extend(
            (
                "        del request\n",
                "        return _unsupported_driver_request("
                'self.instrument_id, "state", "state")\n',
            )
        )
        return "".join(lines)

    decoded_names: list[str] = []
    for constituent in state_constituents:
        decoded_name = f"{constituent.field_name}_patch"
        decoded_names.append(decoded_name)
        lines.append(
            f"        {decoded_name} = "
            f"decode_{_snake_case(constituent.stem)}_patch(request)\n"
        )
        if constituent.optional:
            flag = cast("str", surface.flag_name)
            lines.extend(
                (
                    f"        if {decoded_name} and not self._driver_{flag}_enabled:\n",
                    "            return _unsupported_driver_request(\n",
                    f'                self.instrument_id, "state", '
                    f"{_string_literal(constituent.layout.compiled.ref.interface_id)}\n",
                    "            )\n",
                )
            )

    apply_hook = f"apply_{_snake_case(surface.stem)}_state"
    if len(state_constituents) == 1:
        lines.append(f"        outcome = self.{apply_hook}({decoded_names[0]})\n")
    else:
        lines.extend(
            (
                f"        outcome = self.{apply_hook}(\n",
                f"            {patch_name}(\n",
                *(
                    f"                {constituent.field_name}={decoded_name},\n"
                    for constituent, decoded_name in zip(
                        state_constituents, decoded_names, strict=True
                    )
                ),
                "            )\n",
                "        )\n",
            )
        )
    lines.extend(
        (
            "        if isinstance(outcome, DriverSuccess):\n",
            "            return DriverSuccess(None, metadata=outcome.metadata)\n",
            "        return outcome\n",
        )
    )
    return "".join(lines)


def _annotation_string_literal(annotation: str) -> str:
    return repr(annotation) if '"' in annotation else _string_literal(annotation)


def _render_adapter_invoke(
    surface: _DriverHandlerSurface,
    models: tuple[_DriverOperationModel, ...],
    *,
    renderer: _AnnotationRenderer,
) -> str:
    lines = [
        "\n",
        "    def invoke(\n",
        "        self,\n",
        "        request: DriverOperation,\n",
        "    ) -> DriverOutcome[DriverState | None]:\n",
    ]
    for model in models:
        condition = f"request.target == {model.member_name}"
        if model.optional:
            condition += f" and self._driver_{cast('str', surface.flag_name)}_enabled"
        lines.extend(
            (
                f"        if {condition}:\n",
                "            arguments = request.arguments\n",
            )
        )
        call_arguments: list[str] = []
        for argument in model.declaration.arguments:
            annotation = renderer.render(argument.annotation)
            value = f"arguments[{_string_literal(argument.ref.argument_id)}]"
            if isinstance(argument.spec.value_type.atom, PayloadType):
                value = f'cast("DriverPayload", {value}).value'
            value = f"cast({_annotation_string_literal(annotation)}, {value})"
            if argument.parameter.kind.name == "KEYWORD_ONLY":
                call_arguments.append(
                    f"                {argument.python_name}={value},\n"
                )
            else:
                call_arguments.append(f"                {value},\n")
        if call_arguments:
            lines.extend(
                (
                    f"            outcome = self.{model.hook_name}(\n",
                    *call_arguments,
                    "            )\n",
                )
            )
        else:
            lines.append(f"            outcome = self.{model.hook_name}()\n")
        lines.extend(
            (
                "            if isinstance(outcome, DriverSuccess):\n",
                "                return DriverSuccess(None, "
                "metadata=outcome.metadata)\n",
                "            return outcome\n",
            )
        )
    lines.extend(
        (
            "        return _unsupported_driver_request(\n",
            "            self.instrument_id,\n",
            '            "operation",\n',
            "            request.target.operation_id,\n",
            "        )\n",
        )
    )
    return "".join(lines)


def _render_adapter_collect(
    surface: _DriverHandlerSurface,
    models: tuple[_DriverAcquisitionModel, ...],
) -> str:
    lines = [
        "\n",
        "    def collect(\n",
        "        self,\n",
        "        request: DriverAcquisition,\n",
        "    ) -> DriverOutcome[DriverReadback]:\n",
    ]
    for model in models:
        variable_suffix = model.hook_name.removeprefix("handle_")
        requested_name = f"requested_{variable_suffix}"
        outcome_name = f"outcome_{variable_suffix}"
        readback_name = f"readback_{variable_suffix}"
        values_name = f"values_{variable_suffix}"
        condition = f"request.target == {model.member_name}"
        if model.optional:
            condition += f" and self._driver_{cast('str', surface.flag_name)}_enabled"
        if len(f"        if {condition}:") <= 88:
            lines.append(f"        if {condition}:\n")
        elif model.optional:
            flag = cast("str", surface.flag_name)
            lines.extend(
                (
                    "        if (\n",
                    f"            request.target == {model.member_name}\n",
                    f"            and self._driver_{flag}_enabled\n",
                    "        ):\n",
                )
            )
        else:
            lines.extend(
                ("        if (\n", f"            {condition}\n", "        ):\n")
            )
        requested_declaration = (
            f"            {requested_name}: "
            f"set[{model.type_stem}DriverResultName] = set()\n"
        )
        if len(requested_declaration.rstrip("\n")) <= 88:
            lines.append(requested_declaration)
        else:
            lines.extend(
                (
                    f"            {requested_name}: "
                    f"set[{model.type_stem}DriverResultName] = (\n",
                    "                set()\n",
                    "            )\n",
                )
            )
        lines.append("            for result in request.results:\n")
        for index, field in enumerate(model.fields):
            keyword = "if" if index == 0 else "elif"
            lines.extend(
                (
                    f"                {keyword} result == {field.member_name}:\n",
                    f"                    {requested_name}.add("
                    f"{_string_literal(field.python_name)})\n",
                )
            )
        lines.extend(
            (
                "                else:\n",
                "                    return _unsupported_driver_request(\n",
                "                        self.instrument_id,\n",
                '                        "acquisition_result",\n',
                "                        result.result_id,\n",
                "                    )\n",
            )
        )
        outcome_call = (
            f"            {outcome_name} = self.{model.hook_name}("
            f"frozenset({requested_name}))\n"
        )
        if len(outcome_call.rstrip("\n")) <= 88:
            lines.append(outcome_call)
        else:
            lines.extend(
                (
                    f"            {outcome_name} = self.{model.hook_name}(\n",
                    f"                frozenset({requested_name})\n",
                    "            )\n",
                )
            )
        lines.extend(
            (
                f"            if not isinstance({outcome_name}, DriverSuccess):\n",
                f"                return {outcome_name}\n",
                f"            {readback_name} = {outcome_name}.value\n",
                f"            {values_name}: dict[AcquisitionResultRef, "
                "MeasurementValue] = {}\n",
            )
        )
        for field in model.fields:
            field_literal = _string_literal(field.python_name)
            lines.append(f"            if {field_literal} in {readback_name}.values:\n")
            assignment = (
                f"                {values_name}[{field.member_name}] = "
                f"{readback_name}.values[{field_literal}]\n"
            )
            if len(assignment.rstrip("\n")) <= 88:
                lines.append(assignment)
            else:
                split_index = (
                    f"                {values_name}[{field.member_name}] = "
                    f"{readback_name}.values["
                )
                if len(split_index) <= 88:
                    lines.extend(
                        (
                            f"{split_index}\n",
                            f"                    {field_literal}\n",
                            "                ]\n",
                        )
                    )
                else:
                    lines.extend(
                        (
                            f"                {values_name}[{field.member_name}] = (\n",
                            f"                    {readback_name}.values["
                            f"{field_literal}]\n",
                            "                )\n",
                        )
                    )
        lines.extend(
            (
                "            return DriverSuccess(\n",
                "                DriverReadback(\n",
                f"                    values={values_name},\n",
                f"                    metadata={readback_name}.metadata,\n",
                "                ),\n",
                f"                metadata={outcome_name}.metadata,\n",
                "            )\n",
            )
        )
    lines.extend(
        (
            "        return _unsupported_driver_request(\n",
            "            self.instrument_id,\n",
            '            "acquisition",\n',
            "            request.target.acquisition_id,\n",
            "        )\n",
        )
    )
    return "".join(lines)


def _driver_patch_fields(
    model: _CatalogInterfaceModel,
) -> tuple[_DriverPatchField, ...]:
    annotations_by_id: dict[str, object] = {}
    constant_values_by_id: dict[str, list[object]] = {}
    for layout in model.states:
        for declared_field in layout.fields:
            property_id = declared_field.property_id
            existing = annotations_by_id.get(property_id)
            if existing is not None and existing != declared_field.annotation:
                raise ClientGenerationError(
                    f"driver patch property {model.interface_identity}.{property_id} "
                    "has inconsistent concrete annotations"
                )
            annotations_by_id[property_id] = declared_field.annotation
        for ref, value in layout.constants:
            selected = constant_values_by_id.setdefault(ref.property_id, [])
            if value not in selected:
                selected.append(value)

    for property_id, values in constant_values_by_id.items():
        if property_id in annotations_by_id:
            raise ClientGenerationError(
                f"driver patch property {model.interface_identity}.{property_id} "
                "is both a concrete field and a state constant"
            )
        annotations_by_id[property_id] = typing.Literal[*tuple(values)]

    return tuple(
        _DriverPatchField(property_id=property_spec.id, annotation=annotation)
        for property_spec in model.root.spec.properties
        if (annotation := annotations_by_id.get(property_spec.id)) is not None
    )


def _driver_patch_name(model: _CatalogInterfaceModel) -> str:
    stem = model.interface_type_name.removesuffix("Interface")
    return f"{stem}DriverPatch"


def _driver_patch_decoder_name(model: _CatalogInterfaceModel) -> str:
    stem = model.interface_type_name.removesuffix("Interface")
    return f"decode_{_snake_case(stem)}_patch"


def _render_driver_patch_type(
    name: str,
    fields: tuple[tuple[str, str], ...],
) -> str:
    if all(
        field_name.isidentifier() and not keyword.iskeyword(field_name)
        for field_name, _ in fields
    ):
        body = "".join(
            _render_state_projection_field(field_name, annotation, required=True)
            for field_name, annotation in fields
        )
        return f"\n\nclass {name}(TypedDict, total=False):\n{body}"
    entries = "".join(
        f"        {_string_literal(field_name)}: {annotation},\n"
        for field_name, annotation in fields
    )
    return (
        f"\n\n{name} = TypedDict(\n"
        f"    {_string_literal(name)},\n"
        "    {\n"
        f"{entries}"
        "    },\n"
        "    total=False,\n"
        ")\n"
    )


def _render_driver_patch_decoder(
    model: _CatalogInterfaceModel,
    *,
    patch_name: str,
    decoder_name: str,
    fields: tuple[tuple[str, str], ...],
    member_imports: set[str],
) -> str:
    body: list[str] = [
        _render_driver_function_header(
            decoder_name,
            parameter="request",
            parameter_type="DriverStatePatch",
            return_type=patch_name,
        ),
        f"    decoded: {patch_name} = {{}}\n",
        "    values = request.values\n",
    ]
    for property_id, annotation in fields:
        member_name = _join_constant_name(model.constant_prefix, property_id)
        member_imports.add(member_name)
        annotation_literal = (
            repr(annotation) if '"' in annotation else _string_literal(annotation)
        )
        body.extend(
            (
                f"    if {member_name} in values:\n",
                f"        decoded[{_string_literal(property_id)}] = cast(\n",
                f"            {annotation_literal},\n",
                f"            values[{member_name}],\n",
                "        )\n",
            )
        )
    body.append("    return decoded\n")
    return "\n\n" + "".join(body)


def _state_encoder_name(source_type: type[object]) -> str:
    stem = _snake_case(source_type.__name__)
    if not stem.endswith("_state"):
        stem = f"{stem}_state"
    return f"encode_{stem}"


def _observation_encoder_name(source_type: type[object]) -> str:
    return f"encode_{_snake_case(source_type.__name__)}"


def _render_exact_state_encoder(
    layout: DeclaredStateLayout,
    *,
    constant_prefix: str,
    encoder_name: str,
    source_type_name: str,
    member_imports: set[str],
) -> str:
    source_fields = {
        item.name
        for item in dataclass_fields(
            layout.source_type  # pyright: ignore[reportArgumentType]
        )
    }
    selected_fields = tuple(
        declared_field
        for declared_field in layout.fields
        if declared_field.python_name in source_fields
    )
    entries: list[str] = []
    for ref, value in layout.constants:
        member_name = _member_constant_name(constant_prefix, ref)
        member_imports.add(member_name)
        literal = _string_literal(value) if isinstance(value, str) else repr(value)
        entries.append(f"        {member_name}: {literal},\n")
    for declared_field in selected_fields:
        member_name = _member_constant_name(constant_prefix, declared_field.ref)
        member_imports.add(member_name)
        entries.append(f"        {member_name}: state.{declared_field.python_name},\n")
    return (
        "\n\n"
        + _render_driver_function_header(
            encoder_name,
            parameter="state",
            parameter_type=source_type_name,
            return_type="dict[PropertyRef, DriverScalar]",
        )
        + "    return {\n"
        + "".join(entries)
        + "    }\n"
    )


def _render_observation_encoder(
    observation: DeclaredObservedState[object],
    *,
    constant_prefix: str,
    encoder_name: str,
    observation_type_name: str,
    member_imports: set[str],
) -> str:
    entries: list[str] = []
    for observed_field in observation.fields:
        member_name = _member_constant_name(constant_prefix, observed_field.ref)
        member_imports.add(member_name)
        entries.append(f"        {member_name}: state.{observed_field.python_name},\n")
    return (
        "\n\n"
        + _render_driver_function_header(
            encoder_name,
            parameter="state",
            parameter_type=observation_type_name,
            return_type="dict[PropertyRef, DriverScalar]",
        )
        + "    return {\n"
        + "".join(entries)
        + "    }\n"
    )


def _member_constant_name(constant_prefix: str, ref: PropertyRef) -> str:
    return _join_constant_name(constant_prefix, ref.property_id)


def _render_driver_function_header(
    name: str,
    *,
    parameter: str,
    parameter_type: str,
    return_type: str,
) -> str:
    compact = f"def {name}({parameter}: {parameter_type}, /) -> {return_type}:\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return f"def {name}(\n    {parameter}: {parameter_type}, /\n) -> {return_type}:\n"


def _render_driver_import_block(imports: dict[str, set[str]]) -> str:
    standard_modules = {"abc", "collections.abc", "dataclasses", "typing"}
    local_modules = {
        module
        for module in imports
        if module.startswith(
            ("scopecat_instruments", "client_codegen_fixture", "generated_")
        )
    }
    third_party_modules = imports.keys() - standard_modules - local_modules
    sections = tuple(
        "".join(
            _render_from_import(module, imports[module])
            for module in sorted(modules & imports.keys())
        )
        for modules in (standard_modules, third_party_modules, local_modules)
    )
    return "\n".join(section for section in sections if section)


def _render_encode_driver_state() -> str:
    return (
        "\n\n"
        "def encode_driver_state(\n"
        "    *states: Mapping[PropertyRef, DriverScalar],\n"
        "    metadata: dict[str, JsonValue] | None = None,\n"
        ") -> DriverState:\n"
        "    values: dict[PropertyRef, DriverScalar] = {}\n"
        "    for state in states:\n"
        "        values.update(state)\n"
        "    return DriverState(\n"
        "        values=values,\n"
        "        metadata={} if metadata is None else metadata,\n"
        "    )\n"
    )


def _state_projection_layout_name(names: _StateProjectionNames) -> str:
    stem = names.patch.removesuffix("Patch")
    return f"_{_snake_case(stem).upper()}_STATE_LAYOUT"


def _render_state_projection_layout(
    name: str,
    layout: DeclaredStateLayout,
    *,
    constant_prefix: str,
    member_imports: set[str],
) -> str:
    fields: list[str] = []
    for field in layout.fields:
        member_name = _member_constant_name(constant_prefix, field.ref)
        member_imports.add(member_name)
        fields.append(
            f"StateProjectionField({_string_literal(field.python_name)}, {member_name})"
        )

    constants: list[str] = []
    for ref, value in layout.constants:
        if not isinstance(value, str):
            raise ClientGenerationError(
                "generated state case discriminator must be a string"
            )
        member_name = _member_constant_name(constant_prefix, ref)
        member_imports.add(member_name)
        constants.append(f"({member_name}, {_string_literal(value)})")

    return (
        f"\n\n{name} = StateProjectionLayout(\n"
        + _render_state_layout_argument("fields", fields)
        + _render_state_layout_argument("constants", constants)
        + ")\n"
    )


def _render_state_layout_argument(name: str, values: list[str]) -> str:
    compact_tuple = f"({', '.join(values)}{',' if len(values) == 1 else ''})"
    compact = f"    {name}={compact_tuple},\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return (
        f"    {name}=(\n"
        + "".join(f"        {value},\n" for value in values)
        + "    ),\n"
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


def render_generation_target(
    target: GenerationTarget,
    *,
    declaration_cache: _DeclarationCache | None = None,
) -> str:
    """Render one configured generated module."""

    return render_client_module(
        target.surfaces,
        state_projection_module=target.state_projection_module,
        declaration_cache=declaration_cache,
    )


def render_client_module(
    surfaces: tuple[GenerationSurface, ...],
    *,
    state_projection_module: str,
    declaration_cache: _DeclarationCache | None = None,
) -> str:
    """Render an independently importable module for selected declarations."""

    renderer = _AnnotationRenderer()
    cache = declaration_cache or _DeclarationCache()
    models, facade_models = _client_models(
        surfaces,
        renderer=renderer,
        state_projection_module=state_projection_module,
        declaration_cache=cache,
    )

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


def _client_models(
    surfaces: tuple[GenerationSurface, ...],
    *,
    renderer: _AnnotationRenderer,
    state_projection_module: str,
    declaration_cache: _DeclarationCache,
) -> tuple[tuple[_InterfaceModel, ...], tuple[_BundleFlagFacadeModel, ...]]:
    suppressed_families = _facade_base_identities(surfaces)
    models = tuple(
        _generation_model(
            surface,
            renderer=renderer,
            state_projection_module=state_projection_module,
            suppressed_families=suppressed_families,
            declaration_cache=declaration_cache,
        )
        for surface in surfaces
    )
    if not models:
        raise ClientGenerationError("a generated client module requires a declaration")
    facade_models = _bundle_flag_facade_models(surfaces, models=models)
    _validate_generated_symbols(models, facades=facade_models)
    return models, facade_models


def render_package_exports_target(
    target: PackageExportsTarget,
    *,
    declaration_cache: _DeclarationCache | None = None,
) -> str:
    """Render static package export routes without importing generated modules."""

    cache = declaration_cache or _DeclarationCache()
    client_models, facade_models = _client_models(
        target.client_target.surfaces,
        renderer=_AnnotationRenderer(),
        state_projection_module=target.client_target.state_projection_module,
        declaration_cache=cache,
    )
    catalog_models = _catalog_models(
        target.catalog_target.interface_types,
        declaration_cache=cache,
    )
    state_layouts = _unique_state_layouts(catalog_models)
    state_exports = _state_export_owners(
        catalog_models,
        public_types=target.catalog_target.public_types,
        state_layouts=state_layouts,
    )

    routes: dict[str, str] = {}
    for name, module in target.static_exports:
        _register_package_export(routes, name=name, module=module)
    for name in _client_export_names(client_models, facades=facade_models):
        _register_package_export(routes, name=name, module=target.client_module)
    for name in state_exports:
        _register_package_export(routes, name=name, module=target.states_module)
    return _render_package_exports_module(routes)


def _register_package_export(
    routes: dict[str, str],
    *,
    name: str,
    module: str,
) -> None:
    existing = routes.get(name)
    if existing is not None:
        raise ClientGenerationError(
            f"generated package export collision {name}: {existing} vs {module}"
        )
    routes[name] = module


def _render_package_exports_module(routes: dict[str, str]) -> str:
    names_by_module: dict[str, set[str]] = {}
    for name, module in routes.items():
        names_by_module.setdefault(module, set()).add(name)
    type_checking_imports = "".join(
        "".join(
            f"    {line}"
            for line in _render_bare_from_import(module, names).splitlines(
                keepends=True
            )
        )
        for module, names in sorted(names_by_module.items())
    )
    return (
        "# This file was auto-generated by scripts/generate_instrument_clients.py.\n"
        "# Do not make direct changes to the file.\n"
        "# ruff: noqa: F401\n"
        "# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false\n"
        '"""Generated typed and lazy instrument package facade."""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from importlib import import_module\n"
        "from typing import TYPE_CHECKING, cast\n"
        "\n"
        "if TYPE_CHECKING:\n"
        f"{type_checking_imports}"
        "\n"
        "\n"
        "_PUBLIC_EXPORT_MODULES: dict[str, str] = {\n"
        + "".join(
            f"    {_string_literal(name)}: {_string_literal(module)},\n"
            for name, module in sorted(routes.items())
        )
        + "}\n"
        "\n"
        "\n"
        "def __getattr__(name: str) -> object:\n"
        "    module = _PUBLIC_EXPORT_MODULES.get(name)\n"
        "    if module is None:\n"
        "        raise AttributeError("
        'f"module {__name__!r} has no attribute {name!r}")\n'
        '    value = cast("object", getattr(import_module(module), name))\n'
        "    globals()[name] = value\n"
        "    return value\n"
        "\n"
        "\n"
        "def __dir__() -> list[str]:\n"
        "    return sorted({*globals(), *_PUBLIC_EXPORT_MODULES})\n"
        "\n"
        "\n"
        "__all__ = sorted(_PUBLIC_EXPORT_MODULES)\n"
    )


def _generation_model(
    surface: GenerationSurface,
    *,
    renderer: _AnnotationRenderer,
    state_projection_module: str,
    suppressed_families: frozenset[str],
    declaration_cache: _DeclarationCache,
) -> _InterfaceModel:
    if isinstance(surface, BundleClientSurface):
        return _bundle_model(
            surface,
            renderer=renderer,
            state_projection_module=state_projection_module,
            declaration_cache=declaration_cache,
        )
    return _interface_model(
        surface,
        renderer=renderer,
        state_projection_module=state_projection_module,
        generate_family=_type_identity(surface.interface_type)
        not in suppressed_families,
        declaration_cache=declaration_cache,
    )


def _interface_model(
    surface: ClientSurface,
    *,
    renderer: _AnnotationRenderer,
    state_projection_module: str,
    generate_family: bool,
    declaration_cache: _DeclarationCache,
) -> _InterfaceModel:
    constituent = _constituent_model(
        surface.interface_type,
        renderer=renderer,
        declaration_cache=declaration_cache,
    )
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
        layout.states,
        state_projection_module=state_projection_module,
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
        keyword_state=_state_keyword_model(layout.states, renderer=renderer),
        constituents=(constituent,),
        root=root,
    )


def _bundle_model(
    surface: BundleClientSurface,
    *,
    renderer: _AnnotationRenderer,
    state_projection_module: str,
    declaration_cache: _DeclarationCache,
) -> _InterfaceModel:
    bundle_type = surface.bundle_type
    bundle_identity = f"{bundle_type.__module__}.{bundle_type.__qualname__}"
    constituents = tuple(
        _constituent_model(
            interface_type,
            renderer=renderer,
            declaration_cache=declaration_cache,
        )
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
            new_layouts,
            state_projection_module=state_projection_module,
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
        keyword_state=_state_keyword_model(tuple(state_layouts), renderer=renderer),
        constituents=constituents,
        root=root,
    )


def _constituent_model(
    interface_type: type[object],
    *,
    renderer: _AnnotationRenderer,
    declaration_cache: _DeclarationCache,
) -> _InterfaceConstituentModel:
    layout = declaration_cache.layout(interface_type)
    interface_name = interface_type.__name__
    observation_type_name = (
        None
        if layout.observed_state is None
        else renderer.reference(layout.observed_state.state_type)
    )
    return _InterfaceConstituentModel(
        interface_identity=f"{interface_type.__module__}.{interface_type.__qualname__}",
        interface_id=layout.compiled.ref.interface_id,
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
    operation: DeclaredOperation,
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
                argument_id=argument.argument_id,
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
    has_keyword_state = any(model.keyword_state is not None for model in models)
    has_plain_root = any(model.live_state_type_name is None for model in models)

    imports: dict[str, set[str]] = {
        "scopecat.authoring": {"EachEntity", "OneEntity"},
        "scopecat.sdk.instruments": {"InterfaceRef"},
        "scopecat_instruments._symbolic_runtime": {"SymbolicInstrumentRecorder"},
    }
    if facades:
        imports["typing"] = {"Literal", "overload"}
        imports["scopecat.api._instruments"] = {"InstrumentRef", "instrument"}
        imports["scopecat.authoring"].add("EntitySelection")
    if any(model.generate_family for model in models):
        imports["scopecat_instruments._family_runtime"] = {"InstrumentFamily"}
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
    if has_keyword_state:
        imports.setdefault("typing", set()).update({"overload", "override"})
        imports["scopecat.authoring"].update({"PerEntity", "ValueRef"})
        imports.setdefault("scopecat.sdk.instruments", set()).add("ApplyReceipt")
    if has_operations or has_acquisitions:
        imports["scopecat.authoring"].add("PerEntity")
    if has_operations:
        imports["scopecat.authoring"].add("ValueRef")
    if has_acquisitions:
        imports["dataclasses"] = {"dataclass", "field"}
        imports["scopecat.authoring"].add("ProductRef")
        imports["scopecat.records.measurement"] = {"MeasurementValue"}
        imports["scopecat.sdk.instruments"].add("CollectReceipt")
        imports.setdefault("scopecat_instruments._client_runtime", set()).update(
            {
                "ClientAcquisition",
                "ClientAcquisitionAxis",
                "ClientAcquisitionLayout",
                "ClientAcquisitionResult",
            }
        )
    if has_operations:
        imports.setdefault("scopecat.sdk.instruments", set()).add("InvokeReceipt")
    if has_observations:
        imports.setdefault("scopecat_instruments._client_runtime", set()).update(
            {
                "ClientObservedField",
                "ClientObservedState",
                "client_property_value_type",
            }
        )
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


def _import_name_key(name: str) -> tuple[int | str, ...]:
    if name.isupper():
        return (0, *name.casefold().split("_"))
    if name[0].isupper():
        return (1, *name.casefold().split("_"))
    return (2, *name.casefold().split("_"))


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
        f"\n{constituent.ref_name} = InterfaceRef("
        f"{_string_literal(constituent.interface_id)})\n"
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
    sections: list[str] = []
    observation = constituent.layout.observed_state
    if observation is not None:
        observation_name = constituent.observation_descriptor_name
        observation_type_name = constituent.observation_type_name
        if observation_name is None or observation_type_name is None:
            raise AssertionError("observed constituent requires a descriptor name")
        sections.append(
            _render_client_observation(
                observation_name,
                observation_type_name,
                observation,
            )
        )
    _append_client_scope_descriptors(
        sections,
        constituent.layout.root,
        root_ref_name=constituent.ref_name,
        constant_prefix=constituent.constant_prefix,
    )
    return "".join(sections)


def _render_client_observation(
    name: str,
    observation_type_name: str,
    observation: DeclaredObservedState[object],
) -> str:
    fields: list[str] = []
    for field in observation.fields:
        value_type_json = _json_model_field(
            field.spec.model_dump_json(),
            "value_type",
        )
        ref_argument = _render_client_ref_argument(
            _property_ref_expression(field.ref),
            indent=12,
        )
        value_type_argument = _render_client_value_type_argument(
            value_type_json,
            indent=12,
        )
        fields.append(
            "        ClientObservedField(\n"
            f"            {_string_literal(field.python_name)},\n"
            f"{ref_argument}"
            f"{value_type_argument}"
            "        ),\n"
        )
    return (
        f"\n{name} = ClientObservedState(\n"
        f"    {observation_type_name},\n"
        "    fields=(\n"
        f"{''.join(fields)}"
        "    ),\n"
        ")\n"
    )


def _append_client_scope_descriptors(
    sections: list[str],
    scope: DeclaredScopeLayout,
    *,
    root_ref_name: str,
    constant_prefix: str,
) -> None:
    for operation in scope.operations:
        sections.append(
            "\n"
            + _render_ref_assignment(
                _descriptor_name(
                    constant_prefix,
                    scope.python_path,
                    operation.method_name,
                ),
                _operation_ref_expression(root_ref_name, operation.ref),
            )
        )
    for acquisition in scope.acquisitions:
        sections.append(
            _render_client_acquisition(
                _descriptor_name(
                    constant_prefix,
                    scope.python_path,
                    acquisition.method_name,
                ),
                acquisition,
                root_ref_name=root_ref_name,
            )
        )
    for component in scope.components:
        _append_client_scope_descriptors(
            sections,
            component,
            root_ref_name=root_ref_name,
            constant_prefix=constant_prefix,
        )


def _render_client_acquisition(
    name: str,
    acquisition: DeclaredAcquisition[object],
    *,
    root_ref_name: str,
) -> str:
    acquisition_ref = _acquisition_ref_expression(root_ref_name, acquisition.ref)
    layouts = "".join(
        _render_client_acquisition_layout(
            layout,
            acquisition_ref=acquisition_ref,
        )
        for layout in acquisition.layouts
    )
    discriminator = (
        "None"
        if acquisition.discriminator is None
        else _property_ref_expression(acquisition.discriminator)
    )
    return (
        f"\n{name} = ClientAcquisition(\n"
        f"    ref={acquisition_ref},\n"
        f"    discriminator={discriminator},\n"
        "    layouts=(\n"
        f"{layouts}"
        "    ),\n"
        ")\n"
    )


def _render_client_acquisition_layout(
    layout: DeclaredResultLayout,
    *,
    acquisition_ref: str,
) -> str:
    fields = "".join(
        _render_client_acquisition_result(field, acquisition_ref=acquisition_ref)
        for field in layout.fields
    )
    case_value = (
        "None" if layout.case_value is None else _string_literal(layout.case_value)
    )
    return (
        "        ClientAcquisitionLayout(\n"
        f"            case_value={case_value},\n"
        "            fields=(\n"
        f"{fields}"
        "            ),\n"
        "        ),\n"
    )


def _render_client_acquisition_result(
    field: DeclaredResultField,
    *,
    acquisition_ref: str,
) -> str:
    axes = tuple(_render_client_acquisition_axis(axis) for axis in field.spec.axes)
    axes_expression = "(\n" + "".join(axes) + "                    )" if axes else "()"
    result_ref = f"{acquisition_ref}.result({_string_literal(field.result_id)})"
    return (
        "                ClientAcquisitionResult(\n"
        f"                    {_string_literal(field.python_name)},\n"
        f"{_render_client_ref_argument(result_ref, indent=20)}"
        f"                    dtype={_string_literal(field.spec.dtype)},\n"
        f"                    unit={_optional_string_literal(field.spec.unit)},\n"
        f"                    axes={axes_expression},\n"
        "                ),\n"
    )


def _render_client_acquisition_axis(axis: AcquisitionAxisSpec) -> str:
    size = axis.size
    if isinstance(size, int):
        size_argument = f"                            size={size},\n"
    else:
        size_expression = _property_ref_expression(
            PropertyRef(
                size.interface_id,
                tuple(size.component_path),
                size.property_id,
            )
        )
        size_argument = _render_client_ref_keyword(
            "size",
            size_expression,
            indent=28,
        )
    return (
        "                        ClientAcquisitionAxis(\n"
        f"                            id={_string_literal(axis.id)},\n"
        f"{size_argument}"
        f"                            kind={_string_literal(axis.kind)},\n"
        f"                            unit={_optional_string_literal(axis.unit)},\n"
        "                        ),\n"
    )


def _scope_ref_expression(root_ref_name: str, component_path: tuple[str, ...]) -> str:
    expression = root_ref_name
    for component_id in component_path:
        expression += f".component({_string_literal(component_id)})"
    return expression


def _property_ref_expression(ref: PropertyRef) -> str:
    root = f"InterfaceRef({_string_literal(ref.interface_id)})"
    scope = _scope_ref_expression(root, ref.component_path)
    return f"{scope}.property({_string_literal(ref.property_id)})"


def _operation_ref_expression(root_ref_name: str, ref: OperationRef) -> str:
    scope = _scope_ref_expression(root_ref_name, ref.component_path)
    return f"{scope}.operation({_string_literal(ref.operation_id)})"


def _acquisition_ref_expression(root_ref_name: str, ref: AcquisitionRef) -> str:
    scope = _scope_ref_expression(root_ref_name, ref.component_path)
    return f"{scope}.acquisition({_string_literal(ref.acquisition_id)})"


def _render_ref_assignment(name: str, expression: str) -> str:
    compact = f"{name} = {expression}\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    chained = expression.replace(").", ")\n    .")
    return f"{name} = (\n    {chained}\n)\n"


def _render_client_ref_argument(expression: str, *, indent: int) -> str:
    prefix = " " * indent
    compact = f"{prefix}{expression},\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    receiver, separator, call = expression.rpartition(".")
    method, open_paren, argument = call.partition("(")
    if not separator or not open_paren or not argument.endswith(")"):
        return compact
    return f"{prefix}{receiver}.{method}(\n{prefix}    {argument[:-1]}\n{prefix}),\n"


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


def _render_keyword_projection_method(
    *,
    method_name: str,
    positional_name: str,
    positional_annotation: str,
    projection_type_name: str,
    fields: tuple[_StateKeywordFieldModel, ...],
    field_annotation: str,
    return_annotation: str,
    helper_name: str,
    returns: bool,
) -> str:
    positional_parameter = f"        {positional_name}: {positional_annotation},\n"
    if len(positional_parameter.rstrip("\n")) > 88:
        branches = _split_top_level_union(positional_annotation)
        positional_parameter = f"        {positional_name}: (\n"
        positional_parameter += f"            {branches[0]}\n"
        positional_parameter += "".join(
            f"            | {branch}\n" for branch in branches[1:]
        )
        positional_parameter += "        ),\n"

    keyword_parameters = "".join(
        _render_optional_keyword_parameter(
            field,
            annotation=cast("str", getattr(field, field_annotation)),
        )
        for field in fields
    )
    if fields:
        keyword_overload = (
            f"    @overload\n"
            f"    def {method_name}(\n"
            "        self,\n"
            "        *,\n"
            f"{keyword_parameters}"
            f"    ) -> {return_annotation}: ...\n"
        )
    else:
        keyword_overload = (
            f"    @overload\n    def {method_name}(self) -> {return_annotation}: ...\n"
        )
    return_prefix = "return " if returns else ""
    return (
        "    @overload\n"
        f"    def {method_name}(\n"
        "        self,\n"
        f"{positional_parameter}"
        f"    ) -> {return_annotation}: ...\n"
        "\n"
        f"{keyword_overload}"
        "\n"
        "    @override\n"
        f"    def {method_name}(\n"
        "        self,\n"
        f"        {positional_name}: {positional_annotation} | None = None,\n"
        "        **fields: object,\n"
        f"    ) -> {return_annotation}:\n"
        f"        {return_prefix}self.{helper_name}(\n"
        f"            {positional_name},\n"
        f"            {projection_type_name},\n"
        "            fields,\n"
        "        )\n"
    )


def _render_client_ref_keyword(name: str, expression: str, *, indent: int) -> str:
    prefix = " " * indent
    compact = f"{prefix}{name}={expression},\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    receiver, separator, call = expression.rpartition(".")
    method, open_paren, argument = call.partition("(")
    if not separator or not open_paren or not argument.endswith(")"):
        return compact
    return (
        f"{prefix}{name}={receiver}.{method}(\n"
        f"{prefix}    {argument[:-1]}\n"
        f"{prefix}),\n"
    )


def _render_client_value_type_argument(value_type_json: str, *, indent: int) -> str:
    prefix = " " * indent
    literal = _formatted_string_literal(value_type_json)
    compact = f"{prefix}client_property_value_type({literal}),\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return (
        f"{prefix}client_property_value_type(\n"
        f"{_render_string_literal_lines(value_type_json, indent=indent + 4)}"
        f"{prefix}),\n"
    )


def _render_optional_keyword_parameter(
    field: _StateKeywordFieldModel,
    *,
    annotation: str,
) -> str:
    compact = f"        {field.python_name}: {annotation} = ...,\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    branches = _split_top_level_union(annotation)
    lines = [f"        {field.python_name}: (\n", f"            {branches[0]}\n"]
    lines.extend(f"            | {branch}\n" for branch in branches[1:])
    lines.append("        ) = ...,\n")
    return "".join(lines)


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
    if scope.is_root and model.keyword_state is not None:
        state = model.keyword_state
        body.append(
            _render_keyword_projection_method(
                method_name="apply",
                positional_name="patch",
                positional_annotation=state.patch_type_name,
                projection_type_name=state.patch_type_name,
                fields=state.fields,
                field_annotation="concrete_annotation",
                return_annotation="ApplyReceipt",
                helper_name="_apply_projected",
                returns=True,
            )
        )
    if scope.is_root and model.observation_type_name is not None:
        _append_member_separator(body)
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
    call = _render_operation_call(
        operation,
        receiver="self._invoke",
        returns=True,
    )
    return signature + call


def _render_live_acquisition(acquisition: _AcquisitionModel) -> str:
    return (
        f"    def {acquisition.method_name}(self) -> {acquisition.readback_name}:\n"
        "        return self._collect(\n"
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
        if model.keyword_state is not None:
            _append_member_separator(body)
            state = model.keyword_state
            body.append(
                _render_keyword_projection_method(
                    method_name="ensure",
                    positional_name="state",
                    positional_annotation=state.target_type_name,
                    projection_type_name=state.target_type_name,
                    fields=state.fields,
                    field_annotation="symbolic_annotation",
                    return_annotation="None",
                    helper_name="_ensure_projected",
                    returns=False,
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
    call = _render_operation_call(
        operation,
        receiver="self._invoke",
        effect_id=True,
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
        "        return self._acquire(\n"
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
        if model.keyword_state is not None:
            _append_member_separator(body)
            state = model.keyword_state
            body.append(
                _render_keyword_projection_method(
                    method_name="ensure",
                    positional_name="state",
                    positional_annotation=(
                        f"{state.group_target_type_name} | "
                        f"PerEntity[{state.target_type_name}]"
                    ),
                    projection_type_name=state.group_target_type_name,
                    fields=state.fields,
                    field_annotation="group_annotation",
                    return_annotation="None",
                    helper_name="_ensure_projected",
                    returns=False,
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


def _render_operation_call(
    operation: _OperationModel,
    *,
    receiver: str,
    returns: bool,
    effect_id: bool = False,
) -> str:
    prefix = "return " if returns else ""
    lines = [f"        {prefix}{receiver}(\n"]
    lines.append(f"            {operation.descriptor_name},\n")
    if effect_id:
        lines.append("            effect_id,\n")
    if not operation.arguments:
        lines.append("            {},\n")
        lines.append("        )\n")
        return "".join(lines)
    lines.append("            {\n")
    for argument in operation.arguments:
        lines.append(
            f"                {operation.descriptor_name}.argument(\n"
            f"                    {_string_literal(argument.argument_id)}\n"
            f"                ): {argument.python_name},\n"
        )
    lines.append("            },\n")
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
    return _render_all(_client_export_names(models, facades=facades))


def _client_export_names(
    models: tuple[_InterfaceModel, ...],
    *,
    facades: tuple[_BundleFlagFacadeModel, ...] = (),
) -> tuple[str, ...]:
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
    return tuple(sorted(exports))


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
                    existing.interface_id != constituent.interface_id
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


def _optional_string_literal(value: str | None) -> str:
    return "None" if value is None else _string_literal(value)


def _json_model_field(model_json: str, field_name: str) -> str:
    decoded = cast("dict[str, object]", json.loads(model_json))
    value = decoded[field_name]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _render_string_literal_lines(value: str, *, indent: int) -> str:
    chunk_size = max(1, (84 - indent) // 2)
    prefix = " " * indent
    return "".join(
        f"{prefix}{_formatted_string_literal(value[index : index + chunk_size])}\n"
        for index in range(0, len(value), chunk_size)
    )


def _formatted_string_literal(value: str) -> str:
    if '"' in value and "'" not in value:
        return repr(value)
    return _string_literal(value)


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
    declaration_cache = _DeclarationCache()
    rendered = (
        *(
            (
                target.output,
                render_generation_target(
                    target,
                    declaration_cache=declaration_cache,
                ),
            )
            for target in _generation_targets()
        ),
        *(
            rendered_source
            for target in _catalog_targets()
            for rendered_source in render_catalog_target(
                target,
                declaration_cache=declaration_cache,
            )
        ),
        *(
            (
                target.output,
                render_driver_handler_target(
                    target,
                    declaration_cache=declaration_cache,
                ),
            )
            for target in _driver_handler_targets()
        ),
        *(
            (
                target.output,
                render_package_exports_target(
                    target,
                    declaration_cache=declaration_cache,
                ),
            )
            for target in _package_exports_targets()
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
