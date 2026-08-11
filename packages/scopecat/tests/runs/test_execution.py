from __future__ import annotations

from pathlib import Path

import pytest
from testkit.execution import execute_invocation_run
from testkit.instrument_host import compose_test_instruments
from testkit.runtime import sqlite_project_services
from testkit.signal_instruments import TestSignalInstrumentProvider
from testkit.workflow_fixtures import (
    config_with_instrument_id,
    load_config,
    load_invocation,
)

from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.runs.service import read_run_record_json
from scopecat.sdk.instruments import (
    InstrumentConnectionContext,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
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


def test_state_evidence_requires_matching_observed_and_baseline_order() -> None:
    with pytest.raises(ValueError, match="same order"):
        InstrumentStateEvidence(
            run_id="run-1",
            observed_state=[InstrumentStateSnapshot(instrument_id="source-a")],
            baseline_state=[InstrumentStateSnapshot(instrument_id="source-b")],
        )


def test_execution_uses_provider_selected_config_instrument(
    tmp_path: Path,
) -> None:
    config = config_with_instrument_id("source-a")
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    manifest = execute_invocation_run(
        config=config,
        experiment=load_invocation(),
        system=composition.system,
        instrument_backend=composition.backend,
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
    assert evidence.baseline_state == evidence.observed_state


def test_execution_uses_resolved_catalog_without_redescribing_provider(
    tmp_path: Path,
) -> None:
    provider = _CountingProvider()
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=provider,
    )

    manifest = execute_invocation_run(
        config=config,
        experiment=load_invocation(),
        system=composition.system,
        instrument_backend=composition.backend,
        project_root=tmp_path,
    )

    assert manifest.status == "completed"
    assert provider.describe_calls == 1
    assert provider.connect_calls == 1
