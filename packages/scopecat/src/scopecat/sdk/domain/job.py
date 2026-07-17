"""Declarative target-job values accepted by the public domain SDK.

These values contain only laboratory-owned payloads, stable target identity,
SDK-neutral resource names, and measurement values. Compiler and execution
proofs are closed later by a context-bound ``DomainPreparationBuilder``.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Literal

from scopecat.records.measurement import MeasurementValue

type DomainResourceKind = Literal["target", "instrument", "channel", "group"]


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

    The payload is transient and target-owned. ``adapter_intent`` must be
    stable-content encodable because core fingerprints it when binding the
    invocation to an exact result mapping.
    """

    invocation_id: str
    target: DomainTargetArtifactIdentity
    adapter_intent: object = field(repr=False)
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


@dataclass(frozen=True, slots=True)
class DomainResourceClaim:
    """Laboratory-visible exclusive resource used by a prepared target job."""

    kind: DomainResourceKind
    id: str

    def __post_init__(self) -> None:
        if self.kind not in {"target", "instrument", "channel", "group"}:
            msg = f"unsupported domain resource kind {self.kind!r}"
            raise ValueError(msg)
        if not self.kind or not self.id:
            msg = "domain resource claim kind and id must be non-empty"
            raise ValueError(msg)
