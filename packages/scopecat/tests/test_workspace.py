from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

import scopecat as sc
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, PlanSnapshot
from scopecat.models.parameter import Quantity
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.records import read_model

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simulated_scan"


class AnalysisArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


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
    (
        run.analysis("plot artifact")
        .artifact(
            title="plot bytes",
            kind="plot",
            artifact_id="analysis-plot",
            filename="analysis-plot.png",
            content=b"\x89PNG\r\n",
            media_type="image/png",
        )
        .save()
    )
    figure = data.figure("analysis-plot")
    plan_preview = data.plan_preview()

    assert isinstance(lab, sc.Workspace)
    assert isinstance(run, sc.Run)
    assert raw.artifact.id == "raw-measurements"
    assert [artifact.id for artifact in measurement_artifacts] == ["raw-measurements"]
    assert raw_artifact.path == "artifacts/raw-measurements.jsonl"
    assert len(raw.dataset.records) == 3
    assert figure.artifact.id == "analysis-plot"
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

    with pytest.raises(ValidationFailed) as escape_error:
        data.artifact("../workspace.json")
    assert escape_error.value.diagnostics[0].code == "artifact_selector_path_escape"


def test_run_attachment_can_feed_analysis_inputs(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())

    attachment = run.attach(
        key="notebook",
        text="manual fit notes",
        filename="manual-fit-notes.md",
        media_type="text/markdown",
        metadata={"section": "fit"},
    )
    saved = (
        run.analysis("attachment-backed review")
        .input("notebook", role="notes", expected_kind="attachment")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .note("used notebook notes and raw measurements")
        .save()
    )
    payload = run.data().json(saved.artifact.id).content

    assert attachment.id == "notebook"
    assert attachment.kind == "attachment"
    assert run.data().text("notebook").content == "manual fit notes\n"
    assert run.data().artifact("notebook").metadata["owner_type"] == "run"
    assert saved.source_artifact_ids == ("notebook", "raw-measurements")
    assert [input_ref["target"] for input_ref in payload["inputs"]] == [
        "notebook",
        "raw-measurements",
    ]


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
        .input("raw-measurements", expected_kind="measurement_dataset")
        .input(uri="file:///tmp/manual-notes.ipynb", role="notes", title="notebook")
        .propose(
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
        "proposal",
    ]
    assert [input_ref.target for input_ref in analysis.inputs] == [
        "raw-measurements",
        "file:///tmp/manual-notes.ipynb",
    ]
    assert candidate.source_run_id == run.id
    assert candidate.analysis_title == "manual readout review"
    assert candidate.analysis_key == "manual-readout-review"
    assert candidate.proposals[0].parameter_id == "drive_frequency"
    assert candidate.reason == "inspect in notebook first"
    assert saved.artifact.kind == "analysis"
    assert saved.artifact.path == "artifacts/analysis-manual-readout-review.json"
    assert saved.source_artifact_ids == ("raw-measurements",)
    assert saved.artifact.metadata["source_artifact_ids"] == ["raw-measurements"]
    assert saved_payload.content["schema_version"] == "scopecat.analysis.v2"
    assert saved_payload.content["title"] == "manual readout review"
    assert saved_payload.content["key"] == "manual-readout-review"
    assert saved_payload.content["source_artifact_ids"] == ["raw-measurements"]
    assert saved_payload.content["inputs"][0]["target_type"] == "artifact"
    assert saved_payload.content["inputs"][0]["target"] == ("raw-measurements")
    assert saved_payload.content["inputs"][1]["target_type"] == "uri"
    assert saved_payload.content["inputs"][1]["target"] == (
        "file:///tmp/manual-notes.ipynb"
    )
    assert saved_payload.content["proposals"][0]["parameter_id"] == "drive_frequency"
    assert [artifact.id for artifact in run.data().list(kind="analysis")] == [
        "analysis-manual-readout-review"
    ]


def test_run_analysis_persists_report_artifacts(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())
    source_report = tmp_path / "fit-report.html"
    source_report.write_text("<h1>fit</h1>\n")

    saved = (
        run.analysis("manual report review")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .report(
            title="source html",
            path=source_report,
            artifact_id="manual-html-report",
            metadata={"section": "fit"},
        )
        .report(
            title="fit markdown",
            text="best point: 1",
            filename="fit-summary.md",
            media_type="text/markdown",
        )
        .report(
            title="plot bytes",
            content=b"\x89PNG\r\n",
            filename="fit-plot.bin",
        )
        .save()
    )
    saved_payload = run.data().json(saved.artifact.id)
    overview = run.overview()

    assert [output["kind"] for output in saved_payload.content["outputs"]] == [
        "report",
        "report",
        "report",
    ]
    assert [artifact.kind for artifact in saved.report_artifacts] == [
        "analysis_report",
        "analysis_report",
        "analysis_report",
    ]
    assert [artifact.id for artifact in run.data().list(kind="analysis_report")] == [
        "manual-html-report",
        "analysis-report-manual-report-review-fit-markdown",
        "analysis-report-manual-report-review-plot-bytes",
    ]
    assert run.data().text("manual-html-report").content == "<h1>fit</h1>\n"
    assert (
        run.data().text("analysis-report-manual-report-review-fit-markdown").content
        == "best point: 1\n"
    )
    assert (
        run.data().bytes("analysis-report-manual-report-review-plot-bytes").content
        == b"\x89PNG\r\n"
    )
    assert saved.report_artifacts[0].metadata["section"] == "fit"
    assert saved.report_artifacts[0].metadata["source_analysis_artifact_id"] == (
        saved.artifact.id
    )
    assert saved.report_artifacts[0].metadata["source_artifact_ids"] == [
        "raw-measurements"
    ]
    assert saved_payload.content["outputs"][0]["content"]["target"] == (
        "manual-html-report"
    )
    assert [report.artifact_id for report in overview.overview.analysis_reports] == [
        "analysis-report-manual-report-review-fit-markdown",
        "analysis-report-manual-report-review-plot-bytes",
        "manual-html-report",
    ]
    assert overview.overview.analysis_records[0].report_artifact_ids == [
        "manual-html-report",
        "analysis-report-manual-report-review-fit-markdown",
        "analysis-report-manual-report-review-plot-bytes",
    ]


def test_run_analysis_persists_owned_artifacts(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())
    source = tmp_path / "source-report.html"
    source.write_text("<h1>source</h1>\n")

    saved = (
        run.analysis("artifact persistence")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .artifact(
            title="model result",
            kind="analysis_model",
            artifact_id="analysis-model",
            model=AnalysisArtifactPayload(value=7),
        )
        .artifact(
            title="json result",
            kind="analysis_json",
            artifact_id="analysis-json",
            json_content={"ok": True},
        )
        .artifact(
            title="text result",
            kind="summary",
            artifact_id="analysis-text",
            text="hello",
            media_type="text/plain",
        )
        .artifact(
            title="bytes result",
            kind="blob",
            artifact_id="analysis-bytes",
            content=b"abc",
        )
        .artifact(
            title="file result",
            kind="html",
            artifact_id="analysis-file",
            path=source,
            media_type="text/html",
        )
        .save()
    )
    payload = run.data().json(saved.artifact.id).content

    assert [artifact.id for artifact in saved.output_artifacts] == [
        "analysis-model",
        "analysis-json",
        "analysis-text",
        "analysis-bytes",
        "analysis-file",
    ]
    assert run.data().json("analysis-model").content == {"value": 7}
    assert run.data().json("analysis-json").content == {"ok": True}
    assert run.data().text("analysis-text").content == "hello\n"
    assert run.data().bytes("analysis-bytes").content == b"abc"
    assert run.data().text("analysis-file").content == "<h1>source</h1>\n"
    assert [output["kind"] for output in payload["outputs"]] == [
        "artifact",
        "artifact",
        "artifact",
        "artifact",
        "artifact",
    ]
    assert payload["outputs"][0]["content"]["target"] == "analysis-model"
    assert saved.output_artifacts[0].metadata["source_artifact_ids"] == [
        "raw-measurements"
    ]


def test_run_analysis_report_save_rejects_duplicate_ids_and_filenames(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="dry",
    )
    run = lab.run(load_experiment())

    with pytest.raises(ValidationFailed) as duplicate_id:
        (
            run.analysis("manual report review")
            .report(
                title="first",
                text="one",
                filename="one.md",
                artifact_id="fit-report",
            )
            .report(
                title="second",
                text="two",
                filename="two.md",
                artifact_id="fit-report",
            )
            .save()
        )
    assert duplicate_id.value.diagnostics[0].code == (
        "analysis_report_artifact_id_duplicated"
    )
    run_artifacts_dir = tmp_path / "runs" / run.id / "artifacts"
    assert not (run_artifacts_dir / "one.md").exists()


def test_run_analysis_artifact_save_rejects_duplicate_ids_and_filenames(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        mode="dry",
    )
    run = lab.run(load_experiment())

    with pytest.raises(ValidationFailed) as duplicate_id:
        (
            run.analysis("artifact review")
            .artifact(
                title="first",
                kind="summary",
                artifact_id="fit-artifact",
                filename="one.md",
                text="one",
            )
            .artifact(
                title="second",
                kind="summary",
                artifact_id="fit-artifact",
                filename="two.md",
                text="two",
            )
            .save()
        )
    assert duplicate_id.value.diagnostics[0].code == "analysis_artifact_id_duplicated"
    assert not (tmp_path / "runs" / run.id / "artifacts" / "one.md").exists()

    with pytest.raises(ValidationFailed) as duplicate_filename:
        (
            run.analysis("artifact review")
            .artifact(
                title="first",
                kind="summary",
                artifact_id="one",
                filename="duplicate.md",
                text="one",
            )
            .artifact(
                title="second",
                kind="summary",
                artifact_id="two",
                filename="duplicate.md",
                text="two",
            )
            .save()
        )
    assert duplicate_filename.value.diagnostics[0].code == (
        "analysis_artifact_filename_duplicated"
    )


def test_analysis_artifact_refs_dedupe_sources_and_feed_overview(
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
        .input("raw-measurements", expected_kind="measurement_dataset")
        .input(
            uri="file:///tmp/manual-source-review.ipynb",
            role="notes",
            title="notebook",
        )
        .input("raw-measurements", expected_kind="measurement_dataset")
        .propose("drive_frequency", 5.0, unit="GHz")
        .save()
    )
    saved_payload = run.data().json(saved.artifact.id)
    overview = run.overview()

    assert saved.source_artifact_ids == ("raw-measurements",)
    assert saved.artifact.metadata["source_artifact_ids"] == ["raw-measurements"]
    assert saved_payload.content["source_artifact_ids"] == ["raw-measurements"]
    assert [
        analysis.source_artifact_ids for analysis in overview.overview.analysis_records
    ] == [["raw-measurements"]]


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
        .input("raw-measurements", expected_kind="measurement_dataset")
        .report(
            title="fit notes",
            text="manual fit notes",
            filename="gui-fit-notes.md",
            media_type="text/markdown",
        )
        .propose("drive_frequency", 5.0, unit="GHz", reason="manual fit")
    )
    saved = analysis.save()
    candidate = analysis.candidate_config(reason="manual fit")
    review = lab.review(candidate, note="accept from workbench")
    follow_up = lab.run(experiment, config=review)
    comparison = lab.compare(baseline, follow_up, observable="signal")
    overview = baseline.overview()

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
    assert [artifact.id for artifact in gui_data.list(kind="analysis_report")] == [
        saved.report_artifacts[0].id
    ]
    assert gui_data.text(saved.report_artifacts[0].id).content == "manual fit notes\n"
    assert [view.id for view in gui_run.comparisons()] == [comparison.id]
    assert overview.overview.run_id == baseline.id


@pytest.mark.parametrize(
    ("action", "expected_code"),
    [
        (lambda analysis: analysis.note(""), "analysis_note_invalid"),
        (
            lambda analysis: analysis.report(
                title="bad source",
                text="x",
                content=b"x",
                filename="x.md",
            ),
            "analysis_report_source_invalid",
        ),
        (
            lambda analysis: analysis.report(
                title="bad filename",
                text="x",
                filename="../x.md",
            ),
            "analysis_report_filename_invalid",
        ),
        (
            lambda analysis: analysis.artifact(
                title="missing file",
                kind="html",
                path="/missing/analysis-source.html",
            ),
            "analysis_artifact_source_missing",
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
                .propose("drive_frequency", 5.0, unit="GHz")
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

    assert [output.kind for output in analysis.outputs] == [
        "note",
        "table",
        "proposal",
    ]
    assert promoted.id == "readout.fit"
    assert rerun_analysis.title == "readout fit"
    assert rerun_analysis.key == "readout.fit"
    assert rerun_analysis.step_id == "readout.fit"
    assert rerun_analysis.outputs == analysis.outputs
    assert rerun_analysis.parameter_proposals == analysis.parameter_proposals


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
        .propose("drive_frequency", 5.5, unit="GHz", confidence=0.9)
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
