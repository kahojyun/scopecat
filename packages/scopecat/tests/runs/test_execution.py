from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.planning.system import ExperimentSystem
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.runs.service import read_run_record_json
from scopecat.sdk.instruments import (
    InstrumentConnectionContext,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from tests.testkit.execution import execute_invocation_run
from tests.testkit.runtime import sqlite_project_services
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import (
    config_with_instrument_id,
    load_config,
    load_invocation,
)


class _CountingProvider:
    def __init__(self) -> None:
        self.delegate = TestSignalInstrumentProvider()
        self.describe_calls = 0
        self.connect_calls = 0

    @property
    def provider_id(self) -> str:
        return self.delegate.provider_id

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        self.describe_calls += 1
        return self.delegate.describe(context)

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        self.connect_calls += 1
        return self.delegate.connect(context)


def test_state_evidence_requires_matching_observed_and_prepared_order() -> None:
    with pytest.raises(ValueError, match="same order"):
        InstrumentStateEvidence(
            run_id="run-1",
            observed_state=[InstrumentStateSnapshot(instrument_id="source-a")],
            prepared_state=[InstrumentStateSnapshot(instrument_id="source-b")],
        )


def test_execution_uses_provider_selected_config_instrument(
    tmp_path: Path,
) -> None:
    manifest = execute_invocation_run(
        config=config_with_instrument_id("source-a"),
        experiment=load_invocation(),
        system=ExperimentSystem(provider=TestSignalInstrumentProvider()),
        project_root=tmp_path,
    )
    snapshot = read_run_record_json(
        run_id=manifest.run_id,
        selector="instrument-state-evidence",
        services=sqlite_project_services(tmp_path),
        expected_kind="instrument_state_evidence",
    )
    evidence = InstrumentStateEvidence.model_validate(snapshot.content)

    assert manifest.status == "completed"
    assert [state.instrument_id for state in evidence.observed_state] == ["source-a"]
    assert evidence.prepared_state == evidence.observed_state


def test_execution_reuses_point_provider_preflight(tmp_path: Path) -> None:
    provider = _CountingProvider()

    manifest = execute_invocation_run(
        config=load_config(),
        experiment=load_invocation(),
        system=ExperimentSystem(provider=provider),
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert provider.describe_calls == 1
    assert provider.connect_calls == 1
