from __future__ import annotations

import socket
import subprocess
import sys
from threading import Thread
from typing import cast

import pytest
from scopecat.kernel.entity import EntityRef
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentBindingSpec,
    InstrumentConnection,
    InstrumentRegistry,
    InstrumentSpec,
    SystemSpec,
    TcpipSocketInstrumentConnection,
    Topology,
    VirtualInstrumentConnection,
    instrument_bindings,
)
from scopecat.records.parameter import ParameterCatalog, ParameterSnapshot
from scopecat.sdk.instruments import (
    DriverFault,
    InstrumentConnectionContext,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)

from scopecat_instruments.drivers import YokogawaGS200
from scopecat_instruments.provider import (
    KEYSIGHT_E5080B,
    LAKESHORE_372,
    ROHDE_SCHWARZ_SGS100A,
    SUPPORTED_DRIVER_IDS,
    VIRTUAL_DC_SOURCE,
    VIRTUAL_RF_SOURCE,
    VIRTUAL_TEMPERATURE_MONITOR,
    VIRTUAL_VNA,
    YOKOGAWA_GS200,
    ConfiguredInstrumentProvider,
)
from scopecat_instruments.virtual import VirtualDcSource


def test_driver_id_catalog_does_not_import_driver_implementations() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import scopecat_instruments.driver_ids; "
                "forbidden = ('scopecat_instruments.provider', "
                "'scopecat_instruments.drivers', "
                "'scopecat_instruments.transport'); "
                "loaded = [name for name in forbidden if name in sys.modules]; "
                "assert not loaded, loaded"
            ),
        ],
        check=True,
    )


def test_registered_driver_ids_match_the_lightweight_catalog() -> None:
    assert {
        YOKOGAWA_GS200,
        ROHDE_SCHWARZ_SGS100A,
        LAKESHORE_372,
        KEYSIGHT_E5080B,
        VIRTUAL_RF_SOURCE,
        VIRTUAL_DC_SOURCE,
        VIRTUAL_TEMPERATURE_MONITOR,
        VIRTUAL_VNA,
    } == SUPPORTED_DRIVER_IDS


class _IdnServer:
    def __init__(
        self,
        response: str,
        *,
        query_responses: dict[str, str] | None = None,
    ) -> None:
        self.query_responses = {
            "*IDN?": response,
            **({} if query_responses is None else query_responses),
        }
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
                    response = self.query_responses.get(command)
                    if response is not None:
                        connection.sendall(response.encode("ascii") + b"\n")
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


def _describe_binding(
    driver_id: str,
    connection: InstrumentConnection,
) -> InstrumentProviderDescription:
    return ConfiguredInstrumentProvider().describe(
        InstrumentProviderContext(
            bindings=(
                InstrumentBindingSpec(
                    id="device",
                    driver_id=driver_id,
                    connection=connection,
                ),
            )
        )
    )


def test_provider_probes_real_device_before_returning_driver() -> None:
    server = _IdnServer("Rohde&Schwarz,SGS100A,1419.5505k02/100001,5.00")
    config = _config(
        InstrumentSpec(
            id="lo",
            exclusivity_key="lo",
            driver_id=ROHDE_SCHWARZ_SGS100A,
            connection=TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=server.port,
            ),
            run_start="preserve",
        )
    )

    driver = ConfiguredInstrumentProvider().connect(
        InstrumentConnectionContext(binding=instrument_bindings(config)[0])
    )

    assert driver.instrument_id == "lo"
    assert server.commands == ["*IDN?"]
    driver.disconnect()


def test_provider_rejects_wrong_device_identity() -> None:
    server = _IdnServer("OTHER,NOT_AN_SGS,123,1")
    config = _config(
        InstrumentSpec(
            id="lo",
            exclusivity_key="lo",
            driver_id=ROHDE_SCHWARZ_SGS100A,
            connection=TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=server.port,
            ),
            run_start="preserve",
        )
    )

    with pytest.raises(DriverFault) as caught:
        ConfiguredInstrumentProvider().connect(
            InstrumentConnectionContext(binding=instrument_bindings(config)[0])
        )

    assert caught.value.problem.code == "instrument_connection_failed"
    assert server.commands == ["*IDN?"]


def test_provider_connects_gs200_with_verified_monitor_profile() -> None:
    server = _IdnServer(
        "YOKOGAWA,GS200,91X000001,2.03",
        query_responses={
            "*OPT?": "/MON",
            ":SENS:REM?": "1",
            ":SENS:GUAR?": "0",
        },
    )
    config = _config(
        InstrumentSpec(
            id="bias",
            exclusivity_key="bias",
            driver_id=YOKOGAWA_GS200,
            connection=TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=server.port,
                options={
                    "monitor_option": True,
                    "remote_sense": True,
                    "guard_enabled": False,
                },
            ),
            run_start="preserve",
        )
    )

    driver = ConfiguredInstrumentProvider().connect(
        InstrumentConnectionContext(binding=instrument_bindings(config)[0])
    )

    assert isinstance(driver, YokogawaGS200)
    assert driver.monitor_option is True
    assert driver.remote_sense is True
    assert driver.guard_enabled is False
    assert server.commands == [
        "*IDN?",
        "*OPT?",
        ":SENS:REM?",
        ":SENS:GUAR?",
    ]
    driver.disconnect()


def test_provider_rejects_gs200_without_requested_monitor_option() -> None:
    server = _IdnServer(
        "YOKOGAWA,GS200,91X000001,2.03",
        query_responses={"*OPT?": "0"},
    )
    config = _config(
        InstrumentSpec(
            id="bias",
            exclusivity_key="bias",
            driver_id=YOKOGAWA_GS200,
            connection=TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=server.port,
                options={"monitor_option": True},
            ),
            run_start="preserve",
        )
    )

    with pytest.raises(DriverFault) as caught:
        ConfiguredInstrumentProvider().connect(
            InstrumentConnectionContext(binding=instrument_bindings(config)[0])
        )

    assert caught.value.problem.code == "instrument_connection_failed"
    assert server.commands == ["*IDN?", "*OPT?"]


@pytest.mark.parametrize(
    ("driver_id", "connection"),
    [
        (
            YOKOGAWA_GS200,
            TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=5025,
                options={"monitor_option": "yes"},
            ),
        ),
        (
            KEYSIGHT_E5080B,
            TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=5025,
                options={"channel": 0},
            ),
        ),
        (
            VIRTUAL_DC_SOURCE,
            VirtualInstrumentConnection(options={"seed": 7}),
        ),
    ],
)
def test_provider_validates_registered_options(
    driver_id: str,
    connection: InstrumentConnection,
) -> None:
    description = _describe_binding(driver_id, connection)
    assert description.instruments == ()
    assert description.problems[0].code == "instrument_driver_configuration_invalid"


@pytest.mark.parametrize(
    ("driver_id", "connection"),
    [
        (
            VIRTUAL_DC_SOURCE,
            TcpipSocketInstrumentConnection(host="127.0.0.1", port=5025),
        ),
        (
            ROHDE_SCHWARZ_SGS100A,
            VirtualInstrumentConnection(),
        ),
    ],
)
def test_provider_uses_the_registered_connection_kind(
    driver_id: str,
    connection: InstrumentConnection,
) -> None:
    description = _describe_binding(driver_id, connection)
    assert description.instruments == ()
    assert description.problems[0].code == "instrument_driver_configuration_invalid"


def test_virtual_state_survives_driver_recreation() -> None:
    config = _config(
        InstrumentSpec(
            id="flux",
            exclusivity_key="flux",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_start="preserve",
        ),
        InstrumentSpec(
            id="unused",
            exclusivity_key="unused",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_start="preserve",
        ),
    )
    provider = ConfiguredInstrumentProvider(seed=17)
    context = InstrumentConnectionContext(
        binding=instrument_bindings(config)[0],
    )

    description = provider.describe(
        InstrumentProviderContext(bindings=instrument_bindings(config))
    )
    first = provider.connect(context)
    assert isinstance(first, VirtualDcSource)
    first.set_voltage_level(0.2)
    first.set_output(True)
    first.disconnect()
    second = provider.connect(context)

    assert [item.instrument_id for item in description.instruments] == [
        "flux",
        "unused",
    ]
    assert isinstance(second, VirtualDcSource)
    assert second.output_enabled() is True
    assert provider.world.flux_bias() == 0.8


def test_provider_connects_exact_requested_instrument() -> None:
    config = _config(
        InstrumentSpec(
            id="a",
            exclusivity_key="a",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_start="preserve",
        ),
        InstrumentSpec(
            id="b",
            exclusivity_key="b",
            driver_id=VIRTUAL_DC_SOURCE,
            connection=VirtualInstrumentConnection(),
            run_start="preserve",
        ),
    )
    provider = ConfiguredInstrumentProvider()
    bindings = instrument_bindings(config)
    description = provider.describe(InstrumentProviderContext(bindings=bindings))
    driver = provider.connect(InstrumentConnectionContext(binding=bindings[1]))

    assert [item.instrument_id for item in description.instruments] == ["a", "b"]
    assert driver.instrument_id == "b"
    driver.disconnect()
