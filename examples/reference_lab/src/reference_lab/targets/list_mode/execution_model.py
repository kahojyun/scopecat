"""Array-native execution results and identities for the list-mode target."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from scopecat_quantum._ids import TargetCompileEntryId
from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.targets.list_mode.model import (
    DigitizerAcquisitionWindow,
    ListModeArtifact,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
)


@dataclass(frozen=True, slots=True)
class DigitizerValueBlock:
    """One acquisition address across a contiguous vector of shots."""

    values: NDArray[np.complex128]
    available: NDArray[np.bool_]

    def __post_init__(self) -> None:
        values, available = _normalized_arrays(self.values, self.available, ndim=1)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "available", available)


@dataclass(frozen=True, slots=True)
class DigitizerResultBatch:
    """Address-major integrated-IQ matrix with one column per shot."""

    addresses: tuple[TargetAcquisitionAddress, ...]
    values: NDArray[np.complex128]
    available: NDArray[np.bool_]

    def __post_init__(self) -> None:
        values, available = _normalized_arrays(self.values, self.available, ndim=2)
        if values.shape[0] != len(self.addresses):
            raise ValueError("digitizer result rows must match acquisition addresses")
        if len(self.addresses) != len(set(self.addresses)):
            raise ValueError("digitizer result addresses must be unique")
        object.__setattr__(self, "addresses", tuple(self.addresses))
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "available", available)

    @property
    def result_count(self) -> int:
        """Return the number of address-qualified shot results."""

        return int(self.values.size)

    def select(
        self,
        addresses: tuple[TargetAcquisitionAddress, ...],
    ) -> DigitizerResultBatch:
        """Select and reorder address rows without constructing shot objects."""

        row_by_address = {
            address: row_index for row_index, address in enumerate(self.addresses)
        }
        rows = [row_by_address[address] for address in addresses]
        return DigitizerResultBatch(
            addresses=addresses,
            values=self.values[rows],
            available=self.available[rows],
        )


class AcquisitionResponse(Protocol):
    """Pluggable deterministic vector response for virtual acquisitions."""

    @property
    def fingerprint(self) -> str:
        """Return the stable identity of this response behavior."""
        ...

    def values_for(
        self,
        *,
        entry_id: TargetCompileEntryId,
        window: DigitizerAcquisitionWindow,
        shot_indices: NDArray[np.int64],
    ) -> DigitizerValueBlock:
        """Return one address's values for a contiguous shot vector."""
        ...


@dataclass(frozen=True, slots=True)
class ListModeRun:
    """Immutable result of one complete list-mode execution."""

    results: DigitizerResultBatch
    artifact: ListModeArtifact
    fingerprint: str


def digitizer_addresses(
    artifact: ListModeArtifact,
) -> tuple[TargetAcquisitionAddress, ...]:
    """Return canonical address rows in target entry/window order."""

    return tuple(
        TargetAcquisitionAddress(entry_id=entry.entry_id, slot_id=window.slot_id)
        for entry in artifact.entries
        for window in entry.acquisitions
    )


def run_fingerprint(
    *,
    artifact: ListModeArtifact,
    results: DigitizerResultBatch,
    response_fingerprint: str,
) -> str:
    """Identify one array-native raw result without per-shot JSON expansion."""

    return canonical_fingerprint(
        {
            "schema": "reference_lab.virtual_list_mode_run.v3",
            "artifact_id": artifact.id.value,
            "artifact_fingerprint": artifact.artifact_fingerprint,
            "response_fingerprint": response_fingerprint,
            "addresses": [
                {
                    "entry_id": address.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(address.slot_id),
                }
                for address in results.addresses
            ],
            "shape": list(results.values.shape),
            "values_sha256": hashlib.sha256(
                memoryview(results.values).cast("B")
            ).hexdigest(),
            "available_sha256": hashlib.sha256(
                memoryview(results.available).cast("B")
            ).hexdigest(),
        }
    )


def _normalized_arrays(
    values: object,
    available: object,
    *,
    ndim: int,
) -> tuple[NDArray[np.complex128], NDArray[np.bool_]]:
    selected_values = np.ascontiguousarray(values, dtype=np.complex128)
    selected_available = np.ascontiguousarray(available, dtype=np.bool_)
    if (
        selected_values.ndim != ndim
        or selected_values.shape != selected_available.shape
    ):
        raise ValueError("digitizer values and availability must have matching shape")
    if not np.all(selected_available):
        selected_values = selected_values.copy()
        selected_values[~selected_available] = 0j
    selected_values.flags.writeable = False
    selected_available.flags.writeable = False
    return selected_values, selected_available


__all__ = [
    "AcquisitionResponse",
    "DigitizerResultBatch",
    "DigitizerValueBlock",
    "ListModeRun",
    "digitizer_addresses",
    "run_fingerprint",
]
