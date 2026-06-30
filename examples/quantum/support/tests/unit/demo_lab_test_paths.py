from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2]
REPO_ROOT = Path(__file__).parents[5]
QUANTUM_FIXTURE_DIR = REPO_ROOT / "fixtures" / "quantum"

READOUT_FREQUENCY_FIXTURE_DIR = QUANTUM_FIXTURE_DIR / "readout_frequency_calibration"
READOUT_FREQUENCY_RESPONSE_FIXTURE = (
    READOUT_FREQUENCY_FIXTURE_DIR / "readout-response.json"
)
READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE = (
    READOUT_FREQUENCY_FIXTURE_DIR / "virtual-lab.json"
)

READOUT_IQ_FIXTURE_DIR = QUANTUM_FIXTURE_DIR / "readout_iq_quality"
READOUT_IQ_RESPONSE_FIXTURE = READOUT_IQ_FIXTURE_DIR / "readout-iq-response.json"
READOUT_IQ_VIRTUAL_LAB_PROFILE = READOUT_IQ_FIXTURE_DIR / "virtual-lab.json"

SAMPLE_TEMPLATES_FIXTURE_DIR = QUANTUM_FIXTURE_DIR / "sample_templates"
SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE = SAMPLE_TEMPLATES_FIXTURE_DIR / "virtual-lab.json"
