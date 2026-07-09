"""Internal prepared invocation plan for workflow terminals."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.authoring.templates import ExperimentInvocation
from scopecat.experiments import ScanRecord


@dataclass(frozen=True)
class InvocationRequestContext:
    id: str
    template_id: str | None
    template_inputs: dict[str, object] = field(default_factory=dict)
    scans: tuple[ScanRecord, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    operator: str | None = None


@dataclass(frozen=True)
class PreparedInvocation:
    invocation: ExperimentInvocation
    request_context: InvocationRequestContext


def prepare_invocation(
    invocation: ExperimentInvocation,
    *,
    request_context: InvocationRequestContext | None = None,
) -> PreparedInvocation:
    return PreparedInvocation(
        invocation,
        request_context or default_request_context(invocation),
    )


def default_request_context(
    invocation: ExperimentInvocation,
) -> InvocationRequestContext:
    return InvocationRequestContext(
        id=f"{invocation.template.id}.request",
        template_id=invocation.template.id,
    )
