from __future__ import annotations

from pathlib import Path

import scopecat as sc
import scopecat.authoring as authoring
from scopecat.authoring import ExperimentDraft, ExperimentTemplate, TemplateRegistry
from scopecat.experiments import acquire
from scopecat.models.parameter import Quantity
from scopecat.session import TemplateBrowser
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_experiment

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


SIMPLE_FREQUENCY_SCAN = authoring.recipe(
    id="test.session.simple_frequency_scan",
    experiment_id="session-test-frequency-scan",
    kind="simple_frequency_scan",
    resources=[
        authoring.resource_role(
            "source",
            authoring.requires("set_frequency"),
            resource_id="source-0",
        )
    ],
    variables=[
        authoring.sweep(
            "drive_frequency",
            default_span=Quantity(value=200.0, unit="MHz"),
            points=3,
        )
    ],
    bindings=[
        authoring.bind(
            "source.set_frequency.frequency",
            authoring.var_ref("drive_frequency"),
        )
    ],
    acquisition=acquire("scalar"),
)


def simple_frequency_scan(*, subject: str) -> ExperimentDraft:
    return simple_frequency_scan_template()(subject=subject)


def simple_frequency_scan_template() -> ExperimentTemplate:
    return SIMPLE_FREQUENCY_SCAN.template(
        label="Session test frequency scan",
        metadata={"category": "session-test"},
    )


def test_workspace_runs_experiment_spec(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    preview = lab.preview(load_experiment())

    assert preview.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert len(preview.plan.points) == 3


def test_workspace_closed_loop_uses_notebook_first_candidate_config(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = load_experiment()

    baseline = lab.run(experiment)
    raw = baseline.measurements()
    analysis = (
        baseline.analysis("manual best signal")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .propose(
            "drive_frequency",
            sc.set_param(
                "drive_frequency",
                raw.dataset.records[1].coordinates["drive_frequency"],
            ),
            reason="manual notebook pick",
        )
    )
    saved = analysis.save()
    candidate_config = analysis.candidate_config()
    candidate = lab.run(experiment, config=candidate_config)
    comparison = lab.compare(baseline, candidate)
    comparison_review = comparison.review(state="accepted")
    overview = baseline.overview()

    assert baseline.id.startswith("run_")
    assert raw.dataset_entry.id == "raw-measurements"
    assert [input_ref.target for input_ref in saved.inputs] == ["raw-measurements"]
    assert any(
        record.kind == "candidate_config"
        for record in lab.get_run(baseline.id).manifest.records
    )
    assert candidate.manifest.status == "completed"
    assert comparison.result.outcome == "unchanged"
    assert comparison_review.review.decision == "accepted"
    assert overview.run_id == baseline.id


def test_workspace_provider_closed_loop_uses_candidate_config_shortcut(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = load_experiment()

    baseline = lab.run(experiment)
    raw = baseline.measurements()
    analysis = baseline.analysis("manual center point").propose(
        "drive_frequency",
        sc.set_param(
            "drive_frequency",
            raw.dataset.records[1].coordinates["drive_frequency"],
        ),
        reason="manual center point",
    )
    candidate_config = analysis.candidate_config()
    candidate = lab.run(experiment, config=candidate_config)
    comparison = lab.compare(baseline, candidate)
    review = comparison.review(state="accepted")
    overview = baseline.overview()

    assert baseline.manifest.status == "completed"
    assert baseline.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert raw.dataset_entry.id == "raw-measurements"
    assert (
        candidate_config.parameter_changes[0].patches[0].parameter_id
        == "drive_frequency"
    )
    assert candidate.manifest.status == "completed"
    assert comparison.result.outcome == "unchanged"
    assert review.review.decision == "accepted"
    assert overview.run_id == baseline.id


def test_session_template_browser_lists_builds_and_previews(tmp_path: Path) -> None:
    template = simple_frequency_scan_template()
    registry = TemplateRegistry()
    registry.register(template)
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    browser = TemplateBrowser(session=lab, registry=registry)

    selected_templates = browser.list(category="session-test")
    draft = browser.build("test.session.simple_frequency_scan", subject="q0")
    preview = browser.preview(draft)

    assert template in selected_templates
    assert preview.template_id == "test.session.simple_frequency_scan"
