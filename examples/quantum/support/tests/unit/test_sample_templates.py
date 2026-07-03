from __future__ import annotations

from pathlib import Path

import pytest
from demo_lab_sample_testkit import load_sample_config, sample_parameter_build
from scopecat.authoring import ExperimentDraft, TemplateRegistry, resolve_experiment
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    ExperimentSpec,
    plan_experiment,
)
from scopecat.models.parameter import Quantity
from scopecat.workflows import preview_experiment

from quantum_lab_demo.sample import (
    CZ_RB_TEMPLATE_ID,
    RABI_TEMPLATE_ID,
    READOUT_TEMPLATE_ID,
    SQG_RB_TEMPLATE_ID,
    cz_rb,
    rabi,
    readout_frequency,
    register_templates,
    sqg_rb,
)


def test_sample_template_registry_covers_sample_templates() -> None:
    registry = TemplateRegistry()

    templates = register_templates(registry)

    assert [experiment_template.id for experiment_template in templates] == [
        RABI_TEMPLATE_ID,
        READOUT_TEMPLATE_ID,
        SQG_RB_TEMPLATE_ID,
        CZ_RB_TEMPLATE_ID,
    ]
    draft = registry.build(RABI_TEMPLATE_ID, qubit="q0")
    assert draft.template is not None
    assert draft.template.id == RABI_TEMPLATE_ID


@pytest.mark.parametrize(
    ("label", "draft", "template_id", "kind"),
    [
        (
            "rabi",
            rabi(qubit="q0"),
            RABI_TEMPLATE_ID,
            "sample_rabi",
        ),
        (
            "readout",
            readout_frequency(qubit="q0"),
            READOUT_TEMPLATE_ID,
            "sample_readout_frequency",
        ),
        (
            "sqg_rb",
            sqg_rb(qubit="q0", lengths=[4, 8], seed=11),
            SQG_RB_TEMPLATE_ID,
            "sample_sqg_rb",
        ),
        (
            "cz_rb",
            cz_rb(control_qubit="q0", partner_qubit="q1", lengths=[2, 4], seed=17),
            CZ_RB_TEMPLATE_ID,
            "sample_cz_rb",
        ),
    ],
)
def test_sample_templates_resolve_to_and_preview_draft(
    tmp_path: Path,
    label: str,
    draft: ExperimentDraft,
    template_id: str,
    kind: str,
) -> None:
    config = load_sample_config()

    resolved = resolve_experiment(
        draft,
        workspace=tmp_path,
        config_profile=config,
    )

    assert resolved.template_id == template_id
    assert isinstance(resolved.experiment, ExperimentSpec)
    assert resolved.experiment.kind == kind
    assert resolved.experiment.assets
    plan = plan_experiment(resolved.experiment, sample_parameter_build())
    assert plan.expected_dataset_schema is not None

    preview = preview_experiment(
        draft,
        workspace=tmp_path,
        config_profile=config,
    )
    assert preview.plan.expected_dataset_schema is not None, label
    assert preview.resolved_experiment is not None
    assert preview.resolved_experiment.template_id == template_id


def test_sample_rabi_infers_default_sweep_from_config(tmp_path: Path) -> None:
    resolved = resolve_experiment(
        rabi(qubit="q0"),
        workspace=tmp_path,
        config_profile=load_sample_config(),
    )

    assert isinstance(resolved.experiment, ExperimentSpec)
    points = resolved.experiment.points.evaluate(sample_parameter_build())

    assert len(points) == 5
    assert points[0]["drive_length"] == Quantity(value=10.0, unit="ns")
    assert points[-1]["drive_length"] == Quantity(value=90.0, unit="ns")


def test_sample_template_reports_empty_sequence_axis(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            sqg_rb(qubit="q0", lengths=[]),
            workspace=tmp_path,
            config_profile=load_sample_config(),
        )

    assert error.value.diagnostics[0].code == "sample_template_empty_count_axis"
