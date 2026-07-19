from __future__ import annotations

from pathlib import Path

import scopecat as sc
import scopecat.authoring as authoring
from scopecat.authoring import (
    ExperimentInvocation,
    ExperimentTemplate,
)
from scopecat.execution.observation import RuntimeEvent, RuntimeTransitionEvent
from scopecat.records.parameter import Quantity
from tests.testkit.authoring import DRIVE_FREQUENCY_POINT
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_invocation

SIMPLE_FREQUENCY_SCAN = (
    authoring.module("test.session.simple_frequency_scan")
    .resource("source", requires=("set_frequency",))
    .bind_field(
        "source",
        capability="set_frequency",
        field="frequency",
        value=DRIVE_FREQUENCY_POINT,
    )
    .record("signal", resource="source", unit="ratio")
    .build()
)


def simple_frequency_scan(*, subject: str) -> ExperimentInvocation:
    return simple_frequency_scan_template().bind(subject=subject)


def simple_frequency_scan_template() -> ExperimentTemplate:
    return (
        SIMPLE_FREQUENCY_SCAN.template(
            "test.session.simple_frequency_scan",
            kind="simple_frequency_scan",
        )
        .experiment_id("session-test-frequency-scan")
        .scan(
            DRIVE_FREQUENCY_POINT,
            center=authoring.parameter(
                "drive_frequency",
                authoring.ScalarType(authoring.QuantityType()),
            ),
            span=Quantity(value=200.0, unit="MHz"),
            points=3,
        )
        .label("Session test frequency scan")
        .category("session-test")
        .build()
    )


def test_workspace_runs_experiment_spec(tmp_path: Path) -> None:
    assert simple_frequency_scan_template().category == "session-test"
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )

    preview = lab.prepare(load_invocation()).preview()

    assert preview.point_count == 3
    assert preview.primary_observables == ("signal",)


def test_workspace_closed_loop_uses_notebook_first_candidate_config(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    experiment = load_invocation()

    baseline = lab.prepare(experiment).run()
    raw = baseline.measurements()
    analysis = (
        baseline.analysis("manual best signal")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .propose(
            "drive_frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                raw.dataset.records[2].coordinates["drive_frequency"],
            ),
            reason="manual notebook pick",
        )
    )
    saved = analysis.save()
    candidate_config = analysis.candidate_config()
    candidate = lab.prepare(experiment, config=candidate_config).run()

    assert baseline.id.startswith("run_")
    assert raw.dataset_entry.id == "raw-measurements"
    assert [input_ref.target for input_ref in saved.inputs] == ["raw-measurements"]
    assert not any(
        record.kind == "candidate_config" for record in baseline.manifest.records
    )
    assert candidate.manifest.status == "completed"


def test_workspace_run_can_observe_transient_runtime_events(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    events: list[RuntimeEvent] = []

    run = lab.prepare(load_invocation()).run(
        event_sink=events.append,
    )

    assert run.manifest.status == "completed"
    assert events[0].kind == "run_started"
    assert events[-1].kind == "run_finished"
    assert (
        len(
            [
                event
                for event in events
                if isinstance(event, RuntimeTransitionEvent)
                and event.stage == "seal_measurement"
                and event.state == "completed"
            ]
        )
        == 1
    )


def test_workspace_provider_closed_loop_uses_candidate_config_shortcut(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    experiment = load_invocation()

    baseline = lab.prepare(experiment).run()
    raw = baseline.measurements()
    analysis = baseline.analysis("manual center point").propose(
        "drive_frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            raw.dataset.records[2].coordinates["drive_frequency"],
        ),
        reason="manual center point",
    )
    candidate_config = analysis.candidate_config()
    candidate = lab.prepare(experiment, config=candidate_config).run()

    assert baseline.manifest.status == "completed"
    assert len(raw.dataset.records) == 3
    assert raw.dataset_entry.id == "raw-measurements"
    assert (
        candidate_config.parameter_proposals[0].deltas[0].parameter_id
        == "drive_frequency"
    )
    assert candidate.manifest.status == "completed"
