from __future__ import annotations

from pathlib import Path

import pytest

from scopecat._workflows.runs import read_run_record_json, start_run
from scopecat.errors import ValidationFailed
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
    snapshot = read_run_record_json(
        run_id=manifest.run_id,
        selector="execution-summary",
        workspace=tmp_path,
        expected_kind="execution_summary",
    )

    assert manifest.status == "completed"
    assert snapshot.content["instrument_ids"] == ["source-a"]


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
