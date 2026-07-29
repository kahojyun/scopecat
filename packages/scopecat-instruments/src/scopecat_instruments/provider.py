"""Config-driven provider for real and virtual instrument drivers."""

from __future__ import annotations

from contextlib import suppress

from scopecat.sdk.instruments import (
    DriverFault,
    InstrumentBindingSpec,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    TcpipSocketInstrumentConnection,
    VirtualInstrumentConnection,
)
from scopecat.sdk.instruments.scpi import ScpiIdentity, ScpiTransport
from scopecat.sdk.problems import Problem

from scopecat_instruments._support import provider_problem
from scopecat_instruments.driver_ids import (
    KEYSIGHT_E5080B,
    LAKESHORE_372,
    ROHDE_SCHWARZ_SGS100A,
    SUPPORTED_DRIVER_IDS,
    VIRTUAL_DC_SOURCE,
    VIRTUAL_RF_SOURCE,
    VIRTUAL_TEMPERATURE_MONITOR,
    VIRTUAL_VNA,
    YOKOGAWA_GS200,
)
from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.transport import TcpScpiTransport
from scopecat_instruments.virtual import (
    VirtualDcSource,
    VirtualLabWorld,
    VirtualNetworkAnalyzer,
    VirtualRfSource,
    VirtualTemperatureMonitor,
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
    """Instantiate exactly the drivers declared by configured bindings.

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
        problems: list[Problem] = []
        descriptions: list[InstrumentDescription] = []
        for index, binding in enumerate(context.bindings):
            try:
                driver = self._build_driver(
                    binding,
                    transport=self._transport_for(binding),
                )
                descriptions.append(driver.describe())
            except Exception as error:
                problems.append(_configuration_problem(binding, index, error))
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(descriptions),
            problems=tuple(problems),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        binding = context.binding
        driver: _ConfiguredDriver | None = None
        try:
            transport = self._transport_for(binding)
            driver = self._build_driver(binding, transport=transport)
            self._probe_real_driver(driver)
            return driver
        except Exception as error:
            if driver is not None:
                with suppress(Exception):
                    driver.disconnect()
            if isinstance(error, DriverFault):
                raise
            raise DriverFault(_connection_problem(binding, error)) from error

    def _transport_for(self, binding: InstrumentBindingSpec) -> ScpiTransport:
        if binding.driver_id not in SUPPORTED_DRIVER_IDS:
            raise ValueError(f"unsupported instrument driver_id {binding.driver_id!r}")
        if binding.driver_id.startswith("scopecat.virtual."):
            if not isinstance(binding.connection, VirtualInstrumentConnection):
                raise ValueError(f"{binding.driver_id} requires a virtual connection")
            return _NoIoTransport()
        connection = binding.connection
        if not isinstance(connection, TcpipSocketInstrumentConnection):
            raise ValueError(
                f"{binding.driver_id} v1 supports only tcpip_socket connections"
            )
        return TcpScpiTransport(
            connection.host,
            connection.port,
            timeout_seconds=connection.timeout_seconds,
        )

    def _build_driver(
        self,
        binding: InstrumentBindingSpec,
        *,
        transport: ScpiTransport,
    ) -> _ConfiguredDriver:
        driver_id = binding.driver_id
        if driver_id == YOKOGAWA_GS200:
            _check_options(
                binding,
                {"monitor_option", "remote_sense", "guard_enabled"},
            )
            return YokogawaGS200(
                binding.id,
                transport,
                monitor_option=_bool_option(
                    binding,
                    "monitor_option",
                    default=False,
                ),
                remote_sense=_bool_option(
                    binding,
                    "remote_sense",
                    default=False,
                ),
                guard_enabled=_bool_option(
                    binding,
                    "guard_enabled",
                    default=False,
                ),
            )
        if driver_id == ROHDE_SCHWARZ_SGS100A:
            _check_options(binding, set())
            return RohdeSchwarzSGS100A(binding.id, transport)
        if driver_id == LAKESHORE_372:
            _check_options(binding, set())
            return LakeShore372(binding.id, transport)
        if driver_id == KEYSIGHT_E5080B:
            _check_options(binding, {"channel", "measurement"})
            return KeysightE5080B(
                binding.id,
                transport,
                channel=_int_option(binding, "channel", default=1),
                measurement=_int_option(binding, "measurement", default=1),
            )
        if driver_id == VIRTUAL_RF_SOURCE:
            _require_virtual(binding)
            _check_options(binding, set())
            return VirtualRfSource(binding.id, self.world)
        if driver_id == VIRTUAL_DC_SOURCE:
            _require_virtual(binding)
            _check_options(binding, set())
            return VirtualDcSource(binding.id, self.world)
        if driver_id == VIRTUAL_TEMPERATURE_MONITOR:
            _require_virtual(binding)
            _check_options(binding, set())
            return VirtualTemperatureMonitor(binding.id, self.world)
        if driver_id == VIRTUAL_VNA:
            _require_virtual(binding)
            _check_options(binding, set())
            return VirtualNetworkAnalyzer(binding.id, self.world)
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


def _require_virtual(binding: InstrumentBindingSpec) -> None:
    if not isinstance(binding.connection, VirtualInstrumentConnection):
        raise ValueError(f"{binding.driver_id} requires a virtual connection")


def _check_options(binding: InstrumentBindingSpec, supported: set[str]) -> None:
    unknown = sorted(set(binding.connection.options) - supported)
    if unknown:
        raise ValueError(
            f"unsupported {binding.driver_id} connection options: {', '.join(unknown)}"
        )


def _bool_option(
    binding: InstrumentBindingSpec,
    key: str,
    *,
    default: bool,
) -> bool:
    value = binding.connection.options.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{binding.driver_id} option {key!r} must be boolean")
    return value


def _int_option(
    binding: InstrumentBindingSpec,
    key: str,
    *,
    default: int,
) -> int:
    value = binding.connection.options.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{binding.driver_id} option {key!r} must be an integer")
    return value


def _configuration_problem(
    binding: InstrumentBindingSpec,
    index: int,
    error: Exception,
) -> Problem:
    return provider_problem(
        "instrument_driver_configuration_invalid",
        f"invalid driver configuration for {binding.id} ({type(error).__name__})",
        "context",
        "bindings",
        index,
        details={
            "instrument_id": binding.id,
            "driver_id": binding.driver_id,
            "exception_type": (f"{type(error).__module__}.{type(error).__qualname__}"),
        },
    )


def _connection_problem(
    binding: InstrumentBindingSpec,
    error: Exception,
) -> Problem:
    return provider_problem(
        "instrument_connection_failed",
        f"could not open and identify {binding.id} ({type(error).__name__})",
        "context",
        "binding",
        "connection",
        details={
            "instrument_id": binding.id,
            "driver_id": binding.driver_id,
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
