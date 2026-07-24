from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat import Quantity
from scopecat.measurements.results import MeasurementArray
from scopecat_quantum import authoring as q

from quantum_lab_demo.lab import quantum_lab_compiler

from .demo_lab_experiment_testkit import in_process_quantum_lab

_SAMPLES = 8
_SHOTS = 3


@q.program(id="test.raw-trace-result-contract")
def _raw_trace_program(qubit: q.Qubit) -> q.QuantumFragment:
    return q.acquire(
        qubit,
        duration=Quantity(_SAMPLES, "ns"),
        result="trace",
        contract=q.raw_trace_result(_SAMPLES),
    )


@sc.scratch(id="test.raw-trace-result-contract.experiment", kind="raw_trace")
def _raw_trace_experiment() -> sc.ExperimentBody:
    call = _raw_trace_program(qubit="q0").with_shots(_SHOTS)
    return sc.experiment(call).record_product(call.results.trace, record_id="trace")


def test_raw_trace_contract_runs_through_domain_compiler(tmp_path: Path) -> None:
    compiler = quantum_lab_compiler()

    run = (
        in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
        .prepare(_raw_trace_experiment())
        .run()
    )
    dataset = run.data().measurements().dataset
    [record] = dataset.records
    trace = record.observables["trace"]

    assert run.manifest.status == "completed"
    assert isinstance(trace, MeasurementArray)
    assert trace.dtype == "complex128"
    assert trace.unit == "ratio"
    assert trace.shape == [_SHOTS, _SAMPLES]
    [variable] = dataset.dataset_schema.variables
    assert variable.dims == ["point", "shot", "sample"]
    [evidence] = compiler.trace.preparations(_raw_trace_program.id)
    assert len(evidence.entries) == 1
