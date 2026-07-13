from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopecat._workflows.runs import read_run_record_json
from scopecat.errors import ProviderContractError, RunFailed, RunIndeterminate
from scopecat.instruments.sdk import (
    CollectCommand,
    CollectReceipt,
    InstrumentReadback,
)
from scopecat.models.measurement import MeasurementDatasetSchema
from scopecat.models.parameter import Quantity
from scopecat.runs import dataset_storage_ref, open_run_store
from tests.support.execution import execute_bound_run
from tests.support.records import read_measurement_records
from tests.support.signal_instruments import TestSignalInstrument
from tests.support.workflow_fixtures import load_config, load_experiment


class FailingCollectInstrument(TestSignalInstrument):
    implementation_id = "test.failing_instrument"

    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        raise RuntimeError("boom")


class UnexpectedProductInstrument(TestSignalInstrument):
    implementation_id = "test.unexpected_product_instrument"

    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    "signal": Quantity(value=1.0, unit="ratio"),
                    "unexpected": Quantity(value=1.0, unit="ratio"),
                }
            )
        )


class InterruptingCollectInstrument(TestSignalInstrument):
    implementation_id = "test.interrupting_instrument"

    def __init__(self) -> None:
        super().__init__()
        self.aborted = False

    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        raise KeyboardInterrupt("operator cancelled")

    def abort(self) -> None:
        self.aborted = True


class FailAfterFirstCollectInstrument(TestSignalInstrument):
    implementation_id = "test.fail_after_first_instrument"

    def __init__(self) -> None:
        super().__init__()
        self.collect_count = 0

    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_count += 1
        if self.collect_count > 1:
            raise RuntimeError("second collection failed")
        return super().collect(command)


def test_run_rejects_missing_instrument(tmp_path: Path) -> None:
    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[],
            workspace=tmp_path,
        )

    assert error.value.problems[-1].code == "missing_instrument_description"
    assert open_run_store(tmp_path).list_runs() == []


def test_run_rejects_unsupported_field(tmp_path: Path) -> None:
    experiment = load_experiment()
    state = experiment.state[0].model_copy(update={"field_path": "amplitude"})
    experiment = experiment.model_copy(update={"state": [state]})

    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    assert error.value.problems[-1].code == "instrument_driver_unsupported_field"
    assert open_run_store(tmp_path).list_runs() == []


def test_run_rejects_unsupported_instrument_product(tmp_path: Path) -> None:
    experiment = load_experiment()
    experiment = experiment.model_copy(
        update={
            "records": [
                experiment.records[0].model_copy(update={"product_key": "missing"})
            ]
        }
    )

    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    assert error.value.problems[-1].code == "instrument_product_unsupported"
    assert open_run_store(tmp_path).list_runs() == []


def test_run_rejects_instrument_product_dtype_mismatch(tmp_path: Path) -> None:
    experiment = load_experiment()
    experiment = experiment.model_copy(
        update={
            "records": [experiment.records[0].model_copy(update={"dtype": "int64"})]
        }
    )

    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    assert error.value.problems[-1].code == "instrument_product_dtype_mismatch"
    assert open_run_store(tmp_path).list_runs() == []


def test_instrument_exception_keeps_unknown_run(tmp_path: Path) -> None:
    with pytest.raises(RunIndeterminate) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[FailingCollectInstrument()],
            workspace=tmp_path,
        )

    assert "instrument_collect_unknown" in {
        problem.code for problem in error.value.problems
    }
    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "unknown"
    snapshot = read_run_record_json(
        run_id=manifests[0].run_id,
        selector="execution-summary",
        workspace=tmp_path,
        expected_kind="execution_summary",
    )
    assert snapshot.content["outcome"]["result"] == "failed"
    assert snapshot.content["outcome"]["certainty"] == "indeterminate"
    assert {problem["code"] for problem in snapshot.content["problems"]} >= {
        "instrument_collect_unknown"
    }


def test_run_rejects_unexpected_instrument_products(tmp_path: Path) -> None:
    with pytest.raises(RunFailed) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[UnexpectedProductInstrument()],
            workspace=tmp_path,
        )

    assert error.value.problems[-1].code == "instrument_unexpected_product"
    manifest = open_run_store(tmp_path).list_runs()[0]
    assert manifest.status == "failed"


def test_keyboard_interrupt_commits_interrupted_terminal_run(tmp_path: Path) -> None:
    instrument = InterruptingCollectInstrument()

    with pytest.raises(KeyboardInterrupt, match="operator cancelled"):
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[instrument],
            workspace=tmp_path,
        )

    manifest = open_run_store(tmp_path).list_runs()[0]
    assert manifest.status == "interrupted"
    assert manifest.datasets == []
    assert instrument.aborted
    snapshot = read_run_record_json(
        run_id=manifest.run_id,
        selector="execution-summary",
        workspace=tmp_path,
        expected_kind="execution_summary",
    )
    assert snapshot.content["outcome"]["result"] == "cancelled"
    assert "execution_interrupted" in {
        problem["code"] for problem in snapshot.content["problems"]
    }
    journal_entries = [
        json.loads(path.read_text())
        for path in sorted(
            (tmp_path / "runs" / manifest.run_id / "execution" / "journal").glob(
                "*.json"
            )
        )
    ]
    collect_states = [
        entry["state"] for entry in journal_entries if entry["stage"] == "collect"
    ]
    assert collect_states == ["started", "unknown"]


def test_failed_run_exposes_readable_partial_dataset(tmp_path: Path) -> None:
    instrument = FailAfterFirstCollectInstrument()

    with pytest.raises(RunIndeterminate):
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[instrument],
            workspace=tmp_path,
        )

    manifest = open_run_store(tmp_path).list_runs()[0]
    assert manifest.status == "unknown"
    assert len(manifest.datasets) == 1
    dataset = manifest.datasets[0]
    assert dataset.metadata["partial"] is True
    assert dataset.metadata["expected_record_count"] == 3
    schema = MeasurementDatasetSchema.model_validate(dataset.data_schema)
    point_dimension = next(
        dimension for dimension in schema.dimensions if dimension.kind == "point"
    )
    assert point_dimension.size == 1
    records = read_measurement_records(
        tmp_path / "runs" / manifest.run_id / dataset_storage_ref(dataset)
    )
    assert [record.point_index for record in records] == [0]
    readback_files = list(
        (tmp_path / "runs" / manifest.run_id / "execution" / "readbacks").glob("*.json")
    )
    assert len(readback_files) == 1
