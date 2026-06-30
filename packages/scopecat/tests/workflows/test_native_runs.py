from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.instruments import NativeRunSnapshot
from scopecat.instruments.sdk import (
    NativeInstrumentProviderContext,
    NativeInstrumentProviderDescription,
    NativeInstrumentProviderResult,
)
from scopecat.workflows.runs import (
    native_run_executor,
    run_mode_executor,
    start_native_run,
    start_run,
)
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import (
    config_with_instrument_id,
    experiment_with_resource_id,
    load_config,
    load_experiment,
)


def test_start_run_supports_native_simulate(
    tmp_path: Path,
) -> None:
    result = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    assert result.manifest.runner_id == "scopecat.native"
    assert result.data_ref == "artifacts/raw-measurements.jsonl"
    assert isinstance(result.snapshot, NativeRunSnapshot)
    assert result.snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert result.snapshot.measurement_count == 3
    assert result.resolved_experiment is None


def test_start_native_run_uses_provider_selected_config_instrument(
    tmp_path: Path,
) -> None:
    result = start_native_run(
        config=config_with_instrument_id("source-a"),
        experiment=experiment_with_resource_id("source-a"),
        workspace=tmp_path,
        instrument_provider=TestSignalInstrumentProvider(),
    )

    assert result.manifest.runner_versions == {"tests.signal_instrument": "v0"}
    assert isinstance(result.snapshot, NativeRunSnapshot)
    assert result.snapshot.instrument_ids == ["source-a"]


def test_start_native_run_accepts_experiment_spec(
    tmp_path: Path,
) -> None:
    result = start_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
        instrument_provider=TestSignalInstrumentProvider(),
    )

    assert result.manifest.runner_id == "scopecat.native"
    assert isinstance(result.snapshot, NativeRunSnapshot)
    assert result.snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert result.snapshot.measurement_count == 3
    assert result.resolved_experiment is None


def test_start_native_run_requires_explicit_instrument_provider(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        start_native_run(
            config=load_config(),
            experiment=load_experiment(),
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "missing_native_instrument_provider"


def test_start_native_run_rejects_ambiguous_test_provider_instrument(
    tmp_path: Path,
) -> None:
    config = load_config()
    second_instrument = config.instrument_registry.instruments[0].model_copy(
        update={"id": "source-1"}
    )
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        *config.instrument_registry.instruments,
                        second_instrument,
                    ]
                }
            )
        }
    )

    with pytest.raises(ValidationFailed) as error:
        start_native_run(
            config=config.model_copy(update={"system": system}),
            experiment=load_experiment(),
            workspace=tmp_path,
            instrument_provider=TestSignalInstrumentProvider(),
        )

    assert error.value.diagnostics[0].code == (
        "test_signal_provider_ambiguous_instrument"
    )


def test_start_native_run_accepts_explicit_test_provider_instrument(
    tmp_path: Path,
) -> None:
    config = load_config()
    second_instrument = config.instrument_registry.instruments[0].model_copy(
        update={"id": "source-1"}
    )
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        *config.instrument_registry.instruments,
                        second_instrument,
                    ]
                }
            )
        }
    )
    result = start_native_run(
        config=config.model_copy(update={"system": system}),
        experiment=load_experiment(),
        workspace=tmp_path,
        instrument_provider=TestSignalInstrumentProvider(instrument_id="source-0"),
    )

    assert result.manifest.status == "completed"
    assert isinstance(result.snapshot, NativeRunSnapshot)
    assert result.snapshot.instrument_ids == ["source-0"]


def test_start_native_run_rejects_provider_blocking_diagnostics(
    tmp_path: Path,
) -> None:
    class BlockingProvider:
        provider_id = "test.blocking_provider"

        def describe(self) -> NativeInstrumentProviderDescription:
            return NativeInstrumentProviderDescription(provider_id=self.provider_id)

        def provide(
            self, context: NativeInstrumentProviderContext
        ) -> NativeInstrumentProviderResult:
            del context
            return NativeInstrumentProviderResult(
                instruments=(),
                diagnostics=(
                    Diagnostic(
                        severity="error",
                        code="provider_blocked",
                        message="provider blocked",
                        path="provider",
                    ),
                ),
            )

    with pytest.raises(ValidationFailed) as error:
        start_native_run(
            config=load_config(),
            experiment=load_experiment(),
            workspace=tmp_path,
            instrument_provider=BlockingProvider(),
        )

    assert error.value.diagnostics[0].code == "provider_blocked"


def test_native_provider_returns_fresh_instruments_across_runs(
    tmp_path: Path,
) -> None:
    provider = TestSignalInstrumentProvider()
    first = start_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path / "first",
        instrument_provider=provider,
    )
    second = start_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path / "second",
        instrument_provider=provider,
    )

    assert isinstance(first.snapshot, NativeRunSnapshot)
    assert isinstance(second.snapshot, NativeRunSnapshot)
    assert first.snapshot.initial_state[0].fields == []
    assert second.snapshot.initial_state[0].fields == []
    assert first.snapshot.final_state[0].fields
    assert second.snapshot.final_state[0].fields


def test_native_run_executor_uses_custom_provider(tmp_path: Path) -> None:
    executor = native_run_executor(
        TestSignalInstrumentProvider(instrument_id="source-a")
    )
    result = executor.start(
        config=config_with_instrument_id("source-a"),
        experiment=experiment_with_resource_id("source-a"),
        workspace=tmp_path,
    )

    assert executor.id == "tests.signal_instrument_provider"
    assert result.manifest.status == "completed"
    assert isinstance(result.snapshot, NativeRunSnapshot)
    assert result.snapshot.instrument_ids == ["source-a"]


def test_run_mode_executor_native_simulate_accepts_custom_provider(
    tmp_path: Path,
) -> None:
    executor = run_mode_executor(
        "native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(
            instrument_id="source-a"
        ),
    )
    result = executor.start(
        config=config_with_instrument_id("source-a"),
        experiment=experiment_with_resource_id("source-a"),
        workspace=tmp_path,
    )

    assert executor.id == "native_simulate"
    assert result.manifest.status == "completed"
    assert isinstance(result.snapshot, NativeRunSnapshot)
    assert result.snapshot.instrument_ids == ["source-a"]
