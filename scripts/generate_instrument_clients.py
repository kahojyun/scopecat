"""Generate typed first-party instrument clients from declared interfaces."""

from __future__ import annotations

import argparse
import re
import sys
import types
import typing
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TypeAliasType, TypeVar, cast, get_args, get_origin

from scopecat.kernel.value_types import Payload as PayloadType
from scopecat.sdk.instruments.declarations import (
    CompiledInterface,
    DeclaredAcquisition,
    DeclaredOperation,
    DeclaredScopeLayout,
    declared_interface_layout,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTS_PACKAGE_ROOT = REPOSITORY_ROOT / "packages" / "scopecat-instruments"
OUTPUT = (
    INSTRUMENTS_PACKAGE_ROOT / "src" / "scopecat_instruments" / "_generated_clients.py"
)
FIXTURE_IMPORT_ROOT = INSTRUMENTS_PACKAGE_ROOT / "tests"
FIXTURE_OUTPUT = FIXTURE_IMPORT_ROOT / "generated_client_fixture.py"
_TYPING_UNION_ORIGIN: object = typing.Union  # pyright: ignore[reportDeprecated]


class ClientGenerationError(ValueError):
    """A declaration uses a feature the typed client surface cannot represent."""


@dataclass(frozen=True, slots=True)
class ClientGenerationPolicy:
    """Non-structural inputs that a Python interface declaration cannot carry."""

    declaration_module: str
    declaration_symbol: str
    public_name_overrides: tuple[tuple[str, str], ...] = ()
    import_root: Path | None = None


@dataclass(frozen=True, slots=True)
class GenerationTarget:
    """One independently importable generated module and its declarations."""

    output: Path
    policies: tuple[ClientGenerationPolicy, ...]


class _Options(argparse.Namespace):
    check: bool = False


PRODUCTION_TARGET = GenerationTarget(
    output=OUTPUT,
    policies=(
        ClientGenerationPolicy(
            declaration_module="scopecat_instruments.interface_declarations",
            declaration_symbol="TEMPERATURE_READOUT_DECLARATION",
            public_name_overrides=(("sample.readback", "TemperatureReadback"),),
        ),
        ClientGenerationPolicy(
            declaration_module="scopecat_instruments.interface_declarations",
            declaration_symbol="RF_OUTPUT_DECLARATION",
        ),
    ),
)
FIXTURE_TARGET = GenerationTarget(
    output=FIXTURE_OUTPUT,
    policies=(
        ClientGenerationPolicy(
            declaration_module="client_codegen_fixture_declarations",
            declaration_symbol="COMPONENT_OPERATION_DECLARATION",
            import_root=FIXTURE_IMPORT_ROOT,
        ),
    ),
)
TARGETS = (PRODUCTION_TARGET, FIXTURE_TARGET)


@dataclass(frozen=True, slots=True)
class _OperationArgumentModel:
    python_name: str
    kind: str
    declared_annotation: str
    concrete_annotation: str


@dataclass(frozen=True, slots=True)
class _OperationModel:
    index: int
    method_name: str
    descriptor_name: str
    arguments: tuple[_OperationArgumentModel, ...]


@dataclass(frozen=True, slots=True)
class _AcquisitionModel:
    index: int
    method_name: str
    descriptor_name: str
    result_type_name: str
    result_type_arguments: int
    readback_name: str
    products_name: str


@dataclass(frozen=True, slots=True)
class _ScopeModel:
    python_path: tuple[str, ...]
    component_indexes: tuple[int, ...]
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
class _InterfaceModel:
    declaration_module: str
    declaration_symbol: str
    constant_prefix: str
    interface_name: str
    stem: str
    factory_name: str
    observation_type_name: str | None
    state_type_names: tuple[str, ...]
    root: _ScopeModel

    @property
    def state_type_name(self) -> str | None:
        if not self.state_type_names:
            return None
        if len(self.state_type_names) == 1:
            return self.state_type_names[0]
        return self.state_alias_name

    @property
    def state_alias_name(self) -> str:
        return f"_{self.stem}State"

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
    def needs_layout(self) -> bool:
        return self.observation_type_name is not None or any(
            scope.operations or scope.acquisitions for scope in _walk_scopes(self.root)
        )


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
            return "Literal[" + ", ".join(repr(item) for item in arguments) + "]"
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


def render_generated_clients() -> str:
    """Render the production generated module for tooling compatibility."""

    return render_generation_target(PRODUCTION_TARGET)


def render_generation_target(target: GenerationTarget) -> str:
    """Render one configured generated module."""

    return render_client_module(target.policies)


def render_client_module(policies: tuple[ClientGenerationPolicy, ...]) -> str:
    """Render an independently importable module for selected declarations."""

    renderer = _AnnotationRenderer()
    models = tuple(_interface_model(policy, renderer=renderer) for policy in policies)
    if not models:
        raise ClientGenerationError("a generated client module requires a declaration")
    _validate_generated_symbols(models)

    sections = [_render_header(models, renderer=renderer)]
    for model in models:
        sections.extend(
            (
                _render_state_alias(model),
                _render_descriptors(model),
                _render_result_types(model),
                _render_live_scopes(model),
                _render_symbolic_scopes(model),
                _render_symbolic_group_scopes(model),
                _render_family(model),
            )
        )
    sections.append(_render_exports(models))
    return "".join(sections)


def _interface_model(
    policy: ClientGenerationPolicy,
    *,
    renderer: _AnnotationRenderer,
) -> _InterfaceModel:
    if policy.import_root is not None:
        import_root = str(policy.import_root)
        if import_root not in sys.path:
            sys.path.insert(0, import_root)
    module = import_module(policy.declaration_module)
    compiled = cast(
        "CompiledInterface[object]",
        getattr(module, policy.declaration_symbol),
    )
    layout = declared_interface_layout(compiled)
    interface_name = compiled.interface_type.__name__
    stem = interface_name.removesuffix("Interface")
    overrides = dict(policy.public_name_overrides)
    observation_type_name = (
        None
        if layout.observed_state is None
        else renderer.reference(layout.observed_state.state_type)
    )
    constant_prefix = policy.declaration_symbol.removesuffix("_DECLARATION")
    root = _scope_model(
        layout.root,
        component_indexes=(),
        interface_stem=stem,
        constant_prefix=constant_prefix,
        overrides=overrides,
        renderer=renderer,
    )
    return _InterfaceModel(
        declaration_module=policy.declaration_module,
        declaration_symbol=policy.declaration_symbol,
        constant_prefix=constant_prefix,
        interface_name=interface_name,
        stem=stem,
        factory_name=overrides.get("factory", _snake_case(stem)),
        observation_type_name=observation_type_name,
        state_type_names=tuple(
            renderer.reference(state_type) for state_type in layout.state_types
        ),
        root=root,
    )


def _validate_generated_symbols(models: tuple[_InterfaceModel, ...]) -> None:
    owners_by_symbol: dict[str, list[str]] = {}

    def register(symbol: str, owner: str) -> None:
        owners_by_symbol.setdefault(symbol, []).append(owner)

    for model in models:
        declaration = model.declaration_symbol
        if model.needs_layout:
            register(f"_{model.constant_prefix}_LAYOUT", f"{declaration} layout")
        if model.observation_type_name is not None:
            register(
                f"_{model.constant_prefix}_OBSERVATION_DECLARATION",
                f"{declaration} observation",
            )
        if len(model.state_type_names) > 1:
            register(model.state_alias_name, f"{declaration} state union")
        register(model.factory_name, f"{declaration} factory")
        for scope in _walk_scopes(model.root):
            path = ".".join(scope.python_path) or "<root>"
            scope_owner = f"{declaration} scope {path}"
            register(scope.live_client_name, f"{scope_owner} live client")
            register(scope.symbolic_client_name, f"{scope_owner} symbolic client")
            register(scope.symbolic_group_name, f"{scope_owner} symbolic group")
            for operation in scope.operations:
                register(
                    operation.descriptor_name,
                    f"{scope_owner} operation {operation.method_name}",
                )
            for acquisition in scope.acquisitions:
                acquisition_owner = (
                    f"{scope_owner} acquisition {acquisition.method_name}"
                )
                register(acquisition.descriptor_name, acquisition_owner)
                register(
                    acquisition.readback_name,
                    f"{acquisition_owner} live results",
                )
                register(
                    acquisition.products_name,
                    f"{acquisition_owner} symbolic results",
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
    component_indexes: tuple[int, ...],
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
            index=index,
            python_path=scope.python_path,
            constant_prefix=constant_prefix,
            renderer=renderer,
        )
        for index, operation in enumerate(scope.operations)
    )
    acquisitions = tuple(
        _acquisition_model(
            acquisition,
            index=index,
            python_path=scope.python_path,
            constant_prefix=constant_prefix,
            overrides=overrides,
            renderer=renderer,
        )
        for index, acquisition in enumerate(scope.acquisitions)
    )
    components = tuple(
        _scope_model(
            component,
            component_indexes=(*component_indexes, index),
            interface_stem=interface_stem,
            constant_prefix=constant_prefix,
            overrides=overrides,
            renderer=renderer,
        )
        for index, component in enumerate(scope.components)
    )
    return _ScopeModel(
        python_path=scope.python_path,
        component_indexes=component_indexes,
        class_stem=class_stem,
        operations=operations,
        acquisitions=acquisitions,
        components=components,
    )


def _operation_model(
    operation: DeclaredOperation[...],
    *,
    index: int,
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
        arguments.append(
            _OperationArgumentModel(
                python_name=argument.python_name,
                kind=argument.parameter.kind.name,
                declared_annotation=renderer.render(argument.declared_annotation),
                concrete_annotation=renderer.render(argument.concrete_annotation),
            )
        )
    return _OperationModel(
        index=index,
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
    index: int,
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
        index=index,
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
    renderer: _AnnotationRenderer,
) -> str:
    scopes = tuple(scope for model in models for scope in _walk_scopes(model.root))
    has_components = any(not scope.is_root for scope in scopes)
    has_operations = any(scope.operations for scope in scopes)
    has_acquisitions = any(scope.acquisitions for scope in scopes)
    has_observations = any(model.observation_type_name for model in models)
    has_state = any(model.state_type_name is not None for model in models)
    has_plain_root = any(model.state_type_name is None for model in models)

    imports: dict[str, set[str]] = {
        "scopecat.authoring": {"EachEntity", "OneEntity"},
        "scopecat_instruments._family_runtime": {"InstrumentFamily"},
        "scopecat_instruments._symbolic_runtime": {"SymbolicInstrumentRecorder"},
    }
    if any(model.needs_layout for model in models):
        imports["scopecat.sdk.instruments.declarations"] = {"declared_interface_layout"}
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
    if has_acquisitions:
        imports["dataclasses"] = {"dataclass", "field"}
        imports["scopecat.authoring"].add("ProductRef")
        imports["scopecat.records.measurement"] = {"MeasurementValue"}
        imports["scopecat.sdk.instruments"] = {"CollectReceipt"}
    if has_operations:
        imports.setdefault("scopecat.sdk.instruments", set()).add("InvokeReceipt")
    if has_observations:
        imports["typing"] = {"cast"}
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
    for model in models:
        imports.setdefault(model.declaration_module, set()).add(
            model.declaration_symbol
        )

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
        "# This file was auto-generated by scripts/generate_instrument_clients.py.\n"
        "# Do not make direct changes to the file.\n"
        '"""Typed live and symbolic clients generated from interface declarations."""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        f"{standard_imports}"
        f"{'\n' if standard_imports else ''}"
        f"{external_imports}"
        f"{'\n' if external_imports and local_imports else ''}"
        f"{local_imports}"
    )


def _render_from_import(module: str, names: set[str]) -> str:
    ordered = sorted(names, key=_import_name_key)
    compact = f"from {module} import {', '.join(ordered)}\n"
    if len(compact.rstrip("\n")) <= 88:
        return compact
    return (
        f"from {module} import (\n"
        + "".join(f"    {name},\n" for name in ordered)
        + ")\n"
    )


def _import_name_key(name: str) -> tuple[int, str]:
    if name.isupper():
        return (0, name)
    if name[0].isupper():
        return (1, name)
    return (2, name)


def _render_state_alias(model: _InterfaceModel) -> str:
    if len(model.state_type_names) <= 1:
        return ""
    union = " | ".join(model.state_type_names)
    compact = f"type {model.state_alias_name} = {union}\n"
    if len(compact.rstrip("\n")) <= 88:
        return "\n" + compact
    return (
        f"\ntype {model.state_alias_name} = (\n"
        + "\n".join(
            f"    {'| ' if index else ''}{state_type}"
            for index, state_type in enumerate(model.state_type_names)
        )
        + "\n)\n"
    )


def _render_descriptors(model: _InterfaceModel) -> str:
    if not model.needs_layout:
        return ""
    layout_name = f"_{model.constant_prefix}_LAYOUT"
    sections = [
        "\n",
        f"{layout_name} = declared_interface_layout({model.declaration_symbol})\n",
    ]
    if model.observation_type_name is not None:
        observation_name = f"_{model.constant_prefix}_OBSERVATION_DECLARATION"
        sections.extend(
            (
                f"{observation_name} = cast(\n",
                f'    "DeclaredObservedState[{model.observation_type_name}]",\n',
                f"    {layout_name}.observed_state,\n",
                ")\n",
            )
        )
    for scope in _walk_scopes(model.root):
        scope_expression = _scope_expression(layout_name, scope.component_indexes)
        sections.extend(
            _render_descriptor_assignment(
                operation.descriptor_name,
                scope_expression,
                collection="operations",
                index=operation.index,
            )
            for operation in scope.operations
        )
        sections.extend(
            _render_descriptor_assignment(
                acquisition.descriptor_name,
                scope_expression,
                collection="acquisitions",
                index=acquisition.index,
            )
            for acquisition in scope.acquisitions
        )
    return "".join(sections)


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
            sections.append(
                "\n\n"
                "@dataclass(frozen=True, slots=True)\n"
                f"class {item.readback_name}("
                f"{item.result_type_name}{live_arguments}):\n"
                f'    """Named {item.method_name} results plus their effect '
                'receipt."""\n'
                "\n"
                "    receipt: CollectReceipt = field(repr=False)\n"
                "\n\n"
                "@dataclass(frozen=True, slots=True)\n"
                f"class {item.products_name}("
                f"{item.result_type_name}{product_arguments}):\n"
                f'    """Typed logical products produced by '
                f'{item.method_name}."""\n'
            )
    return "".join(sections)


def _render_live_scopes(model: _InterfaceModel) -> str:
    return "".join(
        _render_live_scope(model, scope) for scope in _walk_scopes_postorder(model.root)
    )


def _render_live_scope(model: _InterfaceModel, scope: _ScopeModel) -> str:
    if scope.is_root:
        base = (
            "InstrumentClientBase"
            if model.state_type_name is None
            else f"DeclaredStateClientBase[{model.state_type_name}]"
        )
    else:
        base = "InstrumentComponentClientBase"
    body: list[str] = []
    if scope.is_root and model.observation_type_name is not None:
        observation_name = f"_{model.constant_prefix}_OBSERVATION_DECLARATION"
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
            if model.state_type_name is None
            else f"DeclaredStateSymbolicClientBase[{model.state_type_name}]"
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
                f"            requires=({model.declaration_symbol}.ref,),\n",
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
        annotation="declared_annotation",
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
            if model.state_type_name is None
            else "DeclaredStateSymbolicGroupBase["
            f"{model.state_type_name}, {scope.symbolic_client_name}]"
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
        f"    {base}\n"
        "):\n" + "".join(body).rstrip("\n") + "\n"
    )


def _render_group_operation(operation: _OperationModel) -> str:
    signature = _render_operation_signature(
        operation,
        annotation="declared_annotation",
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
        f"    requires=({model.declaration_symbol}.ref,),\n"
        ")\n"
    )


def _render_exports(models: tuple[_InterfaceModel, ...]) -> str:
    exports: set[str] = set()
    for model in models:
        exports.add(model.factory_name)
        if model.observation_type_name is not None:
            exports.add(model.observation_type_name)
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


def _scope_expression(layout_name: str, indexes: tuple[int, ...]) -> str:
    expression = f"{layout_name}.root"
    for index in indexes:
        expression += f".components[{index}]"
    return expression


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
    rendered = tuple((target, render_generation_target(target)) for target in TARGETS)
    if options.check:
        stale = tuple(
            target.output
            for target, source in rendered
            if (
                target.output.read_text(encoding="utf-8")
                if target.output.is_file()
                else ""
            )
            != source
        )
        if stale:
            rendered_paths = ", ".join(
                str(path.relative_to(REPOSITORY_ROOT)) for path in stale
            )
            print(
                "generated instrument clients are stale "
                f"({rendered_paths}); run "
                "`uv run python scripts/generate_instrument_clients.py`",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return
    for target, source in rendered:
        target.output.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
