from __future__ import annotations

import pytest
from scopecat_testkit.payload_codecs import json_payload_codecs

from scopecat.execution.local.program import ComputeOperation, PayloadSlot
from scopecat.execution.program import RunHostBinding
from scopecat.kernel.errors import ProviderContractError
from scopecat.kernel.problems import model_location
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.planning.provider_binding import validate_run_host_binding
from scopecat.program.value_graph import ComputeOutput, OperationId, operation_result_id


def _compute_operation(name: str, *, materializes_payload: bool) -> ComputeOperation:
    operation_id = f"point.compute.{name}"
    return ComputeOperation(
        operation_id=operation_id,
        logical_compute_node_id=name,
        implementation_id=f"tests.{name}",
        kernel=lambda: {"program": name},
        inputs={},
        result=ComputeOutput(
            id=operation_result_id(OperationId(SymbolId(local_id=name))),
            value_type=Scalar(Payload("tests.program/v1")),
        ),
        payload_slot=(
            PayloadSlot(
                id=f"{operation_id}.payload",
                schema_id="tests.program/v1",
            )
            if materializes_payload
            else None
        ),
    )


def test_host_contract_requires_one_codec_per_materialized_payload_schema() -> None:
    first = _compute_operation("first", materializes_payload=True)
    repeated = _compute_operation("repeated", materializes_payload=True)
    transient = _compute_operation("transient", materializes_payload=False)
    host = RunHostBinding(
        resource_order=(),
        provider_id="tests.provider",
        advertised_descriptions={},
    )

    with pytest.raises(ProviderContractError) as captured:
        validate_run_host_binding(
            host=host,
            effect_blocks=((first, repeated, transient),),
            problems=(),
        )

    [problem] = captured.value.problems
    assert problem.code == "payload_codec_missing"
    assert problem.location == model_location(
        "execution_program",
        "operations",
        first.operation_id,
        "payload_slot",
        "schema_id",
    )

    registered = RunHostBinding(
        resource_order=(),
        provider_id=host.provider_id,
        advertised_descriptions={},
        payload_codecs=json_payload_codecs("tests.program/v1"),
    )
    assert (
        validate_run_host_binding(
            host=registered,
            effect_blocks=((first, repeated, transient),),
            problems=(),
        )
        is registered
    )
