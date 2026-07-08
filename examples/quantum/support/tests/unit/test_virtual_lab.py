from __future__ import annotations

import pytest
from demo_lab_test_paths import EXPERIMENT_VIRTUAL_LAB_PROFILE
from scopecat.instruments import DriverDiagnostic, InstrumentStateCommand

from quantum_lab_demo.virtual_lab import load_virtual_lab_profile
from quantum_lab_demo.virtual_lab.devices import VirtualDevice
from quantum_lab_demo.virtual_lab.models import VirtualDeviceProfile


def test_virtual_lab_profile_loads_configured_devices_and_responses() -> None:
    profile = load_virtual_lab_profile(EXPERIMENT_VIRTUAL_LAB_PROFILE)

    assert profile.id == "quantum_lab_demo.experiments_templates.virtual_lab"
    assert profile.device_profile("readout-stack").response_model_id is None
    assert profile.response_models == []


def test_virtual_device_rejects_patch_for_other_instrument() -> None:
    device = VirtualDevice(VirtualDeviceProfile(id="readout-stack", kind="readout"))

    with pytest.raises(DriverDiagnostic) as error:
        device.apply(
            InstrumentStateCommand(
                instrument_id="drive-stack",
                fields=[],
            )
        )

    assert error.value.code == "virtual_lab_device_mismatch"
