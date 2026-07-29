"""Config-driven provider for real and virtual instrument drivers."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue
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


class _ConnectionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _NoConnectionOptions(_ConnectionOptions):
    pass


class _Gs200ConnectionOptions(_ConnectionOptions):
    monitor_option: bool = False
    remote_sense: bool = False
    guard_enabled: bool = False


class _E5080BConnectionOptions(_ConnectionOptions):
    channel: int = Field(default=1, ge=1)
    measurement: int = Field(default=1, ge=1)


class _IdentifiableDriver(InstrumentDriver, Protocol):
    def identify(self) -> ScpiIdentity: ...


@dataclass(frozen=True, slots=True)
class _TcpScpiDriverDefinition:
    driver_id: str
    create: Callable[
        [str, ScpiTransport, dict[str, JsonValue]],
        _IdentifiableDriver,
    ]


@dataclass(frozen=True, slots=True)
class _VirtualDriverDefinition:
    driver_id: str
    factory: Callable[[str, VirtualLabWorld], InstrumentDriver]


type _DriverDefinition = _TcpScpiDriverDefinition | _VirtualDriverDefinition


def _tcp_driver_definition[OptionsT: _ConnectionOptions](
    driver_id: str,
    options_type: type[OptionsT],
    factory: Callable[[str, ScpiTransport, OptionsT], _IdentifiableDriver],
) -> _TcpScpiDriverDefinition:
    def create(
        instrument_id: str,
        transport: ScpiTransport,
        raw_options: dict[str, JsonValue],
    ) -> _IdentifiableDriver:
        return factory(
            instrument_id,
            transport,
            options_type.model_validate(raw_options),
        )

    return _TcpScpiDriverDefinition(
        driver_id=driver_id,
        create=create,
    )


_DEFINITIONS: tuple[_DriverDefinition, ...] = (
    _tcp_driver_definition(
        YOKOGAWA_GS200,
        _Gs200ConnectionOptions,
        lambda instrument_id, transport, options: YokogawaGS200(
            instrument_id,
            transport,
            monitor_option=options.monitor_option,
            remote_sense=options.remote_sense,
            guard_enabled=options.guard_enabled,
        ),
    ),
    _tcp_driver_definition(
        ROHDE_SCHWARZ_SGS100A,
        _NoConnectionOptions,
        lambda instrument_id, transport, _options: RohdeSchwarzSGS100A(
            instrument_id,
            transport,
        ),
    ),
    _tcp_driver_definition(
        LAKESHORE_372,
        _NoConnectionOptions,
        lambda instrument_id, transport, _options: LakeShore372(
            instrument_id,
            transport,
        ),
    ),
    _tcp_driver_definition(
        KEYSIGHT_E5080B,
        _E5080BConnectionOptions,
        lambda instrument_id, transport, options: KeysightE5080B(
            instrument_id,
            transport,
            channel=options.channel,
            measurement=options.measurement,
        ),
    ),
    _VirtualDriverDefinition(VIRTUAL_RF_SOURCE, VirtualRfSource),
    _VirtualDriverDefinition(VIRTUAL_DC_SOURCE, VirtualDcSource),
    _VirtualDriverDefinition(
        VIRTUAL_TEMPERATURE_MONITOR,
        VirtualTemperatureMonitor,
    ),
    _VirtualDriverDefinition(VIRTUAL_VNA, VirtualNetworkAnalyzer),
)
_DRIVERS = {definition.driver_id: definition for definition in _DEFINITIONS}
SUPPORTED_DRIVER_IDS = frozenset(_DRIVERS)


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
                descriptions.append(_describe_driver(binding, self.world))
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
        try:
            return _connect_driver(binding, self.world)
        except Exception as error:
            if isinstance(error, DriverFault):
                raise
            raise DriverFault(_connection_problem(binding, error)) from error


class _DescriptionOnlyTransport:
    def write(self, command: str) -> None:
        raise RuntimeError(f"description-only transport cannot write {command!r}")

    def query(self, command: str) -> str:
        raise RuntimeError(f"description-only transport cannot query {command!r}")

    def close(self) -> None:
        pass


def _driver_definition(driver_id: str) -> _DriverDefinition:
    definition = _DRIVERS.get(driver_id)
    if definition is None:
        raise ValueError(f"unsupported instrument driver_id {driver_id!r}")
    return definition


def _describe_driver(
    binding: InstrumentBindingSpec,
    world: VirtualLabWorld,
) -> InstrumentDescription:
    definition = _driver_definition(binding.driver_id)
    if isinstance(definition, _VirtualDriverDefinition):
        return _create_virtual_driver(definition, binding, world).describe()
    connection = _require_tcp_connection(definition, binding)
    return definition.create(
        binding.id,
        _DescriptionOnlyTransport(),
        connection.options,
    ).describe()


def _connect_driver(
    binding: InstrumentBindingSpec,
    world: VirtualLabWorld,
) -> InstrumentDriver:
    definition = _driver_definition(binding.driver_id)
    if isinstance(definition, _VirtualDriverDefinition):
        return _create_virtual_driver(definition, binding, world)
    connection = _require_tcp_connection(definition, binding)
    driver = definition.create(
        binding.id,
        TcpScpiTransport(
            connection.host,
            connection.port,
            timeout_seconds=connection.timeout_seconds,
        ),
        connection.options,
    )
    try:
        driver.identify()
    except Exception:
        with suppress(Exception):
            driver.disconnect()
        raise
    return driver


def _create_virtual_driver(
    definition: _VirtualDriverDefinition,
    binding: InstrumentBindingSpec,
    world: VirtualLabWorld,
) -> InstrumentDriver:
    connection = binding.connection
    if not isinstance(connection, VirtualInstrumentConnection):
        raise ValueError(f"{definition.driver_id} requires a virtual connection")
    _NoConnectionOptions.model_validate(connection.options)
    return definition.factory(binding.id, world)


def _require_tcp_connection(
    definition: _TcpScpiDriverDefinition,
    binding: InstrumentBindingSpec,
) -> TcpipSocketInstrumentConnection:
    connection = binding.connection
    if not isinstance(connection, TcpipSocketInstrumentConnection):
        raise ValueError(
            f"{definition.driver_id} supports only tcpip_socket connections"
        )
    return connection


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
