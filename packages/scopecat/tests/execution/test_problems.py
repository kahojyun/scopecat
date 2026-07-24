from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import override

import pytest

from scopecat.compiler.typed.program import core_acquisitions, core_state
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.kernel.errors import RunFailed, RunIndeterminate
from scopecat.records.instrument import InstrumentReadback
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments.contracts import (
    CollectCommand,
    CollectReceipt,
)
from scopecat.testing import (
    sqlite_execution_services,
    sqlite_run_repository,
)
from tests.testkit.execution import execute_bound_run
from tests.testkit.signal_instruments import TestSignalInstrument
from tests.testkit.workflow_fixtures import load_config, load_experiment


class FailingCollectInstrument(TestSignalInstrument):
    implementation_id = "test.failing_instrument"

    @override
    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        raise RuntimeError("boom")


class UnexpectedProductInstrument(TestSignalInstrument):
    implementation_id = "test.unexpected_product_instrument"

    @override
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

    @override
    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
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
    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_count += 1
        if self.collect_count > 1:
            raise RuntimeError("second collection failed")
        return super().collect(command)


def test_run_rejects_missing_instrument(tmp_path: Path) -> None:
    with pytest.raises(RunFailed) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[],
            project_root=tmp_path,
        )

    assert "missing_instrument_description" in {
        problem.code for problem in error.value.problems
    }
    assert sqlite_run_repository(tmp_path).list_runs()[0].lifecycle == "terminal"


def test_run_rejects_unsupported_field(tmp_path: Path) -> None:
    experiment = load_experiment()
    selected_state = core_state(experiment)[0]
    assert isinstance(selected_state, SetStateSpec)
    state = replace(selected_state, field_path="amplitude")
    experiment = replace(experiment, effects=(state, *core_acquisitions(experiment)))

    with pytest.raises(RunFailed) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            project_root=tmp_path,
        )

    assert "instrument_driver_unsupported_field" in {
        problem.code for problem in error.value.problems
    }
    assert sqlite_run_repository(tmp_path).list_runs()[0].lifecycle == "terminal"


def test_run_rejects_unsupported_instrument_product(tmp_path: Path) -> None:
    experiment = load_experiment()
    acquisition = core_acquisitions(experiment)[0]
    unsupported_acquisition = replace(
        acquisition,
        products=(replace(acquisition.products[0], provider_key="missing"),),
    )
    experiment = replace(
        experiment,
        effects=tuple(
            unsupported_acquisition if effect is acquisition else effect
            for effect in experiment.effects
        ),
    )

    with pytest.raises(RunFailed) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            project_root=tmp_path,
        )

    assert "instrument_product_unsupported" in {
        problem.code for problem in error.value.problems
    }
    assert sqlite_run_repository(tmp_path).list_runs()[0].lifecycle == "terminal"


def test_run_rejects_instrument_product_dtype_mismatch(tmp_path: Path) -> None:
    experiment = load_experiment()
    experiment = replace(
        experiment,
        product_defs=(replace(experiment.product_defs[0], dtype="int64"),),
    )

    with pytest.raises(RunFailed) as error:
        execute_bound_run(
            config=load_config(),
            experiment=experiment,
            instruments=[TestSignalInstrument()],
            project_root=tmp_path,
        )

    assert "instrument_product_dtype_mismatch" in {
        problem.code for problem in error.value.problems
    }
    assert sqlite_run_repository(tmp_path).list_runs()[0].lifecycle == "terminal"


def test_instrument_exception_keeps_unknown_run(tmp_path: Path) -> None:
    with pytest.raises(RunIndeterminate) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[FailingCollectInstrument()],
            project_root=tmp_path,
        )

    assert "instrument_collect_unknown" in {
        problem.code for problem in error.value.problems
    }
    manifests = sqlite_run_repository(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "unknown"
    assert manifests[0].outcome is not None
    assert manifests[0].outcome.result == "failed"
    assert manifests[0].outcome.certainty == "indeterminate"
    assert {problem.code for problem in manifests[0].outcome.problems} >= {
        "instrument_collect_unknown"
    }


def test_run_rejects_unexpected_instrument_products(tmp_path: Path) -> None:
    with pytest.raises(RunFailed) as error:
        execute_bound_run(
            config=load_config(),
            experiment=load_experiment(),
            instruments=[UnexpectedProductInstrument()],
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
    journal_entries = (
        sqlite_execution_services(tmp_path).journal_for(manifest.run_id).entries()
    )
    collect_states = [
        entry.state for entry in journal_entries if entry.stage == "collect"
    ]
    assert collect_states == ["started", "unknown"]


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
    receipts = (
        sqlite_execution_services(tmp_path).collections_for(manifest.run_id).receipts()
    )
    assert len(receipts) == 1
