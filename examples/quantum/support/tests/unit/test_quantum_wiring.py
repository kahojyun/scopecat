from __future__ import annotations

from scopecat.config.profile_validation import validate_config_profile
from scopecat_quantum._ids import QubitId
from scopecat_quantum.pulses import AcquireSignal, DriveSignal

from quantum_lab_demo.targets.fake_list_mode import configured_fake_list_target
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile


def test_quantum_wiring_config_drives_fake_target_channel_bindings() -> None:
    config = quantum_wiring_config_profile()
    target = configured_fake_list_target(config)
    q0 = QubitId("q0")
    drive = target.output_channel(DriveSignal(q0))
    acquisition = target.acquisition_channel(AcquireSignal(q0))

    assert validate_config_profile(config) == ()
    assert config.domain_target is not None
    assert target.id.value == config.domain_target.id
    assert drive is not None
    assert drive.value == "drive-stack:drive.awg0.ch1:q0"
    assert acquisition is not None
    assert acquisition.value == "readout-stack:readout.mux0:q0"
