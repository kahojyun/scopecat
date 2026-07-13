from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.composition.local import local_workspace_services
from scopecat.kernel.errors import CheckFailed
from scopecat.planning.backend import ExecutionBackend
from scopecat.runs.service import read_run_record_json, start_run
from scopecat.sdk.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import (
    config_with_instrument_id,
    load_config,
    load_prepared_invocation,
)


class _CountingProvider:
    def __init__(self) -> None:
        self.delegate = TestSignalInstrumentProvider()
        self.describe_calls = 0
        self.provide_calls = 0

    @property
    def provider_id(self) -> str:
        return self.delegate.provider_id

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        self.describe_calls += 1
        return self.delegate.describe(context)

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        self.provide_calls += 1
        return self.delegate.provide(context)


def test_start_run_uses_provider_selected_config_instrument(
    tmp_path: Path,
) -> None:
    manifest = start_run(
        config=config_with_instrument_id("source-a"),
        experiment=load_prepared_invocation(),
        workspace=tmp_path,
        services=local_workspace_services(tmp_path),
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
    )
    snapshot = read_run_record_json(
        run_id=manifest.run_id,
        selector="execution-summary",
        services=local_workspace_services(tmp_path),
        expected_kind="execution_summary",
    )

    assert manifest.status == "completed"
    assert snapshot.content["instrument_ids"] == ["source-a"]


def test_start_run_reuses_point_provider_preflight(tmp_path: Path) -> None:
    provider = _CountingProvider()

    manifest = start_run(
        config=load_config(),
        experiment=load_prepared_invocation(),
        workspace=tmp_path,
        services=local_workspace_services(tmp_path),
        execution_backend=ExecutionBackend(provider=provider),
    )

    assert manifest.status == "completed"
    assert provider.describe_calls == 1
    assert provider.provide_calls == 1


def test_start_run_requires_explicit_execution_backend(
    tmp_path: Path,
) -> None:
    with pytest.raises(CheckFailed) as error:
        start_run(
            config=load_config(),
            experiment=load_prepared_invocation(),
            workspace=tmp_path,
            services=local_workspace_services(tmp_path),
        )

    assert error.value.problems[0].code == "execution.execution_backend_missing"
