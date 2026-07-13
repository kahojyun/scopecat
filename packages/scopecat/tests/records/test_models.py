from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    OperationId,
    operation_result_id,
)
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    Quantity,
    ScalarParameterValue,
    SeriesParameterValue,
    TableParameterValue,
)
from scopecat.records.run_plan import (
    RunPlanChannelBinding,
    RunPlanDeferredValue,
    RunPlanDomainBatch,
    RunPlanDomainCapabilities,
    RunPlanDomainExecution,
    RunPlanExecutionOptions,
    RunPlanFusionOptions,
    RunPlanOutput,
    RunPlanPayloadValue,
    RunPlanPoint,
    RunPlanPointInstrumentExecution,
    RunPlanRecord,
    RunPlanResolvedRoute,
    RunPlanRoute,
    RunPlanStateChange,
)
from scopecat.records.run_request import (
    AroundScanRecord,
    PointScanRecord,
    RunRequest,
    RunRequestEntityRef,
    RunRequestParameterValue,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.records import assert_model_round_trip


def _valid_run_plan_data() -> dict[str, Any]:
    return {
        "backend_id": "tests.execution.v1",
        "execution_options": {
            "requested": {
                "fusion": "automatic",
                "max_points_per_batch": None,
            },
            "resolved": {
                "fusion": "disabled",
                "max_points_per_batch": 1,
            },
        },
        "experiment_id": "experiment",
        "experiment_kind": "test",
        "execution_units": [_point_execution_data()],
        "point_count": 2,
        "coordinate_ids": ["amplitude"],
        "points": [
            {
                "point_index": 0,
                "point_uid": "point-0",
                "coordinates": {"amplitude": 0.25},
            },
            {
                "point_index": 1,
                "point_uid": "point-1",
                "coordinates": {"amplitude": 0.5},
            },
        ],
        "records": [
            {
                "id": "signal",
                "kind": "observable",
                "producer_kind": "instrument",
                "producer_unit_id": "point-instrument",
                "dtype": "float64",
                "dims": ["point"],
                "shape": [2],
            }
        ],
        "state_changes": [
            {
                "point_index": 1,
                "resource_id": "source",
                "capability_id": "set_amplitude",
                "field_path": "amplitude",
                "after": 0.5,
            }
        ],
        "routes": [
            {
                "port_id": "source",
                "entity_expr_count": 0,
                "resolved": [
                    {
                        "point_index": 0,
                        "port_id": "source",
                        "resource_id": "source-0",
                        "resource_kind": "instrument",
                    },
                    {
                        "point_index": 1,
                        "port_id": "source",
                        "resource_id": "source-0",
                        "resource_kind": "instrument",
                    },
                ],
            }
        ],
        "dataset_dimensions": {"point": 2},
        "primary_observables": ["signal"],
    }


def _point_execution_data() -> dict[str, str]:
    return {
        "kind": "point_instrument",
        "unit_id": "point-instrument",
        "backend_id": "scopecat.execution.v2",
        "provider_id": "tests.signal_instrument_provider",
        "submission_scope": "point",
        "compute_placement": "host",
    }


def _valid_expected_dataset_schema_data() -> dict[str, Any]:
    return {
        "dataset_id": "raw-measurements",
        "dataset_role": "raw",
        "dimensions": [{"id": "point", "kind": "point", "size": 2}],
        "variables": [
            {
                "id": "signal",
                "role": "observable",
                "dtype": "float64",
                "dims": ["point"],
                "shape": [2],
            },
            {
                "id": "quality",
                "role": "auxiliary",
                "dtype": "bool",
                "dims": ["point"],
                "shape": [2],
            },
            {
                "id": "amplitude",
                "role": "coordinate",
                "dtype": "float64",
                "dims": ["point"],
                "shape": [2],
            },
        ],
        "primary_coordinates": ["amplitude"],
        "primary_observables": ["signal"],
    }


def test_config_profile_snapshot_round_trip() -> None:
    snapshot = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    restored = assert_model_round_trip(
        snapshot,
        schema_version="scopecat.config_profile_snapshot.v1",
    )

    assert "source" not in restored.model_dump(mode="python")
    assert restored.parameter_catalog.schema_version == "scopecat.parameter_catalog.v4"
    assert restored.parameter_snapshot.get("drive_frequency") is not None
    assert restored.topology.entity("q0") is not None
    connection = restored.connection_profile.connections[0]
    assert connection.kind == "offline"
    assert "redacted" not in connection.model_dump(mode="json")


def test_run_request_records_config_source() -> None:
    request = RunRequest(
        id="request-001",
        template_id="test.template",
        config_source="active",
    )
    restored = assert_model_round_trip(
        request,
        schema_version="scopecat.run_request.v4",
    )

    assert restored.config_source == "active"


def test_run_request_records_canonical_scans_only() -> None:
    request = RunRequest(
        id="request-001",
        scans=[
            PointScanRecord(
                target_id="drive_frequency",
                axis_id="drive_frequency",
                values=[5.0, 5.1],
                unit="GHz",
            )
        ],
    )
    restored = assert_model_round_trip(
        request,
        schema_version="scopecat.run_request.v4",
    )

    assert restored.scans == request.scans
    assert isinstance(restored.scans[0], PointScanRecord)
    assert restored.model_dump(mode="json")["scans"] == [
        {
            "kind": "point",
            "target_id": "drive_frequency",
            "axis_id": "drive_frequency",
            "values": [5.0, 5.1],
            "unit": "GHz",
        }
    ]
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "schema_version": "scopecat.run_request.v3",
                "id": "request-002",
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "id": "request-002",
                "scans": [
                    {
                        "kind": "point",
                        "target_id": "drive_frequency",
                        "axis_id": "drive_frequency",
                        "values": [5.0],
                        "input_id": "frequencies",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "id": "request-003",
                "scans": [
                    {
                        "kind": "point",
                        "target_id": "drive_frequency",
                        "axis_id": "drive_frequency",
                        "unit": "GHz",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "id": "request-004",
                "scans": [
                    {
                        "kind": "unknown",
                        "axis_id": "drive_frequency",
                    }
                ],
            }
        )


def test_run_request_values_have_a_closed_durable_domain() -> None:
    request = RunRequest.model_validate(
        {
            "id": "request-001",
            "template_inputs": {
                "subject": {
                    "kind": "entity",
                    "entity_id": "q0",
                    "entity_kind": "qubit",
                    "metadata": {},
                },
                "frequency": Quantity(value=5.0, unit="GHz"),
                "settings": {"enabled": True, "labels": ["a", "b"]},
            },
            "scans": [
                {
                    "kind": "scan",
                    "target_id": "drive_frequency",
                    "axis_id": "drive_frequency",
                    "center": {
                        "kind": "parameter",
                        "parameter_id": "drive_frequency",
                    },
                    "span": Quantity(value=100.0, unit="MHz"),
                    "points": 3,
                },
            ],
            "segment_lineage": {"parent_ids": ["run-001"]},
            "metadata": {"notebook": "02_define_experiment"},
        }
    )

    assert isinstance(request.template_inputs["subject"], RunRequestEntityRef)
    assert request.template_inputs["subject"] == RunRequestEntityRef(
        entity_id="q0",
        entity_kind="qubit",
    )
    assert request.model_dump(mode="json")["template_inputs"]["subject"] == {
        "kind": "entity",
        "entity_id": "q0",
        "entity_kind": "qubit",
        "metadata": {},
    }
    assert isinstance(request.template_inputs["frequency"], Quantity)
    scan = request.scans[0]
    assert isinstance(scan, AroundScanRecord)
    assert scan.center == RunRequestParameterValue(parameter_id="drive_frequency")
    assert scan.span == Quantity(value=100.0, unit="MHz")
    assert RunRequest.model_validate_json(request.model_dump_json()) == request


def test_run_request_does_not_guess_entities_from_business_mappings() -> None:
    request = RunRequest.model_validate(
        {
            "id": "request-001",
            "template_inputs": {"settings": {"id": "business-object"}},
        }
    )

    assert request.template_inputs["settings"] == {"id": "business-object"}
    assert request.model_dump(mode="json")["template_inputs"]["settings"] == {
        "id": "business-object"
    }


def test_run_request_does_not_duck_project_semantic_python_objects() -> None:
    class SemanticModel(BaseModel):
        value: str

    @dataclass(frozen=True)
    class SemanticDataclass:
        value: str

    values = (
        EntityRef(id="q0", kind="qubit"),
        SemanticModel(value="model"),
        SemanticDataclass(value="dataclass"),
    )

    for value in values:
        with pytest.raises(
            ValidationError,
            match="unsupported durable run request value",
        ):
            RunRequest.model_validate(
                {
                    "id": "request-001",
                    "template_inputs": {"value": value},
                }
            )


def test_run_request_symbolic_values_are_closed_and_recursive() -> None:
    center = {
        "kind": "case",
        "branches": [
            {
                "when": {
                    "kind": "binary",
                    "operator": ">",
                    "left": {"kind": "axis", "axis_id": "amplitude"},
                    "right": 0.5,
                },
                "then": {"kind": "input", "input_id": "high_frequency"},
            }
        ],
        "fallback": {
            "kind": "parameter_lookup",
            "table_id": "device_parameters",
            "key": {"subject": "q0"},
            "column": "frequency",
        },
    }
    scan = AroundScanRecord.model_validate(
        {
            "target_id": "drive_frequency",
            "axis_id": "drive_frequency",
            "center": center,
            "span": Quantity(value=100.0, unit="MHz"),
            "points": 3,
        }
    )

    assert scan.model_dump(mode="json")["center"] == center
    assert AroundScanRecord.model_validate_json(scan.model_dump_json()) == scan


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("template_inputs", {"opaque": object()}),
        ("metadata", {"opaque": object()}),
        ("segment_lineage", {"opaque": object()}),
    ],
)
def test_run_request_rejects_opaque_values_early(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=r"unsupported .*run request"):
        RunRequest.model_validate({"id": "request-001", field: value})


def test_scan_records_reject_unknown_or_structured_scalar_values() -> None:
    with pytest.raises(ValidationError):
        AroundScanRecord.model_validate(
            {
                "target_id": "drive_frequency",
                "axis_id": "drive_frequency",
                "center": {"kind": "unknown", "value": 5.0},
                "span": 1.0,
                "points": 3,
            }
        )
    with pytest.raises(ValidationError):
        PointScanRecord.model_validate(
            {
                "target_id": "drive_frequency",
                "axis_id": "drive_frequency",
                "values": [{"arbitrary": "mapping"}],
            }
        )


def test_run_plan_state_change_preserves_boolean_values() -> None:
    change = RunPlanStateChange(
        point_index=0,
        resource_id="switch-0",
        capability_id="switch",
        field_path="enabled",
        after=True,
    )

    restored = RunPlanStateChange.model_validate_json(change.model_dump_json())

    assert change.after is True
    assert restored.after is True


def test_run_plan_state_change_accepts_only_durable_descriptors() -> None:
    for value in (
        ComputeResultRef(
            value_id=operation_result_id(
                OperationId(SymbolId(local_id="build-program"))
            )
        ),
        PayloadValue(schema_id="pulse", payload=object()),
    ):
        with pytest.raises(ValidationError):
            RunPlanStateChange.model_validate(
                {
                    "point_index": 0,
                    "resource_id": "source",
                    "capability_id": "execute",
                    "field_path": "program",
                    "after": value,
                }
            )

    compute = RunPlanStateChange(
        point_index=0,
        resource_id="source",
        capability_id="execute",
        field_path="program",
        after=RunPlanDeferredValue(),
    )
    payload = RunPlanStateChange(
        point_index=0,
        resource_id="source",
        capability_id="execute",
        field_path="program",
        after=RunPlanPayloadValue(schema_id="pulse"),
    )

    assert compute.after == RunPlanDeferredValue()
    assert payload.after == RunPlanPayloadValue(schema_id="pulse")
    restored = RunPlanStateChange.model_validate_json(payload.model_dump_json())
    assert restored.after == RunPlanPayloadValue(schema_id="pulse")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_run_plan_models_reject_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValidationError):
        RunPlanPoint(
            point_index=0,
            point_uid="point-0",
            coordinates={"amplitude": value},
        )
    with pytest.raises(ValidationError):
        RunPlanStateChange(
            point_index=0,
            resource_id="source",
            capability_id="set_amplitude",
            field_path="amplitude",
            after=value,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_run_plan_models_reject_nested_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        EntityRef(id="q0", metadata={"nested": [{"value": value}]})

    for invalid_value in (Quantity(value=value, unit="GHz"),):
        with pytest.raises(ValidationError, match="finite"):
            RunPlanPoint(
                point_index=0,
                point_uid="point-0",
                coordinates={"value": invalid_value},
            )
        with pytest.raises(ValidationError, match="finite"):
            RunPlanStateChange(
                point_index=0,
                resource_id="source",
                capability_id="set_value",
                field_path="value",
                before=invalid_value,
                after=0.0,
            )
        with pytest.raises(ValidationError, match="finite"):
            RunPlanStateChange(
                point_index=0,
                resource_id="source",
                capability_id="set_value",
                field_path="value",
                after=invalid_value,
            )


def test_run_plan_nested_values_round_trip_safely() -> None:
    entity = EntityRef(
        id="q0",
        kind="qubit",
        metadata={
            "labels": ["data", "ancilla"],
            "settings": {"enabled": True, "threshold": 0.25},
        },
    )
    point = RunPlanPoint(
        point_index=0,
        point_uid="point-0",
        coordinates={"subject": entity},
    )
    change = RunPlanStateChange(
        point_index=0,
        resource_id="source",
        capability_id="set_subject",
        field_path="subject",
        before=entity,
        after=Quantity(value=5.0, unit="GHz"),
    )

    assert RunPlanPoint.model_validate_json(point.model_dump_json()) == point
    assert RunPlanStateChange.model_validate_json(change.model_dump_json()) == change

    with pytest.raises(ValidationError, match="durable JSON"):
        RunPlanPoint(
            point_index=0,
            point_uid="point-0",
            coordinates={
                "subject": EntityRef(
                    id="q0",
                    metadata={"value": object()},
                )
            },
        )

    tuple_metadata = RunPlanPoint(
        point_index=0,
        point_uid="point-0",
        coordinates={
            "subject": EntityRef(
                id="q0",
                metadata={"value": ("tuple",)},
            )
        },
    )
    assert RunPlanPoint.model_validate_json(tuple_metadata.model_dump_json()) == (
        tuple_metadata
    )


def test_entity_metadata_is_closed_finite_json_at_capture() -> None:
    entity = EntityRef(
        id="q0",
        metadata={"labels": ("data", "ancilla"), "score": 0.5},
    )

    assert entity.metadata == {
        "labels": ("data", "ancilla"),
        "score": 0.5,
    }
    assert EntityRef.model_validate_json(entity.model_dump_json()) == entity
    with pytest.raises(ValidationError, match="durable JSON"):
        EntityRef(id="q0", metadata={"value": object()})
    with pytest.raises(ValidationError, match="finite"):
        EntityRef(id="q0", metadata={"value": float("nan")})


def test_table_parameter_cells_are_closed_finite_and_round_trip_without_catalog() -> (
    None
):
    table = TableParameterValue.model_validate(
        {
            "id": "typed-values",
            "shape": "table",
            "rows": [
                {
                    "enabled": True,
                    "count": 2,
                    "gain": 0.5,
                    "label": "q0",
                    "optional": None,
                    "frequency": {"value": 5.0, "unit": "GHz"},
                    "subject": {
                        "id": "q0",
                        "kind": "logical_qubit",
                        "metadata": {"labels": ["data"]},
                    },
                }
            ],
        }
    )

    subject = table.rows[0]["subject"]
    assert isinstance(subject, EntityRef)
    assert subject.metadata == {"labels": ("data",)}
    assert TableParameterValue.model_validate_json(table.model_dump_json()) == table

    with pytest.raises(ValidationError):
        TableParameterValue(id="invalid", rows=[{"value": object()}])  # type: ignore[list-item]
    with pytest.raises(ValidationError, match="finite"):
        TableParameterValue(id="invalid", rows=[{"value": float("nan")}])
    with pytest.raises(ValidationError, match="finite"):
        TableParameterValue(
            id="invalid",
            rows=[{"value": Quantity(value=float("inf"), unit="GHz")}],
        )
    for value in (b"abc", bytearray(b"abc")):
        with pytest.raises(ValidationError):
            TableParameterValue(id="invalid", rows=[{"value": value}])  # type: ignore[list-item]


def test_parameter_snapshot_is_recursively_immutable_and_durable() -> None:
    table = TableParameterValue(
        id="durable",
        rows=[{"value": 1.0}],
        metadata={"labels": ["data"]},
    )

    assert table.rows == ({"value": 1.0},)
    assert table.metadata == {"labels": ("data",)}
    with pytest.raises(TypeError, match="immutable"):
        table.rows[0]["value"] = float("nan")  # type: ignore[index]
    with pytest.raises(TypeError, match="immutable"):
        table.metadata["late"] = object()  # type: ignore[index]
    with pytest.raises(ValidationError):
        TableParameterValue(id="invalid", metadata={"value": object()})
    with pytest.raises(ValidationError):
        TableParameterValue(id="invalid", metadata={"value": float("nan")})

    snapshot = ParameterSnapshot(id="snapshot", values=[table])
    assert ParameterSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_run_plan_dataset_dimensions_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        RunPlanRecord(
            backend_id="tests.execution.v1",
            execution_options=RunPlanExecutionOptions(
                requested=RunPlanFusionOptions(
                    fusion="automatic",
                    max_points_per_batch=None,
                ),
                resolved=RunPlanFusionOptions(
                    fusion="disabled",
                    max_points_per_batch=1,
                ),
            ),
            experiment_id="experiment",
            experiment_kind="test",
            execution_units=[
                RunPlanPointInstrumentExecution.model_validate(_point_execution_data())
            ],
            point_count=0,
            dataset_dimensions={"point": -1},
        )


def _domain_batch_data(
    batch_ordinal: int,
    point_indices: list[int],
) -> dict[str, Any]:
    return {
        "batch_ordinal": batch_ordinal,
        "point_indices": point_indices,
        "semantic_operation_id": "measure",
        "completion_contract": "synchronous",
        "invocation_id": f"invocation-{batch_ordinal}",
        "intent_fingerprint": f"sha256:intent-{batch_ordinal}",
        "target_id": "target-1",
        "compiler_id": "compiler-1",
        "capability_fingerprint": "sha256:capability",
        "artifact_id": f"artifact-{batch_ordinal}",
        "artifact_fingerprint": f"sha256:artifact-{batch_ordinal}",
    }


def _domain_execution_data() -> dict[str, Any]:
    return {
        "kind": "domain_program",
        "unit_id": "domain-job",
        "adapter_id": "tests.domain.v1",
        "capabilities": {"max_points_per_batch": 2},
        "batches": [_domain_batch_data(0, [0, 1])],
    }


def test_run_plan_domain_execution_is_payload_free_durable_identity() -> None:
    execution = RunPlanDomainExecution.model_validate(_domain_execution_data())

    assert_model_round_trip(execution)
    assert execution.model_dump(mode="json") == _domain_execution_data()
    assert set(execution.batches[0].model_dump(mode="json")).isdisjoint(
        {"payload", "entry_address", "result_address", "target_address"}
    )

    empty_adapter = _domain_execution_data()
    empty_adapter["adapter_id"] = ""
    with pytest.raises(ValidationError, match="adapter_id"):
        RunPlanDomainExecution.model_validate(empty_adapter)

    asynchronous = _domain_execution_data()
    asynchronous["batches"][0]["completion_contract"] = "asynchronous"
    with pytest.raises(ValidationError, match="completion_contract"):
        RunPlanDomainExecution.model_validate(asynchronous)


def test_run_plan_domain_batches_retain_capability_bounded_point_partitions() -> None:
    first = RunPlanDomainBatch.model_validate(_domain_batch_data(0, [0]))
    second = RunPlanDomainBatch.model_validate(_domain_batch_data(1, [1]))
    capabilities = RunPlanDomainCapabilities(max_points_per_batch=1)
    execution = RunPlanDomainExecution(
        unit_id="domain-program",
        adapter_id="tests.domain.v1",
        capabilities=capabilities,
        batches=[first, second],
    )
    data = _valid_run_plan_data()
    data["execution_options"]["resolved"] = {
        "fusion": "automatic",
        "max_points_per_batch": 1,
    }
    data["execution_units"] = [execution.model_dump(mode="json")]
    data["records"][0].update(
        producer_kind="domain",
        producer_unit_id="domain-program",
    )

    plan = RunPlanRecord.model_validate(data)

    assert plan.execution_units == [execution]
    assert [batch.point_indices for batch in execution.batches] == [[0], [1]]

    excessive = _domain_execution_data()
    excessive["capabilities"]["max_points_per_batch"] = 1
    with pytest.raises(ValidationError, match="adapter point capability"):
        RunPlanDomainExecution.model_validate(excessive)

    skipped_ordinal = _domain_execution_data()
    skipped_ordinal["batches"][0]["batch_ordinal"] = 1
    with pytest.raises(ValidationError, match="ordinals"):
        RunPlanDomainExecution.model_validate(skipped_ordinal)


@pytest.mark.parametrize(
    "point_partitions",
    [
        [[0]],
        [[0], [0, 1]],
        [[1], [0]],
        [[0, 2]],
    ],
)
def test_run_plan_domain_batches_must_exactly_partition_logical_points(
    point_partitions: list[list[int]],
) -> None:
    data = _valid_run_plan_data()
    domain = _domain_execution_data()
    domain["batches"] = [
        _domain_batch_data(ordinal, point_indices)
        for ordinal, point_indices in enumerate(point_partitions)
    ]
    data["execution_units"] = [domain]
    data["records"][0].update(
        producer_kind="domain",
        producer_unit_id="domain-job",
    )

    with pytest.raises(ValidationError, match="partition every logical point"):
        RunPlanRecord.model_validate(data)


def test_run_plan_execution_options_retain_requested_and_resolved_fusion() -> None:
    options = RunPlanExecutionOptions(
        requested=RunPlanFusionOptions(
            fusion="automatic",
            max_points_per_batch=4,
        ),
        resolved=RunPlanFusionOptions(
            fusion="automatic",
            max_points_per_batch=2,
        ),
    )

    assert RunPlanExecutionOptions.model_validate_json(options.model_dump_json()) == (
        options
    )
    with pytest.raises(ValidationError, match="requested point bound"):
        RunPlanExecutionOptions(
            requested=RunPlanFusionOptions(
                fusion="automatic",
                max_points_per_batch=2,
            ),
            resolved=RunPlanFusionOptions(
                fusion="automatic",
                max_points_per_batch=3,
            ),
        )
    with pytest.raises(ValidationError, match="disabled request"):
        RunPlanExecutionOptions(
            requested=RunPlanFusionOptions(
                fusion="disabled",
                max_points_per_batch=None,
            ),
            resolved=RunPlanFusionOptions(
                fusion="automatic",
                max_points_per_batch=None,
            ),
        )
    with pytest.raises(ValidationError, match="one-point bound"):
        RunPlanExecutionOptions(
            requested=RunPlanFusionOptions(
                fusion="automatic",
                max_points_per_batch=None,
            ),
            resolved=RunPlanFusionOptions(
                fusion="disabled",
                max_points_per_batch=None,
            ),
        )


def test_point_only_run_plan_requires_pointwise_resolved_execution() -> None:
    data = _valid_run_plan_data()
    data["execution_options"]["resolved"] = {
        "fusion": "automatic",
        "max_points_per_batch": 2,
    }

    with pytest.raises(ValidationError, match="resolve to pointwise execution"):
        RunPlanRecord.model_validate(data)


def test_run_plan_domain_outputs_require_accepted_execution_identity() -> None:
    wrong_unit_kind = _valid_run_plan_data()
    wrong_unit_kind["records"][0]["producer_kind"] = "domain"
    with pytest.raises(
        ValidationError,
        match="domain or host-transform outputs require a domain-program unit",
    ):
        RunPlanRecord.model_validate(wrong_unit_kind)

    unknown_unit = _valid_run_plan_data()
    unknown_unit["records"][0]["producer_unit_id"] = "missing-unit"
    with pytest.raises(ValidationError, match="unknown producer unit"):
        RunPlanRecord.model_validate(unknown_unit)


def test_run_plan_accepts_mixed_instrument_and_domain_output_units() -> None:
    mixed = _valid_run_plan_data()
    mixed["execution_options"]["resolved"] = {
        "fusion": "automatic",
        "max_points_per_batch": 2,
    }
    mixed["execution_units"].append(_domain_execution_data())
    mixed["records"].append(
        {
            "id": "domain-signal",
            "kind": "observable",
            "producer_kind": "domain",
            "producer_unit_id": "domain-job",
            "dtype": "float64",
            "dims": ["point"],
            "shape": [2],
        }
    )

    plan = RunPlanRecord.model_validate(mixed)

    assert [unit.unit_id for unit in plan.execution_units] == [
        "point-instrument",
        "domain-job",
    ]
    assert [record.producer_unit_id for record in plan.records] == [
        "point-instrument",
        "domain-job",
    ]
    domain = plan.execution_units[1]
    assert isinstance(domain, RunPlanDomainExecution)
    assert domain.batches[0].target_id == "target-1"


def test_run_plan_record_enforces_point_table_invariants() -> None:
    mismatched_count = _valid_run_plan_data()
    mismatched_count["point_count"] = 1
    with pytest.raises(ValidationError, match="point_count"):
        RunPlanRecord.model_validate(mismatched_count)

    duplicate_index = _valid_run_plan_data()
    duplicate_index["points"][1]["point_index"] = 0
    with pytest.raises(ValidationError, match="unique, contiguous"):
        RunPlanRecord.model_validate(duplicate_index)

    duplicate_uid = _valid_run_plan_data()
    duplicate_uid["points"][1]["point_uid"] = "point-0"
    with pytest.raises(ValidationError, match="point UIDs must be unique"):
        RunPlanRecord.model_validate(duplicate_uid)

    mismatched_coordinates = _valid_run_plan_data()
    mismatched_coordinates["points"][0]["coordinates"] = {}
    with pytest.raises(ValidationError, match="coordinate keys"):
        RunPlanRecord.model_validate(mismatched_coordinates)


def test_run_plan_record_rejects_out_of_range_point_references() -> None:
    invalid_state = _valid_run_plan_data()
    invalid_state["state_changes"][0]["point_index"] = 2
    with pytest.raises(ValidationError, match="state change point_index"):
        RunPlanRecord.model_validate(invalid_state)

    invalid_route = _valid_run_plan_data()
    invalid_route["routes"][0]["resolved"][0]["point_index"] = 2
    with pytest.raises(ValidationError, match="resolved route point_index"):
        RunPlanRecord.model_validate(invalid_route)


def test_run_plan_output_requires_a_non_negative_shape_matching_dims() -> None:
    with pytest.raises(ValidationError, match="dims and shape"):
        RunPlanOutput(
            id="signal",
            kind="observable",
            producer_kind="instrument",
            producer_unit_id="point-instrument",
            dtype="float64",
            dims=["point"],
            shape=[],
        )
    with pytest.raises(ValidationError):
        RunPlanOutput(
            id="signal",
            kind="observable",
            producer_kind="instrument",
            producer_unit_id="point-instrument",
            dtype="float64",
            dims=["point"],
            shape=[-1],
        )
    with pytest.raises(ValidationError, match="both logical and physical"):
        RunPlanOutput(
            id="signal",
            kind="observable",
            producer_kind="instrument",
            producer_unit_id="point-instrument",
            resource_port_id="readout",
            physical_resource_id="digitizer-0",
            dtype="float64",
        )
    with pytest.raises(ValidationError):
        RunPlanOutput(
            id="signal",
            kind="observable",
            producer_kind="instrument",
            producer_unit_id="point-instrument",
            resource_port_id="",
            dtype="float64",
        )


def test_run_plan_record_closes_logical_resource_inventory() -> None:
    incomplete_route = _valid_run_plan_data()
    incomplete_route["routes"][0]["resolved"].pop()
    with pytest.raises(ValidationError, match="exactly once for every point"):
        RunPlanRecord.model_validate(incomplete_route)

    changed_resolved_port = _valid_run_plan_data()
    changed_resolved_port["routes"][0]["resolved"][1]["port_id"] = "other"
    with pytest.raises(ValidationError, match="same logical port ID"):
        RunPlanRecord.model_validate(changed_resolved_port)

    changed_fixed_resource = _valid_run_plan_data()
    changed_fixed_resource["routes"][0]["fixed_resource_id"] = "source-1"
    with pytest.raises(ValidationError, match="fixed physical resource ID"):
        RunPlanRecord.model_validate(changed_fixed_resource)

    missing_record_port = _valid_run_plan_data()
    missing_record_port["records"][0]["resource_port_id"] = "missing"
    with pytest.raises(ValidationError, match="unknown logical resource port"):
        RunPlanRecord.model_validate(missing_record_port)

    missing_capability = _valid_run_plan_data()
    missing_capability["records"][0].update(
        resource_port_id="source",
        capability="acquire",
    )
    with pytest.raises(ValidationError, match="not provided by resource port"):
        RunPlanRecord.model_validate(missing_capability)


def test_run_plan_record_closes_logical_effect_targets() -> None:
    valid = _valid_run_plan_data()
    valid["routes"][0]["capabilities"] = ["set_amplitude"]
    for resolved in valid["routes"][0]["resolved"]:
        resolved.update(
            entity_ids=["q0"],
            served_entity_ids=["q0"],
            channel_bindings=[
                {
                    "entity_id": "q0",
                    "channel_id": "drive-q0",
                    "capability": "set_amplitude",
                }
            ],
        )
    valid["state_changes"][0].update(
        resource_id="source-0",
        resource_port_id="source",
        entity_ids=["q0"],
        channel_bindings=[
            {
                "entity_id": "q0",
                "channel_id": "drive-q0",
                "capability": "set_amplitude",
            }
        ],
    )
    RunPlanRecord.model_validate(valid)

    missing_capability = deepcopy(valid)
    missing_capability["state_changes"][0]["capability_id"] = "missing"
    missing_capability["state_changes"][0]["channel_bindings"][0]["capability"] = (
        "missing"
    )
    with pytest.raises(ValidationError, match="capability is not provided"):
        RunPlanRecord.model_validate(missing_capability)

    unserved_entity = deepcopy(valid)
    unserved_entity["state_changes"][0]["entity_ids"] = ["q1"]
    unserved_entity["state_changes"][0]["channel_bindings"] = []
    with pytest.raises(ValidationError, match="outside its logical route target"):
        RunPlanRecord.model_validate(unserved_entity)

    unbound_channel = deepcopy(valid)
    unbound_channel["state_changes"][0]["channel_bindings"][0]["channel_id"] = (
        "readout-q0"
    )
    with pytest.raises(ValidationError, match="channel bindings are outside"):
        RunPlanRecord.model_validate(unbound_channel)

    non_instrument_state = deepcopy(valid)
    non_instrument_state["routes"][0]["resolved"][1]["resource_kind"] = "service"
    with pytest.raises(ValidationError, match="resolve to an instrument"):
        RunPlanRecord.model_validate(non_instrument_state)

    duplicate_target = deepcopy(valid)
    duplicate_target["state_changes"].append(deepcopy(valid["state_changes"][0]))
    with pytest.raises(ValidationError, match="unique physical targets"):
        RunPlanRecord.model_validate(duplicate_target)


def test_run_plan_logical_records_resolve_only_to_instruments() -> None:
    invalid = _valid_run_plan_data()
    invalid["records"][0].update(
        resource_port_id="source",
        capability="measure",
    )
    invalid["routes"][0]["capabilities"] = ["measure"]
    invalid["routes"][0]["resolved"][0]["resource_kind"] = "service"

    with pytest.raises(ValidationError, match="resolve to instruments"):
        RunPlanRecord.model_validate(invalid)


def test_run_plan_record_validates_observable_and_dimension_references() -> None:
    unknown_observable = _valid_run_plan_data()
    unknown_observable["primary_observables"] = ["missing"]
    with pytest.raises(ValidationError, match="primary observables"):
        RunPlanRecord.model_validate(unknown_observable)

    wrong_size = _valid_run_plan_data()
    wrong_size["dataset_dimensions"] = {"point": 3}
    with pytest.raises(ValidationError, match="must have size 2"):
        RunPlanRecord.model_validate(wrong_size)

    missing_size = _valid_run_plan_data()
    missing_size["dataset_dimensions"] = {}
    with pytest.raises(ValidationError, match="missing known dimensions"):
        RunPlanRecord.model_validate(missing_size)

    unknown_dimension = _valid_run_plan_data()
    unknown_dimension["dataset_dimensions"] = {"point": 2, "unknown": 1}
    with pytest.raises(ValidationError, match="unknown dimensions"):
        RunPlanRecord.model_validate(unknown_dimension)


def test_run_plan_record_cross_aligns_expected_dataset_schema_by_id() -> None:
    data = _valid_run_plan_data()
    data["expected_dataset_schema"] = _valid_expected_dataset_schema_data()

    plan = RunPlanRecord.model_validate(data)
    restored = RunPlanRecord.model_validate_json(plan.model_dump_json())

    assert restored == plan
    assert plan.expected_dataset_schema is not None
    assert [variable.id for variable in plan.expected_dataset_schema.variables] == [
        "signal",
        "quality",
        "amplitude",
    ]


@pytest.mark.parametrize("value", [object(), float("nan")])
def test_run_plan_record_rejects_non_durable_schema_metadata(value: object) -> None:
    for metadata_target in ("schema", "dimension", "variable"):
        data = _valid_run_plan_data()
        schema = _valid_expected_dataset_schema_data()
        if metadata_target == "schema":
            schema["metadata"] = {"value": value}
        elif metadata_target == "dimension":
            schema["dimensions"][0]["metadata"] = {"value": value}
        else:
            schema["variables"][0]["metadata"] = {"value": value}
        data["expected_dataset_schema"] = schema

        with pytest.raises(ValidationError, match="metadata"):
            RunPlanRecord.model_validate(data)


def test_run_plan_record_rejects_tuple_schema_metadata() -> None:
    data = _valid_run_plan_data()
    schema = _valid_expected_dataset_schema_data()
    schema["metadata"] = {"tags": ("raw", "accepted")}
    data["expected_dataset_schema"] = schema

    with pytest.raises(ValidationError, match="not a valid JSON value"):
        RunPlanRecord.model_validate(data)


def test_run_plan_record_aligns_schema_primary_ids() -> None:
    coordinate_mismatch = _valid_run_plan_data()
    coordinate_mismatch["expected_dataset_schema"] = (
        _valid_expected_dataset_schema_data()
    )
    coordinate_mismatch["coordinate_ids"] = ["frequency"]
    for point in coordinate_mismatch["points"]:
        point["coordinates"] = {"frequency": 5.0}
    with pytest.raises(ValidationError, match="primary_coordinates"):
        RunPlanRecord.model_validate(coordinate_mismatch)

    observable_mismatch = _valid_run_plan_data()
    schema = _valid_expected_dataset_schema_data()
    schema["primary_observables"] = []
    observable_mismatch["expected_dataset_schema"] = schema
    with pytest.raises(ValidationError, match="primary_observables"):
        RunPlanRecord.model_validate(observable_mismatch)


def test_run_plan_record_aligns_schema_observable_ids_and_kind() -> None:
    id_mismatch = _valid_run_plan_data()
    schema = _valid_expected_dataset_schema_data()
    schema["variables"].append(
        {
            "id": "other",
            "role": "observable",
            "dtype": "float64",
            "dims": ["point"],
            "shape": [2],
        }
    )
    id_mismatch["expected_dataset_schema"] = schema
    with pytest.raises(ValidationError, match="observable variable IDs"):
        RunPlanRecord.model_validate(id_mismatch)

    kind_mismatch = _valid_run_plan_data()
    kind_mismatch["expected_dataset_schema"] = _valid_expected_dataset_schema_data()
    kind_mismatch["records"][0]["kind"] = "status"
    with pytest.raises(ValidationError, match="kind must be 'observable'"):
        RunPlanRecord.model_validate(kind_mismatch)


@pytest.mark.parametrize(
    ("record_updates", "message"),
    [
        ({"dtype": "int64"}, "dtype"),
        ({"unit": "ratio"}, "unit"),
        ({"dims": ["point", "sample"], "shape": [2, 1]}, "dims and shape"),
        ({"shape": [1]}, "dims and shape"),
    ],
)
def test_run_plan_record_aligns_schema_observable_type_and_shape(
    record_updates: dict[str, Any],
    message: str,
) -> None:
    data = _valid_run_plan_data()
    data["expected_dataset_schema"] = _valid_expected_dataset_schema_data()
    data["records"][0].update(record_updates)

    with pytest.raises(ValidationError, match=message):
        RunPlanRecord.model_validate(data)


@pytest.mark.parametrize(
    "metadata",
    [
        {"resource_port_id": "other"},
        {"physical_resource_id": "source-0"},
        {"resource": "source"},
    ],
)
def test_run_plan_dataset_metadata_is_independent_of_producer_resource_identity(
    metadata: dict[str, str],
) -> None:
    data = _valid_run_plan_data()
    data["records"][0]["resource_port_id"] = "source"
    schema = _valid_expected_dataset_schema_data()
    schema["variables"][0]["metadata"] = metadata
    data["expected_dataset_schema"] = schema

    restored = RunPlanRecord.model_validate(data)

    assert restored.expected_dataset_schema is not None
    assert restored.expected_dataset_schema.variables[0].metadata == metadata


def test_run_plan_models_share_closed_finite_configuration() -> None:
    models = (
        RunPlanDeferredValue,
        RunPlanPayloadValue,
        RunPlanPoint,
        RunPlanOutput,
        RunPlanStateChange,
        RunPlanChannelBinding,
        RunPlanResolvedRoute,
        RunPlanRoute,
        RunPlanRecord,
    )

    for model in models:
        assert model.model_config.get("extra") == "forbid"
        assert model.model_config.get("allow_inf_nan") is False


def test_parameter_snapshot_uses_one_shape_discriminated_namespace() -> None:
    snapshot = ParameterSnapshot(
        id="parameter-snapshot",
        values=[
            ScalarParameterValue(id="enabled", value=True),
            SeriesParameterValue(id="frequencies", items=[4.9, 5.0]),
            TableParameterValue(id="calibrations", rows=[{"id": "q0"}]),
        ],
    )

    restored = ParameterSnapshot.model_validate_json(snapshot.model_dump_json())

    assert isinstance(restored.get("enabled"), ScalarParameterValue)
    assert isinstance(restored.get("frequencies"), SeriesParameterValue)
    assert isinstance(restored.get("calibrations"), TableParameterValue)
    with pytest.raises(ValidationError, match="duplicate stored parameter value"):
        ParameterSnapshot(
            id="duplicate",
            values=[
                ScalarParameterValue(id="same", value=1),
                SeriesParameterValue(id="same", items=[1]),
            ],
        )


def test_parameter_catalog_supports_all_value_shapes() -> None:
    catalog = ParameterCatalog(
        id="public-lab-catalog",
        definitions=[
            ParameterDefinition(
                id="enabled",
                value_type=Scalar(Bool()),
            ),
            ParameterDefinition(
                id="frequencies",
                value_type=Series(Scalar(QuantityType(unit="GHz"))),
            ),
            ParameterDefinition(
                id="calibration_points",
                value_type=Table(
                    primary_key=("point_index",),
                    columns=(
                        TableColumn(
                            id="point_index",
                            value_type=Scalar(String()),
                        ),
                        TableColumn(
                            id="frequency",
                            value_type=Scalar(QuantityType(unit="GHz")),
                        ),
                    ),
                ),
            ),
        ],
    )

    restored = assert_model_round_trip(catalog)

    assert isinstance(restored.get("enabled").value_type, Scalar)  # type: ignore[union-attr]
    assert isinstance(restored.get("frequencies").value_type, Series)  # type: ignore[union-attr]
    assert isinstance(restored.get("calibration_points").value_type, Table)  # type: ignore[union-attr]


def test_durable_parameter_schema_model_copy_revalidates_updates() -> None:
    definition = ParameterDefinition(id="enabled", value_type=Scalar(Bool()))
    catalog = ParameterCatalog(id="catalog", definitions=[definition])

    with pytest.raises(ValidationError, match="supports only bool, int, float"):
        definition.model_copy(update={"value_type": Scalar(Payload("command"))})
    with pytest.raises(ValidationError, match="duplicate parameter definition"):
        catalog.model_copy(update={"definitions": [definition, definition]})
    with pytest.raises(ValidationError, match="unsupported unit"):
        Quantity(1.0, "GHz").model_copy(update={"unit": "invalid"})


@pytest.mark.parametrize(
    "value_type",
    [
        Scalar(Bool()),
        Scalar(Int(minimum=1, maximum=3)),
        Scalar(Float(minimum=0.0, maximum=1.0)),
        Scalar(String(min_length=1, choices=("a", "b"))),
        Scalar(Entity(entity_kind="qubit")),
        Scalar(
            QuantityType(
                dimension="frequency",
                unit="GHz",
                minimum=4.0,
                maximum=6.0,
            ),
            nullable=True,
        ),
    ],
)
def test_parameter_definition_scalar_type_has_stable_wire_format(
    value_type: Scalar,
) -> None:
    definition = ParameterDefinition(id="value", value_type=value_type)

    compact = definition.model_dump(mode="json", exclude_defaults=True)
    restored = ParameterDefinition.model_validate(compact)
    restored_from_json = ParameterDefinition.model_validate_json(
        definition.model_dump_json()
    )

    assert compact["value_type"]["shape"] == "scalar"
    assert compact["value_type"]["atom"]["type"]
    assert restored == definition
    assert restored_from_json == definition
    assert restored_from_json.model_dump_json() == definition.model_dump_json()


def test_persistable_value_type_wire_is_strict_and_schema_matches_it() -> None:
    definition = ParameterDefinition(
        id="value",
        value_type=Scalar(Float(minimum=0)),
    )
    value_type = definition.value_type

    assert isinstance(value_type, Scalar)
    assert isinstance(value_type.atom, Float)
    assert value_type.atom.minimum == 0.0
    with pytest.raises(ValidationError, match="unknown fields: garbage"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "bool", "garbage": True},
                },
            }
        )
    with pytest.raises(ValidationError, match="must require finite values"):
        ParameterDefinition(
            id="value",
            value_type=Scalar(Float(finite=False)),
        )
    with pytest.raises(ValidationError, match="supports only bool, int, float"):
        ParameterDefinition(
            id="value",
            value_type=Scalar(Payload("pulse_program")),
        )
    with pytest.raises(ValidationError, match="field 'finite' must be a bool"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "float", "finite": "false"},
                },
            }
        )
    with pytest.raises(ValidationError, match="field names must be strings"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "float", 1: "unexpected"},
                },
            }
        )

    integer_definition = ParameterDefinition.model_validate(
        {
            "id": "value",
            "value_type": {
                "shape": "scalar",
                "atom": {"type": "int", "minimum": 1.0},
            },
        }
    )
    assert isinstance(integer_definition.value_type, Scalar)
    assert isinstance(integer_definition.value_type.atom, Int)
    assert integer_definition.value_type.atom.minimum == 1

    schema = ParameterDefinition.model_json_schema(mode="validation")
    value_schema = schema["properties"]["value_type"]
    value_schema = schema["$defs"][value_schema["$ref"].rsplit("/", maxsplit=1)[-1]]
    assert len(value_schema["oneOf"]) == 3
    assert all(
        variant["additionalProperties"] is False for variant in value_schema["oneOf"]
    )


def test_durable_scalar_models_reject_malformed_runtime_declarations() -> None:
    invalid_nullable = Scalar(Float())
    object.__setattr__(invalid_nullable, "nullable", "false")
    invalid_finite = Float()
    object.__setattr__(invalid_finite, "finite", "false")
    invalid_length = String()
    object.__setattr__(invalid_length, "min_length", False)

    for value_type in (
        invalid_nullable,
        Scalar(invalid_finite),
        Scalar(invalid_length),
    ):
        with pytest.raises(ValidationError):
            ParameterDefinition(id="value", value_type=value_type)


@pytest.mark.parametrize(
    "column",
    [
        TableColumn(
            id="id",
            value_type=Scalar(String()),
            required=False,
        ),
        TableColumn(
            id="id",
            value_type=Scalar(String(), nullable=True),
        ),
    ],
)
def test_parameter_table_primary_key_must_be_required_and_non_null(
    column: TableColumn,
) -> None:
    with pytest.raises(ValueError, match="required and non-null"):
        ParameterDefinition(
            id="values",
            value_type=Table(primary_key=("id",), columns=(column,)),
        )
