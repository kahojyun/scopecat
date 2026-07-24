"""In-process registrations behind the daemon experiment catalog."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import cast

from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.invocation import (
    InvocationRequestContext,
    PreparedInvocation,
)
from scopecat.daemon.wire import (
    ExperimentCatalog,
    ManagedRunSubmission,
    RegisteredExperimentDescriptor,
)
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.records.run_request import RunRequest

type RegisteredExperimentFactory = Callable[
    [RunRequest],
    ExperimentInvocation | PreparedInvocation,
]
type RegistrationIdentity = tuple[str, str]


@dataclass(frozen=True, slots=True)
class RegisteredExperiment:
    """One explicit wire identity paired with a process-local factory."""

    id: str
    version: str
    descriptor: RegisteredExperimentDescriptor
    factory: RegisteredExperimentFactory = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (self.id, self.version) != (
            self.descriptor.id,
            self.descriptor.version,
        ):
            msg = "registration id and version must match its descriptor"
            raise ValueError(msg)


class RegisteredExperimentCatalog:
    """Canonical catalog snapshot plus process-local factory lookup."""

    __slots__ = ("_by_identity", "_registrations", "_snapshot")

    def __init__(
        self,
        registrations: Iterable[RegisteredExperiment] = (),
    ) -> None:
        selected = tuple(
            sorted(
                registrations,
                key=lambda item: (item.id, item.version),
            )
        )
        by_identity: dict[RegistrationIdentity, RegisteredExperiment] = {
            (item.id, item.version): item for item in selected
        }
        if len(by_identity) != len(selected):
            msg = "registered experiment id and version pairs must be unique"
            raise ValueError(msg)

        descriptors = tuple(item.descriptor for item in selected)
        self._registrations = selected
        self._by_identity = by_identity
        self._snapshot = ExperimentCatalog(
            revision=_catalog_revision(descriptors),
            experiments=descriptors,
        )

    @property
    def registrations(self) -> tuple[RegisteredExperiment, ...]:
        return self._registrations

    @property
    def snapshot(self) -> ExperimentCatalog:
        return self._snapshot

    @property
    def revision(self) -> str:
        return self._snapshot.revision

    def lookup(self, id: str, version: str) -> RegisteredExperiment:  # noqa: A002
        """Find one exact registration without selecting a mutable latest version."""

        identity = (id, version)
        try:
            return self._by_identity[identity]
        except KeyError as error:
            msg = f"registered experiment {id!r} version {version!r} was not found"
            raise KeyError(msg) from error

    def prepare(self, submission: ManagedRunSubmission) -> PreparedInvocation:
        """Build transient compiler input while retaining the submitted request."""

        registration = self.lookup(
            submission.registration_id,
            submission.registration_version,
        )
        built = registration.factory(submission.request)
        invocation = (
            built.invocation if isinstance(built, PreparedInvocation) else built
        )
        return PreparedInvocation(
            invocation=invocation,
            request_context=_request_context(submission.request),
        )


def _catalog_revision(
    descriptors: tuple[RegisteredExperimentDescriptor, ...],
) -> str:
    content = {
        "schema": "scopecat.registered_experiment_catalog_revision.v1",
        "experiments": [
            descriptor.model_dump(mode="json") for descriptor in descriptors
        ],
    }
    return f"sha256:{stable_content_hash(content)}"


def _request_context(request: RunRequest) -> InvocationRequestContext:
    # Dumping through the wire converts nested request models back into the
    # closed runtime value shapes accepted by InvocationRequestContext.
    wire = request.model_dump(mode="json")
    return InvocationRequestContext(
        id=request.id,
        template_id=request.template_id,
        template_inputs=cast("dict[str, object]", wire["template_inputs"]),
        scans=tuple(request.scans),
        metadata=cast("dict[str, object]", wire["metadata"]),
        operator=request.operator,
    )


__all__ = [
    "RegisteredExperiment",
    "RegisteredExperimentCatalog",
    "RegisteredExperimentFactory",
]
