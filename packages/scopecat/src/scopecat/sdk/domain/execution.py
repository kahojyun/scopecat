"""Public target boundary for one prepared domain-program execution.

Domain adapters consume the target-neutral linked program and close every
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
from typing import Literal, Protocol, cast

from scopecat.measurements.host_transforms import BoundHostMeasurementTransformPlan
from scopecat.measurements.values import BoundDomainMeasurementValueFragment
from scopecat.planning.coverage import ExecutionResourceClaim
from scopecat.records.run_plan import RunPlanDomainBatch
from scopecat.sdk.domain.context import (
    DomainBatchContext,
    DomainExecutionOffer,
    context_adapter_id_internal,
    context_linked_points_internal,
)
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    ClosedDomainOutputValues,
)
from scopecat.sdk.domain.runtime import CorrelatedDomainFetch, DomainRuntime
from scopecat.sdk.domain.view import DomainBatchView, DomainProductUseRef

type ErasedDomainInvocation = ClosedDomainInvocation[Hashable, Hashable, object]
type ErasedDomainRuntime = DomainRuntime[object, object]
type ErasedDomainRealizer = Callable[
    [CorrelatedDomainFetch[object]],
    ClosedDomainOutputValues[Hashable, Hashable],
]


@dataclass(frozen=True, slots=True)
class PreparedDomainExecution:
    """A pure proof that one linked program is ready for domain effects.

    The type-erased runtime fields form an existential adapter boundary: an
    adapter constructs all three from one concrete address/payload/result type
    family, while core never inspects those domain-owned values.
    """

    adapter_id: str
    context: DomainBatchContext = field(repr=False)
    _invocation: object = field(repr=False)
    _runtime: object = field(repr=False, compare=False)
    _realize: object = field(repr=False, compare=False)
    _source_fragment: object = field(repr=False)
    _resource_claims: object = field(default=(), repr=False)
    _transforms: object = field(default=None, repr=False)
    completion_contract: Literal["synchronous"] = "synchronous"

    @property
    def direct_product_uses(self) -> tuple[DomainProductUseRef, ...]:
        """Return exact SDK references produced by the physical target."""

        return self.context.direct_product_uses

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]:
        """Return every direct or host-derived value owned by this job."""

        return self.context.product_uses

    @property
    def semantic_operation_id(self) -> str:
        return self.context.call.id


class DomainExecutionAdapter(Protocol):
    """Pure selector of one explicitly covered domain-program execution unit.

    The adapter owns only the tasks retained by ``PreparedDomainExecution``.
    Exact whole-plan coverage and composition with local instrument units are
    selected by the execution backend before effects.
    """

    @property
    def adapter_id(self) -> str: ...

    def select(
        self,
        view: DomainBatchView,
    ) -> DomainExecutionOffer | None: ...

    def prepare(self, context: DomainBatchContext) -> PreparedDomainExecution: ...


def project_domain_run_plan_batch_internal(
    prepared: PreparedDomainExecution,
    *,
    context: DomainBatchContext,
) -> RunPlanDomainBatch:
    """Project one accepted batch identity without adapter payloads."""

    if prepared.context is not context:
        msg = "domain run-plan batches must retain their preparation context"
        raise ValueError(msg)

    intent = prepared_domain_invocation_internal(prepared).intent
    return RunPlanDomainBatch(
        batch_ordinal=context.batch_ordinal,
        point_indices=list(context_linked_points_internal(context).point_indices),
        semantic_operation_id=prepared.semantic_operation_id,
        completion_contract=prepared.completion_contract,
        invocation_id=intent.invocation_id,
        intent_fingerprint=intent.intent_fingerprint,
        target_id=intent.target_id,
        compiler_id=intent.compiler_id,
        capability_fingerprint=intent.capability_fingerprint,
        artifact_id=intent.artifact_id,
        artifact_fingerprint=intent.artifact_fingerprint,
    )


def make_prepared_domain_execution_internal[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
    PayloadT,
    ResultT,
](
    *,
    context: DomainBatchContext,
    invocation: ClosedDomainInvocation[EntryAddressT, ResultAddressT, PayloadT],
    runtime: DomainRuntime[PayloadT, ResultT],
    realize: Callable[
        [CorrelatedDomainFetch[ResultT]],
        ClosedDomainOutputValues[EntryAddressT, ResultAddressT],
    ],
    source_fragment: BoundDomainMeasurementValueFragment[
        EntryAddressT,
        ResultAddressT,
    ],
    resource_claims: tuple[ExecutionResourceClaim, ...] = (),
    transforms: BoundHostMeasurementTransformPlan | None = None,
) -> PreparedDomainExecution:
    """Close one concrete adapter type family behind the core execution ABI."""

    return PreparedDomainExecution(
        adapter_id=context_adapter_id_internal(context),
        context=context,
        _invocation=cast("ErasedDomainInvocation", invocation),
        _runtime=cast("ErasedDomainRuntime", runtime),
        _realize=cast("ErasedDomainRealizer", realize),
        _source_fragment=cast(
            "BoundDomainMeasurementValueFragment[Hashable, Hashable]",
            source_fragment,
        ),
        _resource_claims=resource_claims,
        _transforms=transforms,
    )


def prepared_domain_invocation_internal(
    prepared: PreparedDomainExecution,
) -> ErasedDomainInvocation:
    return cast(
        "ErasedDomainInvocation",
        object.__getattribute__(prepared, "_invocation"),
    )


def prepared_domain_runtime_internal(
    prepared: PreparedDomainExecution,
) -> ErasedDomainRuntime:
    return cast("ErasedDomainRuntime", object.__getattribute__(prepared, "_runtime"))


def prepared_domain_realizer_internal(
    prepared: PreparedDomainExecution,
) -> ErasedDomainRealizer:
    return cast(
        "ErasedDomainRealizer",
        object.__getattribute__(prepared, "_realize"),
    )


def prepared_domain_source_fragment_internal(
    prepared: PreparedDomainExecution,
) -> BoundDomainMeasurementValueFragment[Hashable, Hashable]:
    return cast(
        "BoundDomainMeasurementValueFragment[Hashable, Hashable]",
        object.__getattribute__(prepared, "_source_fragment"),
    )


def prepared_domain_transforms_internal(
    prepared: PreparedDomainExecution,
) -> BoundHostMeasurementTransformPlan | None:
    return cast(
        "BoundHostMeasurementTransformPlan | None",
        object.__getattribute__(prepared, "_transforms"),
    )


def prepared_domain_resource_claims_internal(
    prepared: PreparedDomainExecution,
) -> tuple[ExecutionResourceClaim, ...]:
    return cast(
        "tuple[ExecutionResourceClaim, ...]",
        object.__getattribute__(prepared, "_resource_claims"),
    )


__all__ = [
    "DomainExecutionAdapter",
    "PreparedDomainExecution",
]
