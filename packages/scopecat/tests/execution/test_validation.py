from __future__ import annotations

import pytest
from pydantic import ValidationError
from scopecat_testkit.local_materialization import (
    LocalEffectInspection,
    effects_at_point,
)

from scopecat.execution.local.program import (
    CollectionResultBinding,
    CollectOperation,
    ResourceProvenance,
)
from scopecat.execution.local.validation import validate_local_effect_block_instruments
from scopecat.execution.persistence import validate_run_measurements
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.points import AcceptedRunPoint
from scopecat.kernel.product_identity import product_id, product_use
from scopecat.kernel.resource_identity import (
    DEFAULT_RESOURCE_ROLE,
    ResourceRequirement,
    logical_resource_port_id,
)
from scopecat.program.measurement_types import MeasurementDType
from scopecat.records.measurement import MeasurementRecord
from scopecat.sdk.instruments.commands import (
    CollectCommand,
    CollectResultRequest,
)
from scopecat.sdk.instruments.contracts import (
    InstrumentDescription,
    InterfaceSpec,
    acquisition,
    acquisition_result,
    interface,
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
        {"id": "signal", "interface_id": ""},
    ),
)
def test_collect_result_request_requires_complete_interface_identity(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CollectResultRequest.model_validate(payload)


def test_explicit_collect_interface_selects_one_matching_result() -> None:
    program = _collect_program(interface_id="test.spectrum/v1", dtype="int64")
    description = _description(
        interfaces=(
            interface(
                "test.readout/v1",
                acquisitions=(
                    acquisition(
                        "sample",
                        results=(acquisition_result("signal", dtype="float64"),),
                    ),
                ),
            ),
            interface(
                "test.spectrum/v1",
                acquisitions=(
                    acquisition(
                        "sample",
                        results=(acquisition_result("signal", dtype="int64"),),
                    ),
                ),
            ),
        )
    )

    problems = _validate(
        program,
        descriptions={"source-0": description},
    )

    assert problems == []


def test_duplicate_result_id_within_acquisition_is_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match="acquisition result ids must be unique",
    ):
        acquisition(
            "sample",
            results=(
                acquisition_result("signal"),
                acquisition_result("signal"),
            ),
        )


def test_run_measurements_have_expected_unique_points_and_values() -> None:
    records = [
        MeasurementRecord(
            run_id="run-1",
            point_index=1,
            coordinates={},
            observables={},
        )
        for _ in range(2)
    ]

    problems = validate_run_measurements(
        measurements=records,
        expected_indices={0},
    )

    assert [item.code for item in problems] == [
        "execution_plan_measurement_point_unknown",
        "execution_plan_measurement_values_missing",
        "execution_plan_measurement_point_duplicate",
        "execution_plan_measurement_point_unknown",
        "execution_plan_measurement_values_missing",
    ]


def _collect_program(
    *,
    interface_id: str,
    dtype: MeasurementDType,
) -> LocalEffectInspection:
    operation_id = "point-0.collect.source-0"
    signal_use = product_use(product_id("signal"))
    return LocalEffectInspection(
        points=(
            AcceptedRunPoint(
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
                    resource=ResourceProvenance(
                        logical_port_id=logical_resource_port_id("source-0"),
                        requested_role=DEFAULT_RESOURCE_ROLE,
                        route_id="source-0",
                        route_role_id=None,
                    ),
                    command=CollectCommand(
                        command_id=operation_id,
                        instrument_id="source-0",
                        point_index=0,
                        point_count=1,
                        requests=[
                            CollectResultRequest(
                                id="signal",
                                interface_id=interface_id,
                                acquisition_id="sample",
                                result_id="signal",
                                dtype=dtype,
                            )
                        ],
                    ),
                    result_bindings=(
                        CollectionResultBinding(
                            request_id="signal",
                            product_use_ids=(signal_use.id,),
                        ),
                    ),
                ),
            ),
        ),
        resource_order=("source-0",),
        resource_requirements=(ResourceRequirement(id="source-0"),),
    )


def _description(
    *,
    interfaces: tuple[InterfaceSpec, ...],
) -> InstrumentDescription:
    return InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.product_lookup",
        implementation_version="v1",
        interfaces=list(interfaces),
    )
