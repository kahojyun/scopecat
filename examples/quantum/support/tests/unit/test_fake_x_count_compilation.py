"""End-to-end domain compiler partitioning tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import override

import pytest
import scopecat as sc
from scopecat.kernel.content_identity import content_fingerprint
from scopecat.kernel.errors import RunIndeterminate
from scopecat.kernel.problems import ProblemPhase, problem
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.domain.runtime import (
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
)
from scopecat_quantum import authoring as quantum
from tests.testkit.runtime import (
    sqlite_execution_session,
    sqlite_project_services,
)

from quantum_lab_demo import QuantumLabCompiler, quantum_lab_compiler
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    configured_fake_list_target,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile
from quantum_lab_demo.workflows.fake_x_count_bias import (
    FakeBiasVoltageProvider,
    fake_x_count_bias_config,
    fake_x_count_bias_template,
)

from .demo_lab_experiment_testkit import (
    InProcessQuantumLab,
)


class _SecondBatchUnknownRuntime(FakeListDomainRuntime):
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
                    submission_key=request.submission_id.submission_key,
                    job_id=request.job_id,
                    status="unknown",
                    problems=(
                        problem(
                            "injected_second_batch_unknown",
                            "the second batch result is unknown",
                            phase=ProblemPhase.EXECUTION,
                        ),
                    ),
                )
            )
        return super().fetch(request)


def test_resource_independent_domain_spans_bias_state_coverage(
    tmp_path: Path,
) -> None:
    run, source, _compiler = _run_mixed_experiment(tmp_path)
    records = run.data().measurements().dataset.records
    journal = sqlite_execution_session(tmp_path, run.id).journal.entries()

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
    assert domain_stages == ["domain_submit", "domain_fetch"]
    second_state = effect_stages.index("apply_state", 1)
    assert "domain_fetch" in effect_stages[1:second_state]
    assert "domain_submit" not in effect_stages[second_state + 1 :]


def test_eager_target_artifact_binds_each_selected_point_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind_calls = 0
    bind = quantum.bind

    def count_bind(
        declaration: quantum.Program,
        bindings: Mapping[str, object] | None = None,
    ) -> quantum.BoundProgram:
        nonlocal bind_calls
        bind_calls += 1
        return bind(declaration, bindings)

    monkeypatch.setattr(quantum, "bind", count_bind)

    run, _source, _compiler = _run_mixed_experiment(tmp_path)

    assert run.manifest.status == "completed"
    assert bind_calls == len(run.data().measurements().dataset.records)


def test_different_target_partitions_preserve_the_logical_dataset(
    tmp_path: Path,
) -> None:
    logical_datasets: list[object] = []
    execution_counts: list[int] = []
    for max_list_entries in (256, 2):
        compiler = quantum_lab_compiler(
            target=replace(
                configured_fake_list_target(quantum_wiring_config_profile()),
                max_list_entries=max_list_entries,
            )
        )
        lab = InProcessQuantumLab(
            project_root=tmp_path / f"capacity-{max_list_entries}",
            services=sqlite_project_services(tmp_path / f"capacity-{max_list_entries}"),
            config="active",
            config_profile=fake_x_count_bias_config(),
            system=sc.ExperimentSystem(
                provider=FakeBiasVoltageProvider(),
                domain_compiler=compiler,
            ),
        )

        run = lab.prepare(fake_x_count_bias_template).run()
        records = run.data().measurements().dataset.records
        logical_datasets.append(
            content_fingerprint(
                tuple(
                    {
                        "logical_point_id": record.logical_point_id,
                        "point_index": record.point_index,
                        "coordinates": record.coordinates,
                        "observables": record.observables,
                    }
                    for record in records
                )
            )
        )
        journal = sqlite_execution_session(lab.project_root, run.id).journal
        execution_counts.append(
            sum(
                entry.stage == "domain_submit" and entry.state == "started"
                for entry in journal.entries()
            )
        )

    assert execution_counts[0] < execution_counts[1]
    assert logical_datasets[0] == logical_datasets[1]


def test_later_batch_failure_has_one_domain_problem_and_partial_dataset(
    tmp_path: Path,
) -> None:
    source = FakeBiasVoltageProvider()
    compiler = quantum_lab_compiler(
        target=replace(
            configured_fake_list_target(quantum_wiring_config_profile()),
            max_list_entries=4,
        ),
        runtime=_SecondBatchUnknownRuntime(),
    )
    lab = InProcessQuantumLab(
        project_root=tmp_path,
        services=sqlite_project_services(tmp_path),
        config="active",
        config_profile=fake_x_count_bias_config(),
        system=sc.ExperimentSystem(
            provider=source,
            domain_compiler=compiler,
        ),
    )

    with pytest.raises(RunIndeterminate) as captured:
        lab.prepare(fake_x_count_bias_template).run()

    codes = [problem.code for problem in captured.value.outcome.problems]
    [persisted] = lab.runs()
    journal = sqlite_execution_session(lab.project_root, captured.value.run_id).journal

    assert codes.count("injected_second_batch_unknown") == 1
    assert "execution_middle_effect_failed" not in codes
    assert (
        sum(
            entry.stage == "domain_submit" and entry.state == "started"
            for entry in journal.entries()
        )
        == 2
    )
    [dataset] = persisted.manifest.datasets
    assert dataset.metadata["partial"] is True
    assert dataset.metadata["expected_record_count"] == 8


def _run_mixed_experiment(
    project_root: Path,
) -> tuple[sc.RunHandle, FakeBiasVoltageProvider, QuantumLabCompiler]:
    source = FakeBiasVoltageProvider()
    compiler = quantum_lab_compiler()
    lab = InProcessQuantumLab(
        project_root=project_root,
        services=sqlite_project_services(project_root),
        config="active",
        config_profile=fake_x_count_bias_config(),
        system=sc.ExperimentSystem(
            provider=source,
            domain_compiler=compiler,
        ),
    )
    run = lab.prepare(fake_x_count_bias_template).run()
    return run, source, compiler
