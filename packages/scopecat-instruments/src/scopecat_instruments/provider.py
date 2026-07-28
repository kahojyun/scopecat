"""Config-driven provider for real and virtual instrument drivers."""

from __future__ import annotations

from contextlib import suppress

from scopecat.records.config import (
    InstrumentSpec,
    TcpipSocketInstrumentConnection,
    VirtualInstrumentConnection,
)
from scopecat.sdk.instruments import (
    DriverFault,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from scopecat.sdk.problems import Problem

from scopecat_instruments._support import ScpiIdentity, provider_problem
from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.transport import ScpiTransport, TcpScpiTransport
from scopecat_instruments.virtual import (
    VirtualDcSource,
    VirtualLabWorld,
    VirtualNetworkAnalyzer,
    VirtualRfSource,
    VirtualTemperatureMonitor,
)

YOKOGAWA_GS200 = YokogawaGS200.implementation_id
ROHDE_SCHWARZ_SGS100A = RohdeSchwarzSGS100A.implementation_id
LAKESHORE_372 = LakeShore372.implementation_id
KEYSIGHT_E5080B = KeysightE5080B.implementation_id
VIRTUAL_RF_SOURCE = VirtualRfSource.implementation_id
VIRTUAL_DC_SOURCE = VirtualDcSource.implementation_id
VIRTUAL_TEMPERATURE_MONITOR = VirtualTemperatureMonitor.implementation_id
VIRTUAL_VNA = VirtualNetworkAnalyzer.implementation_id

SUPPORTED_DRIVER_IDS = frozenset(
    {
        YOKOGAWA_GS200,
        ROHDE_SCHWARZ_SGS100A,
        LAKESHORE_372,
        KEYSIGHT_E5080B,
        VIRTUAL_RF_SOURCE,
        VIRTUAL_DC_SOURCE,
        VIRTUAL_TEMPERATURE_MONITOR,
        VIRTUAL_VNA,
    }
)

type _ConfiguredDriver = (
    YokogawaGS200
    | RohdeSchwarzSGS100A
    | LakeShore372
    | KeysightE5080B
    | VirtualRfSource
    | VirtualDcSource
    | VirtualTemperatureMonitor
    | VirtualNetworkAnalyzer
)


class ConfiguredInstrumentProvider:
    """Instantiate exactly the drivers declared by an accepted config snapshot.

    Every new real connection is probed with ``*IDN?`` before it is returned.
    Virtual driver instances share the provider's world, so device state survives
    connection retirement and recreation.
    """

    provider_id = "scopecat.instruments.configured"

    def __init__(
        self,
        *,
        world: VirtualLabWorld | None = None,
        seed: int = 0,
    ) -> None:
        self.world = world if world is not None else VirtualLabWorld(seed=seed)

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        specifications = list(enumerate(context.config.instrument_registry.instruments))
        problems: list[Problem] = []
        descriptions: list[InstrumentDescription] = []
        for index, spec in specifications:
            try:
                driver = self._build_driver(
                    spec,
                    transport=self._transport_for(spec),
                )
                descriptions.append(driver.describe())
            except Exception as error:
                problems.append(_configuration_problem(spec, index, error))
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(descriptions),
            problems=tuple(problems),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        indexed = list(enumerate(context.config.instrument_registry.instruments))
        by_id = {spec.id: (index, spec) for index, spec in indexed}
        selected = by_id.get(context.instrument_id)
        if selected is None:
            raise DriverFault(
                provider_problem(
                    "instrument_provider_unknown_instrument",
                    f"configured instrument does not exist: {context.instrument_id}",
                    "context",
                    "instrument_id",
                    details={"instrument_id": context.instrument_id},
                )
            )
        index, spec = selected
        driver: _ConfiguredDriver | None = None
        try:
            transport = self._transport_for(spec)
            driver = self._build_driver(spec, transport=transport)
            self._probe_real_driver(driver)
            return driver
        except Exception as error:
            if driver is not None:
                with suppress(Exception):
                    driver.disconnect()
            if isinstance(error, DriverFault):
                raise
            raise DriverFault(_connection_problem(spec, index, error)) from error

    def _transport_for(self, spec: InstrumentSpec) -> ScpiTransport:
        if spec.driver_id not in SUPPORTED_DRIVER_IDS:
            raise ValueError(f"unsupported instrument driver_id {spec.driver_id!r}")
        if spec.driver_id.startswith("scopecat.virtual."):
            if not isinstance(spec.connection, VirtualInstrumentConnection):
                raise ValueError(f"{spec.driver_id} requires a virtual connection")
            return _NoIoTransport()
        connection = spec.connection
        if not isinstance(connection, TcpipSocketInstrumentConnection):
            raise ValueError(
                f"{spec.driver_id} v1 supports only tcpip_socket connections"
            )
        return TcpScpiTransport(
            connection.host,
            connection.port,
            timeout_seconds=connection.timeout_seconds,
        )

    def _build_driver(
        self,
        spec: InstrumentSpec,
        *,
        transport: ScpiTransport,
    ) -> _ConfiguredDriver:
        driver_id = spec.driver_id
        if driver_id == YOKOGAWA_GS200:
            _check_options(spec, {"monitor_option"})
            return YokogawaGS200(
                spec.id,
                transport,
                monitor_option=_bool_option(
                    spec,
                    "monitor_option",
                    default=False,
                ),
            )
        if driver_id == ROHDE_SCHWARZ_SGS100A:
            _check_options(spec, set())
            return RohdeSchwarzSGS100A(spec.id, transport)
        if driver_id == LAKESHORE_372:
            _check_options(spec, set())
            return LakeShore372(spec.id, transport)
        if driver_id == KEYSIGHT_E5080B:
            _check_options(spec, {"channel", "measurement"})
            return KeysightE5080B(
                spec.id,
                transport,
                channel=_int_option(spec, "channel", default=1),
                measurement=_int_option(spec, "measurement", default=1),
            )
        if driver_id == VIRTUAL_RF_SOURCE:
            _require_virtual(spec)
            _check_options(spec, set())
            return VirtualRfSource(spec.id, self.world)
        if driver_id == VIRTUAL_DC_SOURCE:
            _require_virtual(spec)
            _check_options(spec, set())
            return VirtualDcSource(spec.id, self.world)
        if driver_id == VIRTUAL_TEMPERATURE_MONITOR:
            _require_virtual(spec)
            _check_options(spec, set())
            return VirtualTemperatureMonitor(spec.id, self.world)
        if driver_id == VIRTUAL_VNA:
            _require_virtual(spec)
            _check_options(spec, set())
            return VirtualNetworkAnalyzer(spec.id, self.world)
        raise AssertionError(f"unreachable supported driver_id {driver_id!r}")

    @staticmethod
    def _probe_real_driver(
        driver: _ConfiguredDriver,
    ) -> ScpiIdentity | None:
        if isinstance(driver, YokogawaGS200):
            return driver.identify()
        if isinstance(driver, RohdeSchwarzSGS100A):
            return driver.identify()
        if isinstance(driver, LakeShore372):
            return driver.identify()
        if isinstance(driver, KeysightE5080B):
            return driver.identify()
        return None


class _NoIoTransport:
    def write(self, command: str) -> None:
        raise RuntimeError(f"description-only transport cannot write {command!r}")

    def query(self, command: str) -> str:
        raise RuntimeError(f"description-only transport cannot query {command!r}")

    def close(self) -> None:
        pass


def _require_virtual(spec: InstrumentSpec) -> None:
    if not isinstance(spec.connection, VirtualInstrumentConnection):
        raise ValueError(f"{spec.driver_id} requires a virtual connection")


def _check_options(spec: InstrumentSpec, supported: set[str]) -> None:
    unknown = sorted(set(spec.connection.options) - supported)
    if unknown:
        raise ValueError(
            f"unsupported {spec.driver_id} connection options: {', '.join(unknown)}"
        )


def _bool_option(spec: InstrumentSpec, key: str, *, default: bool) -> bool:
    value = spec.connection.options.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{spec.driver_id} option {key!r} must be boolean")
    return value


def _int_option(spec: InstrumentSpec, key: str, *, default: int) -> int:
    value = spec.connection.options.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{spec.driver_id} option {key!r} must be an integer")
    return value


def _configuration_problem(
    spec: InstrumentSpec,
    index: int,
    error: Exception,
) -> Problem:
    return provider_problem(
        "instrument_driver_configuration_invalid",
        f"invalid driver configuration for {spec.id} ({type(error).__name__})",
        "config",
        "system",
        "instrument_registry",
        "instruments",
        index,
        details={
            "instrument_id": spec.id,
            "driver_id": spec.driver_id,
            "exception_type": (f"{type(error).__module__}.{type(error).__qualname__}"),
        },
    )


def _connection_problem(
    spec: InstrumentSpec,
    index: int,
    error: Exception,
) -> Problem:
    return provider_problem(
        "instrument_connection_failed",
        f"could not open and identify {spec.id} ({type(error).__name__})",
        "config",
        "system",
        "instrument_registry",
        "instruments",
        index,
        "connection",
        details={
            "instrument_id": spec.id,
            "driver_id": spec.driver_id,
            "exception_type": (f"{type(error).__module__}.{type(error).__qualname__}"),
        },
    )


__all__ = [
    "KEYSIGHT_E5080B",
    "LAKESHORE_372",
    "ROHDE_SCHWARZ_SGS100A",
    "SUPPORTED_DRIVER_IDS",
    "VIRTUAL_DC_SOURCE",
    "VIRTUAL_RF_SOURCE",
    "VIRTUAL_TEMPERATURE_MONITOR",
    "VIRTUAL_VNA",
    "YOKOGAWA_GS200",
    "ConfiguredInstrumentProvider",
]
