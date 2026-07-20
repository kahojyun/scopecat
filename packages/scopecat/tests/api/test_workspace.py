from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

import scopecat as sc
from scopecat.kernel.errors import CheckFailed, Conflict, NotFound
from scopecat.kernel.problems import ProblemPhase
from scopecat.records.parameter import Quantity
from scopecat.records.run_request import (
    AroundScanRecord,
    PointScanRecord,
    RunRequest,
    RunRequestParameterValue,
    ScanGroupRecord,
    parameter_scan_records,
    scan_axis_index,
)
from tests.testkit.authoring import (
    DRIVE_FREQUENCY_POINT,
    SIMPLE_MODULE,
    simple_template,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.records import read_model
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_invocation

PHASE_OFFSET_POINT = sc.point(
    "phase_offset",
    sc.ScalarType(sc.QuantityType(unit="rad")),
)
READOUT_GAIN_POINT = sc.point(
    "readout_gain",
    sc.ScalarType(sc.FloatType()),
)


class AnalysisArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _workspace_readout_instance(instance_id: str) -> sc.ModuleInvocation:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    module = (
        sc.module("workspace.readout")
        .inputs(subject)
        .resource("source", requires=("set_frequency", "scalar_signal"))
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=DRIVE_FREQUENCY_POINT,
        )
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    return module.instantiate(instance_id, subject="q0")


def test_workspace_runs_and_reads_exploratory_data(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )

    run = lab.prepare(load_invocation()).run()
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

    assert isinstance(lab, sc.Workspace)
    assert isinstance(run, sc.Run)
    assert raw.dataset_entry.id == "raw-measurements"
    assert [dataset.id for dataset in measurement_datasets] == ["raw-measurements"]
    assert len(raw.dataset.records) == 3
    assert figure.artifact.id == "analysis-plot"
    assert figure.content == b"\x89PNG\r\n"
    assert isinstance(schema, sc.MeasurementDatasetSchema)
    assert schema.primary_observables == ["signal"]
    assert data.artifacts == run.artifacts
    assert data.datasets == run.datasets


def test_workspace_resolves_authoritative_active_config(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    config = lab.resolve_config()
    q0 = next(entity for entity in config.topology.entities if entity.id == "q0")
    source = next(
        instrument
        for instrument in config.instrument_registry.instruments
        if instrument.id == "source-0"
    )

    assert config.id == "example-workspace-profile"
    assert config.primary_entity_id == "q0"
    assert len(config.topology.entities) == 3
    assert len(config.topology.channels) == 2
    assert q0.kind == "logical_device"
    assert source.id == "source-0"
    assert [
        (binding.capability, binding.entity_id, binding.channel_id)
        for binding in config.routing.bindings
        if binding.instrument_id == source.id
    ] == [
        ("set_frequency", "q0", "drive-q0"),
        ("scalar_signal", "q0", "readout-q0"),
    ]


def test_workspace_activates_direct_configs_and_rolls_back_with_cas(
    tmp_path: Path,
) -> None:
    lab = sc.open(tmp_path, config_profile=EXAMPLE_DIR / "config-profile.json")
    baseline = lab.activate_config(
        load_config(),
        entry_id="workspace-baseline",
        registered_by="registrar",
        operator="deployer",
        note="register baseline",
        activation_note="select baseline",
        expected_generation=0,
    )
    updated = lab.activate_config(
        load_config().model_copy(update={"id": "workspace-updated"}),
        entry_id="workspace-updated",
        expected_generation=baseline.active_state.generation,
    )

    with pytest.raises(Conflict) as stale:
        lab.activate_config(
            load_config().model_copy(update={"id": "workspace-stale"}),
            entry_id="workspace-stale",
            expected_generation=baseline.active_state.generation,
        )

    restored = lab.rollback(
        expected_generation=updated.active_state.generation,
        operator="rollback-operator",
        note="restore baseline",
    )

    assert baseline.entry.registered_by == "registrar"
    assert baseline.entry.note == "register baseline"
    assert baseline.activation.operator == "deployer"
    assert baseline.activation.note == "select baseline"
    assert updated.active_state.generation == 2
    assert stale.value.problems[0].code == "config_registry.conflict"
    assert restored.active_state.generation == 3
    assert restored.active_state.active_entry_id == baseline.entry.id
    assert restored.activation.action == "rollback"
    assert restored.activation.operator == "rollback-operator"
    assert restored.activation.note == "restore baseline"


def test_data_selectors_report_structured_problems(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()
    data = run.data()

    assert data.list(metadata={"source_step": "unknown"}) == ()

    with pytest.raises(NotFound) as missing_error:
        data.artifact("missing-artifact")
    assert missing_error.value.problems[0].code == "run.artifact_not_found"

    with pytest.raises(CheckFailed) as escape_error:
        data.artifact("../workspace.json")
    assert escape_error.value.problems[0].code == "run.artifact_selector_path_escape"


def test_run_attachment_can_feed_analysis_inputs(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()

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
    assert [(input_ref.kind, input_ref.target) for input_ref in saved.inputs] == [
        ("artifact", "notebook"),
        ("dataset", "raw-measurements"),
    ]


def test_workspace_experiment_wraps_existing_module_source(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    readout = _workspace_readout_instance("readout")
    experiment = (
        lab.experiment("readout scan")
        .use(readout)
        .scan(
            DRIVE_FREQUENCY_POINT,
            [
                Quantity(value=4.9, unit="GHz"),
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=5.1, unit="GHz"),
            ],
        )
        .record_product(readout.products.signal, record_id="signal")
    )

    run = experiment.run()

    assert experiment.name == "readout scan"
    assert run.manifest.status == "completed"


def test_workspace_experiment_composes_module_source_with_authored_content(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(
            provider=TestSignalInstrumentProvider(
                additional_product_keys=("manual_signal",),
            )
        ),
    )
    readout = _workspace_readout_instance("readout")
    experiment = (
        lab.experiment("readout scan")
        .use(readout)
        .scan(
            DRIVE_FREQUENCY_POINT,
            [
                Quantity(value=4.9, unit="GHz"),
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=5.1, unit="GHz"),
            ],
        )
        .record_product(readout.products.signal, record_id="signal")
        .resource("source", requires=("scalar_signal",))
        .record(
            "manual_signal",
            resource="source",
            capability="scalar_signal",
            product_key="manual_signal",
            unit="ratio",
        )
    )

    preview = experiment.preview()

    assert preview.point_count == 3
    assert set(preview.primary_observables) == {"signal", "manual_signal"}


def test_prepared_experiment_check_returns_authoring_problems(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    validation = lab.prepare(simple_template()).check()

    assert validation.ok is False
    assert validation.preview is None
    assert [problem.code for problem in validation.problems] == [
        "experiment_template_missing_input"
    ]
    assert validation.problems[0].phase is ProblemPhase.AUTHORING


def test_prepared_experiment_check_returns_config_selection_problems(
    tmp_path: Path,
) -> None:
    lab = sc.open(tmp_path)

    validation = (
        lab.prepare(
            simple_template(),
            config=load_config(),
            config_profile=EXAMPLE_DIR / "config-profile.json",
        )
        .input("subject", "q0")
        .check()
    )

    assert validation.ok is False
    assert validation.preview is None
    assert [problem.code for problem in validation.problems] == [
        "config.source_conflict"
    ]


def test_prepared_experiment_check_returns_record_schema_problems(
    tmp_path: Path,
) -> None:
    module = (
        sc.module("test.invalid-record-unit")
        .product("signal", unit="not-a-unit")
        .build()
    )
    template = (
        module.template(
            "test.invalid-record-unit",
            kind="invalid_record",
        )
        .record_product("signal")
        .build()
    )
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    validation = lab.prepare(template).check()

    assert validation.ok is False
    assert validation.preview is None
    assert [problem.code for problem in validation.problems] == [
        "product_unit_unsupported"
    ]


def test_prepared_experiment_check_returns_candidate_config_problems(
    tmp_path: Path,
) -> None:
    candidate = sc.CandidateConfig(
        parameter_proposals=(),
    )
    prepared = (
        sc.open(tmp_path)
        .prepare(simple_template(), config=candidate)
        .input("subject", "q0")
    )

    validation = prepared.check()

    assert validation.ok is False
    assert validation.preview is None
    assert [problem.code for problem in validation.problems] == [
        "candidate_config_empty"
    ]
    with pytest.raises(CheckFailed) as preview_error:
        prepared.preview()
    assert [problem.code for problem in preview_error.value.problems] == [
        "candidate_config_empty"
    ]


def test_workspace_experiment_lowers_to_runnable_spec(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    experiment = (
        lab.experiment("manual signal scan")
        .entity("qubit", "q0")
        .scan(
            DRIVE_FREQUENCY_POINT,
            [
                Quantity(value=4.9, unit="GHz"),
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=5.1, unit="GHz"),
            ],
        )
        .resource("source", requires=("scalar_signal",))
        .measure("signal", resource="source", capability="scalar_signal")
    )

    run = experiment.run()

    assert run.manifest.status == "completed"
    run_dir = tmp_path / "runs" / run.id
    persisted_request = read_model(run_dir / "run-request.json", RunRequest)
    assert persisted_request.template_id == "scopecat.workspace.experiment"
    assert persisted_request.template_inputs["name"] == "manual signal scan"
    assert persisted_request.template_inputs["entity_inputs"] == {"qubit": "q0"}
    scan_axes = scan_axis_index(persisted_request.scans)
    drive_frequency_scan = scan_axes["drive_frequency"]
    assert isinstance(drive_frequency_scan, PointScanRecord)
    assert drive_frequency_scan.axis_id == "drive_frequency"
    dataset = run.measurements().dataset
    assert [point.coordinates["drive_frequency"] for point in dataset.records] == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert dataset.dataset_schema.primary_observables == ["signal"]
    assert run.config.workspace_id == "example-workspace"
    assert run.request == persisted_request


def test_workspace_run_options_materialize_internal_run_request(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )

    run = (
        lab.prepare(simple_template())
        .input("subject", "q0")
        .scan(
            DRIVE_FREQUENCY_POINT,
            span=Quantity(value=100.0, unit="MHz"),
            points=3,
        )
        .run(
            name="narrow readout scan",
            tags=("notebook", "calibration"),
            description="previewed in the notebook before running",
            metadata={"notebook": "02_define_experiment"},
            operator="alice",
        )
    )

    run_dir = tmp_path / "runs" / run.id
    persisted_request = read_model(run_dir / "run-request.json", RunRequest)

    assert run.manifest.status == "completed"
    assert persisted_request.template_id == "test.simple_scan"
    assert persisted_request.template_inputs["subject"] == "q0"
    drive_scan = scan_axis_index(persisted_request.scans)["drive_frequency"]
    assert isinstance(drive_scan, AroundScanRecord)
    assert drive_scan.target_id == "drive_frequency"
    assert drive_scan.axis_id == "drive_frequency"
    assert drive_scan.center == RunRequestParameterValue(parameter_id="drive_frequency")
    assert drive_scan.span == Quantity(value=100.0, unit="MHz")
    assert drive_scan.points == 3
    assert parameter_scan_records(persisted_request.scans) == []
    assert persisted_request.metadata == {
        "notebook": "02_define_experiment",
        "name": "narrow readout scan",
        "tags": ["notebook", "calibration"],
        "description": "previewed in the notebook before running",
    }
    assert persisted_request.operator == "alice"


def test_workspace_terminals_reject_non_finite_metadata(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )
    prepared = lab.prepare(simple_template())

    with pytest.raises(ValueError, match="finite"):
        prepared.check(metadata={"score": float("nan")})


def test_prepared_template_builder_preview_and_run_terminals(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    template = (
        SIMPLE_MODULE.template("test.prepared_builder", kind="simple_scan")
        .experiment_id("prepared-builder")
        .input("subject")
        .input("drive_frequency")
        .scan(
            DRIVE_FREQUENCY_POINT,
            center=Quantity(value=5.0, unit="GHz"),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        )
        .record_product("signal")
    )

    plan = (
        lab.prepare(template)
        .input("subject", "q0")
        .scan(
            DRIVE_FREQUENCY_POINT,
            span=Quantity(value=100.0, unit="MHz"),
            points=3,
        )
    )
    preview = plan.preview()
    run = plan.run(name="prepared builder scan")

    assert preview.point_count == 3
    assert run.manifest.status == "completed"
    assert len(run.measurements().dataset.records) == 3
    persisted_request = read_model(
        tmp_path / "runs" / run.id / "run-request.json",
        RunRequest,
    )
    assert persisted_request.template_id == "test.prepared_builder"
    assert persisted_request.metadata["name"] == "prepared builder scan"
    drive_scan = scan_axis_index(persisted_request.scans)["drive_frequency"]
    assert isinstance(drive_scan, AroundScanRecord)
    assert drive_scan.center == Quantity(value=5.0, unit="GHz")


def test_workspace_experiment_preview_and_run_terminals(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    experiment = (
        lab.experiment("terminal signal scan")
        .entity("qubit", "q0")
        .scan(DRIVE_FREQUENCY_POINT, span="200 MHz", points=3)
        .resource("source", requires=("scalar_signal",))
        .measure("signal", resource="source", capability="scalar_signal")
    )

    preview = experiment.preview()
    run = experiment.run(name="terminal signal scan")

    assert preview.point_count == 3
    assert run.manifest.status == "completed"


def test_workspace_extra_scans_can_zip_axes(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )

    run = (
        lab.prepare(simple_template())
        .input("subject", "q0")
        .scan(
            sc.zip(
                sc.axis(PHASE_OFFSET_POINT, [0.0, 0.5], unit="rad"),
                sc.axis(READOUT_GAIN_POINT, [1.0, 2.0]),
            )
        )
        .run()
    )

    run_dir = tmp_path / "runs" / run.id
    persisted_request = read_model(run_dir / "run-request.json", RunRequest)

    assert len(run.measurements().dataset.records) == 10
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
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    template = (
        SIMPLE_MODULE.template("test.default_zip_override", kind="default_zip_override")
        .experiment_id("default-zip-override")
        .input("subject")
        .scan(
            sc.zip(
                sc.axis(DRIVE_FREQUENCY_POINT, [4.9, 5.0], unit="GHz"),
                sc.axis(PHASE_OFFSET_POINT, [0.0, 0.5], unit="rad"),
            )
        )
    )

    preview = (
        lab.prepare(template)
        .input("subject", "q0")
        .scan(
            DRIVE_FREQUENCY_POINT,
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


def test_implicit_around_override_of_values_default_uses_active_center(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    template = (
        SIMPLE_MODULE.template(
            "test.values_default_active_override",
            kind="values_default_active_override",
        )
        .experiment_id("values-default-active-override")
        .input("subject")
        .scan(DRIVE_FREQUENCY_POINT, [4.9, 5.0], unit="GHz")
    )

    preview = (
        lab.prepare(template)
        .input("subject", "q0")
        .scan(DRIVE_FREQUENCY_POINT, span="200 MHz", points=3)
        .preview()
    )

    assert [point.coordinates["drive_frequency"] for point in preview.points] == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]


def test_invocation_scan_group_rejects_mixed_default_override(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    template = (
        SIMPLE_MODULE.template("test.mixed_scan_override", kind="mixed_scan_override")
        .experiment_id("mixed-scan-override")
        .input("subject")
        .scan(DRIVE_FREQUENCY_POINT, [4.9, 5.0], unit="GHz")
    )

    with pytest.raises(CheckFailed) as error:
        (
            lab.prepare(template)
            .input("subject", "q0")
            .scan(
                sc.zip(
                    sc.axis(DRIVE_FREQUENCY_POINT, [5.1, 5.2], unit="GHz"),
                    sc.axis(PHASE_OFFSET_POINT, [0.0, 0.5], unit="rad"),
                )
            )
            .preview()
        )

    assert error.value.problems[0].code == "scan_group_mixed_override"


def test_workspace_experiment_supports_active_center_scan(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    experiment = (
        lab.experiment("active centered scan")
        .scan(DRIVE_FREQUENCY_POINT, span="200 MHz", points=3)
        .resource("source", requires=("scalar_signal",))
        .measure("signal", resource="source", capability="scalar_signal")
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


def test_workspace_experiment_defines_complete_experiment(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    experiment = (
        lab.experiment("complete scripted scan")
        .resource("source", requires=("set_frequency", "scalar_signal"))
        .scan(DRIVE_FREQUENCY_POINT, span="200 MHz", points=3)
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=DRIVE_FREQUENCY_POINT,
        )
        .record("signal", resource="source", capability="scalar_signal")
    )

    preview = experiment.preview()
    run = experiment.run()

    assert run.manifest.status == "completed"
    assert preview.point_count == 3
    assert preview.coordinate_ids == ("drive_frequency",)
    assert [record.id for record in preview.records] == ["signal"]


def test_workspace_module_can_be_composed(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    drive_frequency = sc.input(
        "drive_frequency",
        sc.ScalarType(sc.QuantityType()),
    )
    signal_scan = (
        sc.module("workspace.signal_scan")
        .inputs(drive_frequency)
        .resource("source", requires=("set_frequency", "scalar_signal"))
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=drive_frequency,
        )
        .product("signal")
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    signal_scan_instance = signal_scan.instantiate(
        "signal-scan",
        drive_frequency=DRIVE_FREQUENCY_POINT,
    )

    run = (
        lab.experiment("composed signal scan")
        .use(signal_scan_instance)
        .scan(DRIVE_FREQUENCY_POINT, span="200 MHz", points=3)
        .record_product(signal_scan_instance.products.signal, record_id="signal")
        .run()
    )

    assert run.manifest.status == "completed"
    assert run.request is not None
    assert run.request.template_inputs["name"] == "composed signal scan"


def test_workspace_preserves_nominal_product_refs(tmp_path: Path) -> None:
    lab = sc.open(tmp_path, config_profile=EXAMPLE_DIR / "config-profile.json")
    definition = sc.module("workspace.nominal-product").product("signal").build()
    foreign = definition.instantiate("same")
    selected = definition.instantiate("same")

    accepted = (
        lab.experiment("accepted nominal product")
        .use(selected)
        .record_product(selected.products.signal)
        .to_invocation()
    )
    assert accepted.template.record_selections[0].product_origin is not None

    with pytest.raises(CheckFailed) as error:
        (
            lab.experiment("foreign nominal product")
            .use(selected)
            .record_product(foreign.products.signal)
            .to_invocation()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_product_foreign_instance"
    ]


def test_run_analysis_collects_notebook_outputs_and_candidate_config(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()
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
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.1, "GHz"),
            ),
            reason="middle point produced the best signal",
            confidence=0.8,
        )
    )
    candidate = analysis.candidate_config()
    saved = analysis.save()

    assert [output.kind for output in analysis.outputs] == [
        "note",
        "table",
        "parameter_change_proposal",
    ]
    assert [input_ref.target for input_ref in analysis.inputs] == [
        "raw-measurements",
        "file:///tmp/manual-notes.ipynb",
    ]
    assert candidate.source_run_id == run.id
    assert candidate.parameter_proposals[0].deltas[0].parameter_id == "drive_frequency"
    assert saved.record.kind == "analysis"
    assert saved.record.id == "analysis-manual-readout-review"
    assert [
        record.id for record in run.manifest.records if record.kind == "analysis"
    ] == ["analysis-manual-readout-review"]


def test_workspace_candidate_activation_honors_expected_generation(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    baseline = lab.activate_config(
        load_config(),
        entry_id="candidate-baseline",
        expected_generation=0,
    )
    run = lab.prepare(load_invocation(), config="active").run()
    analysis = run.analysis("candidate activation").propose(
        "drive-frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.1, "GHz"),
        ),
    )
    analysis.save()
    lab.review_parameter_proposal(run, "drive-frequency")
    candidate = analysis.candidate_config()

    with pytest.raises(Conflict) as stale:
        lab.activate(
            candidate,
            entry_id="workspace-candidate",
            expected_generation=0,
        )

    published = lab.activate(
        candidate,
        entry_id="workspace-candidate",
        expected_generation=baseline.active_state.generation,
    )

    assert stale.value.problems[0].code == "config_registry.conflict"
    assert published.active_state.generation == 2
    assert published.active_state.active_entry_id == published.entry.id


def test_run_analysis_persists_output_artifacts(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()
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
    assert [artifact.title for artifact in saved.output_artifacts] == [
        "source html",
        "fit markdown",
        "plot bytes",
    ]
    assert [artifact.id for artifact in saved.output_artifacts] == [
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
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()
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
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()

    with pytest.raises(CheckFailed) as duplicate_id:
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
    assert duplicate_id.value.problems[0].code == "analysis_artifact_id_duplicated"

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


def test_analysis_artifacts_preserve_distinct_sources(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()

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
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.1, "GHz"),
            ),
        )
        .save()
    )
    assert [input_ref.target for input_ref in saved.inputs] == [
        "raw-measurements",
        "file:///tmp/manual-source-review.ipynb",
        "raw-measurements",
    ]


def test_workspace_reopens_runs_for_gui_entry_contract(tmp_path: Path) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    experiment = load_invocation()
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
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.1, "GHz"),
            ),
            reason="manual fit",
        )
    )
    saved = analysis.save()
    candidate = analysis.candidate_config()
    follow_up = lab.prepare(experiment, config=candidate).run()
    reopened = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    gui_runs = reopened.runs()
    gui_run = reopened.get_run(baseline.id)
    gui_data = gui_run.data()
    persisted_analysis = gui_run.record_json(saved.record.id, expected_kind="analysis")

    assert [run.id for run in gui_runs] == [baseline.id, follow_up.id]
    assert gui_run.id == baseline.id
    assert gui_data.measurements().dataset_entry.id == "raw-measurements"
    assert persisted_analysis.record.id == saved.record.id
    assert persisted_analysis.content["title"] == "gui review"
    assert [artifact.id for artifact in gui_data.list(kind="fit_notes")] == [
        saved.output_artifacts[0].id
    ]
    assert gui_data.text(saved.output_artifacts[0].id).content == "manual fit notes\n"


type _AnalysisAction = Callable[[sc.Analysis], object]

_INVALID_ANALYSIS_ACTIONS: list[tuple[_AnalysisAction, str]] = [
    (lambda analysis: analysis.note(""), "analysis_note_invalid"),
    (
        lambda analysis: analysis.artifact(
            title="missing file",
            kind="html",
            path="/missing/analysis-source.html",
        ),
        "analysis_artifact_source_missing",
    ),
]


@pytest.mark.parametrize(
    ("action", "expected_code"),
    _INVALID_ANALYSIS_ACTIONS,
)
def test_analysis_rejects_invalid_notebook_payloads(
    tmp_path: Path,
    action: _AnalysisAction,
    expected_code: str,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()

    with pytest.raises(CheckFailed) as error:
        action(run.analysis("manual review"))

    assert error.value.problems[0].code == expected_code


def test_analysis_step_reuses_manual_analysis_shape(tmp_path: Path) -> None:
    class ReadoutFit:
        id = "readout.fit"

        def run(self, context: sc.AnalysisContext) -> sc.Analysis:
            raw = context.data.measurements()
            assert context.config.parameter_snapshot.get("drive_frequency") is not None
            return (
                context.result("readout fit")
                .note(f"loaded {len(raw.dataset.records)} records")
                .table(
                    [{"center": 5.0, "unit": "GHz"}],
                    title="fit summary",
                )
                .propose(
                    "drive_frequency",
                    sc.replace_scalar_parameter(
                        "drive_frequency",
                        sc.Quantity(5.1, "GHz"),
                    ),
                )
            )

    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()
    step: sc.AnalysisStep = ReadoutFit()

    analysis = run.analyze(step)

    assert [output.kind for output in analysis.outputs] == [
        "note",
        "table",
        "parameter_change_proposal",
    ]
    assert analysis.title == "readout fit"
    assert analysis.key == "readout.fit"
    assert analysis.step_id == "readout.fit"
