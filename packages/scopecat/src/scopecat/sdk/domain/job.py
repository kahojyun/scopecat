"""Declarative target-job values accepted by the public domain SDK.

These values contain only laboratory-owned payloads, stable target identity,
SDK-neutral resource names, and measurement values. Compiler and execution
proofs are closed later by a context-bound ``DomainPreparationBuilder``.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field

from scopecat.records.measurement import MeasurementValue


@dataclass(frozen=True, slots=True)
class DomainTargetArtifactIdentity:
    """Stable target/compiler/artifact facts retained by one invocation."""

    target_id: str
    compiler_id: str
    capability_fingerprint: str
    artifact_id: str
    artifact_fingerprint: str

    def __post_init__(self) -> None:
        fields = (
            self.target_id,
            self.compiler_id,
            self.capability_fingerprint,
            self.artifact_id,
            self.artifact_fingerprint,
        )
        if not all(fields):
            msg = "domain target artifact identity fields must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainInvocationSpec[PayloadT]:
    """Laboratory declaration of one idempotent target invocation.

    The payload is transient and target-owned. ``target_intent`` must be
    stable-content encodable because core fingerprints it when binding the
    invocation to an exact result mapping.
    """

    invocation_id: str
    target: DomainTargetArtifactIdentity
    target_intent: object = field(repr=False)
    payload: PayloadT = field(repr=False)

    def __post_init__(self) -> None:
        if not self.invocation_id:
            msg = "domain invocation ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainResultValue[ResultAddressT: Hashable]:
    """One laboratory-decoded value keyed by its physical result address."""

    result_address: ResultAddressT
    value: MeasurementValue
