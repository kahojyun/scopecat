from __future__ import annotations

from typing import cast

import pytest
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import (
    DriverFault,
    InstrumentStateCommand,
    PayloadRef,
    StateValue,
)

from quantum_lab_demo.virtual_lab import load_virtual_lab_profile
from quantum_lab_demo.virtual_lab.devices import VirtualDevice
from quantum_lab_demo.virtual_lab.models import VirtualDeviceProfile, VirtualLabProfile

from .demo_lab_test_paths import EXPERIMENT_VIRTUAL_LAB_PROFILE


def test_virtual_lab_profile_loads_configured_devices() -> None:
    profile = load_virtual_lab_profile(EXPERIMENT_VIRTUAL_LAB_PROFILE)

    assert profile.id == "quantum_lab_demo.virtual_lab"
    assert profile.format_version == "quantum_lab_demo.virtual_lab_profile.v1"
    assert tuple(device.id for device in profile.devices) == (
        "drive-stack",
        "readout-stack",
        "coupler-stack",
    )


def test_virtual_lab_profile_round_trips_structural_initial_state() -> None:
    profile = VirtualLabProfile(
        id="test.virtual-lab",
        devices=[
            VirtualDeviceProfile(
                id="drive-stack",
                initial_state={
                    "set_gain.gain": StateValue(0.5),
                    "set_frequency.frequency": StateValue(
                        Quantity(value=5.0, unit="GHz")
                    ),
                    "play_program.program": StateValue(
                        PayloadRef(payload_id="program-a")
                    ),
                },
            )
        ],
    )

    restored = VirtualLabProfile.model_validate_json(profile.model_dump_json())
    initial_state_wire = cast(
        "object", profile.model_dump(mode="json")["devices"][0]["initial_state"]
    )

    assert restored == profile
    assert initial_state_wire == {
        "set_gain.gain": 0.5,
        "set_frequency.frequency": {"value": 5.0, "unit": "GHz"},
        "play_program.program": {"payload_id": "program-a"},
    }


def test_virtual_device_rejects_patch_for_other_instrument() -> None:
    device = VirtualDevice(VirtualDeviceProfile(id="readout-stack"))

    with pytest.raises(DriverFault) as error:
        device.apply(
            InstrumentStateCommand(
                instrument_id="drive-stack",
                fields=[],
            )
        )

    assert error.value.problem.code == "virtual_lab_device_mismatch"
