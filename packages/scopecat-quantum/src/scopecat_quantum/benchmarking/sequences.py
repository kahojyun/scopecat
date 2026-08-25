"""Hardware-independent reference RB and XEB circuit-family generators."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, cast

from ._cliffords import (
    SingleQubitPrimitive,
    TwoQubitCliffordPrimitive,
    decompose_single_qubit_clifford,
    decompose_two_qubit_clifford,
    single_qubit_clifford_count,
    single_qubit_clifford_inverse,
    single_qubit_clifford_product,
    two_qubit_clifford_count,
    two_qubit_clifford_inverse,
    two_qubit_clifford_product,
)
from ._random import RandomStream, SequenceKey

type LengthSampling = Literal["independent", "shared_prefix"]

SINGLE_QUBIT_RB_PROTOCOL = "scopecat.rb.1q.clifford.v1"
TWO_QUBIT_RB_PROTOCOL = "scopecat.rb.2q.clifford.v1"
SINGLE_QUBIT_XEB_PROTOCOL = "scopecat.xeb.1q.reference.v1"
PHASED_XEB_PROTOCOL = "scopecat.xeb.phased-reference.v1"

_FINGERPRINT_DOMAIN = b"scopecat.quantum.sequence-manifest.v1\0"
_SINGLE_QUBIT_XEB_ENSEMBLE: tuple[SingleQubitPrimitive, ...] = (
    "i",
    "x",
    "y",
    "x90",
    "xm90",
    "y90",
    "ym90",
)
_PHASE_EIGHTH_TURNS = (0, 4, 2, 6, 1, 5, 7, 3)


def _fingerprint(document: dict[str, object]) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(_FINGERPRINT_DOMAIN + payload).hexdigest()


def _sequence_key(
    *,
    protocol: str,
    root_seed: int,
    sample_index: int,
    members: tuple[str, ...],
    length: int,
    length_sampling: LengthSampling,
) -> SequenceKey:
    if length <= 0:
        raise ValueError("benchmark sequence length must be positive")
    if length_sampling not in ("independent", "shared_prefix"):
        raise ValueError("length sampling must be 'independent' or 'shared_prefix'")
    return SequenceKey(
        protocol=protocol,
        root_seed=root_seed,
        sample_index=sample_index,
        members=members,
        length=length if length_sampling == "independent" else None,
        variant=length_sampling,
    )


@dataclass(frozen=True, slots=True)
class SingleQubitRbSequence:
    """One uniformly sampled 1q Clifford sequence and its exact recovery."""

    key: SequenceKey
    length: int
    random_cliffords: tuple[int, ...]
    recovery_clifford: int
    primitives: tuple[SingleQubitPrimitive, ...]

    @property
    def cliffords(self) -> tuple[int, ...]:
        return (*self.random_cliffords, self.recovery_clifford)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "cliffords": self.cliffords,
                "derived_seed": self.key.derived_seed,
                "length": self.length,
                "primitives": self.primitives,
                "protocol": self.key.protocol,
            }
        )


@dataclass(frozen=True, slots=True)
class EntitySingleQubitRbSequence:
    """One member-addressed branch of a parallel 1q RB circuit."""

    member_id: str
    sequence: SingleQubitRbSequence


@dataclass(frozen=True, slots=True)
class TwoQubitRbSequence:
    """One uniformly sampled 2q Clifford sequence and reference decomposition."""

    key: SequenceKey
    length: int
    random_cliffords: tuple[int, ...]
    recovery_clifford: int
    primitives: tuple[TwoQubitCliffordPrimitive, ...]

    @property
    def cliffords(self) -> tuple[int, ...]:
        return (*self.random_cliffords, self.recovery_clifford)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "cliffords": self.cliffords,
                "derived_seed": self.key.derived_seed,
                "length": self.length,
                "primitives": tuple(
                    (primitive.gate, primitive.qubits) for primitive in self.primitives
                ),
                "protocol": self.key.protocol,
            }
        )


@dataclass(frozen=True, slots=True)
class SingleQubitXebSequence:
    """One circuit from the versioned reference 1q XEB ensemble."""

    key: SequenceKey
    depth: int
    primitives: tuple[SingleQubitPrimitive, ...]

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "depth": self.depth,
                "derived_seed": self.key.derived_seed,
                "primitives": self.primitives,
                "protocol": self.key.protocol,
            }
        )


@dataclass(frozen=True, slots=True)
class PhasedXebLayer:
    """One simultaneous layer of π/2 rotations expressed in eighth turns."""

    phases_eighth_turns: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PhasedXebSequence:
    """Random local layers surrounding each entangling cycle."""

    key: SequenceKey
    members: tuple[str, ...]
    cycles: int
    layers: tuple[PhasedXebLayer, ...]

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "cycles": self.cycles,
                "derived_seed": self.key.derived_seed,
                "layers": tuple(layer.phases_eighth_turns for layer in self.layers),
                "members": self.members,
                "protocol": self.key.protocol,
            }
        )


def single_qubit_rb_sequence(
    root_seed: int,
    length: int,
    *,
    sample_index: int = 0,
    member_id: str | None = None,
    length_sampling: LengthSampling = "independent",
) -> SingleQubitRbSequence:
    """Generate uniform 1q Cliffords followed by their exact group inverse."""

    members = () if member_id is None else (member_id,)
    key = _sequence_key(
        protocol=SINGLE_QUBIT_RB_PROTOCOL,
        root_seed=root_seed,
        sample_index=sample_index,
        members=members,
        length=length,
        length_sampling=length_sampling,
    )
    stream = RandomStream(key)
    random_cliffords = tuple(
        stream.randbelow(single_qubit_clifford_count()) for _ in range(length)
    )
    recovery = single_qubit_clifford_inverse(
        single_qubit_clifford_product(random_cliffords)
    )
    primitives = cast(
        "tuple[SingleQubitPrimitive, ...]",
        tuple(
            primitive
            for clifford in (*random_cliffords, recovery)
            for primitive in decompose_single_qubit_clifford(clifford)
        ),
    )
    return SingleQubitRbSequence(
        key=key,
        length=length,
        random_cliffords=random_cliffords,
        recovery_clifford=recovery,
        primitives=primitives,
    )


def parallel_single_qubit_rb_sequences(
    root_seed: int,
    length: int,
    member_ids: tuple[str, ...],
    *,
    sample_index: int = 0,
    length_sampling: LengthSampling = "independent",
) -> tuple[EntitySingleQubitRbSequence, ...]:
    """Generate independently keyed branches while preserving caller axis order."""

    if len(set(member_ids)) != len(member_ids):
        raise ValueError("parallel RB member ids must be unique")
    return tuple(
        EntitySingleQubitRbSequence(
            member_id=member_id,
            sequence=single_qubit_rb_sequence(
                root_seed,
                length,
                sample_index=sample_index,
                member_id=member_id,
                length_sampling=length_sampling,
            ),
        )
        for member_id in member_ids
    )


def two_qubit_rb_sequence(
    root_seed: int,
    length: int,
    *,
    members: tuple[str, str] = ("left", "right"),
    sample_index: int = 0,
    length_sampling: LengthSampling = "independent",
) -> TwoQubitRbSequence:
    """Generate uniform 2q Cliffords with an H/S/S†/CZ reference lowering."""

    if members[0] == members[1]:
        raise ValueError("two-qubit RB members must be distinct")
    key = _sequence_key(
        protocol=TWO_QUBIT_RB_PROTOCOL,
        root_seed=root_seed,
        sample_index=sample_index,
        members=members,
        length=length,
        length_sampling=length_sampling,
    )
    stream = RandomStream(key)
    random_cliffords = tuple(
        stream.randbelow(two_qubit_clifford_count()) for _ in range(length)
    )
    recovery = two_qubit_clifford_inverse(two_qubit_clifford_product(random_cliffords))
    primitives = tuple(
        primitive
        for clifford in (*random_cliffords, recovery)
        for primitive in decompose_two_qubit_clifford(clifford)
    )
    return TwoQubitRbSequence(
        key=key,
        length=length,
        random_cliffords=random_cliffords,
        recovery_clifford=recovery,
        primitives=primitives,
    )


def single_qubit_xeb_sequence(
    root_seed: int,
    depth: int,
    *,
    sample_index: int = 0,
    member_id: str | None = None,
    length_sampling: LengthSampling = "independent",
) -> SingleQubitXebSequence:
    """Sample the versioned I/X/Y/±X90/±Y90 reference ensemble."""

    members = () if member_id is None else (member_id,)
    key = _sequence_key(
        protocol=SINGLE_QUBIT_XEB_PROTOCOL,
        root_seed=root_seed,
        sample_index=sample_index,
        members=members,
        length=depth,
        length_sampling=length_sampling,
    )
    stream = RandomStream(key)
    primitives = cast(
        "tuple[SingleQubitPrimitive, ...]",
        tuple(
            _SINGLE_QUBIT_XEB_ENSEMBLE[
                stream.randbelow(len(_SINGLE_QUBIT_XEB_ENSEMBLE))
            ]
            for _ in range(depth)
        ),
    )
    return SingleQubitXebSequence(key=key, depth=depth, primitives=primitives)


def phased_xeb_sequence(
    root_seed: int,
    cycles: int,
    members: tuple[str, ...],
    *,
    sample_index: int = 0,
    length_sampling: LengthSampling = "independent",
) -> PhasedXebSequence:
    """Sample one local π/2 layer before and after every entangling cycle."""

    if not members:
        raise ValueError("phased XEB requires at least one member")
    if len(set(members)) != len(members):
        raise ValueError("phased XEB member ids must be unique")
    key = _sequence_key(
        protocol=PHASED_XEB_PROTOCOL,
        root_seed=root_seed,
        sample_index=sample_index,
        members=members,
        length=cycles,
        length_sampling=length_sampling,
    )
    stream = RandomStream(key)
    layers = tuple(
        PhasedXebLayer(
            tuple(
                _PHASE_EIGHTH_TURNS[stream.randbelow(len(_PHASE_EIGHTH_TURNS))]
                for _member in members
            )
        )
        for _ in range(cycles + 1)
    )
    return PhasedXebSequence(
        key=key,
        members=members,
        cycles=cycles,
        layers=layers,
    )


def two_qubit_xeb_sequence(
    root_seed: int,
    cycles: int,
    *,
    members: tuple[str, str] = ("left", "right"),
    sample_index: int = 0,
    length_sampling: LengthSampling = "independent",
) -> PhasedXebSequence:
    """Generate the two-member specialization of the phased XEB ensemble."""

    return phased_xeb_sequence(
        root_seed,
        cycles,
        members,
        sample_index=sample_index,
        length_sampling=length_sampling,
    )


__all__ = [
    "PHASED_XEB_PROTOCOL",
    "SINGLE_QUBIT_RB_PROTOCOL",
    "SINGLE_QUBIT_XEB_PROTOCOL",
    "TWO_QUBIT_RB_PROTOCOL",
    "EntitySingleQubitRbSequence",
    "LengthSampling",
    "PhasedXebLayer",
    "PhasedXebSequence",
    "SingleQubitRbSequence",
    "SingleQubitXebSequence",
    "TwoQubitRbSequence",
    "parallel_single_qubit_rb_sequences",
    "phased_xeb_sequence",
    "single_qubit_rb_sequence",
    "single_qubit_xeb_sequence",
    "two_qubit_rb_sequence",
    "two_qubit_xeb_sequence",
]
