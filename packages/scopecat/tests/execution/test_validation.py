from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.execution.local.program import (
    CollectionResultBinding,
    CollectOperation,
)
from scopecat.execution.local.validation import validate_local_effect_block_instruments
from scopecat.execution.points import RunPoint
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import product_id, product_use
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.results import MeasurementDType
from scopecat.sdk.instruments.contracts import (
    CapabilityDescription,
    CollectCommand,
    CollectProductRequest,
    InstrumentDescription,
    capability,
    product,
)
from tests.testkit.local_materialization import (
    LocalEffectInspection,
    effects_at_point,
)


def _validate(
    program: LocalEffectInspection,
    *,
    descriptions: dict[str, InstrumentDescription],
):
    return validate_local_effect_block_instruments(
        resource_order=program.resource_order,
        operations=tuple(effect.operation for effect in program.effects),
        descriptions=descriptions,
        available_payloads={},
    )


@pytest.mark.parametrize(
    "payload",
    (
        {"id": "signal"},
        {"id": "signal", "capability_id": ""},
    ),
)
def test_collect_product_request_requires_non_empty_capability_id(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CollectProductRequest.model_validate(payload)


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

    problems = _validate(
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

    problems = _validate(
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
    assert "under capability 'readout'" in problem.message


def _collect_program(
    *,
    capability_id: str,
    dtype: MeasurementDType,
) -> LocalEffectInspection:
    operation_id = "point-0.collect.source-0"
    signal_use = product_use(product_id("signal"))
    return LocalEffectInspection(
        points=(
            RunPoint(
                logical_id=LogicalPointId(PointDomainId("product-lookup", "root"), 0),
                coordinates={},
            ),
        ),
        effects=effects_at_point(
            0,
            (
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
                            product_use_ids=(signal_use.id,),
                            product_id=signal_use.product_id,
                        ),
                    ),
                ),
            ),
        ),
        resource_order=("source-0",),
        resource_claims=(ResourceClaim(id="source-0"),),
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
