from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

import scopecat as sc
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec, PlanSnapshot
from scopecat.models.parameter import Quantity
from tests.support.records import read_model
from tests.support.signal_instruments import TestSignalInstrumentProvider

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


class AnalysisArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def test_workspace_runs_and_reads_exploratory_data(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )

    run = lab.run(load_experiment())
    data = run.data()
    raw = data.measurements()
    measurement_datasets = data.list(kind="measurement_dataset")
    data.dataset(
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
    assert raw.dataset_entry.id == "raw-measurements"
    assert [dataset.id for dataset in measurement_datasets] == ["raw-measurements"]
    assert len(raw.dataset.records) == 3
    assert figure.artifact.id == "analysis-plot"
    assert figure.content == b"\x89PNG\r\n"
    assert isinstance(plan_preview, PlanSnapshot)
    assert plan_preview.expected_dataset_schema is not None
    assert data.artifacts == run.artifacts
    assert data.datasets == run.datasets


def test_data_selectors_report_notebook_friendly_diagnostics(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
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
        instrument_provider=TestSignalInstrumentProvider(),
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

    assert attachment.id == "notebook"
    assert attachment.kind == "attachment"
    assert attachment.produced_by == "run.attach"
    assert run.data().text("notebook").content == "manual fit notes\n"
    assert [input_ref.target for input_ref in saved.inputs] == [
        "notebook",
        "raw-measurements",
    ]
    assert run.overview().analysis_records[0].input_ids == [
        "artifact:notebook",
        "dataset:raw-measurements",
    ]


def test_workspace_experiment_wraps_existing_source(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
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
        instrument_provider=TestSignalInstrumentProvider(),
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
    assert (
        run.record_json("execution-snapshot").content["experiment_id"]
        == "manual-signal-scan"
    )
    planned_frequencies = [point.row["drive_frequency"] for point in run.plan.points]
    assert planned_frequencies == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert run.plan.expected_dataset_schema is not None


def test_workspace_experiment_builder_supports_active_center_sweep(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    experiment = (
        lab.experiment("active centered scan")
        .sweep("drive_frequency", around="active", span="200 MHz", points=3)
        .measure("signal")
    )

    preview = lab.preview(experiment)

    planned_frequencies = [
        point.row["drive_frequency"] for point in preview.plan.points
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
        instrument_provider=TestSignalInstrumentProvider(),
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
            sc.set_param("drive_frequency", sc.Quantity(5.0, "GHz")),
            reason="middle point produced the best signal",
            confidence=0.8,
        )
    )
    candidate = analysis.candidate_config()
    saved = analysis.save()

    assert [output.kind for output in analysis.outputs] == [
        "note",
        "table",
        "parameter_change",
    ]
    assert [input_ref.target for input_ref in analysis.inputs] == [
        "raw-measurements",
        "file:///tmp/manual-notes.ipynb",
    ]
    assert candidate.source_run_id == run.id
    assert candidate.analysis_title == "manual readout review"
    assert candidate.analysis_key == "manual-readout-review"
    assert candidate.parameter_changes[0].patches[0].parameter_id == "drive_frequency"
    assert saved.record.kind == "analysis"
    assert saved.record.id == "analysis-manual-readout-review"
    assert [record.id for record in run.overview().analysis_records] == [
        "analysis-manual-readout-review"
    ]


def test_run_analysis_persists_output_artifacts(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())
    source_report = tmp_path / "fit-report.html"
    source_report.write_text("<h1>fit</h1>\n")

    saved = (
        run.analysis("manual report review")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .artifact(
            title="source html",
            kind="analysis_html",
            path=source_report,
            artifact_id="manual-html-artifact",
            metadata={"section": "fit"},
        )
        .artifact(
            title="fit markdown",
            kind="analysis_notes",
            text="best point: 1",
            filename="fit-summary.md",
            media_type="text/markdown",
        )
        .artifact(
            title="plot bytes",
            kind="analysis_plot",
            content=b"\x89PNG\r\n",
            filename="fit-plot.bin",
        )
        .save()
    )
    overview = run.overview()

    assert [artifact.kind for artifact in saved.output_artifacts] == [
        "analysis_html",
        "analysis_notes",
        "analysis_plot",
    ]
    assert [artifact.id for artifact in run.data().list(kind="analysis_notes")] == [
        "analysis-manual-report-review-fit-markdown",
    ]
    assert [artifact.id for artifact in run.data().list(kind="analysis_html")] == [
        "manual-html-artifact",
    ]
    assert run.data().text("manual-html-artifact").content == "<h1>fit</h1>\n"
    assert (
        run.data().text("analysis-manual-report-review-fit-markdown").content
        == "best point: 1\n"
    )
    assert (
        run.data().bytes("analysis-manual-report-review-plot-bytes").content
        == b"\x89PNG\r\n"
    )
    assert saved.output_artifacts[0].metadata["section"] == "fit"
    assert overview.analysis_records[0].output_ids == [
        "manual-html-artifact",
        "analysis-manual-report-review-fit-markdown",
        "analysis-manual-report-review-plot-bytes",
    ]


def test_run_analysis_persists_owned_artifacts(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
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


def test_run_analysis_artifact_save_rejects_duplicate_ids_and_filenames(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
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

    saved = (
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
    assert [artifact.id for artifact in saved.output_artifacts] == ["one", "two"]


def test_analysis_artifacts_dedupe_sources_and_feed_overview(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
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
        .propose(
            "drive_frequency",
            sc.set_param("drive_frequency", sc.Quantity(5.0, "GHz")),
        )
        .save()
    )
    overview = run.overview()

    assert [input_ref.target for input_ref in saved.inputs] == [
        "raw-measurements",
        "file:///tmp/manual-source-review.ipynb",
        "raw-measurements",
    ]
    assert [analysis.input_ids for analysis in overview.analysis_records] == [
        ["dataset:raw-measurements", "uri:file:///tmp/manual-source-review.ipynb"]
    ]


def test_workspace_reopens_runs_for_gui_entry_contract(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = load_experiment()
    baseline = lab.run(experiment)
    analysis = (
        baseline.analysis("gui review")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .artifact(
            title="fit notes",
            kind="fit_notes",
            text="manual fit notes",
            filename="gui-fit-notes.md",
            media_type="text/markdown",
        )
        .propose(
            "drive_frequency",
            sc.set_param("drive_frequency", sc.Quantity(5.0, "GHz")),
            reason="manual fit",
        )
    )
    saved = analysis.save()
    candidate = analysis.candidate_config()
    follow_up = lab.run(experiment, config=candidate)
    comparison = lab.compare(baseline, follow_up, observable="signal")
    overview = baseline.overview()

    reopened = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    gui_runs = reopened.runs()
    gui_run = reopened.get_run(baseline.id)
    gui_data = gui_run.data()
    gui_overview = gui_run.overview()

    assert [run.id for run in gui_runs] == [baseline.id, follow_up.id]
    assert gui_run.id == baseline.id
    assert gui_data.measurements().dataset_entry.id == "raw-measurements"
    assert [record.id for record in gui_overview.analysis_records] == [saved.record.id]
    assert gui_overview.analysis_records[0].input_ids == ["dataset:raw-measurements"]
    assert [artifact.id for artifact in gui_data.list(kind="fit_notes")] == [
        saved.output_artifacts[0].id
    ]
    assert gui_data.text(saved.output_artifacts[0].id).content == "manual fit notes\n"
    assert [view.id for view in gui_run.comparisons()] == [comparison.id]
    assert overview.run_id == baseline.id


@pytest.mark.parametrize(
    ("action", "expected_code"),
    [
        (lambda analysis: analysis.note(""), "analysis_note_invalid"),
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
        instrument_provider=TestSignalInstrumentProvider(),
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
                .propose(
                    "drive_frequency",
                    sc.set_param("drive_frequency", sc.Quantity(5.0, "GHz")),
                )
            )

    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.run(load_experiment())
    step: sc.AnalysisStep = ReadoutFit()

    analysis = run.analyze(step)
    promoted = analysis.promote_step(step.id)
    rerun_analysis = promoted.run(run)

    assert [output.kind for output in analysis.outputs] == [
        "note",
        "table",
        "parameter_change",
    ]
    assert promoted.id == "readout.fit"
    assert rerun_analysis.title == "readout fit"
    assert rerun_analysis.key == "readout.fit"
    assert rerun_analysis.step_id == "readout.fit"
    assert rerun_analysis.outputs == analysis.outputs
    assert rerun_analysis.parameter_changes == analysis.parameter_changes
