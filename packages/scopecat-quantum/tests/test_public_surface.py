from __future__ import annotations

import scopecat_quantum as sq


def test_public_surface_disambiguates_composition_ir_layers() -> None:
    assert sq.CircuitSequence is sq.circuits.Sequence
    assert sq.CircuitParallel is sq.circuits.Parallel
    assert sq.PulseSequence is sq.pulses.Sequence
    assert sq.PulseParallel is sq.pulses.Parallel
    assert sq.QuantumSequence is sq.programs.Sequence
    assert sq.QuantumParallel is sq.programs.Parallel


def test_authoring_exposes_one_program_entry_path() -> None:
    names = set(sq.authoring.__all__)

    assert {
        "Program",
        "ProgramDefinition",
        "ProgramResults",
        "QuantumProgramCall",
        "BoundProgram",
        "program",
        "bind",
    } <= names
    assert {"domain_program", "domain_execution", "program_call"}.isdisjoint(names)


def test_public_surface_exports_only_real_unique_attributes() -> None:
    assert len(sq.__all__) == len(set(sq.__all__))
    assert all(hasattr(sq, name) for name in sq.__all__)
