from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.instruments import execute_run
from scopecat.instruments.sdk import (
    AcquisitionContext,
    InstrumentResult,
)
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementSink
from scopecat.runs import open_run_store
from scopecat.workflows import read_run_record_json
from tests.support.signal_instruments import TestSignalInstrument
from tests.support.workflow_fixtures import load_config, load_experiment


class FailingAcquireInstrument(TestSignalInstrument):
    implementation_id = "test.failing_instrument"

    def acquire(
        self,
        context: AcquisitionContext,
        sink: MeasurementSink,
    ) -> InstrumentResult:
        del context, sink
        raise RuntimeError("boom")


class DuplicateMeasurementInstrument(TestSignalInstrument):
    implementation_id = "test.duplicate_instrument"

    def acquire(
        self,
        context: AcquisitionContext,
        sink: MeasurementSink,
    ) -> InstrumentResult:
        for _ in range(2):
            sink.record(
                point_index=context.point.index,
                coordinates=context.point.coordinates,
                observables={"signal": Quantity(value=1.0, unit="ratio")},
            )
        return InstrumentResult()


def test_run_rejects_missing_instrument(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "missing_instrument"


def test_run_rejects_unsupported_field(tmp_path: Path) -> None:
    experiment = load_experiment()
    state = experiment.state[0].model_copy(update={"field": "set_frequency.amplitude"})
    experiment = experiment.model_copy(update={"state": [state]})

    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "unsupported_field"


def test_instrument_exception_keeps_failed_run(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[FailingAcquireInstrument()],
            workspace=tmp_path,
        )

    assert "instrument_acquire_failed" in {
        diagnostic.code for diagnostic in error.value.diagnostics
    }
    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "failed"
    snapshot = read_run_record_json(
        run_id=manifests[0].run_id,
        selector="execution-snapshot",
        workspace=tmp_path,
        expected_kind="execution_snapshot",
    )
    assert snapshot.content["status"] == "failed"
    assert {diagnostic["code"] for diagnostic in snapshot.content["diagnostics"]} >= {
        "instrument_acquire_failed"
    }


def test_run_rejects_duplicate_measurement_indices(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[DuplicateMeasurementInstrument()],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "duplicate_measurement_index"
    manifest = open_run_store(tmp_path).list_runs()[0]
    assert manifest.status == "failed"
