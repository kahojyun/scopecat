from __future__ import annotations

from pathlib import Path

import pytest
from demo_lab_test_paths import (
    SAMPLE_TEMPLATES_FIXTURE_DIR,
    SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE,
)
from scopecat.authoring import ExperimentDraft, resolve_experiment
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.instruments import NativeRunSnapshot
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.runs import open_run_store
from scopecat.workflows import run_experiment

from quantum_lab_demo.sample import (
    CZ_RB_TEMPLATE_ID,
    RABI_TEMPLATE_ID,
    READOUT_TEMPLATE_ID,
    SQG_RB_TEMPLATE_ID,
    cz_rb,
    rabi,
    readout_frequency,
    sqg_rb,
)
from quantum_lab_demo.virtual_lab.provider import SampleVirtualProvider


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(SAMPLE_TEMPLATES_FIXTURE_DIR / "config-profile.json")


@pytest.mark.parametrize(
    ("draft", "template_id", "expected_asset_ids", "expected_measurements"),
    [
        (
            rabi(qubit="q0"),
            RABI_TEMPLATE_ID,
            {"q0-rabi-pulse-program"},
            5,
        ),
        (
            readout_frequency(qubit="q0"),
            READOUT_TEMPLATE_ID,
            {"q0-find-frr-with-pi-pulse"},
            5,
        ),
        (
            sqg_rb(qubit="q0", lengths=[4, 8], seed=11),
            SQG_RB_TEMPLATE_ID,
            {"q0-sqg-rb-sequence", "q0-sqg-rb-pulsedict"},
            2,
        ),
        (
            cz_rb(control_qubit="q0", partner_qubit="q1", lengths=[2, 4], seed=17),
            CZ_RB_TEMPLATE_ID,
            {"q0-q1-cz-rb-sequence", "q0-q1-cz-rb-coupler-pulse"},
            2,
        ),
    ],
)
def test_sample_templates_run_native_python_api(
    tmp_path: Path,
    draft: ExperimentDraft,
    template_id: str,
    expected_asset_ids: set[str],
    expected_measurements: int,
) -> None:
    result = run_experiment(
        draft,
        mode="native_simulate",
        config_profile=load_config(),
        workspace=tmp_path,
        native_instrument_provider=SampleVirtualProvider(
            profile=SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE
        ),
    )

    assert result.manifest.status == "completed"
    assert isinstance(result.snapshot, NativeRunSnapshot)
    assert result.snapshot.measurement_count == expected_measurements
    assert result.resolved_experiment is not None
    assert result.resolved_experiment.template_id == template_id
    assert isinstance(result.resolved_experiment.experiment, ExperimentSpec)
    assert {asset.id for asset in result.resolved_experiment.experiment.assets} == (
        expected_asset_ids
    )


def test_sample_native_rejects_invalid_asset_kind_before_run_created(
    tmp_path: Path,
) -> None:
    resolved = resolve_experiment(
        rabi(qubit="q0"),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    assert isinstance(resolved.experiment, ExperimentSpec)
    experiment = resolved.experiment.model_copy(
        update={
            "assets": [
                resolved.experiment.assets[0].model_copy(
                    update={"kind": "gate_sequence"}
                )
            ]
        }
    )

    with pytest.raises(ValidationFailed) as error:
        run_experiment(
            experiment,
            mode="native_simulate",
            config=load_config(),
            workspace=tmp_path,
            native_instrument_provider=SampleVirtualProvider(
                profile=SAMPLE_TEMPLATES_VIRTUAL_LAB_PROFILE
            ),
        )

    assert error.value.diagnostics[0].code == "managed_native_asset_kind_mismatch"
    assert open_run_store(tmp_path).list_runs()[0].status == "failed"
