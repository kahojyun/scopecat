from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel, ConfigDict

from scopecat.application.lab import LabApplication
from scopecat.automation import ProcedureRegistry, procedure


class _ExampleIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: int


@procedure(
    id="tests.application.example",
    version="1",
    intent=_ExampleIntent,
)
def _example_procedure(_context: object, _intent: _ExampleIntent) -> None:
    pass


def test_application_canonicalizes_procedure_iterable() -> None:
    application = LabApplication(procedures=(_example_procedure,))

    assert isinstance(application.procedures, ProcedureRegistry)
    assert application.procedures.refs == (_example_procedure.ref,)
    assert application.procedures.resolve(_example_procedure.ref) is _example_procedure


def test_application_preserves_prebuilt_procedure_registry() -> None:
    registry = ProcedureRegistry((_example_procedure,))

    application = LabApplication(procedures=registry)
    replaced = replace(application, bootstrap_config=lambda: {"id": "bootstrap"})

    assert application.procedures is registry
    assert replaced.procedures is registry
