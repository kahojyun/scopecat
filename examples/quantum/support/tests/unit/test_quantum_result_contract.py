from __future__ import annotations

from pathlib import Path
from typing import cast

import scopecat as sc
from scopecat import Quantity
from scopecat.measurements.results import MeasurementArray
from scopecat_quantum import authoring as q

from quantum_lab_demo.lab import quantum_lab, quantum_lab_compiler
from quantum_lab_demo.virtual_lab.parameters import quantum_calibration_parameters

_SAMPLES = 8
_SHOTS = 3
_ROUNDS = 2


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


@q.program(id="test.repeated-result-contract")
def _repeated_program(qubit: q.Qubit, rounds: int) -> q.QuantumFragment:
    return q.repeat(
        q.measure(qubit, result="iq"),
        rounds,
        axis="round",
    )


@sc.scratch(id="test.repeated-result-contract.experiment", kind="repeated_readout")
def _repeated_experiment() -> sc.ExperimentBody:
    call = (
        _repeated_program(qubit="q0", rounds=_ROUNDS)
        .with_compiler_inputs(calibrations=quantum_calibration_parameters())
        .with_shots(_SHOTS)
    )
    return sc.experiment(call).record_product(call.results.iq, record_id="iq")


def test_raw_trace_contract_runs_through_domain_compiler(tmp_path: Path) -> None:
    compiler = quantum_lab_compiler()

    run = (
        quantum_lab(workspace=tmp_path, compiler=compiler)
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


def test_repeated_result_contract_runs_through_domain_compiler(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler()

    run = (
        quantum_lab(workspace=tmp_path, compiler=compiler)
        .prepare(_repeated_experiment())
        .run()
    )
    dataset = run.data().measurements().dataset
    [record] = dataset.records
    iq = record.observables["iq"]

    assert run.manifest.status == "completed"
    assert isinstance(iq, MeasurementArray)
    assert iq.shape == [_SHOTS, _ROUNDS]
    assert len(iq.values) == _SHOTS
    assert all(
        isinstance(row, list) and len(cast("list[object]", row)) == _ROUNDS
        for row in iq.values
    )
    [variable] = dataset.dataset_schema.variables
    assert variable.dims == ["point", "shot", "round"]
    [evidence] = compiler.trace.preparations(_repeated_program.id)
    assert len(evidence.entries[0].acquisition_origins) == _ROUNDS
