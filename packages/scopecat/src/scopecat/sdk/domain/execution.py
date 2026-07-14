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


@dataclass(frozen=True, slots=True, init=False)
class PreparedDomainExecution:
    """A pure proof that one linked program is ready for domain effects.

    The type-erased runtime fields form an existential adapter boundary: an
    adapter constructs all three from one concrete address/payload/result type
    family, while core never inspects those domain-owned values.
    """

    adapter_id: str
    context: DomainBatchContext = field(repr=False)
    _invocation: ErasedDomainInvocation = field(repr=False)
    _runtime: ErasedDomainRuntime = field(repr=False, compare=False)
    _realize: ErasedDomainRealizer = field(repr=False, compare=False)
    _source_fragment: BoundDomainMeasurementValueFragment[
        Hashable,
        Hashable,
    ] = field(repr=False)
    _resource_claims: tuple[ExecutionResourceClaim, ...] = field(
        default=(),
        repr=False,
    )
    _transforms: BoundHostMeasurementTransformPlan | None = field(
        default=None,
        repr=False,
    )
    completion_contract: Literal["synchronous"] = "synchronous"

    def __init__(self) -> None:
        msg = "prepared domain executions are minted by a preparation builder"
        raise TypeError(msg)

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.context), DomainBatchContext):
            msg = "prepared domain executions require a domain batch context"
            raise TypeError(msg)
        if self.adapter_id != context_adapter_id_internal(self.context):
            msg = "prepared domain execution lost its context adapter identity"
            raise ValueError(msg)
        if not callable(self._realize):
            msg = "domain execution realizer must be callable"
            raise TypeError(msg)
        if self.completion_contract != "synchronous":
            msg = "domain execution currently supports only synchronous completion"
            raise ValueError(msg)
        for method_name in ("submit", "fetch", "reconcile"):
            if not callable(getattr(self._runtime, method_name, None)):
                msg = f"domain runtime requires a callable {method_name} method"
                raise TypeError(msg)

        resource_claims = tuple(self._resource_claims)
        if len(resource_claims) != len(set(resource_claims)):
            msg = "domain execution resource claims must be unique"
            raise ValueError(msg)
        object.__setattr__(self, "_resource_claims", resource_claims)

        assembly = self._source_fragment.selection
        linked_points = context_linked_points_internal(self.context)
        if self._invocation.result_mapping.linked_points is not linked_points:
            msg = "domain invocation must retain the prepared linked points"
            raise ValueError(msg)
        if assembly.linked_points is not linked_points:
            msg = "domain source fragment must retain the prepared linked points"
            raise ValueError(msg)
        if (
            self._source_fragment.result_contract_fingerprint
            != self._invocation.result_mapping.contract_fingerprint
        ):
            msg = "domain source fragment must retain the invocation result contract"
            raise ValueError(msg)
        transforms = self._transforms
        if transforms is None:
            if tuple(fragment.id for fragment in assembly.fragments) != (
                self._source_fragment.fragment_id,
            ):
                msg = "domain execution without transforms requires one source fragment"
                raise ValueError(msg)
            return
        if transforms.value_assembly is not assembly:
            msg = "domain transforms must retain the source value assembly"
            raise ValueError(msg)
        if transforms.source_fragment_ids != (self._source_fragment.fragment_id,):
            msg = "domain execution currently requires exactly one domain source"
            raise ValueError(msg)

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

    selected = object.__new__(PreparedDomainExecution)
    object.__setattr__(
        selected,
        "adapter_id",
        context_adapter_id_internal(context),
    )
    object.__setattr__(selected, "context", context)
    object.__setattr__(
        selected,
        "_invocation",
        cast("ErasedDomainInvocation", invocation),
    )
    object.__setattr__(selected, "_runtime", cast("ErasedDomainRuntime", runtime))
    object.__setattr__(selected, "_realize", cast("ErasedDomainRealizer", realize))
    object.__setattr__(
        selected,
        "_source_fragment",
        cast(
            "BoundDomainMeasurementValueFragment[Hashable, Hashable]",
            source_fragment,
        ),
    )
    object.__setattr__(selected, "_resource_claims", resource_claims)
    object.__setattr__(selected, "_transforms", transforms)
    object.__setattr__(selected, "completion_contract", "synchronous")
    selected.__post_init__()
    return selected


def prepared_domain_invocation_internal(
    prepared: PreparedDomainExecution,
) -> ErasedDomainInvocation:
    return object.__getattribute__(prepared, "_invocation")


def prepared_domain_runtime_internal(
    prepared: PreparedDomainExecution,
) -> ErasedDomainRuntime:
    return object.__getattribute__(prepared, "_runtime")


def prepared_domain_realizer_internal(
    prepared: PreparedDomainExecution,
) -> ErasedDomainRealizer:
    return object.__getattribute__(prepared, "_realize")


def prepared_domain_source_fragment_internal(
    prepared: PreparedDomainExecution,
) -> BoundDomainMeasurementValueFragment[Hashable, Hashable]:
    return object.__getattribute__(prepared, "_source_fragment")


def prepared_domain_transforms_internal(
    prepared: PreparedDomainExecution,
) -> BoundHostMeasurementTransformPlan | None:
    return object.__getattribute__(prepared, "_transforms")


def prepared_domain_resource_claims_internal(
    prepared: PreparedDomainExecution,
) -> tuple[ExecutionResourceClaim, ...]:
    return object.__getattribute__(prepared, "_resource_claims")


__all__ = [
    "DomainExecutionAdapter",
    "PreparedDomainExecution",
]
