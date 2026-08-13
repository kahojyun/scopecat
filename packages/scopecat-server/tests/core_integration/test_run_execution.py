from __future__ import annotations

from pathlib import Path

import pytest
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.points import PointCandidate
from scopecat.optimization import OptimizationComplete, PointOptimizerContext
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement import MeasurementScalar
from scopecat.runs.service import read_run_measurement_dataset, read_run_record_json
from scopecat.sdk.instruments import (
    InstrumentConnectionContext,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from scopecat_testkit.instrument_host import compose_test_instruments
from scopecat_testkit.server.execution import execute_invocation_run
from scopecat_testkit.server.runtime import sqlite_project_services
from scopecat_testkit.signal_instruments import TestSignalInstrumentProvider
from scopecat_testkit.workflow_fixtures import (
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


class _TwoPointOptimizer:
    id = "tests.two-point-optimizer"

    def __init__(self) -> None:
        self.contexts: list[PointOptimizerContext] = []

    def propose(
        self,
        context: PointOptimizerContext,
    ) -> PointCandidate | OptimizationComplete:
        self.contexts.append(context)
        if context.completed_point_count >= 5:
            return OptimizationComplete("two adaptive points completed")
        if not context.ledger.entries:
            return PointCandidate(
                {"drive_frequency": Quantity(5.15, "GHz")},
                source="optimizer",
                based_on_completed_point_count=context.completed_point_count - 1,
            )
        return PointCandidate(
            {
                "drive_frequency": Quantity(
                    5.2 + 0.1 * (context.completed_point_count - 3),
                    "GHz",
                )
            },
            source="optimizer",
            based_on_completed_point_count=context.completed_point_count,
        )


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


def test_adaptive_execution_observes_and_runs_optimizer_points_in_one_session(
    tmp_path: Path,
) -> None:
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    optimizer = _TwoPointOptimizer()

    manifest = execute_invocation_run(
        config=config,
        experiment=load_invocation().adaptive(optimizer, max_points=7),
        system=composition.system,
        instrument_backend=composition.backend,
        project_root=tmp_path,
    )
    dataset = read_run_measurement_dataset(
        run_id=manifest.run_id,
        services=sqlite_project_services(tmp_path),
    ).dataset

    assert manifest.status == "completed"
    assert [context.completed_point_count for context in optimizer.contexts] == [
        3,
        3,
        4,
        5,
    ]
    assert optimizer.contexts[1].ledger.entries[0].outcome == "rejected"
    assert "based on 2 completed points" in (
        optimizer.contexts[1].ledger.entries[0].reason or ""
    )
    assert all(
        len(context.observations[-1].records) == 1 for context in optimizer.contexts
    )
    assert len(dataset.records) == 5
    assert [record.point_index for record in dataset.records] == list(range(5))
    assert dataset.records[-2].coordinates["drive_frequency"] == (
        MeasurementScalar.create(dtype="float64", value=5.2, unit="GHz")
    )
    assert dataset.records[-1].coordinates["drive_frequency"] == (
        MeasurementScalar.create(dtype="float64", value=5.3, unit="GHz")
    )
