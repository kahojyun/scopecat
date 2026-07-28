from __future__ import annotations

from scopecat.records.config import InstrumentBindingSpec, VirtualInstrumentConnection
from scopecat.sdk.instruments import (
    DriverInvokeRequest,
    DriverOperationArgument,
    DriverPayload,
    InstrumentConnectionContext,
    InstrumentProviderContext,
    PayloadRef,
    StateValue,
)

from quantum_lab_demo.interfaces import (
    PLAY_PULSE_PROGRAM_PLAY,
    PLAY_PULSE_PROGRAM_PROGRAM,
)
from quantum_lab_demo.virtual_lab.profiles import load_virtual_lab_profile
from quantum_lab_demo.virtual_lab.provider import (
    QuantumDriveStack,
    QuantumLabVirtualProvider,
)

from .demo_lab_test_paths import EXPERIMENT_VIRTUAL_LAB_PROFILE


def test_virtual_lab_profile_loads_configured_devices() -> None:
    profile = load_virtual_lab_profile(EXPERIMENT_VIRTUAL_LAB_PROFILE)

    assert profile.id == "quantum_lab_demo.virtual_lab"
    assert profile.format_version == "quantum_lab_demo.virtual_lab_profile.v1"
    assert tuple(device.id for device in profile.devices) == (
        "drive-stack",
        "readout-stack",
    )


def test_virtual_provider_catalog_and_connection_use_exact_bindings() -> None:
    provider = QuantumLabVirtualProvider(EXPERIMENT_VIRTUAL_LAB_PROFILE)
    binding = InstrumentBindingSpec(
        id="drive-stack",
        driver_id="quantum_lab_demo.virtual_lab.drive_stack",
        connection=VirtualInstrumentConnection(),
    )

    described = provider.describe(InstrumentProviderContext(bindings=(binding,)))
    connected = provider.connect(InstrumentConnectionContext(binding=binding))

    assert [item.instrument_id for item in described.instruments] == ["drive-stack"]
    assert connected.instrument_id == "drive-stack"
    assert connected.implementation_id == binding.driver_id
    connected.disconnect()


def test_drive_program_is_an_invocation_not_persistent_state() -> None:
    profile = load_virtual_lab_profile(EXPERIMENT_VIRTUAL_LAB_PROFILE)
    driver = QuantumDriveStack(profile=profile.devices[0])
    payload = DriverPayload(
        id="program-0",
        schema_id="pulse_program",
        codec_id="tests.json",
        codec_version=1,
        media_type="application/json",
        content=b'{"instructions":[]}',
    )
    before = driver.read_state()

    argument = DriverOperationArgument(
        id=PLAY_PULSE_PROGRAM_PROGRAM.argument_id,
        value=StateValue(PayloadRef(payload_id=payload.id)),
    )
    request = DriverInvokeRequest(
        interface_id=PLAY_PULSE_PROGRAM_PLAY.interface_id,
        component_path=PLAY_PULSE_PROGRAM_PLAY.component_path,
        operation_id=PLAY_PULSE_PROGRAM_PLAY.operation_id,
        arguments=(argument,),
        payloads={payload.id: payload},
    )
    receipt = driver.invoke(request)

    assert request.target == PLAY_PULSE_PROGRAM_PLAY
    assert request.argument_target(argument) == PLAY_PULSE_PROGRAM_PROGRAM
    assert receipt.status == "invoked"
    assert receipt.metadata["payload_count"] == 1
    assert driver.read_state() == before
