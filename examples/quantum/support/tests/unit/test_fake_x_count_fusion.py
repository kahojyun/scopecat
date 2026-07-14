"""End-to-end batching tests for the unified execution backend."""

from __future__ import annotations

from pathlib import Path

import pytest
import scopecat as sc
from scopecat.adapters.filesystem.execution import FilesystemExecutionJournal
from scopecat.kernel.errors import RunIndeterminate
from scopecat.records.parameter import Quantity
from scopecat.records.run_plan import RunPlanDomainExecution
from scopecat.sdk.domain.runtime import (
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
)

from quantum_lab_demo.reference_experiments import (
    FAKE_X_COUNT_BIAS_TEMPLATE,
    FakeBiasVoltageProvider,
    FakeXCountDomainExecutionAdapter,
    fake_x_count_bias_config,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
)


class _SecondBatchPendingRuntime(FakeListDomainRuntime):
    def __init__(self) -> None:
        super().__init__()
        self._seen_fetches = 0

    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[FakeListRun]:
        self._seen_fetches += 1
        if self._seen_fetches == 2:
            return DomainFetchCandidate(
                receipt=DomainFetchReceipt(
                    identity=request.identity,
                    job_id=request.job_id,
                    status="pending",
                )
            )
        return super().fetch(request)


def test_scalar_voltage_partitions_programmable_x_count_batches(
    tmp_path: Path,
) -> None:
    run, source, adapter = _run_mixed_experiment(
        tmp_path,
        options=sc.ExecutionOptions(fusion="automatic"),
    )
    plan = run.plan
    records = run.data().measurements().dataset.records
    journal = FilesystemExecutionJournal(tmp_path, run_id=run.id).entries()
    domain = _domain_execution(plan)

    assert run.manifest.status == "completed"
    assert len(records) == 8
    assert source.writes == (
        Quantity(value=-0.1, unit="V"),
        Quantity(value=0.1, unit="V"),
    )
    assert adapter.runtime.physical_execution_count == 2
    assert adapter.runtime.submit_calls == adapter.runtime.fetch_calls == 2
    assert plan.execution_options.requested.fusion == "automatic"
    assert [batch.point_indices for batch in domain.batches] == [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
    ]
    assert {record.id: record.producer_kind for record in plan.records} == {
        "probability_0": "host_transform",
        "probability_1": "host_transform",
        "bias_voltage_readback": "instrument",
    }
    assert all(
        record.observables["bias_voltage_readback"]
        == record.coordinates["bias_voltage"]
        for record in records
    )
    assert [
        entry.stage
        for entry in journal
        if entry.state == "completed"
        and entry.stage in {"apply_state", "domain_submit", "domain_fetch"}
    ] == [
        "apply_state",
        "domain_submit",
        "domain_fetch",
        "apply_state",
        "domain_submit",
        "domain_fetch",
    ]


def test_fusion_option_changes_physical_jobs_without_changing_logical_records(
    tmp_path: Path,
) -> None:
    automatic, _, automatic_adapter = _run_mixed_experiment(
        tmp_path / "automatic",
        options=sc.ExecutionOptions(fusion="automatic"),
    )
    disabled, _, disabled_adapter = _run_mixed_experiment(
        tmp_path / "disabled",
        options=sc.ExecutionOptions(fusion="disabled"),
    )
    disabled_plan = disabled.plan

    assert automatic_adapter.runtime.physical_execution_count == 2
    assert disabled_adapter.runtime.physical_execution_count == 8
    assert [
        batch.point_indices for batch in _domain_execution(disabled_plan).batches
    ] == [[index] for index in range(8)]
    assert _logical_record_values(automatic) == _logical_record_values(disabled)


def test_later_batch_failure_has_one_domain_problem_and_no_partial_dataset(
    tmp_path: Path,
) -> None:
    source = FakeBiasVoltageProvider()
    adapter = FakeXCountDomainExecutionAdapter()
    adapter.runtime = _SecondBatchPendingRuntime()
    lab = sc.open(
        tmp_path,
        config_profile=fake_x_count_bias_config(),
        execution_backend=sc.ExecutionBackend(
            provider=source,
            domain_adapters=(adapter,),
        ),
    )

    with pytest.raises(RunIndeterminate) as captured:
        lab.prepare(FAKE_X_COUNT_BIAS_TEMPLATE).run()

    codes = [problem.code for problem in captured.value.outcome.problems]
    [persisted] = lab.runs()
    summary = persisted.record_json("execution-summary").content

    assert codes.count("domain_synchronous_completion_contract_violated") == 1
    assert "execution_middle_effect_failed" not in codes
    assert adapter.runtime.physical_execution_count == 2
    assert summary["completed_point_count"] == 0
    assert summary["measurement_count"] == 0
    assert persisted.manifest.datasets == []


def _run_mixed_experiment(
    workspace: Path,
    *,
    options: sc.ExecutionOptions,
) -> tuple[sc.RunHandle, FakeBiasVoltageProvider, FakeXCountDomainExecutionAdapter]:
    source = FakeBiasVoltageProvider()
    adapter = FakeXCountDomainExecutionAdapter()
    lab = sc.open(
        workspace,
        config_profile=fake_x_count_bias_config(),
        execution_backend=sc.ExecutionBackend(
            provider=source,
            domain_adapters=(adapter,),
        ),
    )
    run = lab.prepare(
        FAKE_X_COUNT_BIAS_TEMPLATE,
        execution_options=options,
    ).run()
    return run, source, adapter


def _logical_record_values(run: sc.RunHandle) -> dict[tuple[float, int], object]:
    selected: dict[tuple[float, int], object] = {}
    for record in run.data().measurements().dataset.records:
        voltage = record.coordinates["bias_voltage"]
        x_count = record.coordinates["x_count"]
        if not isinstance(voltage, Quantity) or type(x_count) is not int:
            raise AssertionError("mixed scan coordinates lost their declared types")
        selected[(voltage.value, x_count)] = record.model_dump(
            mode="json",
            include={"coordinates", "observables"},
        )
    return selected


def _domain_execution(plan) -> RunPlanDomainExecution:
    [selected] = [
        unit
        for unit in plan.execution_units
        if isinstance(unit, RunPlanDomainExecution)
    ]
    return selected
