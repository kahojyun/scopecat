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
    clients_for_composite,
    render_client_module,
)

declarations = import_module(sys.argv[2])
interface_types = tuple(
    getattr(declarations, name)
    for name in sys.argv[3].split(",")
)
if sys.argv[5] == "-":
    surfaces = (clients_for(interface_types[0]),)
else:
    surfaces = (
        clients_for_composite(
            sys.argv[5],
            *interface_types,
            driver_optional_flag=None if sys.argv[6] == "-" else sys.argv[6],
        ),
    )
print(
    render_client_module(
        surfaces,
        state_projection_module=sys.argv[7],
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
    *interface_names: str,
    state_projection_module: str = FIXTURE_STATE_PROJECTION_MODULE,
    module: str = "client_codegen_fixture_declarations",
    import_root: Path | None = FIXTURE_IMPORT_ROOT,
    composite_name: str | None = None,
    driver_optional_flag: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository code
        [
            sys.executable,
            "-c",
            _RENDER_SURFACE,
            str(GENERATOR.parent),
            module,
            ",".join(interface_names),
            "-" if import_root is None else str(import_root),
            "-" if composite_name is None else composite_name,
            "-" if driver_optional_flag is None else driver_optional_flag,
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
    assert "enabled: Symbolic[bool] = ...," in completed.stdout
    assert (
        "enabled: Symbolic[bool] | PerEntity[Symbolic[bool]] = ...," in completed.stdout
    )
    assert "status: str = ...," not in completed.stdout
    assert "def state(self) -> CatalogProjectionState:" in completed.stdout
    assert "def refresh_state(self) -> CatalogProjectionState:" in completed.stdout


def test_codegen_renders_flat_dc_source_state_and_typed_transitions() -> None:
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
    assert "patch: DCSourcePatch," in live_client
    assert "voltage_protection: Quantity = ...," in live_client
    assert "current_protection: Quantity = ...," in live_client
    assert "output_enabled: bool = ...," in live_client
    assert "source_mode:" not in live_client
    assert 'ClientStateField(\n            "source_mode",' in completed.stdout
    assert "def source_voltage(" in live_client
    assert "def source_current(" in live_client
    assert live_client.count("range: Quantity,") == 2
    assert live_client.count("level: Quantity,") == 2
    assert completed.stdout.count("range: Symbolic[Quantity],") == 2
    assert completed.stdout.count("level: Symbolic[Quantity],") == 2
    assert (
        completed.stdout.count(
            "range: Symbolic[Quantity] | PerEntity[Symbolic[Quantity]],"
        )
        == 2
    )
    assert (
        completed.stdout.count(
            "level: Symbolic[Quantity] | PerEntity[Symbolic[Quantity]],"
        )
        == 2
    )


def test_codegen_accepts_a_projection_module_for_a_stateless_surface() -> None:
    completed = _render_surface("ScalarOperationInterface")

    assert completed.returncode == 0, completed.stderr
    assert "from generated_state_catalog_fixture import" not in completed.stdout


def test_codegen_keeps_read_only_state_out_of_authoring_projections() -> None:
    completed = _render_surface(
        "TemperatureReadoutInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
    )

    assert completed.returncode == 0, completed.stderr
    assert "class TemperatureReadoutClient(InstrumentClientBase):" in completed.stdout
    assert "def state(self) -> TemperatureReadoutState:" in completed.stdout
    assert "def refresh_state(self) -> TemperatureReadoutState:" in completed.stdout
    assert "TemperatureReadoutPatch" not in completed.stdout
    assert "TemperatureReadoutTarget" not in completed.stdout


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
    assert 'mode: Symbolic[Literal["left", "right"]],' in completed.stdout
    assert (
        'mode: Symbolic[Literal["left", "right"]] | '
        'PerEntity[Symbolic[Literal["left", "right"]]],'
    ) in completed.stdout


def test_codegen_types_products_by_native_point_value() -> None:
    scalar = _render_surface("NativeScalarInterface")

    assert scalar.returncode == 0, scalar.stderr
    assert "    boolean: ProductRef[bool]" in scalar.stdout
    assert "    integer: ProductRef[int]" in scalar.stdout
    assert "    floating: ProductRef[float]" in scalar.stdout
    assert "    complex_value: ProductRef[complex]" in scalar.stdout
    assert "    text: ProductRef[str]" in scalar.stdout
    assert "class NativeScalarRecords:" in scalar.stdout
    assert "    boolean: RecordRef[bool]" in scalar.stdout
    assert "    integer: RecordRef[int]" in scalar.stdout
    assert "    floating: RecordRef[float]" in scalar.stdout
    assert "    complex_value: RecordRef[complex]" in scalar.stdout
    assert "    text: RecordRef[str]" in scalar.stdout
    assert "MeasurementArrayData" not in scalar.stdout

    array = _render_surface("DriverFixedAcquisitionInterface")

    assert array.returncode == 0, array.stderr
    assert (
        "from scopecat.measurements.value_spec import MeasurementArrayData"
        in array.stdout
    )
    assert "    response: ProductRef[MeasurementArrayData]" in array.stdout
    assert "    response: RecordRef[MeasurementArrayData]" in array.stdout


def test_codegen_composes_the_production_dc_source_monitor_family() -> None:
    completed = _render_surface(
        "DCSourceInterface",
        "DCMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        import_root=None,
        state_projection_module=PRODUCTION_STATE_PROJECTION_MODULE,
        composite_name="DCSourceMonitor",
        driver_optional_flag="monitor",
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-dc-source-monitor>", "exec")
    assert "type _DCSourceMonitorPatch = DCSourcePatch | DCMonitorPatch" in (
        completed.stdout
    )
    assert "DCSourcePatch" in completed.stdout
    assert "DCSourceTarget" in completed.stdout
    assert "DCSourceGroupTarget" in completed.stdout
    assert "DCMonitorPatch" in completed.stdout
    assert "class DCMonitorCurrentReadback:" in completed.stdout
    assert "    current: MeasurementValue" in completed.stdout
    assert "class DCMonitorCurrentRecords:" in completed.stdout
    assert "    current: RecordRef[float]" in completed.stdout
    assert "    current: ProductRef[float]" in completed.stdout
    assert "class DCMonitorVoltageReadback:" in completed.stdout
    assert "    voltage: MeasurementValue" in completed.stdout
    assert "class DCMonitorVoltageRecords:" in completed.stdout
    assert "    voltage: RecordRef[float]" in completed.stdout
    assert "    voltage: ProductRef[float]" in completed.stdout
    assert "DCMonitorCurrentResults" not in completed.stdout
    assert "DCMonitorVoltageResults" not in completed.stdout
    assert "class DCSourceMonitorClient(" in completed.stdout
    assert "class DCSourceMonitorState:" in completed.stdout
    assert "    dc_source: DCSourceState" in completed.stdout
    assert "    dc_monitor: DCMonitorState" in completed.stdout
    assert "def state(self) -> DCSourceMonitorState:" in completed.stdout
    assert (
        "class SymbolicDCSourceMonitorClient("
        "\n    DeclaredStateSymbolicClientBase[_DCSourceMonitorTarget]"
    ) in completed.stdout
    assert "class SymbolicDCSourceMonitorGroup(" in completed.stdout
    assert '_DC_SOURCE_REF = InterfaceRef("scopecat.dc_source/v3")' in (
        completed.stdout
    )
    assert '_DC_MONITOR_REF = InterfaceRef("scopecat.dc_monitor/v4")' in (
        completed.stdout
    )
    assert "def source_voltage(" in completed.stdout
    assert "def source_current(" in completed.stdout
    assert "def measure_current(" in completed.stdout
    assert "def measure_voltage(" in completed.stdout
    assert "dc_source_monitor: InstrumentFamily[" in completed.stdout
    assert "requires=(_DC_SOURCE_REF, _DC_MONITOR_REF)," in completed.stdout
    assert "compile_interface" not in completed.stdout


def test_codegen_composes_distinct_root_operations_from_each_constituent() -> None:
    completed = _render_surface(
        "CompositeMethodLeftInterface",
        "CompositeMethodPeerInterface",
        composite_name="MethodComposite",
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-method-composite>", "exec")
    assert completed.stdout.count("    def fire(") == 3
    assert completed.stdout.count("    def arm(") == 3
    assert "_COMPOSITE_METHOD_LEFT_FIRE_DECLARATION" in completed.stdout
    assert "_COMPOSITE_METHOD_PEER_ARM_DECLARATION" in completed.stdout
    assert (
        "requires=(_COMPOSITE_METHOD_LEFT_REF, _COMPOSITE_METHOD_PEER_REF),"
        in completed.stdout
    )


def test_codegen_rejects_composite_method_collisions() -> None:
    completed = _render_surface(
        "CompositeMethodLeftInterface",
        "CompositeMethodRightInterface",
        composite_name="MethodCollisionComposite",
    )

    assert completed.returncode != 0
    assert "generated composite method collisions" in completed.stderr
    assert "fire:" in completed.stderr
    assert "CompositeMethodLeftInterface" in completed.stderr
    assert "CompositeMethodRightInterface" in completed.stderr
