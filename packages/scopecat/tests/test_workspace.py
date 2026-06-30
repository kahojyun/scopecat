from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, PlanSnapshot
from scopecat.models.parameter import Quantity
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.processing import FakeProcessingStep
from tests.support.records import read_model

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simulated_scan"


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def test_workspace_runs_and_reads_exploratory_data(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )

    run = lab.run(load_experiment())
    data = run.data()
    raw = data.measurements()
    measurement_artifacts = data.list(kind="measurement_dataset")
    raw_artifact = data.artifact(
        "raw-measurements",
        expected_kind="measurement_dataset",
    )
    lab.client.process(run.id, FakeProcessingStep())
    figure = data.figure("fake-processing-figure")
    plan_preview = data.plan_preview()

    assert isinstance(lab, sc.Workspace)
    assert isinstance(run, sc.Run)
    assert raw.artifact.id == "raw-measurements"
    assert [artifact.id for artifact in measurement_artifacts] == ["raw-measurements"]
    assert raw_artifact.path == "artifacts/raw-measurements.jsonl"
    assert len(raw.dataset.records) == 3
    assert figure.artifact.id == "fake-processing-figure"
    assert figure.content == b"\x89PNG\r\n"
    assert isinstance(plan_preview, PlanSnapshot)
    assert plan_preview.expected_dataset_schema is not None
    assert data.artifacts == run.artifacts


def test_data_selectors_report_notebook_friendly_diagnostics(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())
    data = run.data()

    assert data.list(metadata={"source_step": "unknown"}) == ()

    with pytest.raises(ValidationFailed) as missing_error:
        data.artifact("missing-artifact")
    assert missing_error.value.diagnostics[0].code == "artifact_not_found"
    assert "missing-artifact" in missing_error.value.diagnostics[0].message

    with pytest.raises(ValidationFailed) as escape_error:
        data.artifact("../workspace.json")
    assert escape_error.value.diagnostics[0].code == "artifact_selector_path_escape"

    with pytest.raises(ValidationFailed) as kind_error:
        data.artifact("raw-measurements", expected_kind="analysis")
    assert kind_error.value.diagnostics[0].code == "artifact_kind_mismatch"
    assert "expected analysis" in kind_error.value.diagnostics[0].message

    with pytest.raises(ValidationFailed) as figure_error:
        data.figure("raw-measurements")
    assert figure_error.value.diagnostics[0].code == "artifact_kind_mismatch"
    assert "expected figure" in figure_error.value.diagnostics[0].message

    with pytest.raises(ValidationFailed) as analysis_ref_error:
        run.analysis("manual review").artifact_ref(
            "raw-measurements",
            expected_kind="analysis",
        )
    assert analysis_ref_error.value.diagnostics[0].code == "artifact_kind_mismatch"


def test_workspace_experiment_wraps_existing_source(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = (
        lab.experiment("readout scan", load_experiment())
        .subject("q0")
        .sweep("drive_frequency", [4.9, 5.0, 5.1], points=3)
        .measure("signal")
    )

    run = lab.run(experiment)

    assert experiment.name == "readout scan"
    assert experiment.subject_id == "q0"
    assert experiment.sweeps[0].parameter_id == "drive_frequency"
    assert experiment.observables == ("signal",)
    assert run.manifest.status == "completed"


def test_workspace_experiment_builder_lowers_to_runnable_spec(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = (
        lab.experiment("manual signal scan")
        .sweep(
            "drive_frequency",
            [
                Quantity(value=4.9, unit="GHz"),
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=5.1, unit="GHz"),
            ],
        )
        .measure("signal")
    )

    run = lab.run(experiment)

    assert run.manifest.status == "completed"
    assert run.result.resolved_experiment is not None
    assert run.result.resolved_experiment.experiment.id == "manual-signal-scan"
    planned_frequencies = [
        point.row["drive_frequency"] for point in run.result.snapshot.plan.points
    ]
    assert planned_frequencies == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert run.result.snapshot.plan.expected_dataset_schema is not None


def test_workspace_experiment_builder_supports_active_center_sweep(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="dry",
    )
    experiment = (
        lab.experiment("active centered scan")
        .sweep("drive_frequency", around="active", span="200 MHz", points=3)
        .measure("signal")
    )

    run = lab.run(experiment)

    assert run.manifest.status == "completed"
    planned_frequencies = [
        point.row["drive_frequency"] for point in run.result.snapshot.plan.points
    ]
    assert planned_frequencies == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]


def test_run_analysis_collects_notebook_outputs_and_candidate_config(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())
    raw = run.data().measurements()

    analysis = (
        run.analysis("manual readout review")
        .note("three point scan completed")
        .table(
            [{"point": record.point_index} for record in raw.dataset.records],
            title="points",
        )
        .artifact_ref("raw-measurements", expected_kind="measurement_dataset")
        .external_ref("file:///tmp/manual-notes.ipynb", title="notebook")
        .guess(
            "drive_frequency",
            5.0,
            unit="GHz",
            reason="middle point produced the best signal",
            confidence=0.8,
        )
    )
    candidate = analysis.candidate_config(reason="inspect in notebook first")
    saved = analysis.save()
    saved_payload = run.data().json(saved.artifact.id)

    assert [output.kind for output in analysis.outputs] == [
        "note",
        "table",
        "external_ref",
        "external_ref",
        "guess",
    ]
    assert candidate.source_run_id == run.id
    assert candidate.analysis_title == "manual readout review"
    assert candidate.guesses[0].parameter_id == "drive_frequency"
    assert candidate.reason == "inspect in notebook first"
    assert saved.artifact.kind == "analysis"
    assert saved.artifact.path == "artifacts/analysis-manual-readout-review.json"
    assert saved.source_artifact_ids == ("raw-measurements",)
    assert saved.artifact.metadata["source_artifact_ids"] == ["raw-measurements"]
    assert saved_payload.content["schema_version"] == "scopecat.analysis.v1"
    assert saved_payload.content["title"] == "manual readout review"
    assert saved_payload.content["source_artifact_ids"] == ["raw-measurements"]
    assert saved_payload.content["outputs"][2]["content"]["target_type"] == "artifact"
    assert saved_payload.content["outputs"][2]["content"]["target"] == (
        "raw-measurements"
    )
    assert saved_payload.content["outputs"][3]["content"]["target_type"] == "uri"
    assert saved_payload.content["outputs"][3]["content"]["target"] == (
        "file:///tmp/manual-notes.ipynb"
    )
    assert saved_payload.content["guesses"][0]["parameter_id"] == "drive_frequency"
    assert [artifact.id for artifact in run.data().list(kind="analysis")] == [
        "analysis-manual-readout-review"
    ]


def test_analysis_artifact_refs_dedupe_sources_and_feed_report(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())

    saved = (
        run.analysis("manual source review")
        .artifact_ref("raw-measurements", expected_kind="measurement_dataset")
        .external_ref("file:///tmp/manual-source-review.ipynb", title="notebook")
        .artifact_ref("raw-measurements", expected_kind="measurement_dataset")
        .guess("drive_frequency", 5.0, unit="GHz")
        .save()
    )
    saved_payload = run.data().json(saved.artifact.id)
    report = run.report()
    report_markdown = (
        tmp_path / "runs" / run.id / "artifacts" / "run-report.md"
    ).read_text()

    assert saved.source_artifact_ids == ("raw-measurements",)
    assert saved.artifact.metadata["source_artifact_ids"] == ["raw-measurements"]
    assert saved_payload.content["source_artifact_ids"] == ["raw-measurements"]
    assert [analysis.source_artifact_ids for analysis in report.report.analysis] == [
        ["raw-measurements"]
    ]
    assert "- Source artifacts: raw-measurements" in report_markdown


def test_workspace_reopens_runs_for_gui_entry_contract(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = load_experiment()
    baseline = lab.run(experiment)
    analysis = (
        baseline.analysis("gui review")
        .artifact_ref("raw-measurements", expected_kind="measurement_dataset")
        .guess("drive_frequency", 5.0, unit="GHz", reason="manual fit")
    )
    saved = analysis.save()
    candidate = analysis.candidate_config(reason="manual fit")
    review = lab.review(candidate, note="accept from workbench")
    follow_up = lab.run(experiment, config=review)
    comparison = lab.compare(baseline, follow_up, observable="signal")
    report = baseline.report()

    reopened = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    gui_runs = reopened.runs()
    gui_run = reopened.get_run(baseline.id)
    gui_data = gui_run.data()

    assert [run.id for run in gui_runs] == [baseline.id, follow_up.id]
    assert gui_run.id == baseline.id
    assert gui_run.data_ref == "artifacts/raw-measurements.jsonl"
    assert gui_data.measurements().artifact.id == "raw-measurements"
    assert [artifact.id for artifact in gui_data.list(kind="analysis")] == [
        saved.artifact.id
    ]
    assert [artifact.id for artifact in gui_data.list(kind="candidate_config")] == [
        review.candidate_config_artifact.id
    ]
    assert gui_data.json(saved.artifact.id).content["source_artifact_ids"] == [
        "raw-measurements"
    ]
    assert [view.id for view in gui_run.comparisons()] == [comparison.id]
    assert gui_data.artifact(report.job.output_refs[0]).kind == "run_report"


@pytest.mark.parametrize(
    ("action", "expected_code"),
    [
        (lambda analysis: analysis.note(""), "analysis_note_invalid"),
        (lambda analysis: analysis.external_ref(""), "analysis_external_ref_invalid"),
        (
            lambda analysis: analysis.guess("", 5.0),
            "analysis_guess_parameter_invalid",
        ),
        (
            lambda analysis: analysis.guess("drive_frequency", 5.0, confidence=1.5),
            "analysis_guess_confidence_invalid",
        ),
    ],
)
def test_analysis_rejects_invalid_notebook_payloads(
    tmp_path: Path,
    action,
    expected_code: str,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="dry",
    )
    run = lab.run(load_experiment())

    with pytest.raises(ValidationFailed) as error:
        action(run.analysis("manual review"))

    assert error.value.diagnostics[0].code == expected_code


def test_analysis_step_reuses_manual_analysis_shape(tmp_path: Path) -> None:
    class ReadoutFit:
        id = "readout.fit"

        def run(self, context: sc.AnalysisContext) -> sc.Analysis:
            raw = context.data.measurements()
            assert context.config.parameter_build is not None
            return (
                context.result("readout fit")
                .note(f"loaded {len(raw.dataset.records)} records")
                .table(
                    [{"center": 5.0, "unit": "GHz"}],
                    title="fit summary",
                )
                .guess("drive_frequency", 5.0, unit="GHz")
            )

    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())
    step: sc.AnalysisStep = ReadoutFit()

    analysis = run.analyze(step)
    promoted = analysis.promote_step(step.id)
    rerun_analysis = promoted.run(run)

    assert [output.kind for output in analysis.outputs] == ["note", "table", "guess"]
    assert promoted.id == "readout.fit"
    assert rerun_analysis.title == "readout.fit"
    assert rerun_analysis.outputs == analysis.outputs
    assert rerun_analysis.parameter_guesses == analysis.parameter_guesses


def test_candidate_config_lowers_to_internal_review_and_runs_follow_up(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="dry",
    )
    run = lab.run(load_experiment())
    candidate = (
        run.analysis("manual readout review")
        .guess("drive_frequency", 5.5, unit="GHz", confidence=0.9)
        .candidate_config()
    )

    review = lab.review(candidate, note="checked notebook fit")
    follow_up = lab.run(load_experiment(), config=candidate)
    proposal = run.data().json(review.proposal_artifact.id).content
    candidate_config = run.data().json(review.candidate_config_artifact.id).content
    follow_up_config = lab.client.run_details(follow_up.id).config

    assert isinstance(review, sc.CandidateConfigReview)
    assert review.proposal_artifact.kind == "parameter_change_set"
    assert review.candidate_config_artifact.kind == "candidate_config"
    assert proposal["schema_version"] == "scopecat.parameter_change_set.v1"
    assert proposal["state"] == "approved"
    assert proposal["patches"][0]["parameter_id"] == "drive_frequency"
    assert proposal["patches"][0]["value"] == {"value": 5.5, "unit": "GHz"}
    assert candidate_config["source"]["kind"] == "analysis_candidate_config"
    assert candidate_config["source"]["proposal_id"] == review.proposal_artifact.id
    updated = follow_up_config.parameter_state.scalar_value_set().get("drive_frequency")
    assert updated is not None
    assert updated.quantity.value == 5.5
