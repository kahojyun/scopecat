from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

from scopecat_testkit.instrument_codegen_fixtures.declarations import (
    CompositeAcquisitionLeftInterface,
    CompositeMethodLeftInterface,
    DriverSourceInterface,
)

import scopecat_instruments.driver_observations as driver_observations
from scopecat_instruments.driver_observations import (
    DCMonitorCurrentObservation,
    DCMonitorVoltageObservation,
    NetworkSweepObservation,
    TemperatureSampleObservation,
)
from scopecat_instruments.package_manifest import (
    AcquisitionPublicNames,
    CompositeSurfaceRegistration,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate_instrument_clients.py"
FIXTURE_DECLARATIONS_MODULE = (
    "scopecat_testkit.instrument_codegen_fixtures.declarations"
)
FIXTURE_STATE_PROJECTION_MODULE = (
    "scopecat_testkit.instrument_codegen_fixtures.generated_projections"
)
PRODUCTION_MEMBER_PROJECTION_MODULE = "scopecat_instruments.projections"
_RENDER_SURFACE = """
import json
from importlib import import_module
from runpy import run_path

import sys

generator = run_path(sys.argv[1])
AcquisitionPublicNames = generator["AcquisitionPublicNames"]
clients_for = generator["clients_for"]
clients_for_composite = generator["clients_for_composite"]
render_client_module = generator["render_client_module"]

declarations = import_module(sys.argv[2])
interface_types = tuple(
    getattr(declarations, name)
    for name in sys.argv[3].split(",")
)
acquisition_names = tuple(
    AcquisitionPublicNames(
        getattr(getattr(declarations, interface_name), method_name),
        readback=readback,
        products=products,
    )
    for interface_name, method_name, readback, products in json.loads(sys.argv[9])
)
if sys.argv[4] == "-":
    surfaces = (
        clients_for(interface_types[0], acquisition_names=acquisition_names),
    )
else:
    member_name_overrides = tuple(
        (
            getattr(getattr(declarations, interface_name), member_name),
            public_name,
        )
        for interface_name, member_name, public_name in json.loads(sys.argv[7])
    )
    method_name_overrides = tuple(
        (
            getattr(getattr(declarations, interface_name), method_name),
            public_name,
        )
        for interface_name, method_name, public_name in json.loads(sys.argv[8])
    )
    surfaces = (
        clients_for_composite(
            sys.argv[4],
            *interface_types,
            driver_optional_flag=None if sys.argv[5] == "-" else sys.argv[5],
            member_name_overrides=member_name_overrides,
            method_name_overrides=method_name_overrides,
            acquisition_names=acquisition_names,
        ),
    )
print(
    render_client_module(
        surfaces,
        member_projection_module=sys.argv[6],
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
import scopecat_instruments.driver_observations
import scopecat_instruments.members
import scopecat_instruments.projections
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
    member_projection_module: str = FIXTURE_STATE_PROJECTION_MODULE,
    module: str = FIXTURE_DECLARATIONS_MODULE,
    composite_name: str | None = None,
    driver_optional_flag: str | None = None,
    member_name_overrides: tuple[tuple[str, str, str], ...] = (),
    method_name_overrides: tuple[tuple[str, str, str], ...] = (),
    acquisition_names: tuple[tuple[str, str, str | None, str | None], ...] = (),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository code
        [
            sys.executable,
            "-c",
            _RENDER_SURFACE,
            str(GENERATOR),
            module,
            ",".join(interface_names),
            "-" if composite_name is None else composite_name,
            "-" if driver_optional_flag is None else driver_optional_flag,
            member_projection_module,
            json.dumps(member_name_overrides),
            json.dumps(method_name_overrides),
            json.dumps(acquisition_names),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_generated_catalog_imports_without_runtime_declaration_compilation() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and package code
        [sys.executable, "-c", _IMPORT_STATIC_CATALOG],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_codegen_generates_driver_observations_only_for_physical_acquisitions() -> None:
    assert [field.name for field in fields(TemperatureSampleObservation)] == [
        "temperature",
        "resistance",
        "evidence",
    ]
    assert [field.name for field in fields(DCMonitorCurrentObservation)] == [
        "current",
        "evidence",
    ]
    assert [field.name for field in fields(DCMonitorVoltageObservation)] == [
        "voltage",
        "evidence",
    ]
    assert [field.name for field in fields(NetworkSweepObservation)] == [
        "frequency",
        "s_parameter",
        "evidence",
    ]
    assert "DCBiasReadbackObservation" not in driver_observations.__all__


def test_composite_registration_uses_oo_declaration_objects_for_public_names() -> None:
    registration = CompositeSurfaceRegistration(
        name="SourceMethod",
        interface_types=(
            DriverSourceInterface,
            CompositeMethodLeftInterface,
            CompositeAcquisitionLeftInterface,
        ),
        member_name_overrides=((DriverSourceInterface.enabled, "source_enabled"),),
        method_name_overrides=((CompositeMethodLeftInterface.fire, "fire_source"),),
        acquisition_names=(
            AcquisitionPublicNames(
                CompositeAcquisitionLeftInterface.sample,
                products="SourceSampleProducts",
            ),
        ),
    )

    assert registration.member_name_overrides == (
        (DriverSourceInterface.enabled, "source_enabled"),
    )
    assert registration.method_name_overrides == (
        (CompositeMethodLeftInterface.fire, "fire_source"),
    )
    assert registration.acquisition_names == (
        AcquisitionPublicNames(
            CompositeAcquisitionLeftInterface.sample,
            products="SourceSampleProducts",
        ),
    )


def test_codegen_imports_member_projections_from_the_configured_module() -> None:
    completed = _render_surface(
        "CatalogProjectionInterface",
        member_projection_module="custom.member_projections",
    )

    assert completed.returncode == 0, completed.stderr
    assert "from custom.member_projections import (" in completed.stdout
    assert "CatalogProjectionPatch" in completed.stdout
    assert "CatalogProjectionTarget" in completed.stdout


def test_codegen_adds_keyword_convenience_for_one_flat_property_set() -> None:
    completed = _render_surface("CatalogProjectionInterface")

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-member-projection>", "exec")
    assert "patch: CatalogProjectionPatch," in completed.stdout
    assert "enabled: bool = ...," in completed.stdout
    assert "state: CatalogProjectionTarget," in completed.stdout
    assert "enabled: Symbolic[bool] = ...," in completed.stdout
    assert (
        "enabled: Symbolic[bool] | PerEntity[Symbolic[bool]] = ...," in completed.stdout
    )
    assert "status: str = ...," not in completed.stdout
    assert "def enabled(self) -> InstrumentMemberClient[bool]:" in completed.stdout
    assert "def status(self) -> InstrumentMemberClient[str]:" in completed.stdout
    assert "def state(self)" not in completed.stdout


def test_codegen_renders_flat_dc_source_members_and_typed_transitions() -> None:
    completed = _render_surface(
        "DCSourceInterface",
        module="scopecat_instruments.interface_declarations",
        member_projection_module=PRODUCTION_MEMBER_PROJECTION_MODULE,
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
    assert "def source_mode(" in live_client
    assert 'InstrumentMemberClient[Literal["voltage", "current"]]' in live_client
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
    assert f"from {FIXTURE_STATE_PROJECTION_MODULE} import" not in completed.stdout


def test_codegen_keeps_read_only_state_out_of_authoring_projections() -> None:
    completed = _render_surface(
        "TemperatureReadoutInterface",
        module="scopecat_instruments.interface_declarations",
        member_projection_module=PRODUCTION_MEMBER_PROJECTION_MODULE,
    )

    assert completed.returncode == 0, completed.stderr
    assert "class TemperatureReadoutClient(InstrumentClientBase):" in completed.stdout
    assert "def scan_channel(self) -> InstrumentMemberClient[int]:" in completed.stdout
    assert "def autoscan_enabled(self) -> InstrumentMemberClient[bool]:" in (
        completed.stdout
    )
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
    assert "class NativeScalarRecords:" not in scalar.stdout
    assert "class NativeScalarProducts(ProductBundle):" in scalar.stdout
    assert "RecordRef" not in scalar.stdout
    assert "MeasurementArrayData" not in scalar.stdout

    array = _render_surface("DriverFixedAcquisitionInterface")

    assert array.returncode == 0, array.stderr
    assert (
        "from scopecat.program.measurement_types import MeasurementArrayData"
        in array.stdout
    )
    assert "    response: ProductRef[MeasurementArrayData]" in array.stdout
    assert "RecordRef" not in array.stdout


def test_codegen_names_single_acquisition_carriers_by_declaration() -> None:
    completed = _render_surface(
        "NativeScalarInterface",
        acquisition_names=(
            (
                "NativeScalarInterface",
                "sample",
                "ScalarSampleReadback",
                "ScalarSampleProducts",
            ),
        ),
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-named-acquisition>", "exec")
    assert "class ScalarSampleReadback:" in completed.stdout
    assert "class ScalarSampleProducts(ProductBundle):" in completed.stdout
    assert "def sample(self) -> ScalarSampleReadback:" in completed.stdout
    assert ") -> ScalarSampleProducts:" in completed.stdout


def test_codegen_composes_the_production_dc_source_monitor_family() -> None:
    completed = _render_surface(
        "DCSourceInterface",
        "DCMonitorInterface",
        module="scopecat_instruments.interface_declarations",
        member_projection_module=PRODUCTION_MEMBER_PROJECTION_MODULE,
        composite_name="DCSourceMonitor",
        driver_optional_flag="monitor",
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-dc-source-monitor>", "exec")
    assert "type _DCSourceMonitorPatch" not in completed.stdout
    assert "DCSourceMonitorPatch" in completed.stdout
    assert "DCSourceMonitorTarget" in completed.stdout
    assert "DCSourceMonitorGroupTarget" in completed.stdout
    assert "class DCMonitorCurrentReadback:" in completed.stdout
    assert "    current: MeasurementAcquisitionValue" in completed.stdout
    assert "class DCMonitorCurrentRecords:" not in completed.stdout
    assert "class DCMonitorCurrentProducts(ProductBundle):" in completed.stdout
    assert "    current: ProductRef[float]" in completed.stdout
    assert "class DCMonitorVoltageReadback:" in completed.stdout
    assert "    voltage: MeasurementAcquisitionValue" in completed.stdout
    assert "class DCMonitorVoltageRecords:" not in completed.stdout
    assert "class DCMonitorVoltageProducts(ProductBundle):" in completed.stdout
    assert "    voltage: ProductRef[float]" in completed.stdout
    assert "DCMonitorCurrentResults" not in completed.stdout
    assert "DCMonitorVoltageResults" not in completed.stdout
    assert "class DCSourceMonitorClient(" in completed.stdout
    assert "class DCSourceMonitorState:" not in completed.stdout
    assert "def apply(" in completed.stdout
    assert "measurement_enabled: bool = ..." in completed.stdout
    assert "self._apply_projected(" in completed.stdout
    assert "def source_mode(" in completed.stdout
    assert "def measurement_enabled(" in completed.stdout
    assert (
        "class SymbolicDCSourceMonitorClient("
        "\n    ProjectedMemberSymbolicClientBase[DCSourceMonitorTarget]"
    ) in completed.stdout
    assert "class SymbolicDCSourceMonitorGroup(" in completed.stdout
    assert "self._ensure_projected(" in completed.stdout
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
    assert "requires: tuple[InstrumentCapabilityRef, ...] = (" in completed.stdout
    assert "requires=requires," in completed.stdout
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
    assert "composite MethodCollisionComposite client name collisions" in (
        completed.stderr
    )
    assert "fire:" in completed.stderr
    assert "CompositeMethodLeftInterface" in completed.stderr
    assert "CompositeMethodRightInterface" in completed.stderr
    assert "method_name_overrides" in completed.stderr


def test_codegen_aliases_colliding_operations_across_all_client_time_models() -> None:
    completed = _render_surface(
        "CompositeMethodLeftInterface",
        "CompositeMethodRightInterface",
        composite_name="MethodComposite",
        method_name_overrides=(
            ("CompositeMethodLeftInterface", "fire", "fire_left"),
            ("CompositeMethodRightInterface", "fire", "fire_right"),
        ),
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-aliased-operation-composite>", "exec")
    assert completed.stdout.count("    def fire_left(") == 3
    assert completed.stdout.count("    def fire_right(") == 3
    assert completed.stdout.count("self._clients[entity].fire_left(") == 1
    assert completed.stdout.count("self._clients[entity].fire_right(") == 1
    assert '_COMPOSITE_METHOD_LEFT_REF.operation("left_fire")' in completed.stdout
    assert '_COMPOSITE_METHOD_RIGHT_REF.operation("right_fire")' in completed.stdout


def test_codegen_requires_explicit_names_for_colliding_acquisition_carriers() -> None:
    completed = _render_surface(
        "CompositeAcquisitionLeftInterface",
        "CompositeAcquisitionRightInterface",
        composite_name="AcquisitionComposite",
        method_name_overrides=(
            ("CompositeAcquisitionLeftInterface", "sample", "sample_left"),
            ("CompositeAcquisitionRightInterface", "sample", "sample_right"),
        ),
    )

    assert completed.returncode != 0
    assert "generated symbol collisions" in completed.stderr
    assert "CompositeSampleReadback" in completed.stderr
    assert "CompositeSampleProducts" in completed.stderr


def test_codegen_names_colliding_acquisition_carriers_by_declaration() -> None:
    completed = _render_surface(
        "CompositeAcquisitionLeftInterface",
        "CompositeAcquisitionRightInterface",
        composite_name="AcquisitionComposite",
        method_name_overrides=(
            ("CompositeAcquisitionLeftInterface", "sample", "sample_left"),
            ("CompositeAcquisitionRightInterface", "sample", "sample_right"),
        ),
        acquisition_names=(
            (
                "CompositeAcquisitionLeftInterface",
                "sample",
                "LeftSampleReadback",
                "LeftSampleProducts",
            ),
            (
                "CompositeAcquisitionRightInterface",
                "sample",
                "RightSampleReadback",
                "RightSampleProducts",
            ),
        ),
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-aliased-acquisition-composite>", "exec")
    assert completed.stdout.count("    def sample_left(") == 3
    assert completed.stdout.count("    def sample_right(") == 3
    assert "client.sample_left(id=id)" in completed.stdout
    assert "client.sample_right(id=id)" in completed.stdout
    assert "class LeftSampleReadback:" in completed.stdout
    assert "class LeftSampleProducts(ProductBundle):" in completed.stdout
    assert "class RightSampleReadback:" in completed.stdout
    assert "class RightSampleProducts(ProductBundle):" in completed.stdout
    assert (
        '_COMPOSITE_ACQUISITION_LEFT_REF.acquisition("left_sample")' in completed.stdout
    )
    assert (
        '_COMPOSITE_ACQUISITION_RIGHT_REF.acquisition("right_sample")'
        in completed.stdout
    )


def test_codegen_rejects_member_and_method_names_that_share_a_client_slot() -> None:
    completed = _render_surface(
        "DriverSourceInterface",
        "CompositeEnabledMethodInterface",
        composite_name="SourceEnabledComposite",
    )

    assert completed.returncode != 0
    assert "composite SourceEnabledComposite client name collisions" in (
        completed.stderr
    )
    assert "property enabled" in completed.stderr
    assert "operation enabled" in completed.stderr
    assert "member_name_overrides or method_name_overrides" in completed.stderr


def test_codegen_requires_explicit_names_for_composite_member_collisions() -> None:
    completed = _render_surface(
        "DriverSourceInterface",
        "DriverMonitorInterface",
        composite_name="MonitorComposite",
    )

    assert completed.returncode != 0
    assert "composite MonitorComposite member name collision 'enabled'" in (
        completed.stderr
    )
    assert "member_name_overrides" in completed.stderr


def test_codegen_aliases_colliding_composite_members_across_the_client_view() -> None:
    completed = _render_surface(
        "DriverSourceInterface",
        "DriverMonitorInterface",
        composite_name="MonitorComposite",
        driver_optional_flag="monitor",
        member_name_overrides=(
            ("DriverSourceInterface", "enabled", "source_enabled"),
            ("DriverMonitorInterface", "enabled", "monitor_enabled"),
        ),
    )

    assert completed.returncode == 0, completed.stderr
    compile(completed.stdout, "<generated-aliased-composite>", "exec")
    assert "MonitorCompositePatch" in completed.stdout
    assert "source_enabled: bool = ..." in completed.stdout
    assert "monitor_enabled: bool = ..." in completed.stdout
    assert "def source_enabled(self) -> InstrumentMemberClient[bool]:" in (
        completed.stdout
    )
    assert "def monitor_enabled(self) -> InstrumentMemberClient[bool]:" in (
        completed.stdout
    )
    assert '"source_enabled",' in completed.stdout
    assert '"monitor_enabled",' in completed.stdout
