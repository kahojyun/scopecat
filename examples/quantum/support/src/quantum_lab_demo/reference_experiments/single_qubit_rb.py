"""Single-qubit Clifford RB authored as one point-bound quantum program.

One RB sequence is naturally one program point. Clifford length and seed stay
ordinary experiment axes; ``@q.fragment`` only expands their concrete values
into a composable gate sequence after the point binds.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Annotated, cast

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum import (
    DRAG,
    BinaryIqDiscriminator,
    CalibrationCatalog,
    CalibrationId,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateId,
    IqCentroid,
    Play,
    PulseEventId,
    PulseProgram,
    PulseProgramId,
    QubitId,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as q

SINGLE_QUBIT_RB_TEMPLATE_ID = "quantum_lab_demo.reference.single_qubit_rb"
SINGLE_QUBIT_RB_SHOTS = 128
DEFAULT_CLIFFORD_COUNTS = (4, 16, 64)
DEFAULT_RB_SEEDS = (0, 1, 2)

CLIFFORD_LENGTH = sc.point(
    "clifford_length",
    sc.ScalarType(sc.IntType(minimum=1)),
)
RB_SEED = sc.point("rb_seed", sc.ScalarType(sc.IntType(minimum=0)))

_X90 = q.single_qubit_gate("x90")
_XM90 = q.single_qubit_gate("xm90")
_Y90 = q.single_qubit_gate("y90")
_YM90 = q.single_qubit_gate("ym90")
_PRIMITIVE_GATES = {
    "x90": _X90,
    "xm90": _XM90,
    "y90": _Y90,
    "ym90": _YM90,
}

type _Rotation = tuple[
    tuple[int, int, int],
    tuple[int, int, int],
    tuple[int, int, int],
]

_IDENTITY: _Rotation = (
    (1, 0, 0),
    (0, 1, 0),
    (0, 0, 1),
)
_PRIMITIVE_ROTATIONS: tuple[tuple[str, _Rotation], ...] = (
    (
        "x90",
        (
            (1, 0, 0),
            (0, 0, -1),
            (0, 1, 0),
        ),
    ),
    (
        "xm90",
        (
            (1, 0, 0),
            (0, 0, 1),
            (0, -1, 0),
        ),
    ),
    (
        "y90",
        (
            (0, 0, 1),
            (0, 1, 0),
            (-1, 0, 0),
        ),
    ),
    (
        "ym90",
        (
            (0, 0, -1),
            (0, 1, 0),
            (1, 0, 0),
        ),
    ),
)


def _compose(after: _Rotation, before: _Rotation) -> _Rotation:
    return cast(
        "_Rotation",
        tuple(
            tuple(
                sum(after[row][inner] * before[inner][column] for inner in range(3))
                for column in range(3)
            )
            for row in range(3)
        ),
    )


def _inverse(rotation: _Rotation) -> _Rotation:
    return cast(
        "_Rotation",
        tuple(tuple(rotation[column][row] for column in range(3)) for row in range(3)),
    )


def _build_clifford_decompositions() -> dict[_Rotation, tuple[str, ...]]:
    decompositions: dict[_Rotation, tuple[str, ...]] = {_IDENTITY: ()}
    frontier = [_IDENTITY]
    for current in frontier:
        prefix = decompositions[current]
        for primitive_id, primitive in _PRIMITIVE_ROTATIONS:
            candidate = _compose(primitive, current)
            if candidate not in decompositions:
                decompositions[candidate] = (*prefix, primitive_id)
                frontier.append(candidate)
    if len(decompositions) != 24:
        raise AssertionError(
            "quarter turns must generate the 24 single-qubit Cliffords"
        )
    return decompositions


_CLIFFORD_DECOMPOSITIONS = _build_clifford_decompositions()
_CLIFFORDS = tuple(_CLIFFORD_DECOMPOSITIONS.items())


def _rb_gate_ids(length: int, seed: int) -> tuple[str, ...]:
    rng = random.Random(seed)  # noqa: S311 - reproducibility is the RB contract.
    accumulated = _IDENTITY
    gate_ids: list[str] = []
    for _ in range(length):
        rotation, decomposition = _CLIFFORDS[rng.randrange(len(_CLIFFORDS))]
        accumulated = _compose(rotation, accumulated)
        gate_ids.extend(decomposition)
    gate_ids.extend(_CLIFFORD_DECOMPOSITIONS[_inverse(accumulated)])
    return tuple(gate_ids)


@q.fragment(id="quantum_lab_demo.reference.single_qubit_rb.sequence")
def randomized_clifford_sequence(
    qubit: q.Qubit,
    length: Annotated[int, sc.IntType(minimum=1)],
    seed: Annotated[int, sc.IntType(minimum=0)],
) -> q.QuantumFragment:
    """Generate one seeded Clifford sequence and its exact inverse at bind time."""

    gate_ids = _rb_gate_ids(length, seed)
    if not gate_ids:
        return q.repeat(_X90(qubit), 0)
    return q.sequence(*(_PRIMITIVE_GATES[gate_id](qubit) for gate_id in gate_ids))


@q.program(id="single-qubit-clifford-rb")
def single_qubit_rb_program(
    qubit: q.Qubit,
    length: Annotated[int, sc.IntType(minimum=1)],
    seed: Annotated[int, sc.IntType(minimum=0)],
) -> q.QuantumFragment:
    """Run one seeded Clifford sequence, recovery, and integrated-IQ capture."""

    return q.sequence(
        randomized_clifford_sequence(qubit, length, seed),
        q.measure(qubit, result="iq_shots"),
    )


_RB_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@sc.module(id="quantum_lab_demo.reference.single_qubit_rb.capture")
def single_qubit_rb_capture(
    qubit: Annotated[
        sc.Input[str],
        sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")),
    ],
    clifford_count: Annotated[sc.Input[int], sc.IntType(minimum=1)],
    seed: Annotated[sc.Input[int], sc.IntType(minimum=0)],
):
    """Compile and discriminate one RB point through the lab domain compiler."""

    call = single_qubit_rb_program(
        qubit=qubit,
        length=clifford_count,
        seed=seed,
        shots=SINGLE_QUBIT_RB_SHOTS,
    )
    body = (
        sc.module_body()
        .use(call)
        .product(
            "probability_0",
            "probability_1",
            unit="ratio",
        )
    )
    return body.measurement_transforms(
        binary_iq_probability_transform(
            "binary-iq-probability",
            iq_shots=call.results.iq_shots,
            probability_0=body.products.probability_0,
            probability_1=body.products.probability_1,
            discriminator=_RB_DISCRIMINATOR,
        )
    )


def _single_qubit_rb_body(
    clifford_counts: Sequence[int],
    seeds: Sequence[int],
) -> sc.ExperimentBody:
    capture = single_qubit_rb_capture(
        qubit="q0",
        clifford_count=CLIFFORD_LENGTH,
        seed=RB_SEED,
    )
    return (
        sc.experiment(capture)
        .scan(
            sc.cartesian(
                sc.axis(CLIFFORD_LENGTH, tuple(clifford_counts)),
                sc.axis(RB_SEED, tuple(seeds)),
            )
        )
        .record_product(
            capture.products.probability_0,
            record_id="survival_probability",
        )
    )


@sc.template(
    id=SINGLE_QUBIT_RB_TEMPLATE_ID,
    kind="single_qubit_rb",
    label="single-qubit Clifford RB",
)
def single_qubit_rb_template() -> sc.ExperimentBody:
    """Scan Clifford length and random seed for the calibrated q0 gate set."""

    return _single_qubit_rb_body(DEFAULT_CLIFFORD_COUNTS, DEFAULT_RB_SEEDS)


@sc.scratch(
    id="quantum_lab_demo.reference.single_qubit_rb.scratch",
    kind="single_qubit_rb",
    label="single-qubit Clifford RB scratch",
)
def single_qubit_rb_scratch(
    *,
    clifford_counts: Sequence[int] = DEFAULT_CLIFFORD_COUNTS,
    seeds: Sequence[int] = DEFAULT_RB_SEEDS,
) -> sc.ExperimentBody:
    """Build the same RB semantics with caller-selected axes."""

    return _single_qubit_rb_body(clifford_counts, seeds)


def single_qubit_rb_calibration_catalog() -> CalibrationCatalog:
    """Add the calibrated Y quarter turns used by the RB Clifford generator."""

    qubit = QubitId("q0")
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            tuple(
                GateCalibration(
                    id=CalibrationId(f"single-qubit-rb.{gate_id}.q0"),
                    key=GateCalibrationKey(GateId(gate_id), (qubit,)),
                    pulse_template=PulseProgram(
                        id=PulseProgramId(f"single-qubit-rb.{gate_id}.template"),
                        body=Play(
                            id=PulseEventId("drive"),
                            signal=DriveSignal(qubit),
                            envelope=DRAG(
                                duration=Quantity(16, "ns"),
                                amplitude=Quantity(0.2, "arb"),
                                sigma=Quantity(4, "ns"),
                                beta=Quantity(0.5, "ns"),
                                phase=phase,
                            ),
                        ),
                    ),
                )
                for gate_id, phase in (
                    ("y90", Quantity(math.pi / 2, "rad")),
                    ("ym90", Quantity(-math.pi / 2, "rad")),
                )
            )
        )
    )


__all__ = [
    "CLIFFORD_LENGTH",
    "DEFAULT_CLIFFORD_COUNTS",
    "DEFAULT_RB_SEEDS",
    "RB_SEED",
    "SINGLE_QUBIT_RB_SHOTS",
    "SINGLE_QUBIT_RB_TEMPLATE_ID",
    "randomized_clifford_sequence",
    "single_qubit_rb_calibration_catalog",
    "single_qubit_rb_capture",
    "single_qubit_rb_program",
    "single_qubit_rb_scratch",
    "single_qubit_rb_template",
]
