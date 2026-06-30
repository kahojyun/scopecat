from __future__ import annotations

from pathlib import Path

import pytest

import scopecat.authoring as authoring
from scopecat.authoring import ExperimentDraft
from scopecat.client import Client, client, run_id
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import load_config_profile
from scopecat.models.parameter import Quantity
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.records import read_model
from tests.support.signal_testkit import (
    BestSignalEvaluationStep,
    SummaryStatsProcessingStep,
)

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simulated_scan"


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


SIMPLE_RECIPE = authoring.recipe(
    id="test.client.simple_scan",
    experiment_id="client-authored-simple-scan",
    kind="simple_scan",
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
)


def load_draft() -> ExperimentDraft:
    return SIMPLE_RECIPE(subject="q0")


def test_client_runs_and_reads_notebook_workflow(tmp_path: Path) -> None:
    client = Client.from_profile(
        EXAMPLE_DIR / "config-profile.json",
        workspace=tmp_path,
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )

    run = client.run(load_experiment())
    raw = client.measurements(run)
    processing = client.process(run, SummaryStatsProcessingStep())
    evaluation = client.evaluate(run, BestSignalEvaluationStep())
    summary = client.artifact_text(run, "summary-stats-summary")

    assert run.manifest.status == "completed"
    assert run_id(run) == run.manifest.run_id
    assert raw.artifact.id == "raw-measurements"
    assert len(raw.dataset.records) == 3
    assert processing.result.measurement_count == 3
    assert evaluation.result.best_point_index in {0, 1, 2}
    assert "Scopecat Summary Stats" in summary.content


def test_client_runs_experiment_spec(tmp_path: Path) -> None:
    client = Client.from_profile(
        EXAMPLE_DIR / "config-profile.json",
        workspace=tmp_path,
        mode="dry",
    )

    run = client.run(load_experiment())
    details = client.run_details(run)

    assert run.manifest.runner_id == "scopecat.planner"
    assert run.snapshot.schema_version == "scopecat.dry_run_snapshot.v1"
    assert details.plan.schema_version == "scopecat.plan_snapshot.v1"


def test_client_resolves_from_stored_profile(tmp_path: Path) -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    client_instance = client(workspace=tmp_path, config_profile=config)

    resolved = client_instance.resolve(load_draft())

    assert resolved.experiment.id == "client-authored-simple-scan"
    assert resolved.experiment.schema_version == "scopecat.experiment_spec.v1"
    assert resolved.config_provenance is None


def test_client_resolve_rejects_conflicting_config_sources(tmp_path: Path) -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    client_instance = client(
        workspace=tmp_path,
        config=config,
        config_profile=config,
    )

    with pytest.raises(ValidationFailed) as error:
        client_instance.resolve(load_draft())

    assert error.value.diagnostics[0].code == "conflicting_client_config_source"
