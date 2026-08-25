from __future__ import annotations

from scopecat_quantum.benchmarking import (
    SequenceKey,
    parallel_single_qubit_rb_sequences,
    single_qubit_clifford_product,
    single_qubit_rb_sequence,
    single_qubit_xeb_sequence,
    two_qubit_clifford_count,
    two_qubit_clifford_product,
    two_qubit_rb_sequence,
    two_qubit_xeb_sequence,
)


def test_sequence_key_is_portable_and_domain_separated() -> None:
    key = SequenceKey(
        protocol="scopecat.rb.1q.clifford.v1",
        root_seed=17,
        members=("q0",),
        length=8,
        variant="independent",
    )

    assert key.derived_seed == 327_103_720_341_604_497_917_709_819_177_351_070_441
    assert key.digest().hex() == (
        "f615e28ee09eaae4ad39da86a29942e9c01e781591951b5c88926aad574ca0db"
    )
    assert (
        key.digest()
        != SequenceKey(
            protocol="scopecat.xeb.1q.reference.v1",
            root_seed=17,
            members=("q0",),
            length=8,
            variant="independent",
        ).digest()
    )


def test_single_qubit_rb_is_replayable_and_appends_exact_recovery() -> None:
    sequence = single_qubit_rb_sequence(17, 8, member_id="q0")

    assert sequence.random_cliffords == (0, 18, 8, 10, 11, 23, 16, 12)
    assert sequence.recovery_clifford == 17
    assert single_qubit_clifford_product(sequence.cliffords) == 0
    assert sequence.fingerprint == (
        "sha256:bb72ebad8dc64f864fa20cadd2f5c3f713ef6c33f8fe0223720229359f0e8b84"
    )
    assert sequence == single_qubit_rb_sequence(17, 8, member_id="q0")


def test_parallel_single_qubit_rb_is_member_keyed_and_order_independent() -> None:
    forward = parallel_single_qubit_rb_sequences(17, 8, ("q0", "q1"))
    reverse = parallel_single_qubit_rb_sequences(17, 8, ("q1", "q0"))
    forward_by_member = {branch.member_id: branch.sequence for branch in forward}
    reverse_by_member = {branch.member_id: branch.sequence for branch in reverse}

    assert forward_by_member == reverse_by_member
    assert forward_by_member["q0"] != forward_by_member["q1"]
    assert single_qubit_rb_sequence(17, 26, member_id="q0").key.digest() != (
        single_qubit_rb_sequence(17, 1, member_id="q1").key.digest()
    )


def test_shared_prefix_and_independent_length_modes_are_explicit() -> None:
    prefix_three = single_qubit_rb_sequence(
        17,
        3,
        member_id="q0",
        length_sampling="shared_prefix",
    )
    prefix_five = single_qubit_rb_sequence(
        17,
        5,
        member_id="q0",
        length_sampling="shared_prefix",
    )
    independent_three = single_qubit_rb_sequence(17, 3, member_id="q0")
    independent_five = single_qubit_rb_sequence(17, 5, member_id="q0")

    assert prefix_five.random_cliffords[:3] == prefix_three.random_cliffords
    assert independent_five.random_cliffords[:3] != (independent_three.random_cliffords)


def test_two_qubit_rb_samples_the_full_group_and_recovers_identity() -> None:
    sequence = two_qubit_rb_sequence(17, 3, members=("q0", "q1"))

    assert two_qubit_clifford_count() == 11_520
    assert sequence.random_cliffords == (2_850, 7_562, 261)
    assert sequence.recovery_clifford == 9_046
    assert two_qubit_clifford_product(sequence.cliffords) == 0
    assert sequence.primitives
    assert {primitive.gate for primitive in sequence.primitives} <= {
        "h",
        "s",
        "sdg",
        "cz",
    }


def test_reference_xeb_ensembles_are_replayable() -> None:
    single = single_qubit_xeb_sequence(17, 5, member_id="q0")
    pair = two_qubit_xeb_sequence(17, 3, members=("q0", "q1"))

    assert single.primitives == ("y90", "x90", "y90", "x", "y90")
    assert tuple(layer.phases_eighth_turns for layer in pair.layers) == (
        (3, 4),
        (2, 1),
        (5, 4),
        (3, 0),
    )
    assert pair == two_qubit_xeb_sequence(17, 3, members=("q0", "q1"))
