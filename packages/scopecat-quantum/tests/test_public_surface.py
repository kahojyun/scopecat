from __future__ import annotations

import scopecat_quantum as sq


def test_public_surface_disambiguates_composition_ir_layers() -> None:
    assert sq.CircuitSequence is sq.circuits.Sequence
    assert sq.CircuitParallel is sq.circuits.Parallel
    assert sq.PulseSequence is sq.pulses.Sequence
    assert sq.PulseParallel is sq.pulses.Parallel
    assert sq.QuantumSequence is sq.programs.Sequence
    assert sq.QuantumParallel is sq.programs.Parallel


def test_public_facade_covers_module_exports_except_disambiguated_composition() -> None:
    facade_names = set(sq.__all__)

    assert set(sq.acquisitions.__all__) <= facade_names
    assert set(sq.authoring.__all__) <= facade_names
    assert set(sq.calibrations.__all__) <= facade_names
    assert set(sq.circuits.__all__) - {"Parallel", "Sequence"} <= facade_names
    assert set(sq.pulses.__all__) - {"Parallel", "Sequence"} <= facade_names
    assert set(sq.programs.__all__) - {"Parallel", "Sequence"} <= facade_names
    assert set(sq.program_results.__all__) <= facade_names
    assert set(sq.program_targets.__all__) <= facade_names
    assert set(sq.circuit_pulses.__all__) <= facade_names
    assert set(sq.circuit_results.__all__) <= facade_names
    assert set(sq.circuit_targets.__all__) <= facade_names
    assert set(sq.gates.__all__) <= facade_names
    assert set(sq.measurement_calibrations.__all__) <= facade_names
    assert set(sq.measurement_transforms.__all__) <= facade_names
    assert set(sq.targets.__all__) <= facade_names


def test_authoring_exposes_one_program_entry_path() -> None:
    names = set(sq.authoring.__all__)

    assert {
        "Program",
        "BoundProgram",
        "program",
        "bind",
        "domain_program",
        "domain_call",
    } <= names


def test_public_surface_exports_only_real_unique_attributes() -> None:
    assert len(sq.__all__) == len(set(sq.__all__))
    assert all(hasattr(sq, name) for name in sq.__all__)
