from __future__ import annotations

from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from scopecat.automation import (
    ProcedureFunction,
    ProcedureRegistry,
    procedure,
)
from scopecat.automation.models import ProcedureDefinitionRef, procedure_intent_hash


class DragIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    qubit_id: str
    points: int = 5


class WiderDragIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    qubit_id: str
    points: int = 5
    repetitions: int = 1


class OtherIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    qubit_id: str


class MutableIntent(BaseModel):
    qubit_id: str


_DEFAULT_INTENT = DragIntent(qubit_id="q0")


def record_drag(context: object, intent: DragIntent) -> None:
    cast("list[DragIntent]", context).append(intent)


def record_drag_differently(context: object, intent: DragIntent) -> None:
    selected = cast("list[DragIntent]", context)
    selected.extend((intent, intent))


def record_wider_drag(context: object, intent: WiderDragIntent) -> None:
    del context, intent


def wrong_arity(intent: DragIntent) -> None:
    del intent


def defaulted_context(
    context: object = None,
    intent: DragIntent = _DEFAULT_INTENT,
) -> None:
    del context, intent


def wrong_intent(context: object, intent: OtherIntent) -> None:
    del context, intent


def undeclared_return(context: object, intent: DragIntent):
    del context, intent


def non_none_return(context: object, intent: DragIntent) -> str:
    del context, intent
    return "done"


async def asynchronous(context: object, intent: DragIntent) -> None:
    del context, intent


def mutable_intent(context: object, intent: MutableIntent) -> None:
    del context, intent


DRAG = procedure(
    id="reference-lab.drag-beta",
    version="1",
    intent=DragIntent,
)(record_drag)
DRAG_V2 = procedure(
    id="reference-lab.drag-beta",
    version="2",
    intent=DragIntent,
)(record_drag)
OTHER = procedure(
    id="reference-lab.other",
    version="1",
    intent=DragIntent,
)(record_drag)


def test_procedure_decorator_builds_versioned_typed_definition() -> None:
    assert DRAG.id == "reference-lab.drag-beta"
    assert DRAG.version == "1"
    assert DRAG.intent_type is DragIntent
    assert DRAG.__wrapped__ is record_drag
    assert DRAG.__name__ == "record_drag"
    assert DRAG.ref == ProcedureDefinitionRef(
        id=DRAG.id,
        version=DRAG.version,
        fingerprint=DRAG.fingerprint,
    )


def test_procedure_normalizes_validates_hashes_and_runs_typed_intent() -> None:
    encoded = DRAG.encode_intent({"qubit_id": "q0"})
    observed: list[DragIntent] = []

    DRAG(observed, encoded)

    assert encoded == {"qubit_id": "q0", "points": 5}
    assert DRAG.intent_hash(encoded) == procedure_intent_hash(DRAG.ref, encoded)
    assert observed == [DragIntent(qubit_id="q0")]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DRAG.encode_intent({"qubit_id": "q0", "unknown": True})


def test_procedure_fingerprint_covers_version_schema_and_implementation() -> None:
    same = procedure(
        id=DRAG.id,
        version=DRAG.version,
        intent=DragIntent,
    )(record_drag)
    changed_implementation = procedure(
        id=DRAG.id,
        version=DRAG.version,
        intent=DragIntent,
    )(record_drag_differently)
    changed_schema = procedure(
        id=DRAG.id,
        version=DRAG.version,
        intent=WiderDragIntent,
    )(record_wider_drag)

    assert same.fingerprint == DRAG.fingerprint
    assert DRAG_V2.fingerprint != DRAG.fingerprint
    assert changed_implementation.fingerprint != DRAG.fingerprint
    assert changed_schema.fingerprint != DRAG.fingerprint


@pytest.mark.parametrize(
    "definition,match",
    [
        (wrong_arity, "exactly"),
        (defaulted_context, "exactly"),
        (wrong_intent, "intent annotation"),
        (undeclared_return, "None return"),
        (non_none_return, "None return"),
        (asynchronous, "synchronous"),
    ],
)
def test_procedure_rejects_functions_outside_the_worker_contract(
    definition: object,
    match: str,
) -> None:
    with pytest.raises(TypeError, match=match):
        procedure(
            id="tests.invalid",
            version="1",
            intent=DragIntent,
        )(cast("ProcedureFunction", definition))


@pytest.mark.parametrize("id,version", [("", "1"), ("tests.drag", "  ")])
def test_procedure_rejects_empty_definition_identity(id: str, version: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        procedure(id=id, version=version, intent=DragIntent)(record_drag)


def test_procedure_requires_immutable_intent_model() -> None:
    with pytest.raises(TypeError, match="frozen=True"):
        procedure(
            id="tests.mutable-intent",
            version="1",
            intent=MutableIntent,
        )(mutable_intent)


def test_registry_resolves_exact_versions_and_fingerprints() -> None:
    registry = ProcedureRegistry((DRAG_V2, OTHER, DRAG))

    assert tuple(registry) == (
        ("reference-lab.drag-beta", "1"),
        ("reference-lab.drag-beta", "2"),
        ("reference-lab.other", "1"),
    )
    assert registry[(DRAG.id, DRAG.version)] is DRAG
    assert registry.require(DRAG_V2.id, DRAG_V2.version) is DRAG_V2
    assert registry.resolve(DRAG.ref) is DRAG
    assert registry.refs == (DRAG.ref, DRAG_V2.ref, OTHER.ref)

    mismatched = DRAG.ref.model_copy(update={"fingerprint": f"sha256:{'f' * 64}"})
    with pytest.raises(ValueError, match="fingerprint"):
        registry.resolve(mismatched)
    with pytest.raises(LookupError, match="no procedure"):
        registry.require(DRAG.id, "missing")


def test_registry_rejects_duplicate_exact_version() -> None:
    with pytest.raises(ValueError, match="registered more than once"):
        ProcedureRegistry((DRAG, DRAG))
