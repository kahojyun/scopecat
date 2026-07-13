from __future__ import annotations

import math
from collections.abc import Sequence as SequenceCollection
from typing import cast

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    CouplerId,
    GateId,
    PulseEventId,
    PulseProgramId,
    QubitId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import (
    CircuitNode,
    CircuitProgram,
    CircuitVerificationError,
    Measure,
    Parallel,
    Sequence,
    iter_circuit_operations,
    verify_circuit_program,
)
from scopecat_quantum.gates import (
    GateArgument,
    GateCall,
    GateDefinition,
    GateParameterDefinition,
    GateParameterKind,
)

_NONEMPTY_IDS = st.text(min_size=1).filter(lambda value: bool(value.strip()))
_STRUCTURAL_ID_SEGMENT = st.text(
    alphabet=st.sampled_from(tuple("ab/%[] \tΩ中")),
    min_size=1,
    max_size=6,
).filter(lambda value: bool(value.strip()))
_STRUCTURAL_ID_PARTS = st.tuples(
    st.lists(_STRUCTURAL_ID_SEGMENT, max_size=3).map(tuple),
    _STRUCTURAL_ID_SEGMENT,
)


@given(_NONEMPTY_IDS)
def test_quantum_identities_are_nominal_and_nonempty(value: str) -> None:
    identity_types = (
        CalibrationId,
        CircuitId,
        CircuitOperationId,
        CouplerId,
        GateId,
        PulseProgramId,
        QubitId,
        TargetArtifactId,
        TargetCompileEntryId,
        TargetCompilerId,
        TargetId,
    )
    identities = tuple(identity_type(value) for identity_type in identity_types)
    event_id = PulseEventId(value)
    slot_id = AcquisitionSlotId(value)

    assert len({*identities, event_id, slot_id}) == len(identity_types) + 2
    assert all(identity.value == value for identity in identities)
    assert event_id.local_id == value
    assert event_id.scope == ()
    assert slot_id.local_id == value
    assert slot_id.scope == ()


def test_pulse_event_identity_is_structural_and_rendered_injectively() -> None:
    embedded_separator = PulseEventId("c", scope=("a/b",))
    separate_segments = PulseEventId("c", scope=("a", "b"))

    assert embedded_separator != separate_segments
    assert embedded_separator.qualified_name == "a%2Fb/c"
    assert separate_segments.qualified_name == "a/b/c"
    assert embedded_separator.value == embedded_separator.qualified_name
    assert embedded_separator.prefixed("outer") == PulseEventId(
        "c",
        scope=("outer", "a/b"),
    )


def test_acquisition_slot_identity_is_structural_and_rendered_injectively() -> None:
    embedded_separator = AcquisitionSlotId("c", scope=("a/b",))
    separate_segments = AcquisitionSlotId("c", scope=("a", "b"))

    assert embedded_separator != separate_segments
    assert embedded_separator.qualified_name == "a%2Fb/c"
    assert separate_segments.qualified_name == "a/b/c"
    assert embedded_separator.value == embedded_separator.qualified_name
    assert embedded_separator.prefixed("outer") == AcquisitionSlotId(
        "c",
        scope=("outer", "a/b"),
    )


@pytest.mark.parametrize("identity_type", [PulseEventId, AcquisitionSlotId])
@pytest.mark.parametrize("scope", [("",), (" ",), ("valid", "\n")])
def test_structural_identity_rejects_blank_scope_segments(
    identity_type: type[PulseEventId | AcquisitionSlotId],
    scope: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="scope segments must be non-empty"):
        identity_type("event", scope=scope)


@pytest.mark.parametrize(
    ("local_id", "scope"),
    [("\ud800", ()), ("event", ("\udfff",))],
)
@pytest.mark.parametrize("identity_type", [PulseEventId, AcquisitionSlotId])
def test_structural_identity_rejects_unicode_surrogates(
    identity_type: type[PulseEventId | AcquisitionSlotId],
    local_id: str,
    scope: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="Unicode surrogates"):
        identity_type(local_id, scope=scope)


@given(
    first_parts=_STRUCTURAL_ID_PARTS,
    second_parts=_STRUCTURAL_ID_PARTS,
    first_prefix=st.lists(_STRUCTURAL_ID_SEGMENT, max_size=3).map(tuple),
    second_prefix=st.lists(_STRUCTURAL_ID_SEGMENT, max_size=3).map(tuple),
)
def test_pulse_event_qualified_names_are_injective_after_prefixing(
    first_parts: tuple[tuple[str, ...], str],
    second_parts: tuple[tuple[str, ...], str],
    first_prefix: tuple[str, ...],
    second_prefix: tuple[str, ...],
) -> None:
    first_scope, first_local_id = first_parts
    second_scope, second_local_id = second_parts
    first = PulseEventId(first_local_id, scope=first_scope).prefixed(*first_prefix)
    second = PulseEventId(second_local_id, scope=second_scope).prefixed(*second_prefix)
    assume(first != second)

    assert first.qualified_name != second.qualified_name


@given(
    first_parts=_STRUCTURAL_ID_PARTS,
    second_parts=_STRUCTURAL_ID_PARTS,
    first_prefix=st.lists(_STRUCTURAL_ID_SEGMENT, max_size=3).map(tuple),
    second_prefix=st.lists(_STRUCTURAL_ID_SEGMENT, max_size=3).map(tuple),
)
def test_acquisition_slot_qualified_names_are_injective_after_prefixing(
    first_parts: tuple[tuple[str, ...], str],
    second_parts: tuple[tuple[str, ...], str],
    first_prefix: tuple[str, ...],
    second_prefix: tuple[str, ...],
) -> None:
    first_scope, first_local_id = first_parts
    second_scope, second_local_id = second_parts
    first = AcquisitionSlotId(first_local_id, scope=first_scope).prefixed(*first_prefix)
    second = AcquisitionSlotId(second_local_id, scope=second_scope).prefixed(
        *second_prefix
    )
    assume(first != second)

    assert first.qualified_name != second.qualified_name


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_quantum_identities_reject_blank_values(value: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        CircuitId(value)


@pytest.mark.parametrize("value", [None, 1, True, object()])
def test_quantum_identities_reject_non_string_values(value: object) -> None:
    with pytest.raises(TypeError, match="must be a string"):
        CircuitId(cast("str", value))


def test_nominal_quantum_identities_reject_unicode_surrogates() -> None:
    with pytest.raises(ValueError, match="Unicode surrogates"):
        CircuitId("\ud800")


@pytest.mark.parametrize("arity", [0, -1, True, 1.5])
def test_gate_definitions_require_positive_integer_arity(arity: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        GateDefinition(GateId("invalid"), cast("int", arity))


def test_gate_parameter_definitions_require_a_parameter_kind() -> None:
    with pytest.raises(ValueError, match="GateParameterKind"):
        GateParameterDefinition("theta", cast("GateParameterKind", "angle"))


@given(st.permutations(("z", "x", "y")))
def test_gate_catalog_verification_is_permutation_invariant(
    gate_order: SequenceCollection[str],
) -> None:
    definitions = {
        "z": GateDefinition(GateId("z"), qubit_arity=1),
        "x": GateDefinition(GateId("x"), qubit_arity=1),
        "y": GateDefinition(GateId("y"), qubit_arity=1),
    }
    program = CircuitProgram(
        CircuitId("program"),
        GateCall(
            CircuitOperationId("x-q0"),
            GateId("x"),
            (QubitId("q0"),),
        ),
    )

    verified = verify_circuit_program(
        program,
        tuple(definitions[item] for item in gate_order),
    )

    assert tuple(item.id.value for item in verified.gate_definitions) == (
        "x",
        "y",
        "z",
    )


@given(st.lists(st.integers(min_value=0, max_value=10_000), unique=True))
def test_sequence_preserves_generated_operation_order(operation_ids: list[int]) -> None:
    operations = tuple(
        GateCall(
            CircuitOperationId(f"op-{operation_id}"),
            GateId("x"),
            (QubitId(f"q-{operation_id}"),),
        )
        for operation_id in operation_ids
    )
    program = CircuitProgram(CircuitId("sequence"), Sequence(operations))

    verified = verify_circuit_program(
        program,
        (GateDefinition(GateId("x"), qubit_arity=1),),
    )

    expected = tuple(operation.id for operation in operations)
    assert tuple(operation.id for operation in verified.operations) == expected
    assert tuple(
        operation.id for operation in iter_circuit_operations(program.body)
    ) == (expected)


def test_parallel_branches_must_have_disjoint_qubits() -> None:
    program = CircuitProgram(
        CircuitId("parallel"),
        Parallel(
            (
                GateCall(
                    CircuitOperationId("left"),
                    GateId("x"),
                    (QubitId("q0"),),
                ),
                Sequence(
                    (
                        GateCall(
                            CircuitOperationId("right"),
                            GateId("x"),
                            (QubitId("q0"),),
                        ),
                    )
                ),
            )
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(
            program,
            (GateDefinition(GateId("x"), qubit_arity=1),),
        )

    assert [issue.code for issue in error.value.issues] == ["parallel_qubit_conflict"]


@given(_NONEMPTY_IDS)
def test_generated_parallel_overlap_is_always_rejected(qubit_value: str) -> None:
    qubit = QubitId(qubit_value)
    program = CircuitProgram(
        CircuitId("parallel-generated-conflict"),
        Parallel(
            (
                GateCall(CircuitOperationId("left"), GateId("x"), (qubit,)),
                GateCall(CircuitOperationId("right"), GateId("x"), (qubit,)),
            )
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(
            program,
            (GateDefinition(GateId("x"), qubit_arity=1),),
        )

    assert any(issue.code == "parallel_qubit_conflict" for issue in error.value.issues)


def test_gate_arguments_require_exact_coverage_and_matching_types() -> None:
    definition = GateDefinition(
        GateId("rotation"),
        qubit_arity=1,
        parameters=(
            GateParameterDefinition("turns", GateParameterKind.INTEGER),
            GateParameterDefinition("scale", GateParameterKind.NUMBER),
            GateParameterDefinition("phase", GateParameterKind.ANGLE),
        ),
    )
    program = CircuitProgram(
        CircuitId("invalid-arguments"),
        GateCall(
            CircuitOperationId("rotation-q0"),
            GateId("rotation"),
            (QubitId("q0"), QubitId("q1")),
            (
                GateArgument("turns", 1.5),
                GateArgument("phase", Quantity(5, "ns")),
                GateArgument("extra", 1),
            ),
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(program, (definition,))

    assert {issue.code for issue in error.value.issues} == {
        "circuit_gate_argument_missing",
        "circuit_gate_argument_type_mismatch",
        "circuit_gate_argument_unknown",
        "circuit_gate_arity_mismatch",
    }
    assert (
        sum(
            issue.code == "circuit_gate_argument_type_mismatch"
            for issue in error.value.issues
        )
        == 2
    )


def test_verified_gate_arguments_are_canonicalized_to_definition_order() -> None:
    definition = GateDefinition(
        GateId("rotation"),
        qubit_arity=1,
        parameters=(
            GateParameterDefinition("turns", GateParameterKind.INTEGER),
            GateParameterDefinition("scale", GateParameterKind.NUMBER),
            GateParameterDefinition("phase", GateParameterKind.ANGLE),
        ),
    )
    program = CircuitProgram(
        CircuitId("canonical-arguments"),
        GateCall(
            CircuitOperationId("rotation-q0"),
            GateId("rotation"),
            (QubitId("q0"),),
            (
                GateArgument("phase", Quantity(180, "deg")),
                GateArgument("scale", 0.5),
                GateArgument("turns", 2),
            ),
        ),
    )

    verified = verify_circuit_program(program, (definition,))
    call = verified.operations[0]

    assert isinstance(call, GateCall)
    assert tuple(argument.id for argument in call.arguments) == (
        "turns",
        "scale",
        "phase",
    )
    phase = call.arguments[2].value
    assert isinstance(phase, Quantity)
    assert phase.unit == "rad"
    assert phase.value == pytest.approx(math.pi)
    assert verified.gate_definition(GateId("rotation")) == definition


def test_non_finite_or_unrepresentable_numbers_are_rejected() -> None:
    definition = GateDefinition(
        GateId("scaled"),
        qubit_arity=1,
        parameters=(GateParameterDefinition("scale", GateParameterKind.NUMBER),),
    )

    for value in (math.inf, math.nan, 10**10_000):
        program = CircuitProgram(
            CircuitId("invalid-number"),
            GateCall(
                CircuitOperationId("scaled-q0"),
                definition.id,
                (QubitId("q0"),),
                (GateArgument("scale", value),),
            ),
        )

        with pytest.raises(CircuitVerificationError) as error:
            verify_circuit_program(program, (definition,))

        assert "circuit_gate_argument_type_mismatch" in {
            issue.code for issue in error.value.issues
        }


def test_malformed_angle_quantity_is_reported_by_verification() -> None:
    definition = GateDefinition(
        GateId("rotation"),
        qubit_arity=1,
        parameters=(GateParameterDefinition("phase", GateParameterKind.ANGLE),),
    )
    malformed = Quantity.model_construct(
        value=cast("float", "not-a-number"),
        unit="rad",
    )
    program = CircuitProgram(
        CircuitId("malformed-angle"),
        GateCall(
            CircuitOperationId("rotation-q0"),
            definition.id,
            (QubitId("q0"),),
            (GateArgument("phase", malformed),),
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(program, (definition,))

    assert "circuit_gate_argument_type_mismatch" in {
        issue.code for issue in error.value.issues
    }


@given(st.sets(st.sampled_from(("turns", "scale", "phase", "extra"))))
def test_generated_gate_argument_coverage_is_exact(supplied_ids: set[str]) -> None:
    definition = GateDefinition(
        GateId("rotation"),
        qubit_arity=1,
        parameters=(
            GateParameterDefinition("turns", GateParameterKind.INTEGER),
            GateParameterDefinition("scale", GateParameterKind.NUMBER),
            GateParameterDefinition("phase", GateParameterKind.ANGLE),
        ),
    )
    values = {
        "turns": 1,
        "scale": 0.5,
        "phase": Quantity(0, "rad"),
        "extra": 7,
    }
    program = CircuitProgram(
        CircuitId("generated-coverage"),
        GateCall(
            CircuitOperationId("rotation-q0"),
            GateId("rotation"),
            (QubitId("q0"),),
            tuple(
                GateArgument(argument_id, values[argument_id])
                for argument_id in sorted(supplied_ids)
            ),
        ),
    )
    expected_ids = {"turns", "scale", "phase"}

    if supplied_ids == expected_ids:
        assert verify_circuit_program(program, (definition,)).program == program
        return

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(program, (definition,))

    missing_paths = {
        issue.path[-1]
        for issue in error.value.issues
        if issue.code == "circuit_gate_argument_missing"
    }
    unknown_paths = {
        issue.path[-1]
        for issue in error.value.issues
        if issue.code == "circuit_gate_argument_unknown"
    }
    assert missing_paths == expected_ids - supplied_ids
    assert unknown_paths == supplied_ids - expected_ids


def test_verification_aggregates_unknown_gate_and_duplicate_identities() -> None:
    duplicate_operation_id = CircuitOperationId("duplicate")
    duplicate_slot_id = AcquisitionSlotId("slot")
    program = CircuitProgram(
        CircuitId("aggregate"),
        Sequence(
            (
                GateCall(
                    duplicate_operation_id,
                    GateId("unknown"),
                    (QubitId("q0"),),
                ),
                Measure(
                    duplicate_operation_id,
                    QubitId("q1"),
                    duplicate_slot_id,
                    AcquisitionKind.INTEGRATED_IQ,
                ),
                Measure(
                    CircuitOperationId("measure-2"),
                    QubitId("q2"),
                    duplicate_slot_id,
                    AcquisitionKind.INTEGRATED_IQ,
                ),
            )
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(program, ())

    assert {issue.code for issue in error.value.issues} == {
        "circuit_acquisition_slot_duplicate",
        "circuit_gate_unknown",
        "circuit_operation_duplicate",
    }


def test_measure_requires_a_runtime_acquisition_kind() -> None:
    program = CircuitProgram(
        CircuitId("invalid-measure-kind"),
        Measure(
            CircuitOperationId("measure-q0"),
            QubitId("q0"),
            AcquisitionSlotId("readout"),
            cast("AcquisitionKind", "integrated_iq"),
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(program, ())

    assert [issue.code for issue in error.value.issues] == [
        "circuit_acquisition_kind_invalid"
    ]
    assert error.value.issues[0].path == ("body", "acquisition_kind")


def test_measure_preserves_acquisition_contract_when_verified() -> None:
    measurement = Measure(
        CircuitOperationId("measure-q0"),
        QubitId("q0"),
        AcquisitionSlotId("readout", scope=("experiment",)),
        AcquisitionKind.RAW_TRACE,
    )

    verified = verify_circuit_program(
        CircuitProgram(CircuitId("measurement"), measurement),
        (),
    )

    assert verified.operations == (measurement,)


@given(st.lists(st.integers(min_value=0, max_value=20), min_size=1, unique=True))
def test_generated_parallel_branches_with_distinct_qubits_verify(
    qubit_ordinals: list[int],
) -> None:
    branches = tuple(
        GateCall(
            CircuitOperationId(f"x-{ordinal}"),
            GateId("x"),
            (QubitId(f"q-{ordinal}"),),
        )
        for ordinal in qubit_ordinals
    )
    program = CircuitProgram(CircuitId("parallel-generated"), Parallel(branches))

    verified = verify_circuit_program(
        program,
        (GateDefinition(GateId("x"), qubit_arity=1),),
    )

    assert tuple(verified.operations) == branches


def test_verifier_reports_invalid_node_shape_without_masking_other_issues() -> None:
    program = CircuitProgram(
        CircuitId("invalid-node"),
        Sequence(
            (
                cast("CircuitNode", object()),
                GateCall(
                    CircuitOperationId("unknown-call"),
                    GateId("unknown"),
                    (QubitId("q0"),),
                ),
            )
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_circuit_program(program, ())

    assert {issue.code for issue in error.value.issues} == {
        "circuit_gate_unknown",
        "circuit_node_invalid",
    }
