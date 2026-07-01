from __future__ import annotations

import pytest
from demo_lab_test_paths import READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE
from scopecat.instruments import NativeDriverDiagnostic, NativeStateChange

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
