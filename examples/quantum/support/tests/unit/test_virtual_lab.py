from __future__ import annotations

import pytest
from demo_lab_test_paths import READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE
from scopecat.instruments import NativeDriverDiagnostic, NativeStateChange
from scopecat.instruments.state import StatePatchField, StateValue
from scopecat.models.parameter import Quantity

from quantum_lab_demo.virtual_lab import load_virtual_lab_profile
from quantum_lab_demo.virtual_lab.devices import VirtualDevice
from quantum_lab_demo.virtual_lab.models import VirtualDeviceProfile


def test_virtual_lab_profile_loads_configured_devices_and_responses() -> None:
    profile = load_virtual_lab_profile(READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE)

    assert profile.id == "quantum_lab_demo.readout_frequency.virtual_lab"
    assert profile.device_profile("readout-stack").response_model_id == (
        "readout-frequency-response"
    )
    assert profile.response_profile("readout-frequency-response").kind == (
        "readout_frequency_response"
    )


def test_virtual_device_apply_records_patch_and_updates_state() -> None:
    device = VirtualDevice(VirtualDeviceProfile(id="readout-stack", kind="readout"))
    value = StateValue(
        kind="quantity",
        quantity=Quantity(value=5.953, unit="GHz"),
    )

    device.apply(
        NativeStateChange(
            instrument_id="readout-stack",
            fields=(
                StatePatchField(
                    resource_id="readout-stack",
                    capability_id="readout_pulse",
                    field_path="frequency",
                    after=value,
                ),
            ),
        )
    )

    assert device.quantity("readout_pulse", "frequency") == value.quantity
    assert len(device.patch_log) == 1
    assert device.patch_log[0].capability_id == "readout_pulse"
    assert device.patch_log[0].field_path == "frequency"
    assert device.patch_log[0].before is None
    assert device.patch_log[0].after == value


def test_virtual_device_rejects_patch_for_other_instrument() -> None:
    device = VirtualDevice(VirtualDeviceProfile(id="readout-stack", kind="readout"))

    with pytest.raises(NativeDriverDiagnostic) as error:
        device.apply(
            NativeStateChange(
                instrument_id="drive-stack",
                fields=(),
            )
        )

    assert error.value.code == "virtual_lab_device_mismatch"
