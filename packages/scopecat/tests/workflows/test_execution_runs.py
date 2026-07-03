from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.instruments import ExecutionSnapshot
from scopecat.runs import open_run_store
from scopecat.workflows.runs import start_run
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import (
    config_with_instrument_id,
    experiment_with_resource_id,
    load_config,
    load_experiment,
)


def test_start_run_uses_provider_selected_config_instrument(
    tmp_path: Path,
) -> None:
    manifest = start_run(
        config=config_with_instrument_id("source-a"),
        experiment=experiment_with_resource_id("source-a"),
        workspace=tmp_path,
        instrument_provider=TestSignalInstrumentProvider(),
    )
    snapshot = open_run_store(tmp_path).read_model(
        manifest.run_id,
        "artifacts/execution.snapshot.json",
        ExecutionSnapshot,
    )

    assert manifest.status == "completed"
    assert snapshot.instrument_ids == ["source-a"]


def test_start_run_requires_explicit_instrument_provider(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        start_run(
            config=load_config(),
            experiment=load_experiment(),
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "missing_instrument_provider"
