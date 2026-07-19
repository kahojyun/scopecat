"""Runtime boundary for one prepared domain-program execution.

Domain compilers consume the target-neutral linked program and close every
target, result, value, transform, and record-projection decision before a run
is durably accepted.  Scopecat retains ownership of runtime submission,
correlation, journalling, recording, and terminal run evidence.

The first public contract is deliberately synchronous: the initial fetch must
either return the complete result or violate the adapter contract. Polling and
resumption require a separate durable lifecycle and are not implied here.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Literal

from scopecat.execution.points import RunPoint
from scopecat.measurements.host_transforms import BoundHostMeasurementTransforms
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.sdk.domain.invocation import ClosedDomainInvocation
from scopecat.sdk.domain.runtime import CorrelatedDomainFetch, DomainRuntime

type ErasedDomainInvocation = ClosedDomainInvocation[Hashable, object]
type ErasedDomainRuntime = DomainRuntime[object, object]
type ErasedDomainRealizer = Callable[
    [CorrelatedDomainFetch[object]],
    tuple[MeasurementValueCandidate, ...],
]


@dataclass(frozen=True, slots=True)
class PreparedDomainExecution:
    """A pure proof that one linked program is ready for domain effects.

    The type-erased runtime fields form an existential adapter boundary: an
    adapter constructs all three from one concrete address/payload/result type
    family, while core never inspects those domain-owned values.
    """

    invocation: ErasedDomainInvocation = field(repr=False)
    runtime: ErasedDomainRuntime = field(repr=False, compare=False)
    realize: ErasedDomainRealizer = field(repr=False, compare=False)
    points: tuple[RunPoint, ...] = field(default=(), repr=False)
    transforms: BoundHostMeasurementTransforms | None = field(
        default=None,
        repr=False,
    )

    @property
    def completion_contract(self) -> Literal["synchronous"]:
        return "synchronous"
