from __future__ import annotations

from pathlib import Path

import pytest

from scopecat._workflows.runs import preview_experiment
from scopecat.authoring import resolve_experiment
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.errors import ValidationFailed
from tests.support.authoring import (
    EXAMPLE_DIR,
    load_config,
    simple_template,
)


def test_template_missing_input_and_unknown_subject_report_stable_diagnostics(
    tmp_path: Path,
) -> None:
    config = load_config()
    missing_subject = simple_template().bind()
    with pytest.raises(ValidationFailed) as missing_error:
        resolve_experiment(missing_subject, workspace=tmp_path, config_profile=config)
    assert missing_error.value.diagnostics[0].code == (
        "experiment_template_missing_input"
    )

    unknown_subject = simple_template().bind(subject="missing")
    with pytest.raises(ValidationFailed) as subject_error:
        resolve_experiment(unknown_subject, workspace=tmp_path, config_profile=config)
    assert subject_error.value.diagnostics[0].code == "unknown_authoring_entity"


def test_template_unknown_inputs_are_reported_together_in_stable_order(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            simple_template().bind(subject="q0", zeta=1, alpha=2),
            workspace=tmp_path,
            config_profile=load_config(),
        )

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "experiment_template_unknown_input"
    assert diagnostic.path == "template.inputs"
    assert diagnostic.message.endswith("alpha, zeta")


def test_preview_experiment_resolves_template_invocation_with_config_profile(
    tmp_path: Path,
) -> None:
    result = preview_experiment(
        prepare_invocation(simple_template().bind(subject="q0")),
        workspace=tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    assert result.template_id == "test.simple_scan"
    assert result.experiment_id == "authored-simple-scan"


def test_preview_experiment_resolves_template_invocation_with_config_snapshot(
    tmp_path: Path,
) -> None:
    result = preview_experiment(
        prepare_invocation(simple_template().bind(subject="q0")),
        workspace=tmp_path,
        config_profile=load_config(),
    )

    assert result.template_id == "test.simple_scan"
    assert result.experiment_id == "authored-simple-scan"
