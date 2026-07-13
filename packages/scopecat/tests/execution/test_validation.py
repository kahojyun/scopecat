from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.execution.local.program import (
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    ExecutionProgram,
    PointProgram,
    RecordProjection,
)
from scopecat.execution.local.validation import validate_execution_program_instruments
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import product_id, product_use
from scopecat.measurements.results import MeasurementDType
from scopecat.sdk.instruments.contracts import (
    CapabilityDescription,
    CollectCommand,
    CollectProductRequest,
    InstrumentDescription,
    capability,
    product,
)


def test_unspecified_collect_capability_rejects_ambiguous_product_key() -> None:
    program = _collect_program(capability_id=None, dtype="float64")
    description = _description(
        capabilities=(
            capability("readout", products=(product("signal"),)),
            capability("spectrum", products=(product("signal"),)),
        )
    )

    problems = validate_execution_program_instruments(
        program,
        descriptions={"source-0": description},
    )

    assert len(problems) == 1
    problem = problems[0]
    assert problem.code == "instrument_product_ambiguous"
    assert problem.impact is ProblemImpact.BLOCKING
    assert problem.category is ProblemCategory.PROVIDER_CONTRACT
    assert problem.phase is ProblemPhase.PROVIDER_PREFLIGHT
    assert problem.location == model_location(
        "execution_program",
        "operations",
        "point-0.collect.source-0",
        "requests",
        "signal",
        "capability_id",
    )
    assert "'readout', 'spectrum'" in problem.message


def test_explicit_collect_capability_selects_one_matching_product() -> None:
    program = _collect_program(capability_id="spectrum", dtype="int64")
    description = _description(
        capabilities=(
            capability(
                "readout",
                products=(product("signal", dtype="float64"),),
            ),
            capability(
                "spectrum",
                products=(product("signal", dtype="int64"),),
            ),
        )
    )

    problems = validate_execution_program_instruments(
        program,
        descriptions={"source-0": description},
    )

    assert problems == []


def test_duplicate_product_key_within_selected_capability_is_ambiguous() -> None:
    program = _collect_program(capability_id="readout", dtype="float64")
    description = _description(
        capabilities=(
            capability(
                "readout",
                products=(product("signal"), product("signal")),
            ),
        )
    )

    problems = validate_execution_program_instruments(
        program,
        descriptions={"source-0": description},
    )

    assert [problem.code for problem in problems] == ["instrument_product_ambiguous"]
    assert "'readout', 'readout'" in problems[0].message


def test_execution_program_rejects_binding_product_identity_mismatch() -> None:
    program = _collect_program(capability_id=None, dtype="float64")
    point = program.points[0]
    stage = point.stages[0]
    assert isinstance(stage, CollectStage)
    operation = stage.operations[0]
    binding = replace(
        operation.result_bindings[0],
        product_id=product_id("another-product"),
    )
    mutated = replace(operation, result_bindings=(binding,))

    with pytest.raises(ValueError, match="exact logical product uses"):
        replace(
            program,
            points=(replace(point, stages=(replace(stage, operations=(mutated,)),)),),
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"point_index": 1}, "point index"),
        ({"point_count": 2}, "point count"),
    ),
)
def test_execution_program_rejects_collect_command_point_mismatch(
    updates: dict[str, int],
    message: str,
) -> None:
    program = _collect_program(capability_id=None, dtype="float64")
    point = program.points[0]
    stage = point.stages[0]
    assert isinstance(stage, CollectStage)
    operation = stage.operations[0]
    mutated = replace(
        operation,
        command=operation.command.model_copy(update=updates),
    )

    with pytest.raises(ValueError, match=message):
        replace(
            program,
            points=(replace(point, stages=(replace(stage, operations=(mutated,)),)),),
        )


def test_collect_operation_rejects_command_identity_mismatch() -> None:
    program = _collect_program(capability_id=None, dtype="float64")
    point = program.points[0]
    stage = point.stages[0]
    assert isinstance(stage, CollectStage)
    operation = stage.operations[0]

    with pytest.raises(ValueError, match="command identity"):
        replace(
            operation,
            command=operation.command.model_copy(update={"operation_id": "wrong"}),
        )


def _collect_program(
    *,
    capability_id: str | None,
    dtype: MeasurementDType,
) -> ExecutionProgram:
    operation_id = "point-0.collect.source-0"
    signal_use = product_use(product_id("signal"))
    return ExecutionProgram(
        experiment_id="product-lookup",
        points=(
            PointProgram(
                point_index=0,
                point_uid="point-0",
                coordinates={},
                stages=(
                    CollectStage(
                        operations=(
                            CollectOperation(
                                operation_id=operation_id,
                                instrument_id="source-0",
                                command=CollectCommand(
                                    operation_id=operation_id,
                                    instrument_id="source-0",
                                    point_index=0,
                                    point_count=1,
                                    requests=[
                                        CollectProductRequest(
                                            id="signal",
                                            capability_id=capability_id,
                                            dtype=dtype,
                                        )
                                    ],
                                ),
                                result_bindings=(
                                    CollectionResultBinding(
                                        provider_key="signal",
                                        product_use_id=signal_use.id,
                                        product_id=signal_use.product_id,
                                    ),
                                ),
                            ),
                        )
                    ),
                ),
            ),
        ),
        product_uses=(signal_use,),
        collection_product_use_ids=(signal_use.id,),
        record_projections=(
            RecordProjection(
                record_id="record.signal",
                product_use_id=signal_use.id,
                product_id=signal_use.product_id,
            ),
        ),
    )


def _description(
    *,
    capabilities: tuple[CapabilityDescription, ...],
) -> InstrumentDescription:
    return InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.product_lookup",
        implementation_version="v1",
        capabilities=list(capabilities),
    )
