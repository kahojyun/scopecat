from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import cast

import pytest

from scopecat.adapters.memory import MemoryCollectionRepository
from scopecat.execution.local.collection_values import (
    BoundLocalCollectionValues,
    bind_local_collection_values,
    local_collection_value_candidates,
)
from scopecat.execution.local.program import (
    ActionStage,
    ApplyStateOperation,
    ApplyStateStage,
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    InstrumentActionOperation,
    PointProgram,
    StateTarget,
)
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.product_identity import ProductUse
from scopecat.kernel.state import StateValue
from scopecat.measurements.results import CoordinateValue
from scopecat.measurements.values import (
    SelectedMeasurementValues,
    seal_measurement_values,
    select_measurement_values,
)
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
)
from scopecat.records.instrument import InstrumentReadback
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments.contracts import (
    CollectCommand,
    CollectProductRequest,
)
from tests.testkit.local_effect_program import StubLocalEffectProgram
from tests.testkit.measurement_assembly import (
    MeasurementAssemblyScenario,
    measurement_assembly_scenario,
)

_RUN_ID = "local-collection-run"
_INSTRUMENT_ID = "local-source-0"
_PROVIDER_KEY = "raw"


def _selection(
    scenario: MeasurementAssemblyScenario,
) -> SelectedMeasurementValues:
    return select_measurement_values(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in scenario.uses),
    )


def _local_selection(
    scenario: MeasurementAssemblyScenario,
) -> SelectedMeasurementValues:
    return select_measurement_values(
        scenario.linked_points,
        required_product_use_ids=(scenario.uses[0].id,),
    )


def _program(
    scenario: MeasurementAssemblyScenario, *, collected_use: ProductUse
) -> StubLocalEffectProgram:
    points = scenario.linked_points.point_domain.points
    coordinate_ids = scenario.linked_points.linked_plan.coordinate_ids
    return StubLocalEffectProgram(
        experiment_id=scenario.linked_points.linked_plan.program.id,
        points=tuple(
            PointProgram(
                point_index=point.logical_ordinal,
                point_uid=point.logical_id.value,
                coordinates=cast(
                    "dict[str, CoordinateValue]",
                    {name: point.row[name] for name in coordinate_ids},
                ),
                stages=(
                    CollectStage(
                        operations=(
                            _operation(
                                collected_use,
                                point_uid=point.logical_id.value,
                                point_index=point.logical_ordinal,
                                point_count=len(points),
                            ),
                        )
                    ),
                ),
            )
            for point in points
        ),
        product_uses=scenario.uses,
        collection_product_use_ids=(collected_use.id,),
        resource_order=(_INSTRUMENT_ID,) if points else (),
        resource_claims=(ResourceClaim(id=_INSTRUMENT_ID),) if points else (),
    )


def _operation(
    collected_use: ProductUse,
    *,
    point_uid: str,
    point_index: int,
    point_count: int,
) -> CollectOperation:
    operation_id = f"{point_uid}.collect.{_INSTRUMENT_ID}"
    return CollectOperation(
        operation_id=operation_id,
        instrument_id=_INSTRUMENT_ID,
        command=CollectCommand(
            operation_id=operation_id,
            instrument_id=_INSTRUMENT_ID,
            point_index=point_index,
            point_count=point_count,
            requests=[
                CollectProductRequest(
                    id=_PROVIDER_KEY,
                    unit="ratio",
                    dtype="float64",
                    metadata={"provider-address": "must-not-escape"},
                )
            ],
        ),
        result_bindings=(
            CollectionResultBinding(
                provider_key=_PROVIDER_KEY,
                product_use_id=collected_use.id,
                product_id=collected_use.product_id,
            ),
        ),
    )


def _bound(
    *,
    point_values: tuple[float, ...] = (0.0, 1.0),
) -> tuple[
    MeasurementAssemblyScenario,
    StubLocalEffectProgram,
    BoundLocalCollectionValues,
]:
    scenario = measurement_assembly_scenario(point_values=point_values, use_count=2)
    program = _program(scenario, collected_use=scenario.uses[0])
    return (
        scenario,
        program,
        bind_local_collection_values(
            _selection(scenario),
            (scenario.uses[0].id,),
            program,
        ),
    )


def _chunks(
    program: StubLocalEffectProgram,
    *,
    run_id: str = _RUN_ID,
) -> tuple[CollectionChunk, ...]:
    return tuple(
        CollectionChunk(
            run_id=run_id,
            operation_id=operation.operation_id,
            command_content_hash=stable_content_hash(
                operation.command.model_dump(mode="json", warnings=False)
            ),
            attempt=operation.command.attempt,
            point_index=point.point_index,
            instrument_id=operation.instrument_id,
            readback=InstrumentReadback(
                values={
                    _PROVIDER_KEY: Quantity(
                        value=float(point.point_index + 1),
                        unit="ratio",
                    )
                },
                metadata={"readback-address": operation.operation_id},
            ),
        )
        for point in program.points
        for stage in point.stages
        if isinstance(stage, CollectStage)
        for operation in stage.operations
    )


def _committed(
    chunks: Sequence[CollectionChunk],
) -> tuple[MemoryCollectionRepository, tuple[CollectionChunkReceipt, ...]]:
    repository = MemoryCollectionRepository()
    return (
        repository,
        tuple(repository.commit(chunk) for chunk in chunks),
    )


def _replace_first_operation(
    program: StubLocalEffectProgram,
    operation: CollectOperation,
) -> StubLocalEffectProgram:
    point = program.points[0]
    stage = next(stage for stage in point.stages if isinstance(stage, CollectStage))
    replacement_stage = replace(stage, operations=(operation,))
    replacement_point = replace(
        point,
        stages=tuple(
            replacement_stage if item is stage else item for item in point.stages
        ),
    )
    return replace(program, points=(replacement_point, *program.points[1:]))


def _problem_codes(error: CheckFailed | ProviderContractError) -> set[str]:
    return {problem.code for problem in error.problems}


def test_binding_rejects_foreign_experiment_before_effects() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    program = replace(
        _program(scenario, collected_use=scenario.uses[0]),
        experiment_id="foreign-experiment",
    )

    with pytest.raises(CheckFailed) as captured:
        bind_local_collection_values(
            _selection(scenario),
            (scenario.uses[0].id,),
            program,
        )

    assert "local_collection_experiment_mismatch" in _problem_codes(captured.value)


def test_binding_rejects_wrong_point_coordinates_before_effects() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    program = _program(scenario, collected_use=scenario.uses[0])
    point = program.points[0]
    bad_point = replace(point, coordinates={"x": 999.0})
    bad_program = replace(program, points=(bad_point, *program.points[1:]))

    with pytest.raises(CheckFailed) as captured:
        bind_local_collection_values(
            _selection(scenario),
            (scenario.uses[0].id,),
            bad_program,
        )

    assert "local_collection_point_coordinates_mismatch" in _problem_codes(
        captured.value
    )


def test_binding_ignores_non_collection_state_and_action_stages() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    program = _program(scenario, collected_use=scenario.uses[0])
    point = program.points[0]
    apply_state = ApplyStateStage(
        operations=(
            ApplyStateOperation(
                operation_id=f"{point.point_uid}.state.{_INSTRUMENT_ID}",
                instrument_id=_INSTRUMENT_ID,
                targets=(
                    StateTarget(
                        capability_id="set_gain",
                        field_path="gain",
                        value=StateValue(1.0),
                    ),
                ),
            ),
        )
    )
    action = ActionStage(
        operations=(
            InstrumentActionOperation(
                operation_id=f"{point.point_uid}.action.{_INSTRUMENT_ID}",
                instrument_id=_INSTRUMENT_ID,
                capability_id="trigger",
            ),
        )
    )
    point_with_effects = replace(
        point,
        stages=(apply_state, action, *point.stages),
    )
    program_with_effects = replace(
        program,
        points=(point_with_effects, *program.points[1:]),
    )

    binding = bind_local_collection_values(
        _selection(scenario),
        (scenario.uses[0].id,),
        program_with_effects,
    )

    assert tuple(
        operation.operation_id for operation in binding.operation_bindings
    ) == tuple(
        operation.operation_id
        for point_program in program.points
        for stage in point_program.stages
        if isinstance(stage, CollectStage)
        for operation in stage.operations
    )


def test_binding_rejects_wrong_point_identity_before_effects() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    program = _program(scenario, collected_use=scenario.uses[0])
    bad_point = replace(program.points[0], point_uid="foreign-point")
    bad_program = replace(program, points=(bad_point, *program.points[1:]))

    with pytest.raises(CheckFailed) as captured:
        bind_local_collection_values(
            _selection(scenario),
            (scenario.uses[0].id,),
            bad_program,
        )

    assert "local_collection_point_identity_mismatch" in _problem_codes(captured.value)


def test_binding_rejects_wrong_request_contract_before_effects() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    program = _program(scenario, collected_use=scenario.uses[0])
    operation = cast("CollectStage", program.points[0].stages[0]).operations[0]
    request = operation.command.requests[0].model_copy(update={"dtype": "int64"})
    command = operation.command.model_copy(update={"requests": [request]})
    bad_program = _replace_first_operation(
        program,
        replace(operation, command=command),
    )

    with pytest.raises(CheckFailed) as captured:
        bind_local_collection_values(
            _selection(scenario),
            (scenario.uses[0].id,),
            bad_program,
        )

    assert "local_collection_request_contract_mismatch" in _problem_codes(
        captured.value
    )


def test_binding_rechecks_mutated_runtime_owned_attempt_before_effects() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    program = _program(scenario, collected_use=scenario.uses[0])
    operation = cast("CollectStage", program.points[0].stages[0]).operations[0]
    operation.command.attempt = 2

    with pytest.raises(CheckFailed) as captured:
        bind_local_collection_values(
            _selection(scenario),
            (scenario.uses[0].id,),
            program,
        )

    assert "local_collection_command_contract_mismatch" in _problem_codes(
        captured.value
    )


def test_binding_requires_requested_values_to_equal_collection_inventory() -> None:
    scenario = measurement_assembly_scenario(use_count=2)
    program = _program(scenario, collected_use=scenario.uses[1])

    with pytest.raises(CheckFailed) as captured:
        bind_local_collection_values(
            _selection(scenario),
            (scenario.uses[0].id,),
            program,
        )

    assert "local_collection_result_use_unexpected" in _problem_codes(captured.value)


def test_runtime_receipt_order_is_canonical_and_value_entries_are_neutral() -> None:
    scenario, program, binding = _bound()
    chunks = _chunks(program)
    repository, receipts = _committed(chunks)
    candidates = local_collection_value_candidates(
        binding,
        run_id=_RUN_ID,
        repository=repository,
        receipts=tuple(reversed(receipts)),
    )

    values = seal_measurement_values(_local_selection(scenario), candidates)
    assert tuple(value.logical_point_id for value in values.values) == tuple(
        point.logical_id for point in scenario.linked_points.point_domain.points
    )
    rendered = repr(
        tuple(
            (
                value.logical_point_id,
                value.product_use_id,
                value.product_id,
                value.value,
            )
            for value in values.values
        )
    )
    assert _RUN_ID not in rendered
    assert _INSTRUMENT_ID not in rendered
    assert _PROVIDER_KEY not in rendered
    assert "readback-address" not in rendered


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("run_id", "foreign-run", "local_collection_chunk_run_mismatch"),
        ("attempt", 2, "local_collection_chunk_attempt_mismatch"),
        ("point_index", 99, "local_collection_chunk_point_mismatch"),
        (
            "instrument_id",
            "foreign-instrument",
            "local_collection_chunk_instrument_mismatch",
        ),
    ),
)
def test_runtime_rejects_wrong_chunk_identity(
    field: str,
    value: str | int,
    code: str,
) -> None:
    _scenario_value, program, binding = _bound()
    chunks = list(_chunks(program))
    chunks[0] = chunks[0].model_copy(update={field: value})
    repository, receipts = _committed(chunks)

    with pytest.raises(ProviderContractError) as captured:
        local_collection_value_candidates(
            binding,
            run_id=_RUN_ID,
            repository=repository,
            receipts=receipts,
        )

    assert code in _problem_codes(captured.value)


@pytest.mark.parametrize("mode", ("missing", "duplicate", "extra"))
def test_runtime_requires_exact_commit_receipt_inventory(mode: str) -> None:
    _scenario_value, program, binding = _bound()
    chunks = _chunks(program)
    repository, committed_receipts = _committed(chunks)
    receipts: Sequence[CollectionChunkReceipt] = committed_receipts
    if mode == "missing":
        receipts = receipts[1:]
        expected = "local_collection_receipt_missing"
    elif mode == "duplicate":
        receipts = (*receipts, receipts[0])
        expected = "local_collection_receipt_duplicate"
    else:
        unexpected_chunk = chunks[0].model_copy(
            update={"operation_id": "unexpected-operation"}
        )
        receipts = (
            *receipts,
            repository.commit(unexpected_chunk),
        )
        expected = "local_collection_receipt_unexpected"

    with pytest.raises(ProviderContractError) as captured:
        local_collection_value_candidates(
            binding,
            run_id=_RUN_ID,
            repository=repository,
            receipts=receipts,
        )

    assert expected in _problem_codes(captured.value)


def test_runtime_rejects_forged_unbacked_receipt() -> None:
    _scenario_value, program, binding = _bound()
    chunks = _chunks(program)
    repository, committed_receipts = _committed(chunks)
    receipts = list(committed_receipts)
    receipts[0] = receipts[0].model_copy(update={"content_hash": "foreign-chunk"})

    with pytest.raises(ProviderContractError) as captured:
        local_collection_value_candidates(
            binding,
            run_id=_RUN_ID,
            repository=repository,
            receipts=receipts,
        )

    assert "local_collection_receipt_unresolvable" in _problem_codes(captured.value)


def test_runtime_rejects_command_mutation_after_binding() -> None:
    _scenario_value, program, binding = _bound()
    operation = cast("CollectStage", program.points[0].stages[0]).operations[0]
    operation.command.metadata["mutated-after-binding"] = True
    chunks = _chunks(program)
    repository, receipts = _committed(chunks)

    with pytest.raises(ProviderContractError) as captured:
        local_collection_value_candidates(
            binding,
            run_id=_RUN_ID,
            repository=repository,
            receipts=receipts,
        )

    assert "local_collection_chunk_command_mismatch" in _problem_codes(captured.value)


def test_runtime_rejects_wrong_readback_key_inventory() -> None:
    _scenario_value, program, binding = _bound()
    chunks = list(_chunks(program))
    chunks[0] = chunks[0].model_copy(
        update={
            "readback": InstrumentReadback(
                values={"unexpected": Quantity(value=1.0, unit="ratio")}
            )
        }
    )
    repository, receipts = _committed(chunks)

    with pytest.raises(ProviderContractError) as captured:
        local_collection_value_candidates(
            binding,
            run_id=_RUN_ID,
            repository=repository,
            receipts=receipts,
        )

    assert "local_collection_chunk_readback_inventory_mismatch" in _problem_codes(
        captured.value
    )


def test_runtime_rechecks_logical_measurement_value_contract() -> None:
    _scenario_value, program, binding = _bound()
    chunks = list(_chunks(program))
    chunks[0] = chunks[0].model_copy(
        update={
            "readback": InstrumentReadback(
                values={_PROVIDER_KEY: Quantity(value=1.0, unit="V")}
            )
        }
    )
    repository, receipts = _committed(chunks)

    with pytest.raises(ProviderContractError) as captured:
        seal_measurement_values(
            _local_selection(_scenario_value),
            local_collection_value_candidates(
                binding,
                run_id=_RUN_ID,
                repository=repository,
                receipts=receipts,
            ),
        )

    assert "measurement_value_unit_mismatch" in _problem_codes(captured.value)


def test_zero_point_collection_retains_contract_without_chunks() -> None:
    scenario, program, binding = _bound(point_values=())
    repository = MemoryCollectionRepository()

    candidates = local_collection_value_candidates(
        binding,
        run_id=_RUN_ID,
        repository=repository,
        receipts=(),
    )

    assert not program.points
    assert candidates == ()
    assert binding.collection_product_use_ids == (scenario.uses[0].id,)
