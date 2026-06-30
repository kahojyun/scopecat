"""Workspace factories for the demo quantum lab workflows."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc

from quantum_lab_demo.fixtures import (
    DEFAULT_READOUT_FREQUENCY_WORKSPACE,
    DEFAULT_READOUT_IQ_WORKSPACE,
    DEFAULT_SAMPLE_TEMPLATES_WORKSPACE,
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
    READOUT_IQ_FIXTURE_DIR,
    READOUT_IQ_VIRTUAL_LAB_PROFILE,
    SAMPLE_TEMPLATES_FIXTURE_DIR,
    SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE,
)
from quantum_lab_demo.virtual_lab.provider import (
    ReadoutFrequencyVirtualProvider,
    ReadoutIQVirtualProvider,
    SampleVirtualProvider,
)

PathInput = str | Path


def readout_frequency_lab(
    *,
    workspace: PathInput = DEFAULT_READOUT_FREQUENCY_WORKSPACE,
    config_profile: PathInput = READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json",
    virtual_lab_profile: PathInput = READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
) -> sc.Workspace:
    return sc.open(
        workspace,
        config_profile=config_profile,
        mode="native_simulate",
        native_instrument_provider=ReadoutFrequencyVirtualProvider(
            profile=virtual_lab_profile,
        ),
    )


def readout_iq_lab(
    *,
    workspace: PathInput = DEFAULT_READOUT_IQ_WORKSPACE,
    config_profile: PathInput = READOUT_IQ_FIXTURE_DIR / "config-profile.json",
    virtual_lab_profile: PathInput = READOUT_IQ_VIRTUAL_LAB_PROFILE,
) -> sc.Workspace:
    return sc.open(
        workspace,
        config_profile=config_profile,
        mode="native_simulate",
        native_instrument_provider=ReadoutIQVirtualProvider(
            profile=virtual_lab_profile,
        ),
    )


def sample_native_lab(
    *,
    workspace: PathInput = DEFAULT_SAMPLE_TEMPLATES_WORKSPACE,
    config_profile: PathInput = SAMPLE_TEMPLATES_FIXTURE_DIR / "config-profile.json",
    virtual_lab_profile: PathInput = SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE,
) -> sc.Workspace:
    return sc.open(
        workspace,
        config_profile=config_profile,
        mode="native_simulate",
        native_instrument_provider=SampleVirtualProvider(profile=virtual_lab_profile),
    )


__all__ = [
    "PathInput",
    "readout_frequency_lab",
    "readout_iq_lab",
    "sample_native_lab",
]
