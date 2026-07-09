from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

import scopecat as sc
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    AroundScanRecord,
    ExperimentSpec,
    PointScanRecord,
    RunRequest,
    ScanGroupRecord,
    parameter_scan_records,
    scan_axis_index,
)
from scopecat.models.config import build_config_parameters
from scopecat.models.parameter import Quantity
from scopecat.relations import lit
from tests.support.authoring import SIMPLE_MODULE, simple_template
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

    run = lab.prepare(load_experiment()).run()
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
    schema = data.schema()
    summary = data.summary("raw-measurements")

    assert isinstance(lab, sc.Workspace)
    assert isinstance(run, sc.Run)
    assert raw.dataset_entry.id == "raw-measurements"
    assert [dataset.id for dataset in measurement_datasets] == ["raw-measurements"]
    assert len(raw.dataset.records) == 3
    assert figure.artifact.id == "analysis-plot"
    assert figure.content == b"\x89PNG\r\n"
    assert isinstance(schema, sc.MeasurementDatasetSchema)
    assert schema.primary_observables == ["signal"]
    assert isinstance(summary, sc.DataDatasetSummary)
    assert summary.record_count == 3
    assert summary.coordinate_ids == ("drive_frequency",)
    assert summary.observable_ids == ("signal",)
    assert data.artifacts == run.artifacts
    assert data.datasets == run.datasets


def test_workspace_system_summary_describes_active_config(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    summary = lab.system()
    q0 = next(entity for entity in summary.entities if entity.id == "q0")
    source = next(
        resource for resource in summary.resources if resource.id == "source-0"
    )

    assert isinstance(summary, sc.SystemSummary)
    assert summary.primary_entity_id == "q0"
    assert summary.entity_count == 3
    assert summary.channel_count == 2
    assert q0.resources == ("source-0",)
    assert source.capabilities == ("set_frequency",)
    assert source.channels == ("drive-q0",)


def test_data_selectors_report_notebook_friendly_diagnostics(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.prepare(load_experiment()).run()
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
    run = lab.prepare(load_experiment()).run()

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
    experiment = lab.experiment("readout scan", load_experiment())

    run = experiment.run()

    assert experiment.name == "readout scan"
    assert run.manifest.status == "completed"


def test_workspace_experiment_rejects_closed_source_fragments(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    experiment = lab.experiment("readout scan", load_experiment()).measure("signal")

    with pytest.raises(ValueError, match="closed ExperimentSpec"):
        experiment.preview()


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
        .entity("qubit", "q0")
        .scan(
            "drive_frequency",
            [
                Quantity(value=4.9, unit="GHz"),
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=5.1, unit="GHz"),
            ],
        )
        .measure("signal")
    )

    run = experiment.run()

    assert run.manifest.status == "completed"
    assert (
        run.record_json("execution-summary").content["experiment_id"]
        == "manual-signal-scan"
    )
    planned_frequencies = [
        point.coordinates["drive_frequency"] for point in run.preview.points
    ]
    assert planned_frequencies == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    run_dir = tmp_path / "runs" / run.id
    persisted_request = read_model(run_dir / "run-request.json", RunRequest)
    persisted_experiment = read_model(run_dir / "experiment-spec.json", ExperimentSpec)
    assert persisted_request.template_id == "scopecat.workspace.experiment"
    assert persisted_request.template_inputs["name"] == "manual signal scan"
    assert persisted_request.template_inputs["entity_inputs"] == {"qubit": "q0"}
    scan_axes = scan_axis_index(persisted_request.scans)
    drive_frequency_scan = scan_axes["drive_frequency"]
    assert isinstance(drive_frequency_scan, PointScanRecord)
    assert drive_frequency_scan.axis_id == "drive_frequency"
    assert persisted_experiment.request == persisted_request
    assert persisted_experiment.config_snapshot_id == run.config.id
    assert run.preview.primary_observables == ("signal",)


def test_workspace_run_options_materialize_internal_run_request(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )

    run = (
        lab.prepare(simple_template())
        .input("subject", "q0")
        .scan(
            "drive_frequency",
            span=Quantity(value=100.0, unit="MHz"),
            points=3,
        )
        .run(
            name="narrow readout scan",
            tags=("notebook", "calibration"),
            description="previewed in the notebook before running",
            overrides={"analysis_mode": "debug"},
            seeds={"fit": 7},
            extra_records={"readback": True},
            execution_flags={"dry_run": False},
            metadata={"notebook": "02_define_experiment"},
            operator="alice",
        )
    )

    run_dir = tmp_path / "runs" / run.id
    persisted_request = read_model(run_dir / "run-request.json", RunRequest)

    assert run.manifest.status == "completed"
    assert run.preview.point_count == 3
    assert persisted_request.template_id == "test.simple_scan"
    assert persisted_request.template_inputs["subject"] == "q0"
    drive_scan = scan_axis_index(persisted_request.scans)["drive_frequency"]
    assert isinstance(drive_scan, AroundScanRecord)
    assert drive_scan.target_id == "drive_frequency"
    assert drive_scan.axis_id == "drive_frequency"
    assert drive_scan.center["kind"] == "param_scalar"
    assert drive_scan.center["name"] == "drive_frequency"
    assert drive_scan.span == {"value": 100.0, "unit": "MHz"}
    assert drive_scan.points == 3
    assert parameter_scan_records(persisted_request.scans) == []
    assert persisted_request.metadata == {
        "notebook": "02_define_experiment",
        "name": "narrow readout scan",
        "tags": ["notebook", "calibration"],
        "description": "previewed in the notebook before running",
    }
    assert persisted_request.run_overrides == {"analysis_mode": "debug"}
    assert persisted_request.seeds == {"fit": 7}
    assert persisted_request.extra_records == {"readback": True}
    assert persisted_request.execution_flags == {"dry_run": False}
    assert persisted_request.operator == "alice"


def test_prepared_template_builder_preview_and_run_terminals(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    template = (
        sc.template("test.prepared_builder", kind="simple_scan")
        .experiment_id("prepared-builder")
        .input("subject", kind="entity")
        .input("drive_frequency", kind="quantity")
        .defaults(drive_frequency=None)
        .scan(
            "drive_frequency",
            center=lit(Quantity(value=5.0, unit="GHz")),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        )
        .use(SIMPLE_MODULE)
    )

    plan = (
        lab.prepare(template)
        .input("subject", "q0")
        .scan(
            "drive_frequency",
            span=Quantity(value=100.0, unit="MHz"),
            points=3,
        )
    )
    preview = plan.preview()
    run = plan.run(name="prepared builder scan")

    assert preview.point_count == 3
    assert run.manifest.status == "completed"
    persisted_request = read_model(
        tmp_path / "runs" / run.id / "run-request.json",
        RunRequest,
    )
    assert persisted_request.template_id == "test.prepared_builder"
    assert persisted_request.metadata["name"] == "prepared builder scan"
    drive_scan = scan_axis_index(persisted_request.scans)["drive_frequency"]
    assert isinstance(drive_scan, AroundScanRecord)
    assert drive_scan.center["kind"] == "literal"
    assert drive_scan.center["value"] == {"value": 5.0, "unit": "GHz"}


def test_workspace_experiment_preview_and_run_terminals(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = (
        lab.experiment("terminal signal scan")
        .entity("qubit", "q0")
        .scan("drive_frequency", span="200 MHz", points=3)
        .measure("signal")
    )

    preview = experiment.preview()
    run = experiment.run(name="terminal signal scan")

    assert preview.point_count == 3
    assert run.manifest.status == "completed"


def test_workspace_extra_scans_can_zip_axes(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )

    run = (
        lab.prepare(simple_template())
        .input("subject", "q0")
        .scan(
            sc.zip(
                sc.axis("phase_offset", [0.0, 0.5], unit="rad"),
                sc.axis("readout_gain", [1.0, 2.0]),
            )
        )
        .run()
    )

    run_dir = tmp_path / "runs" / run.id
    persisted_request = read_model(run_dir / "run-request.json", RunRequest)

    assert run.preview.point_count == 10
    scan_group = persisted_request.scans[-1]
    assert isinstance(scan_group, ScanGroupRecord)
    assert scan_group.model_dump(mode="json") == {
        "kind": "zip",
        "scans": [
            {
                "kind": "point",
                "target_id": "phase_offset",
                "axis_id": "phase_offset",
                "values": [0.0, 0.5],
                "unit": "rad",
            },
            {
                "kind": "point",
                "target_id": "readout_gain",
                "axis_id": "readout_gain",
                "values": [1.0, 2.0],
                "unit": None,
            },
        ],
    }


def test_invocation_scan_overrides_axis_inside_default_zip_group(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    template = (
        sc.template("test.default_zip_override", kind="default_zip_override")
        .experiment_id("default-zip-override")
        .input("subject", kind="entity")
        .scan(
            sc.zip(
                sc.axis("drive_frequency", [4.9, 5.0], unit="GHz"),
                sc.axis("phase_offset", [0.0, 0.5], unit="rad"),
            )
        )
        .use(SIMPLE_MODULE)
    )

    preview = (
        lab.prepare(template)
        .input("subject", "q0")
        .scan(
            "drive_frequency",
            [5.1, 5.2],
            unit="GHz",
        )
        .preview()
    )

    assert preview.point_count == 2
    assert [point.coordinates["drive_frequency"] for point in preview.points] == [
        Quantity(value=5.1, unit="GHz"),
        Quantity(value=5.2, unit="GHz"),
    ]
    assert [point.coordinates["phase_offset"] for point in preview.points] == [
        Quantity(value=0.0, unit="rad"),
        Quantity(value=0.5, unit="rad"),
    ]


def test_invocation_scan_group_rejects_mixed_default_override(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    template = (
        sc.template("test.mixed_scan_override", kind="mixed_scan_override")
        .experiment_id("mixed-scan-override")
        .input("subject", kind="entity")
        .scan("drive_frequency", [4.9, 5.0], unit="GHz")
        .use(SIMPLE_MODULE)
    )

    with pytest.raises(ValidationFailed) as error:
        (
            lab.prepare(template)
            .input("subject", "q0")
            .scan(
                sc.zip(
                    sc.axis("drive_frequency", [5.1, 5.2], unit="GHz"),
                    sc.axis("phase_offset", [0.0, 0.5], unit="rad"),
                )
            )
            .preview()
        )

    assert error.value.diagnostics[0].code == "scan_group_mixed_override"


def test_workspace_experiment_builder_supports_active_center_scan(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    experiment = (
        lab.experiment("active centered scan")
        .scan("drive_frequency", span="200 MHz", points=3)
        .measure("signal")
    )

    preview = experiment.preview()

    planned_frequencies = [
        point.coordinates["drive_frequency"] for point in preview.points
    ]
    assert planned_frequencies == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]


def test_workspace_experiment_builder_defines_complete_experiment(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    experiment = (
        lab.experiment("complete scripted scan")
        .resource("source", requires=("set_frequency",))
        .scan("drive_frequency", span="200 MHz", points=3)
        .bind("source.set_frequency.frequency", sc.var("drive_frequency"))
        .record("signal", resource="source")
    )

    run = experiment.run()

    assert run.manifest.status == "completed"
    assert run.preview.state_changes[0].resource == "source"
    assert run.preview.state_changes[0].field == "set_frequency.frequency"
    assert run.preview.state_changes[0].after == Quantity(
        value=4.9,
        unit="GHz",
    )


def test_workspace_module_can_be_composed(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    signal_scan = (
        sc.module("workspace.signal_scan")
        .input("drive_frequency", kind="quantity")
        .resource("source", requires=("set_frequency",))
        .bind("source.set_frequency.frequency", sc.var("drive_frequency"))
        .product("signal", resource="source")
        .build()
    )

    run = (
        lab.experiment("composed signal scan")
        .use(signal_scan)
        .scan("drive_frequency", span="200 MHz", points=3)
        .record_product("signal")
        .run()
    )

    assert run.manifest.status == "completed"
    assert run.record_json("execution-summary").content["experiment_id"] == (
        "composed-signal-scan"
    )


def test_run_analysis_collects_notebook_outputs_and_candidate_config(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.prepare(load_experiment()).run()
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
    run = lab.prepare(load_experiment()).run()
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
    run = lab.prepare(load_experiment()).run()
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
    run = lab.prepare(load_experiment()).run()

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
    run = lab.prepare(load_experiment()).run()

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
    baseline = lab.prepare(experiment).run()
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
    follow_up = lab.prepare(experiment, config=candidate).run()
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
    run = lab.prepare(load_experiment()).run()

    with pytest.raises(ValidationFailed) as error:
        action(run.analysis("manual review"))

    assert error.value.diagnostics[0].code == expected_code


def test_analysis_step_reuses_manual_analysis_shape(tmp_path: Path) -> None:
    class ReadoutFit:
        id = "readout.fit"

        def run(self, context: sc.AnalysisContext) -> sc.Analysis:
            raw = context.data.measurements()
            assert (
                build_config_parameters(context.config).get("drive_frequency")
                is not None
            )
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
    run = lab.prepare(load_experiment()).run()
    step: sc.AnalysisStep = ReadoutFit()

    analysis = run.analyze(step)

    assert [output.kind for output in analysis.outputs] == [
        "note",
        "table",
        "parameter_change",
    ]
    assert analysis.title == "readout fit"
    assert analysis.key == "readout.fit"
    assert analysis.step_id == "readout.fit"
