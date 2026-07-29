from __future__ import annotations

from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.config import InstrumentBindingSpec, VirtualInstrumentConnection
from scopecat.sdk.instruments import (
    DriverPayload,
    DriverSuccess,
    InstrumentConnectionContext,
    InstrumentProviderContext,
)
from scopecat.sdk.instruments.backend import (
    BackendInvokeRequest,
    BackendOperationArgument,
    BackendPayload,
    decode_driver_operation,
)

from quantum_lab_demo.backend import create_quantum_lab_backend
from quantum_lab_demo.interfaces import (
    PLAY_PULSE_PROGRAM_PLAY,
    PLAY_PULSE_PROGRAM_PROGRAM,
)
from quantum_lab_demo.payloads import PULSE_PROGRAM_SCHEMA_ID, DecodedPulseProgram
from quantum_lab_demo.virtual_lab.profiles import load_virtual_lab_profile
from quantum_lab_demo.virtual_lab.provider import (
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
    backend = create_quantum_lab_backend(EXPERIMENT_VIRTUAL_LAB_PROFILE)
    binding = InstrumentBindingSpec(
        id="drive-stack",
        driver_id="quantum_lab_demo.virtual_lab.drive_stack",
        connection=VirtualInstrumentConnection(),
    )
    driver = backend.provider.connect(InstrumentConnectionContext(binding=binding))
    encoded = backend.payload_codecs.encode(
        PULSE_PROGRAM_SCHEMA_ID,
        {"instructions": []},
    )
    payload = BackendPayload(
        id="program-0",
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )
    before = driver.read_state()

    operation = decode_driver_operation(
        BackendInvokeRequest(
            interface_id=PLAY_PULSE_PROGRAM_PLAY.interface_id,
            component_path=PLAY_PULSE_PROGRAM_PLAY.component_path,
            operation_id=PLAY_PULSE_PROGRAM_PLAY.operation_id,
            arguments=(
                BackendOperationArgument(
                    id=PLAY_PULSE_PROGRAM_PROGRAM.argument_id,
                    value=StateValue(PayloadRef(payload_id=payload.id)),
                ),
            ),
            payloads={payload.id: payload},
        ),
        backend.payload_codecs,
    )
    receipt = driver.invoke(operation)

    [argument] = operation.arguments.values()
    assert isinstance(argument, DriverPayload)
    assert argument.value == DecodedPulseProgram(
        document={"instructions": []},
    )
    assert operation.target == PLAY_PULSE_PROGRAM_PLAY
    assert operation.arguments[PLAY_PULSE_PROGRAM_PROGRAM.argument_id] == argument
    assert isinstance(receipt, DriverSuccess)
    assert receipt.metadata["payload_count"] == 1
    assert driver.read_state() == before
    driver.disconnect()
