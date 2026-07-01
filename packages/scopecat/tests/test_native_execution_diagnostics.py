from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.instruments import (
    NativeBoundaryManifest,
    NativeRunSnapshot,
    execute_native_run,
)
from scopecat.instruments.sdk import (
    NativeAcquisitionContext,
    NativeInstrumentResult,
)
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementSink
from scopecat.runs import open_run_store
from tests.support.native_signal import TestSignalInstrument
from tests.support.records import read_model
from tests.support.workflow_fixtures import load_config, load_experiment


class FailingAcquireInstrument(TestSignalInstrument):
    implementation_id = "test.failing_native"

    def acquire(
        self,
        context: NativeAcquisitionContext,
        sink: MeasurementSink,
    ) -> NativeInstrumentResult:
        del context, sink
        raise RuntimeError("boom")


class DuplicateMeasurementInstrument(TestSignalInstrument):
    implementation_id = "test.duplicate_native"

    def acquire(
        self,
        context: NativeAcquisitionContext,
        sink: MeasurementSink,
    ) -> NativeInstrumentResult:
        for _ in range(2):
            sink.record(
                point_index=context.point.index,
                coordinates=context.point.coordinates,
                observables={"signal": Quantity(value=1.0, unit="ratio")},
            )
        return NativeInstrumentResult()


def test_native_run_rejects_missing_instrument(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_native_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "native_missing_instrument"


def test_native_run_rejects_unsupported_native_field(tmp_path: Path) -> None:
    experiment = load_experiment()
    state = experiment.state[0].model_copy(update={"field": "set_frequency.amplitude"})
    experiment = experiment.model_copy(update={"state": [state]})

    with pytest.raises(ValidationFailed) as error:
        execute_native_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "native_unsupported_field"


def test_native_instrument_exception_keeps_failed_run(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_native_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[FailingAcquireInstrument()],
            workspace=tmp_path,
        )

    assert "native_instrument_acquire_failed" in {
        diagnostic.code for diagnostic in error.value.diagnostics
    }
    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "failed"
    run_dir = tmp_path / "runs" / manifests[0].run_id
    assert (run_dir / "artifacts" / "native-run.snapshot.json").is_file()
    assert (run_dir / "artifacts" / "native-run.boundary.json").is_file()
    assert (run_dir / "artifacts" / "raw-measurements.jsonl").read_text() == ""
    snapshot = read_model(
        run_dir / "artifacts" / "native-run.snapshot.json",
        NativeRunSnapshot,
    )
    boundary = read_model(
        run_dir / "artifacts" / "native-run.boundary.json",
        NativeBoundaryManifest,
    )
    assert snapshot.status == "failed"
    assert snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert {diagnostic.code for diagnostic in snapshot.diagnostics} >= {
        "native_instrument_acquire_failed"
    }
    assert boundary.status == "failed"
    assert boundary.plan_content_hash == snapshot.plan.content_hash
    assert boundary.point_count == snapshot.point_count
    assert boundary.measurement_count == snapshot.measurement_count
    assert boundary.diagnostics == snapshot.diagnostics
    assert {diagnostic.code for diagnostic in boundary.diagnostics} >= {
        "native_instrument_acquire_failed"
    }


def test_native_run_rejects_duplicate_measurement_indices(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_native_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[DuplicateMeasurementInstrument()],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "native_duplicate_measurement_index"
    manifest = open_run_store(tmp_path).list_runs()[0]
    assert manifest.status == "failed"
