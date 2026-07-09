from __future__ import annotations

from pathlib import Path

import scopecat as sc
import scopecat.authoring as authoring
from scopecat.authoring import (
    ExperimentInvocation,
    ExperimentTemplate,
)
from scopecat.models.parameter import Quantity
from scopecat.relations import param
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_experiment

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


SIMPLE_FREQUENCY_SCAN = (
    authoring.module("test.session.simple_frequency_scan")
    .resource("source", requires=authoring.requires("set_frequency"))
    .bind("source.set_frequency.frequency", authoring.var_ref("drive_frequency"))
    .record("signal", resource="source", unit="ratio")
    .build()
)


def simple_frequency_scan(*, subject: str) -> ExperimentInvocation:
    return simple_frequency_scan_template().bind(subject=subject)


def simple_frequency_scan_template() -> ExperimentTemplate:
    return (
        authoring.template(
            "test.session.simple_frequency_scan",
            kind="simple_frequency_scan",
        )
        .experiment_id("session-test-frequency-scan")
        .scan(
            "drive_frequency",
            center=param("drive_frequency"),
            span=Quantity(value=200.0, unit="MHz"),
            points=3,
        )
        .use(SIMPLE_FREQUENCY_SCAN)
        .label("Session test frequency scan")
        .metadata(category="session-test")
        .build()
    )


def test_workspace_runs_experiment_spec(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    preview = lab.prepare(load_experiment()).preview()

    assert preview.point_count == 3
    assert preview.primary_observables == ("signal",)


def test_workspace_closed_loop_uses_notebook_first_candidate_config(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = load_experiment()

    baseline = lab.prepare(experiment).run()
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
    candidate = lab.prepare(experiment, config=candidate_config).run()
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


def test_workspace_run_can_observe_transient_runtime_events(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    event_kinds: list[str] = []

    run = lab.prepare(load_experiment()).run(
        event_sink=lambda event: event_kinds.append(event.kind),
    )

    assert run.manifest.status == "completed"
    assert event_kinds[0] == "run_started"
    assert event_kinds[-1] == "run_finished"
    assert event_kinds.count("record_emitted") == 3


def test_workspace_provider_closed_loop_uses_candidate_config_shortcut(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = load_experiment()

    baseline = lab.prepare(experiment).run()
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
    candidate = lab.prepare(experiment, config=candidate_config).run()
    comparison = lab.compare(baseline, candidate)
    review = comparison.review(state="accepted")
    overview = baseline.overview()

    assert baseline.manifest.status == "completed"
    assert baseline.preview.point_count == 3
    assert raw.dataset_entry.id == "raw-measurements"
    assert (
        candidate_config.parameter_changes[0].patches[0].parameter_id
        == "drive_frequency"
    )
    assert candidate.manifest.status == "completed"
    assert comparison.result.outcome == "unchanged"
    assert review.review.decision == "accepted"
    assert overview.run_id == baseline.id
