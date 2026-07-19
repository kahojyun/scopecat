"""End-to-end domain compiler partitioning tests."""

from __future__ import annotations

from pathlib import Path
from typing import override

import pytest
import scopecat as sc
from scopecat.adapters.filesystem.execution import FilesystemExecutionJournal
from scopecat.kernel.errors import RunIndeterminate
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.runtime import (
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
)

from quantum_lab_demo.reference_experiments import (
    FAKE_X_COUNT_BIAS_TEMPLATE,
    FakeBiasVoltageProvider,
    FakeXCountDomainCompiler,
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

    @override
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


def test_scalar_voltage_barriers_preserve_state_and_logical_results(
    tmp_path: Path,
) -> None:
    run, source, _compiler = _run_mixed_experiment(tmp_path)
    records = run.data().measurements().dataset.records
    journal = FilesystemExecutionJournal(tmp_path, run_id=run.id).entries()

    assert run.manifest.status == "completed"
    assert len(records) == 8
    assert source.writes == (
        Quantity(value=-0.1, unit="V"),
        Quantity(value=0.1, unit="V"),
    )
    assert all(
        record.observables["bias_voltage_readback"]
        == record.coordinates["bias_voltage"]
        for record in records
    )
    effect_stages = [
        entry.stage
        for entry in journal
        if entry.state == "completed"
        and entry.stage in {"apply_state", "domain_submit", "domain_fetch"}
    ]
    assert effect_stages.count("apply_state") == 2
    domain_stages = [stage for stage in effect_stages if stage != "apply_state"]
    assert domain_stages == ["domain_submit", "domain_fetch"] * len(records)
    second_state = effect_stages.index("apply_state", 1)
    assert "domain_fetch" in effect_stages[1:second_state]
    assert "domain_submit" in effect_stages[second_state + 1 :]


def test_later_batch_failure_has_one_domain_problem_and_no_partial_dataset(
    tmp_path: Path,
) -> None:
    source = FakeBiasVoltageProvider()
    compiler = FakeXCountDomainCompiler()
    compiler.runtime = _SecondBatchPendingRuntime()
    lab = sc.open(
        tmp_path,
        config_profile=fake_x_count_bias_config(),
        execution_backend=sc.ExecutionBackend(
            provider=source,
            domain_compilers=(compiler,),
        ),
    )

    with pytest.raises(RunIndeterminate) as captured:
        lab.prepare(FAKE_X_COUNT_BIAS_TEMPLATE).run()

    codes = [problem.code for problem in captured.value.outcome.problems]
    [persisted] = lab.runs()

    assert codes.count("domain_synchronous_completion_contract_violated") == 1
    assert "execution_middle_effect_failed" not in codes
    assert compiler.runtime.physical_execution_count == 2
    assert persisted.manifest.datasets == ()


def _run_mixed_experiment(
    workspace: Path,
) -> tuple[sc.RunHandle, FakeBiasVoltageProvider, FakeXCountDomainCompiler]:
    source = FakeBiasVoltageProvider()
    compiler = FakeXCountDomainCompiler()
    lab = sc.open(
        workspace,
        config_profile=fake_x_count_bias_config(),
        execution_backend=sc.ExecutionBackend(
            provider=source,
            domain_compilers=(compiler,),
        ),
    )
    run = lab.prepare(FAKE_X_COUNT_BIAS_TEMPLATE).run()
    return run, source, compiler
