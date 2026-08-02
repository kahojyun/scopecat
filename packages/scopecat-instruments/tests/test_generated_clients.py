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
from generate_instrument_clients import clients_for, render_client_module

declarations = import_module(sys.argv[2])
surface = clients_for(
    getattr(declarations, sys.argv[3]),
    generate_family=sys.argv[5] == "true",
)
print(render_client_module((surface,)), end="")
"""


def _render_surface(
    interface_name: str,
    *,
    module: str = "client_codegen_fixture_declarations",
    import_root: Path | None = FIXTURE_IMPORT_ROOT,
    generate_family: bool = True,
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
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_committed_generated_client_source_is_current() -> None:
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
