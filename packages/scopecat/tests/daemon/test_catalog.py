from __future__ import annotations

from collections.abc import Callable

import pytest

from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.invocation import (
    InvocationRequestContext,
    PreparedInvocation,
)
from scopecat.daemon.catalog import (
    RegisteredExperiment,
    RegisteredExperimentCatalog,
)
from scopecat.daemon.wire import (
    ManagedRunSubmission,
    RegisteredExperimentDescriptor,
)
from scopecat.records.run_request import (
    PointScanRecord,
    RunRequest,
)
from tests.testkit.workflow_fixtures import load_invocation


def _descriptor(
    *,
    id: str = "simple-scan",  # noqa: A002
    version: str = "1",
    title: str | None = "Simple scan",
) -> RegisteredExperimentDescriptor:
    return RegisteredExperimentDescriptor(
        id=id,
        version=version,
        experiment_kind="simple_scan",
        title=title,
        input_schema={
            "type": "object",
            "properties": {"subject": {"type": "string"}},
        },
        tags=("example",),
    )


def _registration(
    descriptor: RegisteredExperimentDescriptor,
    factory: (
        Callable[[RunRequest], ExperimentInvocation | PreparedInvocation] | None
    ) = None,
) -> RegisteredExperiment:
    def default_factory(_request: RunRequest) -> ExperimentInvocation:
        return load_invocation()

    selected_factory = factory or default_factory
    return RegisteredExperiment(
        id=descriptor.id,
        version=descriptor.version,
        descriptor=descriptor,
        factory=selected_factory,
    )


def _submission() -> ManagedRunSubmission:
    return ManagedRunSubmission(
        submission_id="submission-1",
        registration_id="simple-scan",
        registration_version="1",
        request=RunRequest(
            id="operator-request",
            template_id="simple-scan",
            template_inputs={
                "subject": {
                    "kind": "entity",
                    "entity_id": "q0",
                    "entity_kind": "qubit",
                    "metadata": {"chip": "sample-a"},
                },
                "settings": {"averages": 128},
            },
            config_source="active",
            operator="alice",
            scans=[
                PointScanRecord(
                    target_id="drive_frequency",
                    axis_id="drive_frequency",
                    values=[4.9, 5.0, 5.1],
                    unit="GHz",
                )
            ],
            segment_lineage={"parent_run_id": "run-parent"},
            metadata={"name": "morning scan"},
        ),
    )


def test_registration_identity_must_match_descriptor() -> None:
    descriptor = _descriptor()

    with pytest.raises(ValueError, match="must match"):
        RegisteredExperiment(
            id="another-id",
            version=descriptor.version,
            descriptor=descriptor,
            factory=lambda _request: load_invocation(),
        )


def test_catalog_revision_is_canonical_and_excludes_factories() -> None:
    first = _registration(_descriptor(id="z-last"), lambda _request: load_invocation())
    second = _registration(
        _descriptor(id="a-first"),
        lambda _request: PreparedInvocation(
            load_invocation(),
            InvocationRequestContext(id="factory-context", template_id=None),
        ),
    )

    catalog = RegisteredExperimentCatalog((first, second))
    reordered = RegisteredExperimentCatalog(
        (
            _registration(second.descriptor, lambda _request: load_invocation()),
            _registration(first.descriptor, lambda _request: load_invocation()),
        )
    )

    assert catalog.revision == reordered.revision
    assert catalog.snapshot == reordered.snapshot
    assert tuple(item.id for item in catalog.snapshot.experiments) == (
        "a-first",
        "z-last",
    )
    assert "factory" not in catalog.snapshot.model_dump_json()

    changed = RegisteredExperimentCatalog(
        (_registration(_descriptor(id="a-first", title="Changed")), first)
    )
    assert changed.revision != catalog.revision


def test_catalog_rejects_duplicate_identity_and_requires_exact_lookup() -> None:
    registration = _registration(_descriptor())

    with pytest.raises(ValueError, match="unique"):
        RegisteredExperimentCatalog((registration, registration))

    catalog = RegisteredExperimentCatalog((registration,))
    assert catalog.lookup("simple-scan", "1") is registration
    with pytest.raises(KeyError, match="was not found"):
        catalog.lookup("simple-scan", "2")


@pytest.mark.parametrize("return_prepared", [False, True])
def test_prepare_uses_exact_registration_and_submission_request_context(
    *,
    return_prepared: bool,
) -> None:
    received: list[RunRequest] = []

    def factory(
        request: RunRequest,
    ) -> ExperimentInvocation | PreparedInvocation:
        received.append(request)
        invocation = load_invocation()
        if return_prepared:
            return PreparedInvocation(
                invocation,
                InvocationRequestContext(
                    id="factory-context-is-replaced",
                    template_id=None,
                    metadata={"factory": True},
                ),
            )
        return invocation

    catalog = RegisteredExperimentCatalog((_registration(_descriptor(), factory),))
    submission = _submission()

    prepared = catalog.prepare(submission)

    assert received == [submission.request]
    assert prepared.invocation is not None
    assert prepared.request_context.id == submission.request.id
    assert prepared.request_context.template_id == submission.request.template_id
    assert dict(prepared.request_context.template_inputs) == {
        "subject": {
            "kind": "entity",
            "entity_id": "q0",
            "entity_kind": "qubit",
            "metadata": {"chip": "sample-a"},
        },
        "settings": {"averages": 128},
    }
    assert prepared.request_context.scans == tuple(submission.request.scans)
    assert prepared.request_context.operator == "alice"
    assert dict(prepared.request_context.metadata) == {"name": "morning scan"}
