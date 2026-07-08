from __future__ import annotations

from pathlib import Path

import pytest

from scopecat._runtime.executor import execute_run
from scopecat._workflows.runs import read_run_record_json
from scopecat.errors import ValidationFailed
from scopecat.instruments.sdk import (
    CollectCommand,
    InstrumentReadback,
)
from scopecat.models.parameter import Quantity
from scopecat.runs import open_run_store
from tests.support.signal_instruments import TestSignalInstrument
from tests.support.workflow_fixtures import load_config, load_experiment


class FailingCollectInstrument(TestSignalInstrument):
    implementation_id = "test.failing_instrument"

    def collect(self, command: CollectCommand) -> InstrumentReadback:
        del command
        raise RuntimeError("boom")


class UnexpectedProductInstrument(TestSignalInstrument):
    implementation_id = "test.unexpected_product_instrument"

    def collect(self, command: CollectCommand) -> InstrumentReadback:
        del command
        return InstrumentReadback(
            values={
                "signal": Quantity(value=1.0, unit="ratio"),
                "unexpected": Quantity(value=1.0, unit="ratio"),
            }
        )


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

    assert error.value.diagnostics[-1].code == "instrument_driver_unsupported_field"


def test_run_rejects_unsupported_instrument_product(tmp_path: Path) -> None:
    experiment = load_experiment()
    experiment = experiment.model_copy(
        update={
            "records": [
                experiment.records[0].model_copy(update={"product_key": "missing"})
            ]
        }
    )

    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "instrument_product_unsupported"


def test_run_rejects_instrument_product_dtype_mismatch(tmp_path: Path) -> None:
    experiment = load_experiment()
    experiment = experiment.model_copy(
        update={
            "records": [experiment.records[0].model_copy(update={"dtype": "int64"})]
        }
    )

    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "instrument_product_dtype_mismatch"


def test_instrument_exception_keeps_failed_run(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[FailingCollectInstrument()],
            workspace=tmp_path,
        )

    assert "instrument_collect_failed" in {
        diagnostic.code for diagnostic in error.value.diagnostics
    }
    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "failed"
    snapshot = read_run_record_json(
        run_id=manifests[0].run_id,
        selector="execution-summary",
        workspace=tmp_path,
        expected_kind="execution_summary",
    )
    assert snapshot.content["status"] == "failed"
    assert {diagnostic["code"] for diagnostic in snapshot.content["diagnostics"]} >= {
        "instrument_collect_failed"
    }


def test_run_rejects_unexpected_instrument_products(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[UnexpectedProductInstrument()],
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "instrument_unexpected_product"
    manifest = open_run_store(tmp_path).list_runs()[0]
    assert manifest.status == "failed"
