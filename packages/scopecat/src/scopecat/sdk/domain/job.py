"""Declarative target-job values accepted by the public domain SDK.

These values contain only laboratory-owned payloads, stable target identity,
and measurement values. ``DomainPreparationBuilder`` closes them into one
executable invocation.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field

from scopecat.kernel.json_types import JsonValue
from scopecat.records.measurement import MeasurementAcquisitionValue


@dataclass(frozen=True, slots=True)
class DomainInvocationSpec[PayloadT]:
    """Laboratory declaration of one idempotent target invocation.

    The payload is transient and target-owned. ``target_intent`` must be
    stable-content encodable because core fingerprints it when binding the
    invocation to an exact result mapping. Stable identity fields become
    validated execution intent when the preparation is closed.
    """

    invocation_id: str
    target_id: str
    compiler_id: str
    capability_fingerprint: str
    artifact_id: str
    artifact_fingerprint: str
    execution_summary: Mapping[str, JsonValue]
    target_intent: object = field(repr=False)
    payload: PayloadT = field(repr=False)


@dataclass(frozen=True, slots=True)
class DomainResultValue[ResultAddressT: Hashable]:
    """One laboratory-decoded value keyed by its physical result address."""

    result_address: ResultAddressT
    value: MeasurementAcquisitionValue
