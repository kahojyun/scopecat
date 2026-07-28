from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import override

import pytest

from scopecat.compiler.typed.program import core_acquisitions, core_state
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.kernel.errors import ProviderContractError, RunFailed, RunIndeterminate
from scopecat.kernel.quantity import Quantity
from scopecat.records.instrument import InstrumentReadback
from scopecat.sdk.instruments import CollectReceipt, DriverCollectRequest
from tests.testkit.execution import execute_bound_run
from tests.testkit.runtime import sqlite_run_repository
from tests.testkit.signal_instruments import TestSignalInstrument
from tests.testkit.workflow_fixtures import load_config, load_experiment


class FailingCollectInstrument(TestSignalInstrument):
    implementation_id = "test.failing_instrument"

    @override
    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        del request
        raise RuntimeError("boom")


class UnexpectedResultInstrument(TestSignalInstrument):
    implementation_id = "test.unexpected_result_instrument"

    @override
    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        del request
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

    @override
    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        del request
        raise KeyboardInterrupt("operator cancelled")

    @override
    def abort(self) -> None:
        self.aborted = True


class FailAfterFirstCollectInstrument(TestSignalInstrument):
    implementation_id = "test.fail_after_first_instrument"

    def __init__(self) -> None:
        super().__init__()
        self.collect_count = 0

    @override
    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        self.collect_count += 1
        if self.collect_count > 1:
            raise RuntimeError("second collection failed")
        return super().collect(request)


def test_planning_rejects_missing_instrument(tmp_path: Path) -> None:
    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[],
            project_root=tmp_path,
        )

    assert "missing_instrument_description" in {
        problem.code for problem in error.value.problems
    }


def test_planning_rejects_unsupported_property(tmp_path: Path) -> None:
    experiment = load_experiment()
    selected_state = core_state(experiment)[0]
    assert isinstance(selected_state, SetStateSpec)
    state = replace(selected_state, property_id="amplitude")
    experiment = replace(experiment, effects=(state, *core_acquisitions(experiment)))

    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            project_root=tmp_path,
        )

    assert "instrument_driver_unsupported_property" in {
        problem.code for problem in error.value.problems
    }


def test_planning_rejects_unsupported_acquisition_result(tmp_path: Path) -> None:
    experiment = load_experiment()
    acquisition = core_acquisitions(experiment)[0]
    unsupported_acquisition = replace(
        acquisition,
        results=(replace(acquisition.results[0], result_id="missing"),),
    )
    experiment = replace(
        experiment,
        effects=tuple(
            unsupported_acquisition if effect is acquisition else effect
            for effect in experiment.effects
        ),
    )

    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            project_root=tmp_path,
        )

    assert "instrument_acquisition_result_unsupported" in {
        problem.code for problem in error.value.problems
    }


def test_planning_rejects_acquisition_result_dtype_mismatch(tmp_path: Path) -> None:
    experiment = load_experiment()
    experiment = replace(
        experiment,
        product_defs=(replace(experiment.product_defs[0], dtype="int64"),),
    )

    with pytest.raises(ProviderContractError) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            project_root=tmp_path,
        )

    assert "instrument_acquisition_result_dtype_mismatch" in {
        problem.code for problem in error.value.problems
    }


def test_instrument_exception_keeps_unknown_run(tmp_path: Path) -> None:
    with pytest.raises(RunIndeterminate) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[FailingCollectInstrument()],
            project_root=tmp_path,
        )

    assert "hardware_batch_unknown" in {
        problem.code for problem in error.value.problems
    }
    manifests = sqlite_run_repository(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "unknown"
    assert manifests[0].outcome is not None
    assert manifests[0].outcome.result == "failed"
    assert manifests[0].outcome.certainty == "indeterminate"
    assert {problem.code for problem in manifests[0].outcome.problems} >= {
        "hardware_batch_unknown"
    }


def test_run_rejects_unexpected_instrument_results(tmp_path: Path) -> None:
    with pytest.raises(RunFailed) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[UnexpectedResultInstrument()],
            project_root=tmp_path,
        )

    assert error.value.problems[-1].code == "instrument_unexpected_product"
    manifest = sqlite_run_repository(tmp_path).list_runs()[0]
    assert manifest.status == "failed"


def test_keyboard_interrupt_commits_interrupted_terminal_run(tmp_path: Path) -> None:
    instrument = InterruptingCollectInstrument()

    with pytest.raises(KeyboardInterrupt, match="operator cancelled"):
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[instrument],
            project_root=tmp_path,
        )

    manifest = sqlite_run_repository(tmp_path).list_runs()[0]
    assert manifest.status == "interrupted"
    assert manifest.datasets == ()
    assert instrument.aborted
    assert manifest.outcome is not None
    assert manifest.outcome.result == "cancelled"
    assert "execution_interrupted" in {
        problem.code for problem in manifest.outcome.problems
    }


def test_failed_run_publishes_committed_prefix_as_incomplete_dataset(
    tmp_path: Path,
) -> None:
    instrument = FailAfterFirstCollectInstrument()

    with pytest.raises(RunIndeterminate):
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[instrument],
            project_root=tmp_path,
        )

    manifest = sqlite_run_repository(tmp_path).list_runs()[0]
    assert manifest.status == "unknown"
    [dataset] = manifest.datasets
    assert dataset.metadata["partial"] is True
    assert dataset.metadata["expected_record_count"] == 3
