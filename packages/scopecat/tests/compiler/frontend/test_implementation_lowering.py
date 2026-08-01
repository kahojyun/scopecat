from __future__ import annotations

import scopecat as sc
from scopecat.compiler.frontend.elaboration import compose_module


def test_python_implementation_identity_tracks_its_declaration() -> None:
    @sc.module(id="test.impl.first")
    def first(context: sc.ModuleContext) -> None:
        context.compute(
            "produce",
            fn=lambda: 1.0,
            output_type=sc.ScalarType(sc.FloatType()),
        )

    @sc.module(id="test.impl.second")
    def second(context: sc.ModuleContext) -> None:
        context.compute(
            "produce",
            fn=lambda: 2.0,
            output_type=sc.ScalarType(sc.FloatType()),
        )

    first_program = compose_module(first.definition)
    second_program = compose_module(second.definition)

    first_id = next(iter(first_program.implementations.values())).id
    second_id = next(iter(second_program.implementations.values())).id
    assert first_id != second_id
