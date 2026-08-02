from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate_instrument_clients.py"
FIXTURE_IMPORT_ROOT = REPOSITORY_ROOT / "packages" / "scopecat-instruments" / "tests"
FIXTURE_STATE_PROJECTION_MODULE = "generated_state_catalog_fixture"
PRODUCTION_STATE_PROJECTION_MODULE = "scopecat_instruments.states"
_RENDER_SURFACE = """
import sys
from importlib import import_module

sys.path.insert(0, sys.argv[1])
if sys.argv[4] != "-":
    sys.path.insert(0, sys.argv[4])
from generate_instrument_clients import (
    clients_for,
    clients_for_bundle,
    render_client_module,
)
from scopecat.sdk.instruments.declarations import declared_bundle_interfaces

declarations = import_module(sys.argv[2])
declaration = getattr(declarations, sys.argv[3])
if sys.argv[5] == "facade":
    base, *_ = declared_bundle_interfaces(declaration)
    surfaces = (clients_for_bundle(declaration, facade_flag=sys.argv[6]),)
    if sys.argv[7] == "include-base":
        surfaces = (clients_for(base), *surfaces)
else:
    surfaces = (
        clients_for_bundle(declaration)
        if sys.argv[5] == "bundle"
        else clients_for(declaration),
    )
print(
    render_client_module(
        surfaces,
        state_projection_module=sys.argv[8],
    ),
    end="",
)
"""
_IMPORT_STATIC_CATALOG = """
from scopecat.sdk.instruments import declarations


def reject_runtime_compilation(*args: object, **kwargs: object) -> object:
    raise AssertionError("generated instrument modules compiled a declaration")


declarations.compile_interface = reject_runtime_compilation

import scopecat_instruments.clients
import scopecat_instruments.members
import scopecat_instruments.states
from scopecat_instruments.interfaces import (
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
    temperature_readout_interface,
)

for factory in (
    dc_monitor_interface,
    dc_source_interface,
    network_sweep_interface,
    rf_output_interface,
    temperature_readout_interface,
):
    first = factory()
    second = factory()
    assert first == second
    assert first is not second
"""


def _render_surface(
    interface_name: str,
    *,
    state_projection_module: str = FIXTURE_STATE_PROJECTION_MODULE,
    module: str = "client_codegen_fixture_declarations",
    import_root: Path | None = FIXTURE_IMPORT_ROOT,
    bundle: bool = False,
    facade: bool = False,
    flag: str = "monitor",
    include_base: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository code
        [
            sys.executable,
            "-c",
            _RENDER_SURFACE,
            str(GENERATOR.parent),
            module,
            interface_name,
            "-" if import_root is None else str(import_root),
            "facade" if facade else "bundle" if bundle else "interface",
            flag,
            "include-base" if include_base else "omit-base",
            state_projection_module,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_committed_generated_instrument_sources_are_current() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed repository script
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_generated_catalog_imports_without_runtime_declaration_compilation() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and package code
        [sys.executable, "-c", _IMPORT_STATIC_CATALOG],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_codegen_imports_state_projections_from_the_configured_module() -> None:
    completed = _render_surface(
        "CatalogProjectionInterface",
        state_projection_module="custom.state_projections",
    )

    assert completed.returncode == 0, completed.stderr
    assert "from custom.state_projections import (" in completed.stdout
    assert "CatalogProjectionPatch" in completed.stdout
    assert "CatalogProjectionTarget" in completed.stdout


def test_codegen_adds_keyword_convenience_for_one_flat_state_schema() -> None:
    completed = _render_surface("CatalogProjectionInterface")

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-flat-state>", "exec")
    assert "patch: CatalogProjectionPatch," in completed.stdout
    assert "enabled: bool = ...," in completed.stdout
    assert "state: CatalogProjectionTarget," in completed.stdout
    assert "enabled: bool | ValueRef = ...," in completed.stdout
    assert (
        "enabled: bool | ValueRef | PerEntity[bool | ValueRef] = ...,"
        in completed.stdout
    )


def test_codegen_keeps_discriminated_state_on_carrier_only_surface() -> None:
    completed = _render_surface(
        "DCSourceInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
    )

    assert completed.returncode == 0, completed.stderr
    live_client = completed.stdout.split("class DCSourceClient", maxsplit=1)[1].split(
        "class SymbolicDCSourceClient", maxsplit=1
    )[0]
    assert "def apply(" not in live_client


def test_codegen_accepts_a_projection_module_for_a_stateless_surface() -> None:
    completed = _render_surface("ComponentOperationInterface")

    assert completed.returncode == 0, completed.stderr
    assert "from generated_state_catalog_fixture import" not in completed.stdout


def test_codegen_rejects_payload_operation_arguments_explicitly() -> None:
    completed = _render_surface("PayloadOperationInterface")

    assert completed.returncode != 0
    assert "payload operation argument upload.payload" in completed.stderr


def test_codegen_reserves_symbolic_effect_id_parameter() -> None:
    completed = _render_surface("EffectIdCollisionInterface")

    assert completed.returncode != 0
    assert "reserve operation parameter emit.effect_id" in completed.stderr


def test_codegen_imports_literal_for_resolved_declared_annotations() -> None:
    completed = _render_surface("LiteralOperationInterface")

    assert completed.returncode == 0, completed.stderr
    assert "from typing import Literal" in completed.stdout
    assert 'mode: Literal["left", "right"],' in completed.stdout
    assert 'mode: Literal["left", "right"] | ValueRef,' in completed.stdout
    assert (
        'mode: Literal["left", "right"] | ValueRef | '
        'PerEntity[Literal["left", "right"] | ValueRef],'
    ) in completed.stdout


def test_codegen_rejects_every_colliding_generated_symbol() -> None:
    completed = _render_surface("SymbolCollisionInterface")

    assert completed.returncode != 0
    assert "generated symbol collisions" in completed.stderr
    assert "SymbolCollisionFooBarClient" in completed.stderr
    assert "_SYMBOL_COLLISION_FOO_BAR_FIRE_DECLARATION" in completed.stderr


def test_codegen_derives_base_family_suppression_from_a_facade_bundle() -> None:
    completed = _render_surface(
        "DCSourceMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
        facade=True,
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-dc-source>", "exec")
    assert (
        "type _DCSourcePatch = DCSourcePatch | DCSourceVoltagePatch | "
        "DCSourceCurrentPatch"
    ) in completed.stdout
    assert "class DCSourceClient(DeclaredStateClientBase[_DCSourcePatch]):" in (
        completed.stdout
    )
    assert (
        "class SymbolicDCSourceClient(DeclaredStateSymbolicClientBase["
        "_DCSourceTarget]):"
    ) in completed.stdout
    assert "DeclaredStateSymbolicGroupBase[" in completed.stdout
    assert "_DCSourceTarget, _DCSourceGroupTarget, SymbolicDCSourceClient" in (
        completed.stdout
    )
    assert "DC_SOURCE_DECLARATION" not in completed.stdout
    assert '_DC_SOURCE_REF = InterfaceRef("scopecat.dc_source/v2")' in (
        completed.stdout
    )
    assert "compile_interface" not in completed.stdout
    assert "InstrumentFamily" not in completed.stdout
    assert '"dc_source"' in completed.stdout


def test_codegen_composes_a_root_only_interface_bundle() -> None:
    completed = _render_surface(
        "DCSourceMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
        bundle=True,
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-dc-source-monitor>", "exec")
    assert "type _DCSourceMonitorPatch = (" in completed.stdout
    assert "DCSourcePatch" in completed.stdout
    assert "DCSourceVoltageTarget" in completed.stdout
    assert "DCSourceCurrentGroupTarget" in completed.stdout
    assert "DCMonitorPatch" in completed.stdout
    assert "class DCMonitorReadback(" in completed.stdout
    assert "class DCMonitorProducts(" in completed.stdout
    assert "class DCSourceMonitorClient(" in completed.stdout
    assert "class SymbolicDCSourceMonitorClient(" in completed.stdout
    assert "class SymbolicDCSourceMonitorGroup(" in completed.stdout
    assert "requires=(_DC_SOURCE_REF, _DC_MONITOR_REF)," in completed.stdout
    assert "compile_interface(DCSourceMonitorInterface)" not in completed.stdout


def test_codegen_renders_a_two_interface_boolean_facade() -> None:
    completed = _render_surface(
        "DCSourceMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
        facade=True,
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-dc-source-facade>", "exec")
    assert completed.stdout.count("@overload") == 9
    assert "monitor: Literal[False] = False" in completed.stdout
    assert "monitor: Literal[True]" in completed.stdout
    assert completed.stdout.count("monitor: bool,") == 3
    assert "PerEntity[bool]" not in completed.stdout
    assert "def dc_source(" in completed.stdout
    assert '"dc_source"' in completed.stdout
    assert "requires=(_DC_SOURCE_REF,)" in completed.stdout
    assert "requires=(_DC_SOURCE_REF, _DC_MONITOR_REF)" in completed.stdout


def test_codegen_rejects_a_facade_without_its_base_surface() -> None:
    completed = _render_surface(
        "DCSourceMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
        facade=True,
        include_base=False,
    )

    assert completed.returncode != 0
    assert "requires its first constituent" in completed.stderr
    assert "as a generated base surface" in completed.stderr


def test_codegen_rejects_a_facade_for_more_than_two_interfaces() -> None:
    completed = _render_surface("ThreePartBundleInterface", facade=True)

    assert completed.returncode != 0
    assert "requires exactly two interfaces" in completed.stderr


def test_codegen_reserves_fixed_facade_parameters() -> None:
    completed = _render_surface(
        "DCSourceMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
        facade=True,
        flag="for_",
    )

    assert completed.returncode != 0
    assert "bundle facade flag reserves factory parameter 'for_'" in completed.stderr


def test_codegen_rejects_bundle_components() -> None:
    completed = _render_surface("ComponentBundleInterface", bundle=True)

    assert completed.returncode != 0
    assert "only supports root members" in completed.stderr
    assert "ComponentOperationInterface" in completed.stderr


def test_codegen_composes_distinct_root_operations_from_each_constituent() -> None:
    completed = _render_surface("MethodMergeBundleInterface", bundle=True)

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-method-bundle>", "exec")
    assert completed.stdout.count("    def fire(") == 3
    assert completed.stdout.count("    def arm(") == 3
    assert "_BUNDLE_METHOD_LEFT_FIRE_DECLARATION" in completed.stdout
    assert "_BUNDLE_METHOD_PEER_ARM_DECLARATION" in completed.stdout
    assert (
        "requires=(_BUNDLE_METHOD_LEFT_REF, _BUNDLE_METHOD_PEER_REF),"
        in completed.stdout
    )


def test_codegen_rejects_bundle_method_collisions() -> None:
    completed = _render_surface("MethodCollisionBundleInterface", bundle=True)

    assert completed.returncode != 0
    assert "generated bundle method collisions" in completed.stderr
    assert "fire:" in completed.stderr
    assert "BundleMethodLeftInterface" in completed.stderr
    assert "BundleMethodRightInterface" in completed.stderr
