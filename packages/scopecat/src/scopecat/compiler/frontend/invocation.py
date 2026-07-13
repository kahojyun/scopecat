"""Prepared invocation input for the compiler frontend."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_runtime_inputs,
)
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.records.run_request import ScanRecord


@dataclass(frozen=True)
class InvocationRequestContext:
    id: str
    template_id: str | None
    template_inputs: Mapping[str, object] = field(default_factory=empty_frozen_mapping)
    scans: tuple[ScanRecord, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=empty_frozen_mapping)
    operator: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "template_inputs",
            freeze_runtime_inputs(self.template_inputs),
        )
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


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
