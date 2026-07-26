from __future__ import annotations

from quantum_lab_demo.virtual_lab import load_virtual_lab_profile

from .demo_lab_test_paths import EXPERIMENT_VIRTUAL_LAB_PROFILE


def test_virtual_lab_profile_loads_configured_devices() -> None:
    profile = load_virtual_lab_profile(EXPERIMENT_VIRTUAL_LAB_PROFILE)

    assert profile.id == "quantum_lab_demo.virtual_lab"
    assert profile.format_version == "quantum_lab_demo.virtual_lab_profile.v1"
    assert tuple(device.id for device in profile.devices) == (
        "drive-stack",
        "readout-stack",
    )
