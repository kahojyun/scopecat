from __future__ import annotations

from pathlib import Path

import pytest

from scopecat._workflows.runs import read_run_record_json, start_run
from scopecat.errors import CheckFailed
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import (
    config_with_instrument_id,
    load_config,
    load_prepared_invocation,
)


def test_start_run_uses_provider_selected_config_instrument(
    tmp_path: Path,
) -> None:
    manifest = start_run(
        config=config_with_instrument_id("source-a"),
        experiment=load_prepared_invocation(),
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
    with pytest.raises(CheckFailed) as error:
        start_run(
            config=load_config(),
            experiment=load_prepared_invocation(),
            workspace=tmp_path,
        )

    assert error.value.problems[0].code == "execution.instrument_provider_missing"
