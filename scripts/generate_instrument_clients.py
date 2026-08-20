"""Generate committed first-party instrument surfaces from declarations.

``PACKAGE_MANIFEST`` owns the input catalog. The output path constants below
name every generated runtime module, test fixture, and lazy package facade;
those files are build products and should not be edited directly.
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, TypeAliasType, TypeVar, cast, get_args, get_origin

from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.program.measurement_types import MeasurementDType
from scopecat.sdk.instruments import (
    AcquisitionAxisSpec,
    AcquisitionRef,
    AcquisitionResultSpec,
    InterfaceSpec,
    OperationRef,
    PropertyRef,
)
from scopecat.sdk.instruments.declarations import (
    DeclaredAcquisition,
    DeclaredInterfaceLayout,
    DeclaredOperation,
    DeclaredProperty,
    DeclaredPropertyLayout,
    DeclaredResultField,
    DeclaredScopeLayout,
    Member,
    MemberObservation,
    compile_interface,
    declared_interface_layout,
)
from scopecat_instruments.package_manifest import (
    PACKAGE_MANIFEST,
    AcquisitionPublicNames,
    CompositeSurfaceRegistration,
    InstrumentPackageManifest,
    SurfaceRegistration,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTS_PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "scopecat-instruments"
FIXTURE_MODULE = "scopecat_testkit.instrument_codegen_fixtures"
FIXTURE_PACKAGE_ROOT = (
    REPOSITORY_ROOT
    / "testing"
    / "scopecat-testkit"
    / "src"
    / "scopecat_testkit"
    / "instrument_codegen_fixtures"
)
FIXTURE_MEMBERS_OUTPUT = FIXTURE_PACKAGE_ROOT / "generated_members.py"
FIXTURE_INTERFACES_OUTPUT = FIXTURE_PACKAGE_ROOT / "generated_interfaces.py"
FIXTURE_PROJECTIONS_OUTPUT = FIXTURE_PACKAGE_ROOT / "generated_projections.py"
_TYPING_UNION_ORIGIN: object = typing.Union  # pyright: ignore[reportDeprecated]


class ClientGenerationError(ValueError):
    """A declaration uses a feature the typed client surface cannot represent."""


@dataclass(frozen=True, slots=True)
class ClientSurface:
    """Non-structural inputs that a Python interface declaration cannot carry."""

    interface_type: type[object]
    acquisition_names: tuple[AcquisitionPublicNames, ...] = ()


@dataclass(frozen=True, slots=True)
class CompositeClientSurface:
    """One package-local client surface composed from several interfaces."""

    name: str
    interface_types: tuple[type[object], ...]
    driver_optional_flag: str | None = None
    member_name_overrides: tuple[tuple[Member[object], str], ...] = ()
    method_name_overrides: tuple[
        tuple[Callable[..., object] | MemberObservation, str], ...
    ] = ()
    acquisition_names: tuple[AcquisitionPublicNames, ...] = ()


type GenerationSurface = ClientSurface | CompositeClientSurface


def clients_for(
    interface_type: type[object],
    /,
    *,
    acquisition_names: tuple[AcquisitionPublicNames, ...] = (),
) -> ClientSurface:
    """Select one decorated interface for typed client generation."""

    return ClientSurface(
        interface_type=interface_type,
        acquisition_names=acquisition_names,
    )


def clients_for_composite(
    name: str,
    *interface_types: type[object],
    driver_optional_flag: str | None = None,
    member_name_overrides: tuple[tuple[Member[object], str], ...] = (),
    method_name_overrides: tuple[
        tuple[Callable[..., object] | MemberObservation, str], ...
    ] = (),
    acquisition_names: tuple[AcquisitionPublicNames, ...] = (),
) -> CompositeClientSurface:
    """Select one explicit package-local interface composition."""

    if not name.isidentifier():
        raise ClientGenerationError(f"composite name must be an identifier: {name!r}")
    if len(interface_types) < 2 or len(set(interface_types)) != len(interface_types):
        raise ClientGenerationError(
            "a composite surface requires at least two distinct interfaces"
        )
    return CompositeClientSurface(
        name=name,
        interface_types=interface_types,
        driver_optional_flag=driver_optional_flag,
        member_name_overrides=member_name_overrides,
        method_name_overrides=method_name_overrides,
        acquisition_names=acquisition_names,
    )


def _surface_interface_types(
    surfaces: tuple[GenerationSurface, ...],
) -> tuple[type[object], ...]:
    """Flatten selected interfaces in declaration order without duplicates."""

    selected: list[type[object]] = []
    seen: set[type[object]] = set()
    for surface in surfaces:
        interface_types = (
            surface.interface_types
            if isinstance(surface, CompositeClientSurface)
            else (surface.interface_type,)
        )
        for interface_type in interface_types:
            if interface_type in seen:
                continue
            seen.add(interface_type)
            selected.append(interface_type)
    return tuple(selected)


def _composite_surfaces(
    surfaces: tuple[GenerationSurface, ...],
) -> tuple[CompositeClientSurface, ...]:
    return tuple(
        surface for surface in surfaces if isinstance(surface, CompositeClientSurface)
    )


@dataclass(frozen=True, slots=True)
class GenerationTarget:
    """One independently importable generated module and its declarations."""

    output: Path
    surfaces: tuple[GenerationSurface, ...]
    member_projection_module: str


@dataclass(frozen=True, slots=True)
class CatalogTarget:
    """Public projections generated from a closed set of declared interfaces."""

    members_output: Path
    interfaces_output: Path
    projections_output: Path
    members_module: str
    interface_types: tuple[type[object], ...]
    driver_observations_output: Path | None = None
    composite_surfaces: tuple[CompositeClientSurface, ...] = ()
    public_types: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageExportsTarget:
    """Lazy package exports derived from clients and member projections."""

    output: Path
    client_target: GenerationTarget
    catalog_target: CatalogTarget
    client_module: str
    projections_module: str
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
    fixtures: bool = True
    manifest: str = "scopecat_instruments.package_manifest:PACKAGE_MANIFEST"
    output_root: Path = INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments"
    package_module: str = "scopecat_instruments"


class _FixtureDeclarations(Protocol):
    CatalogProjectionInterface: type[object]
    DriverFixedAcquisitionInterface: type[object]
    DriverMonitorInterface: type[object]
    DriverSourceInterface: type[object]
    LiteralOperationInterface: type[object]
    PayloadOperationInterface: type[object]
    ScalarOperationInterface: type[object]
    SharedPropertyFirstInterface: type[object]
    SharedPropertySecondInterface: type[object]


def _manifest_surface(registration: SurfaceRegistration, /) -> GenerationSurface:
    if isinstance(registration, CompositeSurfaceRegistration):
        return clients_for_composite(
            registration.name,
            *registration.interface_types,
            driver_optional_flag=registration.driver_optional_flag,
            member_name_overrides=registration.member_name_overrides,
            method_name_overrides=registration.method_name_overrides,
            acquisition_names=registration.acquisition_names,
        )
    return clients_for(
        registration.interface_type,
        acquisition_names=registration.acquisition_names,
    )


@dataclass(frozen=True, slots=True)
class PackageGenerationTargets:
    client: GenerationTarget
    catalog: CatalogTarget
    exports: PackageExportsTarget


def package_generation_targets(
    manifest: InstrumentPackageManifest,
    /,
    *,
    package_module: str,
    output_root: Path,
) -> PackageGenerationTargets:
    """Build generated module targets for one instrument package manifest."""

    if not package_module or any(
        not segment.isidentifier() for segment in package_module.split(".")
    ):
        raise ValueError(f"invalid generated package module {package_module!r}")
    surfaces = tuple(
        _manifest_surface(registration) for registration in manifest.surfaces
    )
    client = GenerationTarget(
        output=output_root / "clients.py",
        surfaces=surfaces,
        member_projection_module=f"{package_module}.projections",
    )
    catalog = CatalogTarget(
        members_output=output_root / "members.py",
        interfaces_output=output_root / "interfaces.py",
        projections_output=output_root / "projections.py",
        members_module=f"{package_module}.members",
        interface_types=_surface_interface_types(surfaces),
        driver_observations_output=output_root / "driver_observations.py",
        composite_surfaces=_composite_surfaces(surfaces),
        public_types=manifest.public_types,
    )
    exports = PackageExportsTarget(
        output=output_root / "__init__.py",
        client_target=client,
        catalog_target=catalog,
        client_module=f"{package_module}.clients",
        projections_module=f"{package_module}.projections",
        static_exports=manifest.static_exports,
    )
    return PackageGenerationTargets(client=client, catalog=catalog, exports=exports)


_PRODUCTION_TARGETS = package_generation_targets(
    PACKAGE_MANIFEST,
    package_module="scopecat_instruments",
    output_root=INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments",
)
PRODUCTION_TARGET = _PRODUCTION_TARGETS.client
PRODUCTION_CATALOG_TARGET = _PRODUCTION_TARGETS.catalog
PRODUCTION_PACKAGE_EXPORTS_TARGET = _PRODUCTION_TARGETS.exports


def _fixture_catalog_target() -> CatalogTarget:
    declarations = _fixture_declarations()
    catalog_surfaces = _fixture_catalog_surfaces(declarations)
    return CatalogTarget(
        members_output=FIXTURE_MEMBERS_OUTPUT,
        interfaces_output=FIXTURE_INTERFACES_OUTPUT,
        projections_output=FIXTURE_PROJECTIONS_OUTPUT,
        members_module=f"{FIXTURE_MODULE}.generated_members",
        interface_types=(
            declarations.CatalogProjectionInterface,
            declarations.SharedPropertyFirstInterface,
            declarations.SharedPropertySecondInterface,
            *_surface_interface_types(catalog_surfaces),
        ),
        composite_surfaces=_composite_surfaces(catalog_surfaces),
    )


def _fixture_catalog_surfaces(
    declarations: _FixtureDeclarations,
) -> tuple[GenerationSurface, ...]:
    return (
        clients_for(declarations.ScalarOperationInterface),
        clients_for(declarations.LiteralOperationInterface),
        clients_for(declarations.PayloadOperationInterface),
        clients_for(declarations.DriverFixedAcquisitionInterface),
        clients_for(declarations.DriverSourceInterface),
        clients_for_composite(
            "MonitorComposite",
            declarations.DriverSourceInterface,
            declarations.DriverMonitorInterface,
            driver_optional_flag="monitor",
            member_name_overrides=(
                (
                    _fixture_member(declarations.DriverSourceInterface, "enabled"),
                    "source_enabled",
                ),
                (
                    _fixture_member(declarations.DriverMonitorInterface, "enabled"),
                    "monitor_enabled",
                ),
            ),
        ),
    )


def _fixture_member(interface_type: type[object], name: str) -> Member[object]:
    return cast("Member[object]", getattr(interface_type, name))


def _fixture_declarations() -> _FixtureDeclarations:
    return cast(
        "_FixtureDeclarations",
        cast("object", import_module(f"{FIXTURE_MODULE}.declarations")),
    )


def _generation_targets(
    targets: PackageGenerationTargets = _PRODUCTION_TARGETS,
) -> tuple[GenerationTarget, ...]:
    return (targets.client,)


def _catalog_targets(
    targets: PackageGenerationTargets = _PRODUCTION_TARGETS,
    *,
    fixtures: bool = True,
) -> tuple[CatalogTarget, ...]:
    if fixtures:
        return (targets.catalog, _fixture_catalog_target())
    return (targets.catalog,)


def _package_exports_targets(
    targets: PackageGenerationTargets = _PRODUCTION_TARGETS,
) -> tuple[PackageExportsTarget, ...]:
    return (targets.exports,)


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


_SCALAR_PRODUCT_ANNOTATIONS: dict[MeasurementDType, str] = {
    "bool": "bool",
    "int64": "int",
    "float64": "float",
    "complex128": "complex",
    "string": "str",
}


@dataclass(frozen=True, slots=True)
class _AcquisitionResultModel:
    python_name: str
    spec: AcquisitionResultSpec
    annotation: object

    @property
    def product_value_annotation(self) -> str:
        """Return the native value available at one logical product point."""

        if self.spec.axes:
            return "MeasurementArrayData"
        return _SCALAR_PRODUCT_ANNOTATIONS[self.spec.dtype]


@dataclass(frozen=True, slots=True)
class _AcquisitionModel:
    method_name: str
    descriptor_name: str
    result_type_name: str
    result_fields: tuple[_AcquisitionResultModel, ...]
    readback_name: str
    products_name: str

    @property
    def result_field_names(self) -> tuple[str, ...]:
        return tuple(field.python_name for field in self.result_fields)

    @property
    def result_field_signature(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (field.python_name, field.product_value_annotation)
            for field in self.result_fields
        )


@dataclass(frozen=True, slots=True)
class _ScopeModel:
    class_stem: str
    operations: tuple[_OperationModel, ...]
    acquisitions: tuple[_AcquisitionModel, ...]

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
class _ProjectionKeywordFieldModel:
    python_name: str
    concrete_annotation: str
    symbolic_annotation: str
    group_annotation: str
    ref_expression: str
    member_name: str


@dataclass(frozen=True, slots=True)
class _ProjectionKeywordModel:
    patch_type_name: str
    target_type_name: str
    group_target_type_name: str
    fields: tuple[_ProjectionKeywordFieldModel, ...]
    projection_factory: bool


@dataclass(frozen=True, slots=True)
class _MemberClientModel:
    python_name: str
    annotation: str
    ref_name: str
    property_id: str
    value_type_json: str
    writable: bool
    readable: bool


@dataclass(frozen=True, slots=True)
class _InterfaceConstituentModel:
    interface_identity: str
    interface_id: str
    interface_stem: str
    constant_prefix: str
    layout: DeclaredInterfaceLayout[object]
    members: tuple[_MemberClientModel, ...]

    @property
    def ref_name(self) -> str:
        return f"_{self.constant_prefix}_REF"


@dataclass(frozen=True, slots=True)
class _InterfaceModel:
    interface_identity: str
    stem: str
    factory_name: str
    generate_family: bool
    live_projection_type_name: str | None
    symbolic_projection_type_name: str | None
    group_projection_type_name: str | None
    keyword_projection: _ProjectionKeywordModel | None
    constituents: tuple[_InterfaceConstituentModel, ...]
    root: _ScopeModel

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


@dataclass(frozen=True, slots=True)
class _CatalogInterfaceModel:
    interface_type: type[object]
    interface_identity: str
    interface_type_name: str
    constant_prefix: str
    factory_name: str
    spec: InterfaceSpec
    root: DeclaredScopeLayout
    properties: DeclaredPropertyLayout | None


@dataclass(frozen=True, slots=True)
class _MemberProjectionNames:
    patch: str
    target: str
    group_target: str


def _member_projection_names(
    interface_stem: str,
) -> _MemberProjectionNames:
    return _MemberProjectionNames(
        patch=f"{interface_stem}Patch",
        target=f"{interface_stem}Target",
        group_target=f"{interface_stem}GroupTarget",
    )


def _register_member_projection_types(
    renderer: _AnnotationRenderer,
    properties: DeclaredPropertyLayout | None,
    *,
    interface_stem: str,
    member_projection_module: str,
) -> _MemberProjectionNames | None:
    if properties is None or not _layout_has_writable_properties(properties):
        return None
    names = _member_projection_names(interface_stem)
    renderer.imports.setdefault(member_projection_module, set()).update(
        (names.patch, names.target, names.group_target)
    )
    return names


def _projection_keyword_model(
    properties: DeclaredPropertyLayout | None,
    *,
    interface_stem: str,
    renderer: _AnnotationRenderer,
) -> _ProjectionKeywordModel | None:
    """Describe the keyword surface for one interface's writable properties."""

    if properties is None:
        return None
    writable_fields = _writable_properties(properties)
    if not writable_fields:
        return None
    names = _member_projection_names(interface_stem)
    fields: list[_ProjectionKeywordFieldModel] = []
    for field in writable_fields:
        concrete = renderer.render(field.annotation)
        symbolic = _symbolic_annotation(concrete)
        fields.append(
            _ProjectionKeywordFieldModel(
                python_name=field.python_name,
                concrete_annotation=concrete,
                symbolic_annotation=symbolic,
                group_annotation=f"{symbolic} | PerEntity[{symbolic}]",
                ref_expression=(
                    f"_{_snake_case(interface_stem).upper()}_REF.property("
                    f"{_string_literal(field.ref.property_id)})"
                ),
                member_name=_member_constant_name(
                    _snake_case(interface_stem).upper(),
                    field.ref,
                ),
            )
        )
    return _ProjectionKeywordModel(
        patch_type_name=names.patch,
        target_type_name=names.target,
        group_target_type_name=names.group_target,
        fields=tuple(fields),
        projection_factory=True,
    )


def _composite_projection_keyword_model(
    constituents: tuple[_InterfaceConstituentModel, ...],
    *,
    composite_stem: str,
) -> _ProjectionKeywordModel | None:
    fields: list[_ProjectionKeywordFieldModel] = []
    for constituent in constituents:
        for member in constituent.members:
            if not member.writable:
                continue
            symbolic = _symbolic_annotation(member.annotation)
            fields.append(
                _ProjectionKeywordFieldModel(
                    python_name=member.python_name,
                    concrete_annotation=member.annotation,
                    symbolic_annotation=symbolic,
                    group_annotation=f"{symbolic} | PerEntity[{symbolic}]",
                    ref_expression=(
                        f"{member.ref_name}.property("
                        f"{_string_literal(member.property_id)})"
                    ),
                    member_name=_join_constant_name(
                        constituent.constant_prefix,
                        member.property_id,
                    ),
                )
            )
    if not fields:
        return None
    return _ProjectionKeywordModel(
        patch_type_name=f"{composite_stem}Patch",
        target_type_name=f"{composite_stem}Target",
        group_target_type_name=f"{composite_stem}GroupTarget",
        fields=tuple(fields),
        projection_factory=True,
    )


def _symbolic_annotation(concrete: str) -> str:
    return f"Symbolic[{concrete}]"


def _writable_properties(
    layout: DeclaredPropertyLayout,
) -> tuple[DeclaredProperty, ...]:
    return tuple(field for field in layout.fields if field.spec.access != "read_only")


def _layout_has_writable_properties(layout: DeclaredPropertyLayout) -> bool:
    return bool(_writable_properties(layout))


@dataclass(frozen=True, slots=True)
class _MemberIdentity:
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
    local_package = target.members_module.partition(".")[0]
    rendered: list[tuple[Path, str]] = [
        (
            target.members_output,
            _render_members_module(models, local_package=local_package),
        ),
        (
            target.interfaces_output,
            _render_interfaces_module(models, local_package=local_package),
        ),
        (
            target.projections_output,
            _render_projections_module(
                models,
                composite_surfaces=target.composite_surfaces,
                declaration_cache=cache,
                public_types=target.public_types,
                members_module=target.members_module,
                local_package=local_package,
            ),
        ),
    ]
    if target.driver_observations_output is not None:
        rendered.append(
            (
                target.driver_observations_output,
                _render_driver_observations_module(
                    models,
                    local_package=local_package,
                ),
            )
        )
    return tuple(rendered)


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
                properties=layout.properties,
            )
        )
    return tuple(models)


def _render_members_module(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    local_package: str,
) -> str:
    projections = tuple(
        projection
        for model in models
        for projection in _interface_member_identities(model)
    )
    _validate_member_identities(projections)
    imports: dict[str, set[str]] = {
        "scopecat.sdk.instruments": {"InterfaceRef"},
    }
    declarations = "".join(
        _render_member_identity(projection) for projection in projections
    )
    return (
        _generated_module_header(
            "Typed identities generated from the declared instrument interfaces."
        )
        + _render_import_block(imports, local_package=local_package)
        + "\n"
        + declarations
        + _render_all(tuple(projection.name for projection in projections))
    )


def _render_driver_observations_module(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    local_package: str,
) -> str:
    """Render measurement-valued carriers implemented by concrete drivers."""

    declarations: dict[str, tuple[tuple[str, ...], str]] = {}
    sections: list[str] = []
    for model in models:
        for acquisition in model.root.acquisitions:
            if acquisition.kind == "member_observation":
                continue
            name = f"{acquisition.result.type_name.removesuffix('Results')}Observation"
            field_names = tuple(
                field.python_name for field in acquisition.result_fields
            )
            owner = f"{model.interface_identity}.{acquisition.method_name}"
            existing = declarations.get(name)
            if existing is not None:
                existing_fields, existing_owner = existing
                if existing_fields != field_names:
                    raise ClientGenerationError(
                        f"generated driver observation collision {name}: "
                        f"{existing_owner} vs {owner}"
                    )
                continue
            declarations[name] = (field_names, owner)
            fields_source = "".join(
                f"    {field_name}: MeasurementAcquisitionValue\n"
                for field_name in field_names
            )
            sections.append(
                "\n\n"
                "@dataclass(frozen=True, slots=True)\n"
                f"class {name}:\n"
                f'    """Measurement-valued {acquisition.method_name} observation."""\n'
                "\n"
                f"{fields_source}"
                "    evidence: dict[str, JsonValue] = field(default_factory=dict)\n"
            )
    imports = (
        {
            "dataclasses": {"dataclass", "field"},
            "pydantic": {"JsonValue"},
            "scopecat.records.measurement": {"MeasurementAcquisitionValue"},
        }
        if declarations
        else {}
    )
    if not declarations:
        return (
            _generated_module_header(
                "Measurement-valued observations generated for instrument drivers."
            ).rstrip()
            + "\n"
            + _render_all(())
        )
    return (
        _generated_module_header(
            "Measurement-valued observations generated for instrument drivers."
        )
        + _render_import_block(
            imports,
            local_package=local_package,
        )
        + "".join(sections)
        + "\n"
        + _render_all(tuple(declarations))
    )


def _interface_member_identities(
    model: _CatalogInterfaceModel,
) -> tuple[_MemberIdentity, ...]:
    root_name = model.constant_prefix
    projections = [
        _MemberIdentity(
            name=root_name,
            expression=f"InterfaceRef({_string_literal(model.root.ref.interface_id)})",
            owner=f"{model.interface_identity} interface",
        )
    ]
    _append_scope_member_identities(
        projections,
        model.root,
        scope_name=root_name,
        owner_prefix=model.interface_identity,
    )
    return tuple(projections)


def _append_scope_member_identities(
    projections: list[_MemberIdentity],
    scope: DeclaredScopeLayout,
    *,
    scope_name: str,
    owner_prefix: str,
) -> None:
    for property_spec in scope.spec.properties:
        name = _join_constant_name(scope_name, property_spec.id)
        projections.append(
            _MemberIdentity(
                name=name,
                expression=(
                    f"{scope_name}.property({_string_literal(property_spec.id)})"
                ),
                owner=f"{owner_prefix} property {property_spec.id}",
            )
        )
    for operation in scope.operations:
        operation_name = _join_constant_name(
            scope_name,
            operation.ref.operation_id,
        )
        projections.append(
            _MemberIdentity(
                name=operation_name,
                expression=(
                    f"{scope_name}.operation("
                    f"{_string_literal(operation.ref.operation_id)})"
                ),
                owner=(f"{owner_prefix} operation {operation.method_name}"),
            )
        )
        for argument in operation.arguments:
            argument_name = _join_constant_name(
                operation_name,
                argument.ref.argument_id,
            )
            projections.append(
                _MemberIdentity(
                    name=argument_name,
                    expression=(
                        f"{operation_name}.argument("
                        f"{_string_literal(argument.ref.argument_id)})"
                    ),
                    owner=(
                        f"{owner_prefix} operation "
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
            _MemberIdentity(
                name=acquisition_name,
                expression=(
                    f"{scope_name}.acquisition("
                    f"{_string_literal(acquisition.ref.acquisition_id)})"
                ),
                owner=(f"{owner_prefix} acquisition {acquisition.method_name}"),
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
                _MemberIdentity(
                    name=result_name,
                    expression=(
                        f"{acquisition_name}.result("
                        f"{_string_literal(result_field.result_id)})"
                    ),
                    owner=(
                        f"{owner_prefix} acquisition "
                        f"{acquisition.method_name} result {result_field.python_name}"
                    ),
                )
            )


def _validate_member_identities(
    projections: tuple[_MemberIdentity, ...],
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


def _render_member_identity(projection: _MemberIdentity) -> str:
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


def _render_interfaces_module(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    local_package: str,
) -> str:
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
        + _render_import_block(imports, local_package=local_package)
        + "\n"
        + "\n\n".join(declarations)
        + "\n"
        + _render_all(tuple(model.factory_name for model in models))
    )


def _writable_property_layouts(
    models: tuple[_CatalogInterfaceModel, ...],
) -> tuple[tuple[_CatalogInterfaceModel, DeclaredPropertyLayout], ...]:
    return tuple(
        (model, properties)
        for model in models
        if (properties := model.properties) is not None
        if _layout_has_writable_properties(properties)
    )


def _projection_export_owners(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    composite_projections: tuple[_ProjectionKeywordModel, ...],
    public_types: tuple[object, ...],
    projection_layouts: tuple[
        tuple[_CatalogInterfaceModel, DeclaredPropertyLayout], ...
    ],
) -> dict[str, str]:
    exports_by_name: dict[str, str] = {}
    for candidate in (
        *(
            model.properties.source_type
            for model in models
            if model.properties is not None
        ),
        *public_types,
    ):
        module, name = _public_type_location(candidate)
        owner = f"{module}.{name}"
        existing = exports_by_name.get(name)
        if existing is not None and existing != owner:
            raise ClientGenerationError(
                f"generated projection export collision {name}: {existing} vs {owner}"
            )
        exports_by_name[name] = owner

    for model, layout in projection_layouts:
        owner = f"{layout.source_type.__module__}.{layout.source_type.__qualname__}"
        names = _member_projection_names(
            model.interface_type_name.removesuffix("Interface"),
        )
        for name in (names.patch, names.target, names.group_target):
            existing = exports_by_name.get(name)
            if existing is not None:
                raise ClientGenerationError(
                    "generated projection export collision "
                    f"{name}: {existing} vs {owner}"
                )
            exports_by_name[name] = owner
    for projection in composite_projections:
        owner = f"composite:{projection.patch_type_name.removesuffix('Patch')}"
        for name in (
            projection.patch_type_name,
            projection.target_type_name,
            projection.group_target_type_name,
        ):
            existing = exports_by_name.get(name)
            if existing is not None:
                raise ClientGenerationError(
                    f"generated projection export collision {name}: "
                    f"{existing} vs {owner}"
                )
            exports_by_name[name] = owner
    return exports_by_name


def _catalog_composite_projection_models(
    surfaces: tuple[CompositeClientSurface, ...],
    *,
    renderer: _AnnotationRenderer,
    declaration_cache: _DeclarationCache,
) -> tuple[_ProjectionKeywordModel, ...]:
    projections: list[_ProjectionKeywordModel] = []
    for surface in surfaces:
        constituents = _composite_constituents(
            surface,
            renderer=renderer,
            declaration_cache=declaration_cache,
        )
        projection = _composite_projection_keyword_model(
            constituents,
            composite_stem=surface.name.removesuffix("Interface"),
        )
        if projection is not None:
            projections.append(projection)
    return tuple(projections)


def _render_projections_module(
    models: tuple[_CatalogInterfaceModel, ...],
    *,
    composite_surfaces: tuple[CompositeClientSurface, ...],
    declaration_cache: _DeclarationCache,
    public_types: tuple[object, ...],
    members_module: str,
    local_package: str,
) -> str:
    renderer = _AnnotationRenderer()
    imports: dict[str, set[str]] = {}
    declarations: list[str] = []
    member_imports: set[str] = set()
    projection_layouts = _writable_property_layouts(models)
    composite_projections = _catalog_composite_projection_models(
        composite_surfaces,
        renderer=renderer,
        declaration_cache=declaration_cache,
    )
    exports_by_name = _projection_export_owners(
        models,
        composite_projections=composite_projections,
        public_types=public_types,
        projection_layouts=projection_layouts,
    )

    for candidate in (
        *(
            model.properties.source_type
            for model in models
            if model.properties is not None
        ),
        *public_types,
    ):
        module, name = _public_type_location(candidate)
        imports.setdefault(module, set()).add(f"{name} as {name}")

    if projection_layouts or composite_projections:
        imports["scopecat.authoring"] = {"PerEntity", "Symbolic"}
        imports["scopecat.sdk.instruments.declarations"] = {
            "MemberProjectionField",
            "MemberProjectionLayout",
            "instrument_member_projection",
            "member_projection_field",
        }

    for model, layout in projection_layouts:
        names = _member_projection_names(
            model.interface_type_name.removesuffix("Interface"),
        )
        layout_expression = _member_projection_layout_name(names)
        declarations.append(
            _render_member_projection_layout(
                layout_expression,
                layout,
                constant_prefix=model.constant_prefix,
                member_imports=member_imports,
            )
        )
        declarations.extend(
            (
                _render_member_projection(
                    names.patch,
                    layout,
                    layout_expression=layout_expression,
                    renderer=renderer,
                    projection="live",
                ),
                _render_member_projection(
                    names.target,
                    layout,
                    layout_expression=layout_expression,
                    renderer=renderer,
                    projection="symbolic",
                ),
                _render_member_projection(
                    names.group_target,
                    layout,
                    layout_expression=layout_expression,
                    renderer=renderer,
                    projection="group",
                ),
            )
        )

    for projection in composite_projections:
        names = _MemberProjectionNames(
            projection.patch_type_name,
            projection.target_type_name,
            projection.group_target_type_name,
        )
        layout_expression = _member_projection_layout_name(names)
        declarations.append(
            _render_composite_projection_layout(
                layout_expression,
                projection,
                member_imports=member_imports,
            )
        )
        declarations.extend(
            (
                _render_composite_member_projection(
                    names.patch,
                    projection,
                    layout_expression=layout_expression,
                    projection="live",
                ),
                _render_composite_member_projection(
                    names.target,
                    projection,
                    layout_expression=layout_expression,
                    projection="symbolic",
                ),
                _render_composite_member_projection(
                    names.group_target,
                    projection,
                    layout_expression=layout_expression,
                    projection="group",
                ),
            )
        )

    for module, names in renderer.imports.items():
        imports.setdefault(module, set()).update(names)
    if member_imports:
        imports[members_module] = member_imports
    import_block = (
        _render_import_block(imports, local_package=local_package) if imports else ""
    )
    declaration_block = "".join(declarations)
    if import_block:
        declaration_block = declaration_block.removeprefix("\n")
    return (
        _generated_module_header(
            "Typed member projections generated from instrument interfaces."
        )
        + import_block
        + declaration_block
        + ("\n" if declarations else "")
        + _render_all(tuple(exports_by_name))
    )


def _member_projection_layout_name(names: _MemberProjectionNames) -> str:
    stem = names.patch.removesuffix("Patch")
    return f"_{_snake_case(stem).upper()}_MEMBER_LAYOUT"


def _member_constant_name(constant_prefix: str, ref: PropertyRef) -> str:
    return _join_constant_name(constant_prefix, ref.property_id)


def _render_member_projection_layout(
    name: str,
    layout: DeclaredPropertyLayout,
    *,
    constant_prefix: str,
    member_imports: set[str],
) -> str:
    fields: list[str] = []
    for field in _writable_properties(layout):
        member_name = _member_constant_name(constant_prefix, field.ref)
        member_imports.add(member_name)
        fields.append(
            "MemberProjectionField("
            f"{_string_literal(field.python_name)}, {member_name})"
        )

    return (
        f"\n\n{name} = MemberProjectionLayout(\n"
        + _render_layout_argument("fields", fields)
        + ")\n"
    )


def _render_composite_projection_layout(
    name: str,
    projection: _ProjectionKeywordModel,
    *,
    member_imports: set[str],
) -> str:
    fields: list[str] = []
    for field in projection.fields:
        member_imports.add(field.member_name)
        fields.append(
            "MemberProjectionField("
            f"{_string_literal(field.python_name)}, {field.member_name})"
        )
    return (
        f"\n\n{name} = MemberProjectionLayout(\n"
        + _render_layout_argument("fields", fields)
        + ")\n"
    )


def _render_layout_argument(name: str, values: list[str]) -> str:
    compact_tuple = f"({', '.join(values)}{',' if len(values) == 1 else ''})"
    compact = f"    {name}={compact_tuple},\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return (
        f"    {name}=(\n"
        + "".join(f"        {value},\n" for value in values)
        + "    ),\n"
    )


def _render_member_projection(
    name: str,
    layout: DeclaredPropertyLayout,
    *,
    layout_expression: str,
    renderer: _AnnotationRenderer,
    projection: str,
) -> str:
    fields: list[str] = []
    for declared_field in _writable_properties(layout):
        concrete = renderer.render(declared_field.annotation)
        if projection == "live":
            annotation = concrete
        elif projection == "symbolic":
            annotation = _symbolic_annotation(concrete)
        elif projection == "group":
            symbolic = _symbolic_annotation(concrete)
            annotation = f"{symbolic} | PerEntity[{symbolic}]"
        else:
            raise AssertionError(f"unknown member projection {projection!r}")
        fields.append(
            _render_member_projection_field(
                declared_field.python_name,
                annotation,
                required=False,
            )
        )
    body = "".join(fields) or "    pass\n"
    return (
        f"\n\n@instrument_member_projection({layout_expression})\nclass {name}:\n{body}"
    )


def _render_composite_member_projection(
    name: str,
    model: _ProjectionKeywordModel,
    *,
    layout_expression: str,
    projection: str,
) -> str:
    fields: list[str] = []
    for field in model.fields:
        if projection == "live":
            annotation = field.concrete_annotation
        elif projection == "symbolic":
            annotation = field.symbolic_annotation
        elif projection == "group":
            annotation = field.group_annotation
        else:
            raise AssertionError(f"unknown member projection {projection!r}")
        fields.append(
            _render_member_projection_field(
                field.python_name,
                annotation,
                required=False,
            )
        )
    body = "".join(fields) or "    pass\n"
    return (
        f"\n\n@instrument_member_projection({layout_expression})\nclass {name}:\n{body}"
    )


def _render_member_projection_field(
    name: str,
    annotation: str,
    *,
    required: bool,
) -> str:
    default = "" if required else " = member_projection_field()"
    compact = f"    {name}: {annotation}{default}\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    if not required:
        wrapped_default = f"    {name}: {annotation} = (\n"
        if len(wrapped_default.rstrip("\n")) <= 88:
            return wrapped_default + "        member_projection_field()\n    )\n"

    branches = _split_top_level_union(annotation)
    if len(branches) == 1:
        return compact
    lines = [f"    {name}: (\n", f"        {branches[0]}\n"]
    lines.extend(f"        | {branch}\n" for branch in branches[1:])
    lines.append("    )")
    if not required:
        lines.append(" = member_projection_field()")
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
        member_projection_module=target.member_projection_module,
        declaration_cache=declaration_cache,
    )


def render_client_module(
    surfaces: tuple[GenerationSurface, ...],
    *,
    member_projection_module: str,
    declaration_cache: _DeclarationCache | None = None,
) -> str:
    """Render an independently importable module for selected declarations."""

    renderer = _AnnotationRenderer()
    cache = declaration_cache or _DeclarationCache()
    models = _client_models(
        surfaces,
        renderer=renderer,
        member_projection_module=member_projection_module,
        declaration_cache=cache,
    )
    local_package = member_projection_module.partition(".")[0]

    sections = [
        _render_header(
            models,
            renderer=renderer,
            local_package=local_package,
        ),
        _render_interface_refs(models),
        _render_descriptors(models),
    ]
    rendered_result_types: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
    for model in models:
        sections.extend(
            (
                _render_result_types(model, rendered=rendered_result_types),
                _render_live_scopes(model),
                _render_symbolic_scopes(model),
                _render_symbolic_group_scopes(model),
                _render_family(model),
            )
        )
    sections.append(_render_exports(models))
    return "".join(sections)


def _client_models(
    surfaces: tuple[GenerationSurface, ...],
    *,
    renderer: _AnnotationRenderer,
    member_projection_module: str,
    declaration_cache: _DeclarationCache,
) -> tuple[_InterfaceModel, ...]:
    models = tuple(
        _generation_model(
            surface,
            renderer=renderer,
            member_projection_module=member_projection_module,
            declaration_cache=declaration_cache,
        )
        for surface in surfaces
    )
    if not models:
        raise ClientGenerationError("a generated client module requires a declaration")
    _validate_generated_symbols(models)
    return models


def render_package_exports_target(
    target: PackageExportsTarget,
    *,
    declaration_cache: _DeclarationCache | None = None,
) -> str:
    """Render static package export routes without importing generated modules."""

    cache = declaration_cache or _DeclarationCache()
    client_models = _client_models(
        target.client_target.surfaces,
        renderer=_AnnotationRenderer(),
        member_projection_module=target.client_target.member_projection_module,
        declaration_cache=cache,
    )
    catalog_models = _catalog_models(
        target.catalog_target.interface_types,
        declaration_cache=cache,
    )
    projection_layouts = _writable_property_layouts(catalog_models)
    composite_projections = _catalog_composite_projection_models(
        target.catalog_target.composite_surfaces,
        renderer=_AnnotationRenderer(),
        declaration_cache=cache,
    )
    state_exports = _projection_export_owners(
        catalog_models,
        composite_projections=composite_projections,
        public_types=target.catalog_target.public_types,
        projection_layouts=projection_layouts,
    )

    routes: dict[str, str] = {}
    for name, module in target.static_exports:
        _register_package_export(routes, name=name, module=module)
    for name in _client_export_names(client_models):
        _register_package_export(routes, name=name, module=target.client_module)
    for name in state_exports:
        _register_package_export(routes, name=name, module=target.projections_module)
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
    member_projection_module: str,
    declaration_cache: _DeclarationCache,
) -> _InterfaceModel:
    if isinstance(surface, CompositeClientSurface):
        return _composite_model(
            surface,
            renderer=renderer,
            member_projection_module=member_projection_module,
            declaration_cache=declaration_cache,
        )
    return _interface_model(
        surface,
        renderer=renderer,
        member_projection_module=member_projection_module,
        generate_family=True,
        declaration_cache=declaration_cache,
    )


def _interface_model(
    surface: ClientSurface,
    *,
    renderer: _AnnotationRenderer,
    member_projection_module: str,
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
    acquisition_names = _acquisition_public_names(
        surface_name=stem,
        interface_types=(surface.interface_type,),
        constituents=(constituent,),
        declarations=surface.acquisition_names,
    )
    root = _scope_model(
        layout.root,
        interface_stem=stem,
        constant_prefix=constituent.constant_prefix,
        acquisition_names={
            method_name: names
            for (owner, method_name), names in acquisition_names.items()
            if owner is surface.interface_type
        },
        renderer=renderer,
    )
    projection_names = _register_member_projection_types(
        renderer,
        layout.properties,
        interface_stem=stem,
        member_projection_module=member_projection_module,
    )
    return _InterfaceModel(
        interface_identity=(
            f"{surface.interface_type.__module__}.{surface.interface_type.__qualname__}"
        ),
        stem=stem,
        factory_name=_snake_case(stem),
        generate_family=generate_family,
        live_projection_type_name=(
            None if projection_names is None else projection_names.patch
        ),
        symbolic_projection_type_name=(
            None if projection_names is None else projection_names.target
        ),
        group_projection_type_name=(
            None if projection_names is None else projection_names.group_target
        ),
        keyword_projection=_projection_keyword_model(
            layout.properties,
            interface_stem=stem,
            renderer=renderer,
        ),
        constituents=(constituent,),
        root=root,
    )


def _composite_model(
    surface: CompositeClientSurface,
    *,
    renderer: _AnnotationRenderer,
    member_projection_module: str,
    declaration_cache: _DeclarationCache,
) -> _InterfaceModel:
    composite_identity = "composite:" + surface.name
    constituents = _composite_constituents(
        surface,
        renderer=renderer,
        declaration_cache=declaration_cache,
    )
    method_name_overrides = _composite_method_name_overrides(surface, constituents)
    acquisition_names = _acquisition_public_names(
        surface_name=surface.name,
        interface_types=surface.interface_types,
        constituents=constituents,
        declarations=surface.acquisition_names,
    )

    stem = surface.name.removesuffix("Interface")
    scopes = tuple(
        _scope_model(
            constituent.layout.root,
            interface_stem=stem,
            constant_prefix=constituent.constant_prefix,
            acquisition_names={
                method_name: names
                for (owner, method_name), names in acquisition_names.items()
                if owner is interface_type
            },
            method_name_overrides={
                method_name: public_name
                for (owner, method_name), public_name in method_name_overrides.items()
                if owner is interface_type
            },
            renderer=renderer,
        )
        for interface_type, constituent in zip(
            surface.interface_types,
            constituents,
            strict=True,
        )
    )
    _validate_composite_client_names(surface, constituents, scopes)
    root = _ScopeModel(
        class_stem=stem,
        operations=tuple(
            operation for scope in scopes for operation in scope.operations
        ),
        acquisitions=tuple(
            acquisition for scope in scopes for acquisition in scope.acquisitions
        ),
    )
    keyword_projection = _composite_projection_keyword_model(
        constituents,
        composite_stem=stem,
    )
    projection_names = None
    if keyword_projection is not None:
        projection_names = _member_projection_names(stem)
    if projection_names is not None:
        renderer.imports.setdefault(member_projection_module, set()).update(
            (
                projection_names.patch,
                projection_names.target,
                projection_names.group_target,
            )
        )
    return _InterfaceModel(
        interface_identity=composite_identity,
        stem=stem,
        factory_name=_snake_case(stem),
        generate_family=True,
        live_projection_type_name=(
            None if projection_names is None else projection_names.patch
        ),
        symbolic_projection_type_name=(
            None if projection_names is None else projection_names.target
        ),
        group_projection_type_name=(
            None if projection_names is None else projection_names.group_target
        ),
        keyword_projection=keyword_projection,
        constituents=constituents,
        root=root,
    )


def _constituent_model(
    interface_type: type[object],
    *,
    renderer: _AnnotationRenderer,
    declaration_cache: _DeclarationCache,
    member_name_overrides: dict[str, str] | None = None,
) -> _InterfaceConstituentModel:
    layout = declaration_cache.layout(interface_type)
    interface_name = interface_type.__name__
    interface_stem = interface_name.removesuffix("Interface")
    members = tuple(
        _MemberClientModel(
            python_name=(
                field.python_name
                if member_name_overrides is None
                else member_name_overrides.get(field.property_id, field.python_name)
            ),
            annotation=renderer.render(field.annotation),
            ref_name=f"_{_snake_case(interface_stem).upper()}_REF",
            property_id=field.property_id,
            value_type_json=_json_model_field(
                field.spec.model_dump_json(),
                "value_type",
            ),
            writable=field.spec.access != "read_only",
            readable=field.spec.access != "write_only",
        )
        for field in (() if layout.properties is None else layout.properties.fields)
    )
    return _InterfaceConstituentModel(
        interface_identity=f"{interface_type.__module__}.{interface_type.__qualname__}",
        interface_id=layout.compiled.ref.interface_id,
        interface_stem=interface_stem,
        constant_prefix=_snake_case(interface_stem).upper(),
        layout=layout,
        members=members,
    )


def _composite_constituents(
    surface: CompositeClientSurface,
    *,
    renderer: _AnnotationRenderer,
    declaration_cache: _DeclarationCache,
) -> tuple[_InterfaceConstituentModel, ...]:
    overrides: dict[tuple[type[object], str], str] = {}
    for member, public_name in surface.member_name_overrides:
        if (
            member.owner is None
            or member.python_name is None
            or member.owner not in surface.interface_types
        ):
            raise ClientGenerationError(
                f"composite {surface.name} member name override must reference "
                "a member declared by one of its constituent interfaces"
            )
        if not public_name.isidentifier() or keyword.iskeyword(public_name):
            raise ClientGenerationError(
                f"composite {surface.name} member name override must be a Python "
                f"identifier: {public_name!r}"
            )
        property_id = member.metadata.id or member.python_name
        key = (member.owner, property_id)
        if key in overrides:
            raise ClientGenerationError(
                f"composite {surface.name} repeats a member name override for "
                f"{member.owner.__qualname__}.{property_id}"
            )
        overrides[key] = public_name

    constituents = tuple(
        _constituent_model(
            interface_type,
            renderer=renderer,
            declaration_cache=declaration_cache,
            member_name_overrides={
                property_id: public_name
                for (owner, property_id), public_name in overrides.items()
                if owner is interface_type
            },
        )
        for interface_type in surface.interface_types
    )
    available = {
        (interface_type, member.property_id)
        for interface_type, constituent in zip(
            surface.interface_types,
            constituents,
            strict=True,
        )
        for member in constituent.members
    }
    unknown = overrides.keys() - available
    if unknown:
        owner, property_id = next(iter(unknown))
        raise ClientGenerationError(
            f"composite {surface.name} member name override does not match a "
            f"declared property: {owner.__qualname__}.{property_id}"
        )

    owners_by_name: dict[str, str] = {}
    for constituent in constituents:
        for member in constituent.members:
            owner = f"{constituent.interface_identity}.{member.property_id}"
            existing = owners_by_name.get(member.python_name)
            if existing is not None:
                raise ClientGenerationError(
                    f"composite {surface.name} member name collision "
                    f"{member.python_name!r}: {existing} vs {owner}; assign a "
                    "distinct public name with member_name_overrides"
                )
            owners_by_name[member.python_name] = owner
    return constituents


def _composite_method_name_overrides(
    surface: CompositeClientSurface,
    constituents: tuple[_InterfaceConstituentModel, ...],
) -> dict[tuple[type[object], str], str]:
    targets: dict[object, list[tuple[type[object], str]]] = {}
    for interface_type, constituent in zip(
        surface.interface_types,
        constituents,
        strict=True,
    ):
        declared_method_names = tuple(
            operation.method_name for operation in constituent.layout.root.operations
        ) + tuple(
            acquisition.method_name
            for acquisition in constituent.layout.root.acquisitions
        )
        for method_name in declared_method_names:
            method = cast("object", getattr(interface_type, method_name))
            targets.setdefault(method, []).append((interface_type, method_name))

    overrides: dict[tuple[type[object], str], str] = {}
    for method, public_name in surface.method_name_overrides:
        matches = targets.get(method, [])
        if len(matches) != 1:
            raise ClientGenerationError(
                f"composite {surface.name} method name override must reference "
                "one operation or acquisition declared by a constituent interface"
            )
        if not public_name.isidentifier() or keyword.iskeyword(public_name):
            raise ClientGenerationError(
                f"composite {surface.name} method name override must be a Python "
                f"identifier: {public_name!r}"
            )
        [target] = matches
        if target in overrides:
            owner, method_name = target
            raise ClientGenerationError(
                f"composite {surface.name} repeats a method name override for "
                f"{owner.__qualname__}.{method_name}"
            )
        overrides[target] = public_name
    return overrides


def _acquisition_public_names(
    *,
    surface_name: str,
    interface_types: tuple[type[object], ...],
    constituents: tuple[_InterfaceConstituentModel, ...],
    declarations: tuple[AcquisitionPublicNames, ...],
) -> dict[tuple[type[object], str], AcquisitionPublicNames]:
    targets: dict[object, list[tuple[type[object], str]]] = {}
    for interface_type, constituent in zip(
        interface_types,
        constituents,
        strict=True,
    ):
        for acquisition in constituent.layout.root.acquisitions:
            method = cast("object", getattr(interface_type, acquisition.method_name))
            targets.setdefault(method, []).append(
                (interface_type, acquisition.method_name)
            )

    resolved: dict[tuple[type[object], str], AcquisitionPublicNames] = {}
    for names in declarations:
        matches = targets.get(names.acquisition, [])
        if len(matches) != 1:
            raise ClientGenerationError(
                f"surface {surface_name} acquisition names must reference one "
                "acquisition declared by the selected interface surface"
            )
        if names.readback is None and names.products is None:
            raise ClientGenerationError(
                f"surface {surface_name} acquisition names must specify readback "
                "or products"
            )
        for public_name in (names.readback, names.products):
            if public_name is not None and (
                not public_name.isidentifier() or keyword.iskeyword(public_name)
            ):
                raise ClientGenerationError(
                    f"surface {surface_name} acquisition public name must be a "
                    f"Python identifier: {public_name!r}"
                )
        [target] = matches
        if target in resolved:
            owner, method_name = target
            raise ClientGenerationError(
                f"surface {surface_name} repeats acquisition names for "
                f"{owner.__qualname__}.{method_name}"
            )
        resolved[target] = names
    return resolved


def _validate_composite_client_names(
    surface: CompositeClientSurface,
    constituents: tuple[_InterfaceConstituentModel, ...],
    scopes: tuple[_ScopeModel, ...],
) -> None:
    owners_by_name: dict[str, list[str]] = {}
    for constituent, scope in zip(constituents, scopes, strict=True):
        for member in constituent.members:
            owners_by_name.setdefault(member.python_name, []).append(
                f"{constituent.interface_identity} property {member.property_id}"
            )
        for declared, operation in zip(
            constituent.layout.root.operations,
            scope.operations,
            strict=True,
        ):
            owners_by_name.setdefault(operation.method_name, []).append(
                f"{constituent.interface_identity} operation {declared.method_name}"
            )
        for declared, acquisition in zip(
            constituent.layout.root.acquisitions,
            scope.acquisitions,
            strict=True,
        ):
            owners_by_name.setdefault(acquisition.method_name, []).append(
                f"{constituent.interface_identity} acquisition {declared.method_name}"
            )
    collisions = {
        name: owners for name, owners in owners_by_name.items() if len(owners) > 1
    }
    if not collisions:
        return
    details = "; ".join(
        f"{name}: {' vs '.join(owners)}" for name, owners in sorted(collisions.items())
    )
    raise ClientGenerationError(
        f"composite {surface.name} client name collisions: {details}; assign "
        "distinct public names with member_name_overrides or method_name_overrides"
    )


def _validate_generated_symbols(
    models: tuple[_InterfaceModel, ...],
) -> None:
    owners_by_symbol: dict[str, list[str]] = {}

    def register(symbol: str, owner: str) -> None:
        owners = owners_by_symbol.setdefault(symbol, [])
        if owner not in owners:
            owners.append(owner)

    for constituent in _unique_constituents(models):
        declaration = constituent.interface_identity
        register(constituent.ref_name, f"{declaration} interface ref")
        for operation in constituent.layout.root.operations:
            register(
                _descriptor_name(
                    constituent.constant_prefix,
                    operation.method_name,
                ),
                f"{declaration} operation {operation.method_name}",
            )
        for acquisition in constituent.layout.root.acquisitions:
            register(
                _descriptor_name(
                    constituent.constant_prefix,
                    acquisition.method_name,
                ),
                f"{declaration} acquisition {acquisition.method_name}",
            )

    for model in models:
        declaration = model.interface_identity
        for type_name, projection in (
            (
                model.live_projection_type_name,
                "live patch",
            ),
            (
                model.symbolic_projection_type_name,
                "symbolic target",
            ),
            (
                model.group_projection_type_name,
                "group target",
            ),
        ):
            if type_name is not None:
                register(type_name, f"{declaration} imported {projection}")
        if model.generate_family:
            register(model.factory_name, f"{declaration} factory")
        scope = model.root
        register(scope.live_client_name, f"{declaration} live client")
        register(scope.symbolic_client_name, f"{declaration} symbolic client")
        register(scope.symbolic_group_name, f"{declaration} symbolic group")
        for acquisition in scope.acquisitions:
            result_owner = (
                f"{acquisition.descriptor_name} results {acquisition.result_type_name}"
            )
            register(
                acquisition.readback_name,
                f"{result_owner} live",
            )
            register(
                acquisition.products_name,
                f"{result_owner} symbolic",
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
    acquisition_names: dict[str, AcquisitionPublicNames],
    renderer: _AnnotationRenderer,
    method_name_overrides: dict[str, str] | None = None,
) -> _ScopeModel:
    operations = tuple(
        _operation_model(
            operation,
            constant_prefix=constant_prefix,
            renderer=renderer,
            public_name=(
                None
                if method_name_overrides is None
                else method_name_overrides.get(operation.method_name)
            ),
        )
        for operation in scope.operations
    )
    acquisitions = tuple(
        _acquisition_model(
            acquisition,
            constant_prefix=constant_prefix,
            public_names=acquisition_names.get(acquisition.method_name),
            public_name=(
                None
                if method_name_overrides is None
                else method_name_overrides.get(acquisition.method_name)
            ),
        )
        for acquisition in scope.acquisitions
    )
    return _ScopeModel(
        class_stem=interface_stem,
        operations=operations,
        acquisitions=acquisitions,
    )


def _operation_model(
    operation: DeclaredOperation,
    *,
    constant_prefix: str,
    renderer: _AnnotationRenderer,
    public_name: str | None,
) -> _OperationModel:
    arguments: list[_OperationArgumentModel] = []
    for argument in operation.arguments:
        if argument.python_name == "effect_id":
            raise ClientGenerationError(
                "generated symbolic clients reserve operation parameter "
                f"{operation.method_name}.effect_id"
            )
        if isinstance(argument.spec.value_type.atom, PayloadType):
            raise ClientGenerationError(
                "generated clients do not support payload operation argument "
                f"{operation.method_name}.{argument.python_name}"
            )
        concrete_annotation = renderer.render(argument.annotation)
        arguments.append(
            _OperationArgumentModel(
                python_name=argument.python_name,
                argument_id=argument.argument_id,
                kind=argument.parameter.kind.name,
                concrete_annotation=concrete_annotation,
                symbolic_annotation=_symbolic_annotation(concrete_annotation),
            )
        )
    return _OperationModel(
        method_name=operation.method_name if public_name is None else public_name,
        descriptor_name=_descriptor_name(
            constant_prefix,
            operation.method_name,
        ),
        arguments=tuple(arguments),
    )


def _acquisition_model(
    acquisition: DeclaredAcquisition[object],
    *,
    constant_prefix: str,
    public_names: AcquisitionPublicNames | None,
    public_name: str | None,
) -> _AcquisitionModel:
    result_type_name = acquisition.result.type_name
    result_stem = result_type_name.removesuffix("Results")
    declared_method_name = acquisition.method_name
    method_name = declared_method_name if public_name is None else public_name
    return _AcquisitionModel(
        method_name=method_name,
        descriptor_name=_descriptor_name(
            constant_prefix,
            declared_method_name,
        ),
        result_type_name=result_type_name,
        result_fields=tuple(
            _AcquisitionResultModel(
                python_name=field.python_name,
                spec=field.spec,
                annotation=field.annotation,
            )
            for field in acquisition.result_fields
        ),
        readback_name=(
            f"{result_stem}Readback"
            if public_names is None or public_names.readback is None
            else public_names.readback
        ),
        products_name=(
            f"{result_stem}Products"
            if public_names is None or public_names.products is None
            else public_names.products
        ),
    )


def _render_header(
    models: tuple[_InterfaceModel, ...],
    *,
    renderer: _AnnotationRenderer,
    local_package: str,
) -> str:
    scopes = tuple(model.root for model in models)
    has_operations = any(scope.operations for scope in scopes)
    has_acquisitions = any(scope.acquisitions for scope in scopes)
    has_projections = any(
        model.live_projection_type_name is not None for model in models
    )
    has_keyword_projection = any(
        model.keyword_projection is not None for model in models
    )
    has_plain_root = any(model.live_projection_type_name is None for model in models)
    has_member_clients = any(
        constituent.members for model in models for constituent in model.constituents
    )

    imports: dict[str, set[str]] = {
        "scopecat.authoring": {
            "EachEntity",
            "InstrumentRecorder",
            "OneEntity",
            "ResourceRoleInput",
        },
        "scopecat.sdk.instruments": {"InstrumentCapabilityRef", "InterfaceRef"},
        "scopecat_instruments._symbolic_runtime": set(),
    }
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
    if has_member_clients:
        imports.setdefault("scopecat_instruments._client_runtime", set()).update(
            {
                "ClientMemberDeclaration",
                "InstrumentMemberClient",
                "client_property_value_type",
            }
        )
    if has_projections:
        imports.setdefault("scopecat_instruments._client_runtime", set()).add(
            "ProjectedMemberClientBase"
        )
        imports["scopecat_instruments._symbolic_runtime"].update(
            {
                "ProjectedMemberSymbolicClientBase",
                "ProjectedMemberSymbolicGroupBase",
            }
        )
    if has_keyword_projection:
        imports.setdefault("typing", set()).update({"overload", "override"})
        imports["scopecat.authoring"].update({"PerEntity", "Symbolic"})
        imports.setdefault("scopecat.sdk.instruments", set()).add("ApplyReceipt")
    if has_operations or has_acquisitions:
        imports["scopecat.authoring"].add("PerEntity")
    if has_operations:
        imports["scopecat.authoring"].add("Symbolic")
    if has_acquisitions:
        imports["dataclasses"] = {"dataclass", "field"}
        imports["scopecat.authoring"].add("ProductRef")
        imports["scopecat.authoring"].add("ProductBundle")
        imports["scopecat.records.measurement"] = {"MeasurementAcquisitionValue"}
        if any(
            field.product_value_annotation == "MeasurementArrayData"
            for model in models
            for acquisition in model.root.acquisitions
            for field in acquisition.result_fields
        ):
            imports["scopecat.program.measurement_types"] = {"MeasurementArrayData"}
        imports["scopecat.sdk.instruments"].add("CollectReceipt")
        acquisition_runtime_imports = {
            "ClientAcquisition",
            "ClientAcquisitionResult",
        }
        if any(
            field.spec.axes
            for model in models
            for acquisition in model.root.acquisitions
            for field in acquisition.result_fields
        ):
            acquisition_runtime_imports.add("ClientAcquisitionAxis")
        imports.setdefault("scopecat_instruments._client_runtime", set()).update(
            acquisition_runtime_imports
        )
    if has_operations:
        imports.setdefault("scopecat.sdk.instruments", set()).add("InvokeReceipt")
    for module, names in renderer.imports.items():
        imports.setdefault(module, set()).update(names)

    return (
        "# This file was auto-generated by scripts/generate_instrument_clients.py.\n"
        "# Do not make direct changes to the file.\n"
        "# pyright: reportPrivateUsage=false, reportImplicitStringConcatenation=false\n"
        "# pyright: reportUnannotatedClassAttribute=false\n"
        '"""Typed live and symbolic clients generated from interface declarations."""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        f"{_render_import_block(imports, local_package=local_package)}"
    )


def _render_from_import(module: str, names: set[str]) -> str:
    bare_names = {name for name in names if " as " not in name}
    aliases = names - bare_names
    rendered = _render_bare_from_import(module, bare_names) if bare_names else ""
    return rendered + "".join(
        f"from {module} import (\n    {alias},\n)\n"
        for alias in sorted(
            aliases,
            key=lambda item: _import_name_key(item.partition(" as ")[0]),
        )
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


def _render_import_block(
    imports: dict[str, set[str]],
    *,
    local_package: str,
) -> str:
    standard_modules = {"dataclasses", "typing"}
    local_modules = {
        module
        for module in imports
        if module == local_package or module.startswith(f"{local_package}.")
    }
    external_modules = imports.keys() - standard_modules - local_modules
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
    if not exports:
        return "\n__all__ = []\n"
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
    _append_client_scope_descriptors(
        sections,
        constituent.layout.root,
        root_ref_name=constituent.ref_name,
        constant_prefix=constituent.constant_prefix,
    )
    return "".join(sections)


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
                    acquisition.method_name,
                ),
                acquisition,
                root_ref_name=root_ref_name,
            )
        )


def _render_client_acquisition(
    name: str,
    acquisition: DeclaredAcquisition[object],
    *,
    root_ref_name: str,
) -> str:
    acquisition_ref = _acquisition_ref_expression(root_ref_name, acquisition.ref)
    fields = "".join(
        _render_client_acquisition_result(
            field,
            acquisition_ref=acquisition_ref,
        )
        for field in acquisition.result.fields
    )
    return (
        f"\n{name} = ClientAcquisition(\n"
        f"    ref={acquisition_ref},\n"
        "    result_fields=(\n"
        f"{fields}"
        "    ),\n"
        ")\n"
    )


def _render_client_acquisition_result(
    field: DeclaredResultField,
    *,
    acquisition_ref: str,
) -> str:
    axes = tuple(_render_client_acquisition_axis(axis) for axis in field.spec.axes)
    axes_expression = "(\n" + "".join(axes) + "            )" if axes else "()"
    result_ref = f"{acquisition_ref}.result({_string_literal(field.result_id)})"
    return (
        "        ClientAcquisitionResult(\n"
        f"            {_string_literal(field.python_name)},\n"
        f"{_render_client_ref_argument(result_ref, indent=12)}"
        f"            dtype={_string_literal(field.spec.dtype)},\n"
        f"            unit={_optional_string_literal(field.spec.unit)},\n"
        f"            role={_string_literal(field.spec.role)},\n"
        f"            axes={axes_expression},\n"
        "        ),\n"
    )


def _render_client_acquisition_axis(axis: AcquisitionAxisSpec) -> str:
    size = axis.size
    if isinstance(size, int):
        size_argument = f"                    size={size},\n"
    elif size is None:
        size_argument = "                    size=None,\n"
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
            indent=20,
        )
    return (
        "                ClientAcquisitionAxis(\n"
        f"                    id={_string_literal(axis.id)},\n"
        f"{size_argument}"
        f"                    kind={_string_literal(axis.kind)},\n"
        f"                    unit={_optional_string_literal(axis.unit)},\n"
        "                ),\n"
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


def _render_result_types(
    model: _InterfaceModel,
    *,
    rendered: set[tuple[str, str, tuple[tuple[str, str], ...]]],
) -> str:
    sections: list[str] = []
    for item in model.root.acquisitions:
        identity = (
            item.readback_name,
            item.products_name,
            item.result_field_signature,
        )
        if identity in rendered:
            continue
        rendered.add(identity)
        readback_fields = "".join(
            f"    {field_name}: MeasurementAcquisitionValue\n"
            for field_name in item.result_field_names
        )
        product_fields = "".join(
            f"    {field.python_name}: ProductRef[{field.product_value_annotation}]\n"
            for field in item.result_fields
        )
        sections.append(
            "\n\n"
            "@dataclass(frozen=True, slots=True)\n"
            f"class {item.readback_name}:\n"
            f'    """Named {item.method_name} results plus their effect '
            'receipt."""\n'
            "\n"
            f"{readback_fields}"
            "    receipt: CollectReceipt = field(repr=False)\n"
            "\n\n"
            "@dataclass(frozen=True, slots=True)\n"
            f"class {item.products_name}(ProductBundle):\n"
            f'    """Typed logical products produced by '
            f'{item.method_name}."""\n'
            "\n"
            f"{product_fields}"
        )
    return "".join(sections)


def _render_keyword_projection_method(
    *,
    method_name: str,
    positional_name: str,
    positional_annotation: str,
    projection_type_name: str,
    fields: tuple[_ProjectionKeywordFieldModel, ...],
    field_annotation: str,
    return_annotation: str,
    helper_name: str,
    returns: bool,
    projection_factory: bool,
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

    implementation_annotation = f"{positional_annotation} | None"
    implementation_parameter = (
        f"        {positional_name}: {implementation_annotation} = None,\n"
    )
    if len(implementation_parameter.rstrip("\n")) > 88:
        implementation_parameter = f"        {positional_name}: (\n"
        if len(f"            {implementation_annotation}") <= 88:
            implementation_parameter += f"            {implementation_annotation}\n"
        else:
            branches = _split_top_level_union(implementation_annotation)
            implementation_parameter += f"            {branches[0]}\n"
            implementation_parameter += "".join(
                f"            | {branch}\n" for branch in branches[1:]
            )
        implementation_parameter += "        ) = None,\n"

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
    if projection_factory:
        helper_projection = f"            {projection_type_name},\n"
    else:
        helper_projection = (
            "            {\n"
            + "".join(
                f"                {_string_literal(field.python_name)}: "
                f"{field.ref_expression},\n"
                for field in fields
            )
            + "            },\n"
        )
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
        f"{implementation_parameter}"
        "        **fields: object,\n"
        f"    ) -> {return_annotation}:\n"
        f"        {return_prefix}self.{helper_name}(\n"
        f"            {positional_name},\n"
        f"{helper_projection}"
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
    field: _ProjectionKeywordFieldModel,
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
    return _render_live_scope(model, model.root)


def _render_live_scope(model: _InterfaceModel, scope: _ScopeModel) -> str:
    base = (
        "InstrumentClientBase"
        if model.live_projection_type_name is None
        else f"ProjectedMemberClientBase[{model.live_projection_type_name}]"
    )
    body: list[str] = []
    for constituent in model.constituents:
        for member in constituent.members:
            _append_member_separator(body)
            body.append(_render_live_member(member))
    if model.keyword_projection is not None:
        _append_member_separator(body)
        state = model.keyword_projection
        body.append(
            _render_keyword_projection_method(
                method_name="apply",
                positional_name="patch",
                positional_annotation=state.patch_type_name,
                projection_type_name=state.patch_type_name,
                fields=state.fields,
                field_annotation="concrete_annotation",
                return_annotation="ApplyReceipt",
                helper_name=(
                    "_apply_projected"
                    if state.projection_factory
                    else "_apply_projected_fields"
                ),
                returns=True,
                projection_factory=state.projection_factory,
            )
        )
    for operation in scope.operations:
        _append_member_separator(body)
        body.append(_render_live_operation(operation))
    for acquisition in scope.acquisitions:
        _append_member_separator(body)
        body.append(_render_live_acquisition(acquisition))
    if not body:
        body.append("    pass\n")
    return (
        "\n\n"
        f"class {scope.live_client_name}({base}):\n" + "".join(body).rstrip("\n") + "\n"
    )


def _render_live_member(member: _MemberClientModel) -> str:
    return_annotation = f"InstrumentMemberClient[{member.annotation}]"
    compact_signature = f"    def {member.python_name}(self) -> {return_annotation}:\n"
    signature = (
        compact_signature
        if len(compact_signature.rstrip("\n")) <= 88
        else (
            f"    def {member.python_name}(\n"
            "        self,\n"
            f"    ) -> {return_annotation}:\n"
        )
    )
    readable_argument = "" if member.readable else "            readable=False,\n"
    return (
        "    @property\n"
        f"{signature}"
        "        return self._member(\n"
        "            ClientMemberDeclaration(\n"
        f"                {_string_literal(member.python_name)},\n"
        f"                {member.ref_name}.property("
        f"{_string_literal(member.property_id)}),\n"
        f"{_render_client_value_type_argument(member.value_type_json, indent=16)}"
        "            ),\n"
        f"            writable={member.writable!r},\n"
        f"{readable_argument}"
        "        )\n"
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
    return _render_symbolic_scope(model, model.root)


def _render_symbolic_requires_parameter(model: _InterfaceModel) -> str:
    compact = (
        "        requires: tuple[InstrumentCapabilityRef, ...] = "
        f"{model.requires_expression},\n"
    )
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return (
        "        requires: tuple[InstrumentCapabilityRef, ...] = (\n"
        + "".join(f"            {ref_name},\n" for ref_name in model.ref_names)
        + "        ),\n"
    )


def _render_symbolic_scope(model: _InterfaceModel, scope: _ScopeModel) -> str:
    base = (
        "SymbolicInstrumentClientBase"
        if model.symbolic_projection_type_name is None
        else f"ProjectedMemberSymbolicClientBase[{model.symbolic_projection_type_name}]"
    )
    body: list[str] = ["    __slots__ = ()\n"]
    body.extend(
        (
            "\n",
            "    def __init__(\n",
            "        self,\n",
            "        recorder: InstrumentRecorder,\n",
            "        resource_id: str,\n",
            "        *,\n",
            "        namespace_hint: str,\n",
            _render_symbolic_requires_parameter(model),
            "        for_: OneEntity | None = None,\n",
            "        role: ResourceRoleInput = None,\n",
            "    ) -> None:\n",
            "        super().__init__(\n",
            "            recorder,\n",
            "            resource_id,\n",
            "            namespace_hint=namespace_hint,\n",
            "            requires=requires,\n",
            "            for_=for_,\n",
            "            role=role,\n",
            "        )\n",
        )
    )
    if model.keyword_projection is not None:
        _append_member_separator(body)
        state = model.keyword_projection
        body.append(
            _render_keyword_projection_method(
                method_name="ensure",
                positional_name="state",
                positional_annotation=state.target_type_name,
                projection_type_name=state.target_type_name,
                fields=state.fields,
                field_annotation="symbolic_annotation",
                return_annotation="None",
                helper_name=(
                    "_ensure_projected"
                    if state.projection_factory
                    else "_ensure_projected_fields"
                ),
                returns=False,
                projection_factory=state.projection_factory,
            )
        )
    for operation in scope.operations:
        _append_member_separator(body)
        body.append(_render_symbolic_operation(operation))
    for acquisition in scope.acquisitions:
        _append_member_separator(body)
        body.append(_render_symbolic_acquisition(acquisition))
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
    return _render_symbolic_group_scope(model, model.root)


def _render_symbolic_group_scope(
    model: _InterfaceModel,
    scope: _ScopeModel,
) -> str:
    base = (
        f"SymbolicInstrumentGroupBase[{scope.symbolic_client_name}]"
        if model.symbolic_projection_type_name is None
        else "ProjectedMemberSymbolicGroupBase["
        f"{model.symbolic_projection_type_name}, "
        f"{model.group_projection_type_name}, {scope.symbolic_client_name}]"
    )
    body: list[str] = ["    __slots__ = ()\n"]
    body.extend(
        (
            "\n",
            "    def __init__(\n",
            "        self,\n",
            "        recorder: InstrumentRecorder,\n",
            "        resource_id: str,\n",
            "        *,\n",
            "        namespace_hint: str,\n",
            "        for_: EachEntity,\n",
            _render_symbolic_requires_parameter(model),
            "        role: ResourceRoleInput = None,\n",
            "    ) -> None:\n",
            "        super().__init__(\n",
            "            recorder,\n",
            "            resource_id,\n",
            "            namespace_hint=namespace_hint,\n",
            "            for_=for_,\n",
            f"            client_factory={scope.symbolic_client_name},\n",
            "            requires=requires,\n",
            "            role=role,\n",
            "        )\n",
        )
    )
    if model.keyword_projection is not None:
        _append_member_separator(body)
        state = model.keyword_projection
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
                helper_name=(
                    "_ensure_projected"
                    if state.projection_factory
                    else "_ensure_projected_fields"
                ),
                returns=False,
                projection_factory=state.projection_factory,
            )
        )
    for operation in scope.operations:
        _append_member_separator(body)
        body.append(_render_group_operation(operation))
    for acquisition in scope.acquisitions:
        _append_member_separator(body)
        body.append(_render_group_acquisition(acquisition))
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
        compact = (
            f"                {operation.descriptor_name}.argument("
            f"{_string_literal(argument.argument_id)}): {argument.python_name},\n"
        )
        if len(compact.rstrip("\n")) <= 88:
            lines.append(compact)
        else:
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
        f'    name="{model.factory_name}",\n'
        f"    requires={model.requires_expression},\n"
        ")\n"
    )


def _render_exports(
    models: tuple[_InterfaceModel, ...],
) -> str:
    return _render_all(_client_export_names(models))


def _client_export_names(
    models: tuple[_InterfaceModel, ...],
) -> tuple[str, ...]:
    exports: set[str] = set()
    for model in models:
        if model.generate_family:
            exports.add(model.factory_name)
        scope = model.root
        exports.update(
            {
                scope.live_client_name,
                scope.symbolic_client_name,
                scope.symbolic_group_name,
            }
        )
        for acquisition in scope.acquisitions:
            exports.update(
                {
                    acquisition.products_name,
                    acquisition.readback_name,
                }
            )
    return tuple(sorted(exports))


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
    method_name: str,
) -> str:
    segments = (constant_prefix, method_name, "DECLARATION")
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
    prefix = " " * indent
    literal = _formatted_string_literal(value)
    if len(prefix + literal) <= 88:
        return f"{prefix}{literal}\n"
    chunk_size = max(1, (84 - indent) // 2)
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


def _snake_case(name: str) -> str:
    words = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", words).lower()


def _load_manifest(symbol: str, /) -> InstrumentPackageManifest:
    module_name, separator, attribute = symbol.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("manifest must use the form 'module:attribute'")
    manifest = cast("object", getattr(import_module(module_name), attribute))
    if not isinstance(manifest, InstrumentPackageManifest):
        raise TypeError(f"{symbol!r} is not an InstrumentPackageManifest")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when any committed generated source is stale",
    )
    parser.add_argument(
        "--manifest",
        default="scopecat_instruments.package_manifest:PACKAGE_MANIFEST",
        help="instrument package manifest as module:attribute",
    )
    parser.add_argument(
        "--package-module",
        default="scopecat_instruments",
        help="import path for the generated package",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments",
        help="directory that receives the generated package modules",
    )
    parser.add_argument(
        "--fixtures",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="also generate Scopecat's internal codegen fixtures",
    )
    options = _Options()
    parser.parse_args(argv, namespace=options)
    package_targets = package_generation_targets(
        _load_manifest(options.manifest),
        package_module=options.package_module,
        output_root=options.output_root.resolve(),
    )
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
            for target in _generation_targets(package_targets)
        ),
        *(
            rendered_source
            for target in _catalog_targets(package_targets, fixtures=options.fixtures)
            for rendered_source in render_catalog_target(
                target,
                declaration_cache=declaration_cache,
            )
        ),
        *(
            (
                target.output,
                render_package_exports_target(
                    target,
                    declaration_cache=declaration_cache,
                ),
            )
            for target in _package_exports_targets(package_targets)
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
            rendered_paths = ", ".join(str(path) for path in stale)
            print(
                "generated instrument sources are stale "
                f"({rendered_paths}); run "
                "the instrument client generator without `--check`",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return
    for output, source in rendered:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
