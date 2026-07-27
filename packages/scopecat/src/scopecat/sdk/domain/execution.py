"""Runtime boundary for one prepared domain-program execution.

Domain compilers consume the target-neutral linked program and close target,
result, and value decisions before a run is durably accepted. Scopecat retains
ownership of runtime submission, correlation, journalling, recording, and
terminal run evidence.

The runtime boundary is synchronous: one fetch returns the complete result
while receipts preserve known and indeterminate outcomes.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field

from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.sdk.domain.invocation import ClosedDomainInvocation
from scopecat.sdk.domain.runtime import DomainFetchResult, DomainRuntime

type ErasedDomainInvocation = ClosedDomainInvocation[Hashable, object]
type ErasedDomainRuntime = DomainRuntime[object, object]
type ErasedDomainRealizer = Callable[
    [DomainFetchResult[object]],
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
