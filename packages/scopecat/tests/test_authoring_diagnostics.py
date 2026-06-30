from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.authoring import resolve_experiment
from scopecat.errors import ValidationFailed
from scopecat.experiments import plan_experiment
from scopecat.workflows import run_experiment
from tests.support.authoring import (
    EXAMPLE_DIR,
    custom_asset_recipe,
    load_config,
    parameter_build,
    simple_template,
)


def test_template_missing_input_and_unknown_subject_report_stable_diagnostics(
    tmp_path: Path,
) -> None:
    config = load_config()
    missing_subject = simple_template()()
    with pytest.raises(ValidationFailed) as missing_error:
        resolve_experiment(missing_subject, workspace=tmp_path, config_profile=config)
    assert missing_error.value.diagnostics[0].code == (
        "experiment_template_missing_input"
    )

    unknown_subject = simple_template()(subject="missing")
    with pytest.raises(ValidationFailed) as subject_error:
        resolve_experiment(unknown_subject, workspace=tmp_path, config_profile=config)
    assert subject_error.value.diagnostics[0].code == "unknown_authoring_subject"


def test_missing_opaque_asset_reference_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    resolved = resolve_experiment(
        custom_asset_recipe("missing-program")(subject="q0"),
        workspace=tmp_path,
        config_profile=load_config(),
    )

    plan = plan_experiment(resolved.experiment, parameter_build())
    assert plan.diagnostics[0]["code"] == "unknown_asset_reference"


def test_run_experiment_resolves_template_draft_dry_run_with_config_profile(
    tmp_path: Path,
) -> None:
    result = run_experiment(
        simple_template()(subject="q0"),
        workspace=tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    assert result.manifest.status == "completed"
    assert result.resolved_experiment is not None
    assert result.resolved_experiment.template_id == "test.simple_scan"


def test_run_experiment_resolves_template_draft_dry_run_with_config_snapshot(
    tmp_path: Path,
) -> None:
    result = run_experiment(
        simple_template()(subject="q0"),
        workspace=tmp_path,
        config_profile=load_config(),
    )

    assert result.manifest.status == "completed"
    assert result.resolved_experiment is not None
    assert result.resolved_experiment.template_id == "test.simple_scan"
