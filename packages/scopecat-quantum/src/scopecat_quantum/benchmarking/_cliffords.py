"""Exact reference Clifford groups and deterministic primitive decompositions."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from itertools import product
from typing import Literal

type SingleQubitPrimitive = Literal[
    "i",
    "x",
    "y",
    "x90",
    "xm90",
    "y90",
    "ym90",
]
type TwoQubitPrimitiveGate = Literal["h", "s", "sdg", "cz"]
type _SignedPauli = tuple[int, int]
type _CliffordMap = tuple[_SignedPauli, ...]

_PAULI_SYMBOLS = "IXYZ"
_SINGLE_QUBIT_CLIFFORD_COUNT = 24
_TWO_QUBIT_CLIFFORD_COUNT = 11_520
_SINGLE_QUBIT_GENERATOR_ORDER: tuple[SingleQubitPrimitive, ...] = (
    "x",
    "y",
    "x90",
    "xm90",
    "y90",
    "ym90",
)


@dataclass(frozen=True, slots=True)
class TwoQubitCliffordPrimitive:
    """One reference H/S/S†/CZ operation on positional pair members."""

    gate: TwoQubitPrimitiveGate
    qubits: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _SingleQubitCatalog:
    maps: tuple[_CliffordMap, ...]
    ids: dict[_CliffordMap, int]
    decompositions: tuple[tuple[SingleQubitPrimitive, ...], ...]


@dataclass(frozen=True, slots=True)
class _TwoQubitCatalog:
    maps: tuple[_CliffordMap, ...]
    ids: dict[_CliffordMap, int]
    decompositions: tuple[tuple[TwoQubitCliffordPrimitive, ...], ...]


@cache
def _pauli_labels(qubit_count: int) -> tuple[str, ...]:
    return tuple(
        "".join(symbols) for symbols in product(_PAULI_SYMBOLS, repeat=qubit_count)
    )


@cache
def _pauli_index(label: str) -> int:
    index = 0
    for symbol in label:
        index = index * 4 + _PAULI_SYMBOLS.index(symbol)
    return index


_SINGLE_PAULI_PRODUCT: dict[tuple[str, str], tuple[int, str]] = {
    ("I", "I"): (0, "I"),
    ("I", "X"): (0, "X"),
    ("I", "Y"): (0, "Y"),
    ("I", "Z"): (0, "Z"),
    ("X", "I"): (0, "X"),
    ("Y", "I"): (0, "Y"),
    ("Z", "I"): (0, "Z"),
    ("X", "X"): (0, "I"),
    ("Y", "Y"): (0, "I"),
    ("Z", "Z"): (0, "I"),
    ("X", "Y"): (1, "Z"),
    ("Y", "Z"): (1, "X"),
    ("Z", "X"): (1, "Y"),
    ("Y", "X"): (3, "Z"),
    ("Z", "Y"): (3, "X"),
    ("X", "Z"): (3, "Y"),
}


@cache
def _multiply_paulis(
    qubit_count: int,
    left: int,
    right: int,
) -> tuple[int, int]:
    phase = 0
    output: list[str] = []
    labels = _pauli_labels(qubit_count)
    for left_symbol, right_symbol in zip(labels[left], labels[right], strict=True):
        local_phase, symbol = _SINGLE_PAULI_PRODUCT[left_symbol, right_symbol]
        phase = (phase + local_phase) % 4
        output.append(symbol)
    return phase, _pauli_index("".join(output))


def _map_from_generator_images(
    qubit_count: int,
    images: tuple[_SignedPauli, ...],
) -> _CliffordMap:
    mapped: list[_SignedPauli] = []
    for label in _pauli_labels(qubit_count):
        phase = sum(symbol == "Y" for symbol in label) % 4
        output = 0
        for qubit, symbol in enumerate(label):
            for generator_offset, selected in ((0, "XY"), (1, "ZY")):
                if symbol not in selected:
                    continue
                image, sign = images[2 * qubit + generator_offset]
                local_phase, output = _multiply_paulis(
                    qubit_count,
                    output,
                    image,
                )
                phase = (phase + local_phase + (0 if sign == 1 else 2)) % 4
        if phase not in (0, 2):
            raise AssertionError(
                "Clifford generator image did not preserve Hermiticity"
            )
        mapped.append((output, 1 if phase == 0 else -1))
    return tuple(mapped)


def _identity_map(qubit_count: int) -> _CliffordMap:
    pauli_count = {1: 4, 2: 16}[qubit_count]
    return tuple((index, 1) for index in range(pauli_count))


def _compose(left: _CliffordMap, right: _CliffordMap) -> _CliffordMap:
    return tuple(
        (left[intermediate][0], right_sign * left[intermediate][1])
        for intermediate, right_sign in right
    )


def _inverse(value: _CliffordMap) -> _CliffordMap:
    inverse: list[_SignedPauli] = [(0, 1)] * len(value)
    for input_pauli, (output_pauli, sign) in enumerate(value):
        inverse[output_pauli] = (input_pauli, sign)
    return tuple(inverse)


def _ordered_maps(paths: Mapping[_CliffordMap, object]) -> tuple[_CliffordMap, ...]:
    first = next(iter(paths))
    identity = _identity_map(_qubits(first))
    return (identity, *sorted(value for value in paths if value != identity))


def _qubits(value: _CliffordMap) -> int:
    if len(value) == 4:
        return 1
    if len(value) == 16:
        return 2
    raise AssertionError("reference Clifford map has an unsupported Pauli dimension")


@cache
def _single_qubit_catalog() -> _SingleQubitCatalog:
    x = _pauli_index("X")
    y = _pauli_index("Y")
    z = _pauli_index("Z")
    generator_maps: tuple[tuple[SingleQubitPrimitive, _CliffordMap], ...] = (
        ("x", _map_from_generator_images(1, ((x, 1), (z, -1)))),
        ("y", _map_from_generator_images(1, ((x, -1), (z, -1)))),
        ("x90", _map_from_generator_images(1, ((x, 1), (y, -1)))),
        ("xm90", _map_from_generator_images(1, ((x, 1), (y, 1)))),
        ("y90", _map_from_generator_images(1, ((z, -1), (x, 1)))),
        ("ym90", _map_from_generator_images(1, ((z, 1), (x, -1)))),
    )
    paths: dict[_CliffordMap, tuple[SingleQubitPrimitive, ...]] = {_identity_map(1): ()}
    pending = deque(paths)
    while pending:
        current = pending.popleft()
        for primitive, generator in generator_maps:
            selected = _compose(generator, current)
            if selected in paths:
                continue
            paths[selected] = (*paths[current], primitive)
            pending.append(selected)
    if len(paths) != _SINGLE_QUBIT_CLIFFORD_COUNT:
        raise AssertionError("reference generators did not span the 1q Clifford group")
    maps = _ordered_maps(paths)
    return _SingleQubitCatalog(
        maps=maps,
        ids={value: index for index, value in enumerate(maps)},
        decompositions=tuple(paths[value] or ("i",) for value in maps),
    )


def _two_qubit_generator_maps() -> tuple[
    tuple[TwoQubitCliffordPrimitive, _CliffordMap], ...
]:
    xi = _pauli_index("XI")
    yi = _pauli_index("YI")
    zi = _pauli_index("ZI")
    ix = _pauli_index("IX")
    iy = _pauli_index("IY")
    iz = _pauli_index("IZ")
    return (
        (
            TwoQubitCliffordPrimitive("h", (0,)),
            _map_from_generator_images(2, ((zi, 1), (xi, 1), (ix, 1), (iz, 1))),
        ),
        (
            TwoQubitCliffordPrimitive("s", (0,)),
            _map_from_generator_images(2, ((yi, 1), (zi, 1), (ix, 1), (iz, 1))),
        ),
        (
            TwoQubitCliffordPrimitive("sdg", (0,)),
            _map_from_generator_images(2, ((yi, -1), (zi, 1), (ix, 1), (iz, 1))),
        ),
        (
            TwoQubitCliffordPrimitive("h", (1,)),
            _map_from_generator_images(2, ((xi, 1), (zi, 1), (iz, 1), (ix, 1))),
        ),
        (
            TwoQubitCliffordPrimitive("s", (1,)),
            _map_from_generator_images(2, ((xi, 1), (zi, 1), (iy, 1), (iz, 1))),
        ),
        (
            TwoQubitCliffordPrimitive("sdg", (1,)),
            _map_from_generator_images(2, ((xi, 1), (zi, 1), (iy, -1), (iz, 1))),
        ),
        (
            TwoQubitCliffordPrimitive("cz", (0, 1)),
            _map_from_generator_images(
                2,
                (
                    (_pauli_index("XZ"), 1),
                    (zi, 1),
                    (_pauli_index("ZX"), 1),
                    (iz, 1),
                ),
            ),
        ),
    )


@cache
def _two_qubit_catalog() -> _TwoQubitCatalog:
    paths: dict[_CliffordMap, tuple[TwoQubitCliffordPrimitive, ...]] = {
        _identity_map(2): ()
    }
    pending = deque(paths)
    generators = _two_qubit_generator_maps()
    while pending:
        current = pending.popleft()
        for primitive, generator in generators:
            selected = _compose(generator, current)
            if selected in paths:
                continue
            paths[selected] = (*paths[current], primitive)
            pending.append(selected)
    if len(paths) != _TWO_QUBIT_CLIFFORD_COUNT:
        raise AssertionError("reference generators did not span the 2q Clifford group")
    maps = _ordered_maps(paths)
    return _TwoQubitCatalog(
        maps=maps,
        ids={value: index for index, value in enumerate(maps)},
        decompositions=tuple(paths[value] for value in maps),
    )


def single_qubit_clifford_count() -> int:
    """Return the order of the project reference 1q Clifford group."""

    return _SINGLE_QUBIT_CLIFFORD_COUNT


def single_qubit_clifford_product(cliffords: tuple[int, ...]) -> int:
    """Return the stable id for the Clifford applied by the ordered sequence."""

    catalog = _single_qubit_catalog()
    total = catalog.maps[0]
    for clifford in cliffords:
        total = _compose(catalog.maps[clifford], total)
    return catalog.ids[total]


def single_qubit_clifford_inverse(clifford: int) -> int:
    """Return the stable inverse id of one 1q Clifford."""

    catalog = _single_qubit_catalog()
    return catalog.ids[_inverse(catalog.maps[clifford])]


def decompose_single_qubit_clifford(
    clifford: int,
) -> tuple[SingleQubitPrimitive, ...]:
    """Expand one stable 1q Clifford id into the reference primitive vocabulary."""

    return _single_qubit_catalog().decompositions[clifford]


def two_qubit_clifford_count() -> int:
    """Return the order of the project reference 2q Clifford group."""

    return _TWO_QUBIT_CLIFFORD_COUNT


def two_qubit_clifford_product(cliffords: tuple[int, ...]) -> int:
    """Return the stable id for the two-qubit Clifford sequence product."""

    catalog = _two_qubit_catalog()
    total = catalog.maps[0]
    for clifford in cliffords:
        total = _compose(catalog.maps[clifford], total)
    return catalog.ids[total]


def two_qubit_clifford_inverse(clifford: int) -> int:
    """Return the stable inverse id of one 2q Clifford."""

    catalog = _two_qubit_catalog()
    return catalog.ids[_inverse(catalog.maps[clifford])]


def decompose_two_qubit_clifford(
    clifford: int,
) -> tuple[TwoQubitCliffordPrimitive, ...]:
    """Expand one stable 2q Clifford id into reference H/S/S†/CZ operations."""

    return _two_qubit_catalog().decompositions[clifford]


__all__ = [
    "SingleQubitPrimitive",
    "TwoQubitCliffordPrimitive",
    "TwoQubitPrimitiveGate",
    "decompose_single_qubit_clifford",
    "decompose_two_qubit_clifford",
    "single_qubit_clifford_count",
    "single_qubit_clifford_inverse",
    "single_qubit_clifford_product",
    "two_qubit_clifford_count",
    "two_qubit_clifford_inverse",
    "two_qubit_clifford_product",
]
