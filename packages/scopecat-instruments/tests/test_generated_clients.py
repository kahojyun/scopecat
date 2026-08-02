from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate_instrument_clients.py"
FIXTURE_IMPORT_ROOT = REPOSITORY_ROOT / "packages" / "scopecat-instruments" / "tests"
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

declarations = import_module(sys.argv[2])
declaration = getattr(declarations, sys.argv[3])
surface = (
    clients_for_bundle(declaration)
    if sys.argv[6] == "bundle"
    else clients_for(declaration, generate_family=sys.argv[5] == "true")
)
print(render_client_module((surface,)), end="")
"""


def _render_surface(
    interface_name: str,
    *,
    module: str = "client_codegen_fixture_declarations",
    import_root: Path | None = FIXTURE_IMPORT_ROOT,
    generate_family: bool = True,
    bundle: bool = False,
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
            "true" if generate_family else "false",
            "bundle" if bundle else "interface",
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
    assert "mode: Literal[" in completed.stdout


def test_codegen_rejects_every_colliding_generated_symbol() -> None:
    completed = _render_surface("SymbolCollisionInterface")

    assert completed.returncode != 0
    assert "generated symbol collisions" in completed.stderr
    assert "SymbolCollisionFooBarClient" in completed.stderr
    assert "_SYMBOL_COLLISION_FOO_BAR_FIRE_DECLARATION" in completed.stderr


def test_codegen_renders_discriminated_state_without_an_optional_family() -> None:
    completed = _render_surface(
        "DCSourceInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        generate_family=False,
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-dc-source>", "exec")
    assert (
        "type _DCSourceState = DCSourceState | DCSourceVoltage | DCSourceCurrent"
    ) in completed.stdout
    assert "class DCSourceClient(DeclaredStateClientBase[_DCSourceState]):" in (
        completed.stdout
    )
    assert (
        "class SymbolicDCSourceClient(DeclaredStateSymbolicClientBase[_DCSourceState]):"
    ) in completed.stdout
    assert (
        "DeclaredStateSymbolicGroupBase[_DCSourceState, SymbolicDCSourceClient]"
    ) in completed.stdout
    assert "declared_interface_layout" not in completed.stdout
    assert "compile_interface" not in completed.stdout
    assert "DC_SOURCE_DECLARATION" not in completed.stdout
    assert "_DC_SOURCE_REF = declared_interface_ref(DCSourceInterface)" in (
        completed.stdout
    )
    assert "InstrumentFamily" not in completed.stdout
    assert '"dc_source"' not in completed.stdout


def test_codegen_composes_a_root_only_interface_bundle() -> None:
    completed = _render_surface(
        "DCSourceMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        bundle=True,
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-dc-source-monitor>", "exec")
    assert "type _DCSourceMonitorState = (" in completed.stdout
    assert "DCSourceState" in completed.stdout
    assert "DCSourceVoltage" in completed.stdout
    assert "DCSourceCurrent" in completed.stdout
    assert "DCMonitorState" in completed.stdout
    assert "class DCMonitorReadback(" in completed.stdout
    assert "class DCMonitorProducts(" in completed.stdout
    assert "class DCSourceMonitorClient(" in completed.stdout
    assert "class SymbolicDCSourceMonitorClient(" in completed.stdout
    assert "class SymbolicDCSourceMonitorGroup(" in completed.stdout
    assert "requires=(_DC_SOURCE_REF, _DC_MONITOR_REF)," in completed.stdout
    assert "compile_interface(DCSourceMonitorInterface)" not in completed.stdout


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
