"""Explicit generation and driver registrations for this instrument package."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Literal, cast

from scopecat_instruments.connection_options import (
    ConnectionOptions,
    E5080BConnectionOptions,
    Gs200ConnectionOptions,
    NoConnectionOptions,
)
from scopecat_instruments.interface_declarations import (
    DCMonitorInterface,
    DCSourceInterface,
    NetworkSweepInterface,
    ReferenceSource,
    RFOutputInterface,
    SParameter,
    TemperatureReadoutInterface,
)


@dataclass(frozen=True, slots=True)
class PythonSymbol:
    """One lazily resolved Python object without an eager implementation import."""

    module: str
    qualname: str

    def resolve(self) -> object:
        selected: object = import_module(self.module)
        for segment in self.qualname.split("."):
            selected = cast("object", getattr(selected, segment))
        return selected


@dataclass(frozen=True, slots=True)
class InterfaceSurfaceRegistration:
    interface_type: type[object]
    public_name_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CompositeSurfaceRegistration:
    name: str
    interface_types: tuple[type[object], ...]
    driver_optional_flag: str | None = None


type SurfaceRegistration = InterfaceSurfaceRegistration | CompositeSurfaceRegistration


@dataclass(frozen=True, slots=True)
class DriverRegistration:
    id: str
    implementation_version: str
    implementation: PythonSymbol
    connection_kind: Literal["tcpip_socket", "virtual"]
    options_type: type[ConnectionOptions]
    label: str
    manufacturer: str | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class InstrumentPackageManifest:
    provider_id: str
    surfaces: tuple[SurfaceRegistration, ...]
    public_types: tuple[object, ...]
    drivers: tuple[DriverRegistration, ...]


YOKOGAWA_GS200_DRIVER = DriverRegistration(
    id="scopecat.yokogawa.gs200",
    implementation_version="v2",
    implementation=PythonSymbol(
        "scopecat_instruments.drivers.gs200",
        "YokogawaGS200",
    ),
    connection_kind="tcpip_socket",
    options_type=Gs200ConnectionOptions,
    label="Yokogawa GS200",
    manufacturer="Yokogawa",
    model="GS200",
)
ROHDE_SCHWARZ_SGS100A_DRIVER = DriverRegistration(
    id="scopecat.rohde_schwarz.sgs100a",
    implementation_version="v1",
    implementation=PythonSymbol(
        "scopecat_instruments.drivers.sgs100a",
        "RohdeSchwarzSGS100A",
    ),
    connection_kind="tcpip_socket",
    options_type=NoConnectionOptions,
    label="Rohde & Schwarz SGS100A",
    manufacturer="Rohde & Schwarz",
    model="SGS100A",
)
LAKESHORE_372_DRIVER = DriverRegistration(
    id="scopecat.lakeshore.372",
    implementation_version="v1",
    implementation=PythonSymbol(
        "scopecat_instruments.drivers.lakeshore372",
        "LakeShore372",
    ),
    connection_kind="tcpip_socket",
    options_type=NoConnectionOptions,
    label="Lake Shore 372",
    manufacturer="Lake Shore",
    model="372",
)
KEYSIGHT_E5080B_DRIVER = DriverRegistration(
    id="scopecat.keysight.e5080b",
    implementation_version="v1",
    implementation=PythonSymbol(
        "scopecat_instruments.drivers.e5080b",
        "KeysightE5080B",
    ),
    connection_kind="tcpip_socket",
    options_type=E5080BConnectionOptions,
    label="Keysight E5080B",
    manufacturer="Keysight",
    model="E5080B",
)
VIRTUAL_RF_SOURCE_DRIVER = DriverRegistration(
    id="scopecat.virtual.rf_source",
    implementation_version="v1",
    implementation=PythonSymbol(
        "scopecat_instruments.virtual.drivers",
        "VirtualRfSource",
    ),
    connection_kind="virtual",
    options_type=NoConnectionOptions,
    label="Virtual RF source",
)
VIRTUAL_DC_SOURCE_DRIVER = DriverRegistration(
    id="scopecat.virtual.dc_source",
    implementation_version="v1",
    implementation=PythonSymbol(
        "scopecat_instruments.virtual.drivers",
        "VirtualDcSource",
    ),
    connection_kind="virtual",
    options_type=NoConnectionOptions,
    label="Virtual DC source",
)
VIRTUAL_TEMPERATURE_MONITOR_DRIVER = DriverRegistration(
    id="scopecat.virtual.temperature_monitor",
    implementation_version="v1",
    implementation=PythonSymbol(
        "scopecat_instruments.virtual.drivers",
        "VirtualTemperatureMonitor",
    ),
    connection_kind="virtual",
    options_type=NoConnectionOptions,
    label="Virtual temperature monitor",
)
VIRTUAL_VNA_DRIVER = DriverRegistration(
    id="scopecat.virtual.vna",
    implementation_version="v1",
    implementation=PythonSymbol(
        "scopecat_instruments.virtual.drivers",
        "VirtualNetworkAnalyzer",
    ),
    connection_kind="virtual",
    options_type=NoConnectionOptions,
    label="Virtual network analyzer",
)

YOKOGAWA_GS200 = YOKOGAWA_GS200_DRIVER.id
ROHDE_SCHWARZ_SGS100A = ROHDE_SCHWARZ_SGS100A_DRIVER.id
LAKESHORE_372 = LAKESHORE_372_DRIVER.id
KEYSIGHT_E5080B = KEYSIGHT_E5080B_DRIVER.id
VIRTUAL_RF_SOURCE = VIRTUAL_RF_SOURCE_DRIVER.id
VIRTUAL_DC_SOURCE = VIRTUAL_DC_SOURCE_DRIVER.id
VIRTUAL_TEMPERATURE_MONITOR = VIRTUAL_TEMPERATURE_MONITOR_DRIVER.id
VIRTUAL_VNA = VIRTUAL_VNA_DRIVER.id

PACKAGE_MANIFEST = InstrumentPackageManifest(
    provider_id="scopecat.instruments.configured",
    surfaces=(
        InterfaceSurfaceRegistration(
            TemperatureReadoutInterface,
            public_name_overrides=(("sample.readback", "TemperatureReadback"),),
        ),
        InterfaceSurfaceRegistration(RFOutputInterface),
        InterfaceSurfaceRegistration(DCSourceInterface),
        InterfaceSurfaceRegistration(DCMonitorInterface),
        CompositeSurfaceRegistration(
            name="DCSourceMonitor",
            interface_types=(DCSourceInterface, DCMonitorInterface),
            driver_optional_flag="monitor",
        ),
        InterfaceSurfaceRegistration(NetworkSweepInterface),
    ),
    public_types=(ReferenceSource, SParameter),
    drivers=(
        YOKOGAWA_GS200_DRIVER,
        ROHDE_SCHWARZ_SGS100A_DRIVER,
        LAKESHORE_372_DRIVER,
        KEYSIGHT_E5080B_DRIVER,
        VIRTUAL_RF_SOURCE_DRIVER,
        VIRTUAL_DC_SOURCE_DRIVER,
        VIRTUAL_TEMPERATURE_MONITOR_DRIVER,
        VIRTUAL_VNA_DRIVER,
    ),
)


__all__ = [
    "KEYSIGHT_E5080B",
    "KEYSIGHT_E5080B_DRIVER",
    "LAKESHORE_372",
    "LAKESHORE_372_DRIVER",
    "PACKAGE_MANIFEST",
    "ROHDE_SCHWARZ_SGS100A",
    "ROHDE_SCHWARZ_SGS100A_DRIVER",
    "VIRTUAL_DC_SOURCE",
    "VIRTUAL_DC_SOURCE_DRIVER",
    "VIRTUAL_RF_SOURCE",
    "VIRTUAL_RF_SOURCE_DRIVER",
    "VIRTUAL_TEMPERATURE_MONITOR",
    "VIRTUAL_TEMPERATURE_MONITOR_DRIVER",
    "VIRTUAL_VNA",
    "VIRTUAL_VNA_DRIVER",
    "YOKOGAWA_GS200",
    "YOKOGAWA_GS200_DRIVER",
    "CompositeSurfaceRegistration",
    "DriverRegistration",
    "InstrumentPackageManifest",
    "InterfaceSurfaceRegistration",
    "PythonSymbol",
    "SurfaceRegistration",
]
