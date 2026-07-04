from __future__ import annotations

from pathlib import Path

import scopecat as sc
from demo_lab_test_paths import (
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
    READOUT_IQ_FIXTURE_DIR,
    READOUT_IQ_VIRTUAL_LAB_PROFILE,
)
from scopecat.config_profiles import load_config_profile
from scopecat.experiments import acquire, experiment
from scopecat.instruments.sdk import InstrumentProviderContext
from scopecat.relations import grid, values

from quantum_lab_demo.readout import frequency_calibration, iq_quality
from quantum_lab_demo.virtual_lab.provider import (
    ReadoutFrequencyVirtualProvider,
    ReadoutIQVirtualProvider,
)


def readout_frequency_lab(*, workspace: Path) -> sc.Workspace:
    return sc.open(
        workspace,
        config_profile=READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json",
        instrument_provider=ReadoutFrequencyVirtualProvider(
            profile=READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
        ),
    )


def readout_iq_lab(*, workspace: Path) -> sc.Workspace:
    return sc.open(
        workspace,
        config_profile=READOUT_IQ_FIXTURE_DIR / "config-profile.json",
        instrument_provider=ReadoutIQVirtualProvider(
            profile=READOUT_IQ_VIRTUAL_LAB_PROFILE,
        ),
    )


def test_quantum_providers_return_fresh_instruments() -> None:
    provider_experiment = experiment(
        id="provider-context",
        kind="provider_context",
        points=grid(point=values([0])),
        acquire=acquire("scalar"),
    )
    frr_context = InstrumentProviderContext(
        config=load_config_profile(
            READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json"
        ),
        experiment=provider_experiment,
    )
    iq_context = InstrumentProviderContext(
        config=load_config_profile(READOUT_IQ_FIXTURE_DIR / "config-profile.json"),
        experiment=provider_experiment,
    )
    frr_provider = ReadoutFrequencyVirtualProvider(
        profile=READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE
    )
    iq_provider = ReadoutIQVirtualProvider(profile=READOUT_IQ_VIRTUAL_LAB_PROFILE)
    frr_description = frr_provider.describe()
    iq_description = iq_provider.describe()

    frr_first = frr_provider.provide(frr_context)
    frr_second = frr_provider.provide(frr_context)
    iq_first = iq_provider.provide(iq_context)
    iq_second = iq_provider.provide(iq_context)

    assert frr_first.diagnostics == ()
    assert iq_first.diagnostics == ()
    assert frr_description.provider_id == (
        "quantum_lab_demo.readout_frequency_provider"
    )
    assert frr_description.provided_instrument_ids == (
        "readout-stack",
        "flux-bias-source",
    )
    assert "capture_dataset" in frr_description.capabilities
    assert frr_description.options[0].id == "virtual_lab_profile"
    assert iq_description.provider_id == ("quantum_lab_demo.readout_iq_provider")
    assert iq_description.provided_instrument_ids == ("readout-stack",)
    assert iq_description.capabilities == ("readout_pulse", "capture_shots")
    assert [instrument.instrument_id for instrument in frr_first.instruments] == [
        "readout-stack",
        "flux-bias-source",
    ]
    assert [instrument.instrument_id for instrument in iq_first.instruments] == [
        "readout-stack"
    ]
    assert frr_first.instruments[0] is not frr_second.instruments[0]
    assert frr_first.instruments[1] is not frr_second.instruments[1]
    assert iq_first.instruments[0] is not iq_second.instruments[0]


def test_readout_frequency_virtual_provider_runs_template(
    tmp_path: Path,
) -> None:
    lab = readout_frequency_lab(workspace=tmp_path)
    run = lab.run(frequency_calibration(qubit="q0"))
    measurements = run.measurements().dataset.records

    assert run.manifest.status == "completed"
    assert len(measurements) == 101


def test_readout_iq_virtual_provider_runs_template(tmp_path: Path) -> None:
    lab = readout_iq_lab(workspace=tmp_path)
    run = lab.run(iq_quality(qubit="q0"))
    measurements = run.measurements().dataset.records

    assert run.manifest.status == "completed"
    assert len(measurements) == 240
    assert measurements[0].coordinates["shot_index"].value == 0.0
    assert measurements[0].coordinates["shot_index"].unit == "count"
