from __future__ import annotations

import socket
from threading import Thread
from typing import cast

from scopecat.kernel.entity import EntityRef
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentRegistry,
    InstrumentSpec,
    PreserveRunPreparation,
    SystemSpec,
    TcpipSocketInstrumentConnection,
    Topology,
    VirtualInstrumentConnection,
)
from scopecat.records.parameter import ParameterCatalog, ParameterSnapshot
from scopecat.sdk.instruments import InstrumentProviderContext

from scopecat_instruments.provider import (
    ROHDE_SCHWARZ_SGS100A,
    VIRTUAL_DC_SOURCE,
    ConfiguredInstrumentProvider,
)
from scopecat_instruments.virtual import VirtualDcSource


class _IdnServer:
    def __init__(self, response: str) -> None:
        self.response = response
        self.commands: list[str] = []
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        address = cast("tuple[str, int]", self._server.getsockname())
        self.port: int = address[1]
        self._thread = Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        connection, _address = cast(
            "tuple[socket.socket, object]",
            self._server.accept(),
        )
        with connection:
            buffer = bytearray()
            while True:
                chunk = connection.recv(1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    command = line.decode("ascii")
                    self.commands.append(command)
                    if command == "*IDN?":
                        connection.sendall(self.response.encode("ascii") + b"\n")
        self._server.close()


def _config(*specs: InstrumentSpec) -> ConfigProfileSnapshot:
    return ConfigProfileSnapshot(
        id="test",
        system=SystemSpec(
            id="test-system",
            primary_entity_id="lab",
            topology=Topology(entities=[EntityRef(id="lab", kind="lab")]),
            instrument_registry=InstrumentRegistry(instruments=list(specs)),
            domain_target=None,
            parameter_catalog=ParameterCatalog(id="empty", definitions=[]),
        ),
        parameter_snapshot=ParameterSnapshot(id="empty", values=[]),
    )


def test_provider_probes_real_device_before_returning_driver() -> None:
    server = _IdnServer("Rohde&Schwarz,SGS100A,1419.5505k02/100001,5.00")
    config = _config(
        InstrumentSpec(
            id="lo",
            driver_id=ROHDE_SCHWARZ_SGS100A,
            connection=TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=server.port,
            ),
            run_preparation=PreserveRunPreparation(),
        )
    )

    result = ConfiguredInstrumentProvider().provide(
        InstrumentProviderContext(config=config)
    )

    assert not result.problems
    assert len(result.drivers) == 1
    identities = result.metadata["identities"]
    assert isinstance(identities, dict)
    identity = identities["lo"]
    assert isinstance(identity, str)
    assert identity.startswith("Rohde&Schwarz")
    assert server.commands == ["*IDN?"]
    result.drivers[0].disconnect()


def test_provider_rejects_wrong_device_identity() -> None:
    server = _IdnServer("OTHER,NOT_AN_SGS,123,1")
    config = _config(
        InstrumentSpec(
            id="lo",
            driver_id=ROHDE_SCHWARZ_SGS100A,
            connection=TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=server.port,
            ),
            run_preparation=PreserveRunPreparation(),
        )
    )

    result = ConfiguredInstrumentProvider().provide(
        InstrumentProviderContext(config=config)
    )

    assert not result.drivers
    assert result.problems[0].code == "instrument_connection_failed"
    assert server.commands == ["*IDN?"]


def test_provider_subset_and_virtual_state_survive_sessions() -> None:
    config = _config(
        InstrumentSpec(
            id="flux",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_preparation=PreserveRunPreparation(),
        ),
        InstrumentSpec(
            id="unused",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_preparation=PreserveRunPreparation(),
        ),
    )
    provider = ConfiguredInstrumentProvider(seed=17)
    context = InstrumentProviderContext(
        config=config,
        instrument_ids=("flux",),
    )

    description = provider.describe(context)
    first_result = provider.provide(context)
    first = first_result.drivers[0]
    assert isinstance(first, VirtualDcSource)
    first.set_voltage_level(0.2)
    first.set_output(True)
    first.disconnect()
    second_result = provider.provide(context)
    second = second_result.drivers[0]

    assert [item.instrument_id for item in description.instruments] == ["flux"]
    assert len(first_result.drivers) == 1
    assert isinstance(second, VirtualDcSource)
    assert second.output_enabled() is True
    assert provider.world.flux_bias() == 0.8


def test_provider_returns_requested_subset_in_context_order() -> None:
    config = _config(
        InstrumentSpec(
            id="a",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_preparation=PreserveRunPreparation(),
        ),
        InstrumentSpec(
            id="b",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_preparation=PreserveRunPreparation(),
        ),
    )
    provider = ConfiguredInstrumentProvider()
    context = InstrumentProviderContext(
        config=config,
        instrument_ids=("b", "a"),
    )

    description = provider.describe(context)
    result = provider.provide(context)

    assert [item.instrument_id for item in description.instruments] == ["b", "a"]
    assert [driver.instrument_id for driver in result.drivers] == ["b", "a"]
