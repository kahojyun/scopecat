"""Implementation-independent semantic operation contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OpaqueSemantics:
    """Meaning defined by the local implementation, not by Scopecat core."""


type OperationContract = OpaqueSemantics


LOCAL_OPAQUE_OPERATION_CONTRACT: OperationContract = OpaqueSemantics()
