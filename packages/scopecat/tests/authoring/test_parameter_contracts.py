from __future__ import annotations

from typing import Annotated

import pytest

import scopecat as sc
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.program.domain import domain_program
from scopecat.program.expressions import PointColumnScalarExpr
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import (
    ParameterDefinition,
    TableParameterValue,
)
from tests.testkit.authoring import bind_invocation, load_config
from tests.testkit.domain import domain_call
from tests.testkit.materialized_effects import materialized_effects_contract


def _identity(value: object) -> object:
    return value


def _resolve_dependency(
    value: sc.ValueRef,
    config: ConfigProfileSnapshot,
) -> None:
    _resolve_root_domain_dependency(value, config)


def _resolve_table_dependency(
    value: sc.ValueRef,
    config: ConfigProfileSnapshot,
) -> None:
    _resolve_root_domain_dependency(value, config)


def _resolve_root_domain_dependency(
    value: sc.ValueRef,
    config: ConfigProfileSnapshot,
) -> None:
    program = domain_program(
        "consume-parameter",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        compiler_inputs={"value": value.value_type},
    )

    @sc.template(id="test.parameter-contract", kind="parameter_contract")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(
            domain_call(
                program,
                compiler_inputs={"value": value},
            )
        )

    bind_invocation(template(), config_profile=config)


def _empty_module(id: str) -> sc.ExperimentModule[...]:
    @sc.module(id=id)
    def module(context: sc.ModuleContext) -> None:
        del context

    return module


def _scan_invocation(id: str, *scans: sc.Scan) -> sc.ExperimentInvocation:
    module = _empty_module(id)

    @sc.template(id=id, kind="parameter_contract")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(module())
        experiment.scan(*scans)

    return template()


def _config_with_parameter_table(
    *,
    frequency_type: sc.ScalarType | None = None,
) -> ConfigProfileSnapshot:
    config = load_config()
    definition = ParameterDefinition(
        id="device_parameters",
        value_type=sc.TableType(
            primary_key=("device",),
            columns=(
                sc.TableColumn(
                    id="device",
                    value_type=sc.ScalarType(
                        sc.EntityType(entity_kind="logical_device")
                    ),
                ),
                sc.TableColumn(
                    id="frequency",
                    value_type=frequency_type
                    or sc.ScalarType(sc.QuantityType(unit="GHz")),
                ),
            ),
        ),
    )
    system = config.system.model_copy(
        update={
            "parameter_catalog": config.parameter_catalog.model_copy(
                update={
                    "definitions": (*config.parameter_catalog.definitions, definition)
                }
            )
        }
    )
    parameter_snapshot = config.parameter_snapshot.model_copy(
        update={
            "values": [
                *config.parameter_snapshot.values,
                TableParameterValue(
                    id="device_parameters",
                    rows=[
                        {
                            "device": "q0",
                            "frequency": sc.Quantity(value=5.0, unit="GHz"),
                        }
                    ],
                ),
            ]
        }
    )
    return config.model_copy(
        update={"system": system, "parameter_snapshot": parameter_snapshot}
    )


def _config_with_literal_key_type(
    key_type: sc.ScalarType,
) -> ConfigProfileSnapshot:
    config = load_config()
    definition = ParameterDefinition(
        id="literal_key_parameters",
        value_type=sc.TableType(
            primary_key=("key",),
            columns=(
                sc.TableColumn(id="key", value_type=key_type),
                sc.TableColumn(
                    id="value",
                    value_type=sc.ScalarType(sc.StringType()),
                ),
            ),
        ),
    )
    system = config.system.model_copy(
        update={
            "parameter_catalog": config.parameter_catalog.model_copy(
                update={
                    "definitions": (*config.parameter_catalog.definitions, definition)
                }
            )
        }
    )
    parameter_snapshot = config.parameter_snapshot.model_copy(
        update={
            "values": (
                *config.parameter_snapshot.values,
                TableParameterValue(id="literal_key_parameters"),
            )
        }
    )
    return config.model_copy(
        update={"system": system, "parameter_snapshot": parameter_snapshot}
    )


def test_scalar_parameter_declaration_is_checked_against_catalog() -> None:
    _resolve_dependency(
        sc.parameter(
            "drive_frequency",
            sc.ScalarType(sc.QuantityType(unit="MHz")),
        ),
        load_config(),
    )

    with pytest.raises(CheckFailed) as error:
        _resolve_dependency(
            sc.parameter(
                "drive_frequency",
                sc.ScalarType(sc.StringType()),
            ),
            load_config(),
        )

    assert error.value.problems[0].code == "authoring_parameter_type_mismatch"


def test_unknown_scalar_parameter_has_authoring_problem() -> None:
    with pytest.raises(CheckFailed) as error:
        _resolve_dependency(
            sc.parameter(
                "missing_frequency",
                sc.ScalarType(sc.QuantityType()),
            ),
            load_config(),
        )

    assert error.value.problems[0].code == "unknown_authoring_parameter"
    assert error.value.problems[0].location == model_location(
        "parameters", "missing_frequency"
    )


def test_parameter_contract_survives_nested_elaboration() -> None:
    @sc.module(id="test.parameter-contract-child")
    def child(
        context: sc.ModuleContext,
        frequency: Annotated[sc.Input[str], sc.StringType()],
    ) -> None:
        context.compute(
            "consume-child-frequency",
            fn=_identity,
            inputs={"value": frequency},
            output_type=sc.ScalarType(sc.StringType()),
        )

    @sc.module(id="test.parameter-contract-parent")
    def parent(
        context: sc.ModuleContext,
        frequency: Annotated[sc.Input[str], sc.StringType()],
    ) -> None:
        context.call(
            child.instantiate(
                "parameter-contract-child",
                frequency=frequency,
            )
        )

    parameter = sc.parameter(
        "drive_frequency",
        sc.ScalarType(sc.StringType()),
    )

    @sc.template(id="test.parameter-contract", kind="parameter_contract")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(parent(frequency=parameter))

    with pytest.raises(CheckFailed) as error:
        bind_invocation(template(), config_profile=load_config())

    assert error.value.problems[0].code == "authoring_parameter_type_mismatch"


def test_parameter_contract_survives_scan_lowering() -> None:
    invocation = _scan_invocation(
        "test.parameter-contract-scan",
        sc.axis(
            sc.coordinate(
                "frequency",
                sc.ScalarType(sc.QuantityType()),
            ),
            center=sc.parameter(
                "drive_frequency",
                sc.ScalarType(sc.QuantityType(unit="ns")),
            ),
            span=sc.Quantity(value=100, unit="MHz"),
            points=3,
        ),
    )

    with pytest.raises(CheckFailed) as error:
        bind_invocation(
            invocation,
            config_profile=load_config(),
        )

    assert error.value.problems[0].code == "authoring_parameter_type_mismatch"


@pytest.mark.parametrize(
    ("column", "point_type", "values", "expected_code"),
    [
        (
            "missing",
            sc.ScalarType(sc.StringType()),
            ["value"],
            "unknown_authoring_parameter_column",
        ),
        (
            "frequency",
            sc.ScalarType(sc.StringType()),
            ["value"],
            "authoring_parameter_column_type_mismatch",
        ),
    ],
)
def test_parameter_scan_target_is_checked_against_catalog_column(
    column: str,
    point_type: sc.ScalarType,
    values: list[str],
    expected_code: str,
) -> None:
    scan = sc.param_axis(
        sc.coordinate("scanned_value", point_type),
        sc.parameter_lookup(
            "device_parameters",
            key={"device": "q0"},
            column=column,
            value_type=point_type,
        ),
        values,
    )
    invocation = _scan_invocation("test.parameter-contract-scan-target", scan)

    with pytest.raises(CheckFailed) as error:
        bind_invocation(
            invocation,
            config_profile=_config_with_parameter_table(),
        )

    assert error.value.problems[0].code == expected_code


def test_parameter_scan_retains_row_key_parameter_contracts() -> None:
    scan = sc.param_axis(
        sc.coordinate(
            "scanned_frequency",
            sc.ScalarType(sc.QuantityType(unit="GHz")),
        ),
        sc.parameter_lookup(
            "device_parameters",
            key={
                "device": sc.parameter(
                    "drive_frequency",
                    sc.ScalarType(sc.StringType()),
                )
            },
            column="frequency",
            value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
        ),
        [5.0],
        unit="GHz",
    )
    invocation = _scan_invocation("test.parameter-contract-scan-key", scan)

    with pytest.raises(CheckFailed) as error:
        bind_invocation(
            invocation,
            config_profile=_config_with_parameter_table(),
        )

    assert (
        error.value.problems[0].code == "authoring_parameter_lookup_key_type_mismatch"
    )


def test_parameter_around_scan_materializes_about_the_current_table_cell() -> None:
    config = _config_with_parameter_table()
    frequency_type = sc.ScalarType(sc.QuantityType(unit="GHz"))
    frequency = sc.coordinate("scanned_frequency", frequency_type)
    invocation = _scan_invocation(
        "test.parameter-around-scan",
        sc.param_axis(
            frequency,
            sc.parameter_lookup(
                "device_parameters",
                key={"device": "q0"},
                column="frequency",
                value_type=frequency_type,
            ),
            span="200 MHz",
            points=3,
        ),
    )

    resolved = bind_invocation(invocation, config_profile=config)
    materialized = materialized_effects_contract(
        resolved,
        resolved.environment.parameters,
        config=config,
    )

    scanned = [point.coordinates["scanned_frequency"] for point in materialized.points]
    assert scanned == [
        sc.Quantity(4.9, "GHz"),
        sc.Quantity(5.0, "GHz"),
        sc.Quantity(5.1, "GHz"),
    ]
    assert len(resolved.bindings.parameter_overlays) == 1
    stored = config.parameter_snapshot.get("device_parameters")
    assert isinstance(stored, TableParameterValue)
    assert stored.rows[0]["frequency"] == sc.Quantity(5.0, "GHz")


def test_parameter_scan_specializes_consumers_against_its_point_column() -> None:
    frequency_type = sc.ScalarType(sc.QuantityType(unit="GHz"))
    frequency = sc.coordinate("scanned_frequency", frequency_type)
    lookup = sc.parameter_lookup(
        "device_parameters",
        key={"device": "q0"},
        column="frequency",
        value_type=frequency_type,
    )
    program = domain_program(
        "consume-scanned-parameter",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"frequency": frequency_type},
    )

    @sc.template(id="test.parameter-scan-consumer", kind="parameter_contract")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(domain_call(program, inputs={"frequency": lookup}))
        experiment.scan(
            sc.param_axis(
                frequency,
                lookup,
                span="200 MHz",
                points=3,
            )
        )

    resolved = bind_invocation(
        template(),
        config_profile=_config_with_parameter_table(),
    )

    [execution] = resolved.program.program.domain_executions
    expression = resolved.bindings.values[dict(execution.inputs)["frequency"]]
    assert isinstance(expression, PointColumnScalarExpr)
    assert expression.name == "scanned_frequency"


def test_parameter_scan_type_must_be_writable_to_catalog_column() -> None:
    bounded_frequency = sc.ScalarType(
        sc.QuantityType(unit="GHz", minimum=4.0, maximum=6.0)
    )
    config = _config_with_parameter_table(frequency_type=bounded_frequency)
    frequency_type = sc.ScalarType(sc.QuantityType(unit="GHz"))
    scan = sc.param_axis(
        sc.coordinate("scanned_frequency", frequency_type),
        sc.parameter_lookup(
            "device_parameters",
            key={"device": "q0"},
            column="frequency",
            value_type=frequency_type,
        ),
        [5.0],
        unit="GHz",
    )
    invocation = _scan_invocation("test.parameter-scan-write-type", scan)

    with pytest.raises(CheckFailed) as error:
        bind_invocation(invocation, config_profile=config)

    assert error.value.problems[0].code == "authoring_parameter_scan_type_mismatch"


def test_parameter_lookup_checks_table_column_and_entity_type() -> None:
    config = _config_with_parameter_table()
    _resolve_dependency(
        sc.parameter_lookup(
            "device_parameters",
            key={"device": "q0"},
            column="device",
            value_type=sc.ScalarType(sc.EntityType()),
        ),
        config,
    )

    with pytest.raises(CheckFailed) as missing_column:
        _resolve_dependency(
            sc.parameter_lookup(
                "device_parameters",
                key={"device": "q0"},
                column="missing",
                value_type=sc.ScalarType(sc.StringType()),
            ),
            config,
        )
    with pytest.raises(CheckFailed) as wrong_entity_kind:
        _resolve_dependency(
            sc.parameter_lookup(
                "device_parameters",
                key={"device": "q0"},
                column="device",
                value_type=sc.ScalarType(sc.EntityType(entity_kind="coupler")),
            ),
            config,
        )

    assert missing_column.value.problems[0].code == (
        "unknown_authoring_parameter_column"
    )
    assert wrong_entity_kind.value.problems[0].code == (
        "authoring_parameter_column_type_mismatch"
    )


def test_parameter_lookup_checks_primary_key_shape_and_typed_key_values() -> None:
    config = _config_with_parameter_table()

    @sc.module(id="test.typed-parameter-key")
    def module(
        context: sc.ModuleContext,
        frequency: Annotated[sc.Input[sc.Quantity], sc.QuantityType(unit="GHz")],
    ) -> None:
        context.compute(
            "consume-typed-parameter-key",
            fn=_identity,
            inputs={"value": frequency},
            output_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
        )

    @sc.template(id="test.typed-parameter-key", kind="parameter_contract")
    def template(
        experiment: sc.ExperimentContext,
        device: Annotated[
            sc.Input[sc.EntityRef | str],
            sc.EntityType(entity_kind="logical_device"),
        ],
    ) -> None:
        experiment.run(
            module(
                frequency=sc.parameter_lookup(
                    "device_parameters",
                    key={"device": device},
                    column="frequency",
                    value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
                )
            )
        )

    bind_invocation(
        template(device="q0"),
        config_profile=config,
    )

    with pytest.raises(CheckFailed) as wrong_key_shape:
        _resolve_dependency(
            sc.parameter_lookup(
                "device_parameters",
                key={"other": "q0"},
                column="frequency",
                value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
            ),
            config,
        )
    with pytest.raises(CheckFailed) as wrong_key_type:

        @sc.module(id="test.wrong-parameter-key")
        def wrong_module(
            context: sc.ModuleContext,
            frequency: Annotated[
                sc.Input[sc.Quantity],
                sc.QuantityType(unit="GHz"),
            ],
        ) -> None:
            context.compute(
                "consume-wrong-parameter-key",
                fn=_identity,
                inputs={"value": frequency},
                output_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
            )

        @sc.template(id="test.wrong-parameter-key", kind="parameter_contract")
        def wrong_template(
            experiment: sc.ExperimentContext,
            device: Annotated[
                sc.Input[sc.EntityRef | str],
                sc.EntityType(entity_kind="logical_coupler"),
            ],
        ) -> None:
            experiment.run(
                wrong_module(
                    frequency=sc.parameter_lookup(
                        "device_parameters",
                        key={"device": device},
                        column="frequency",
                        value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
                    )
                )
            )

        bind_invocation(wrong_template(device="q0"), config_profile=config)

    assert wrong_key_shape.value.problems[0].code == (
        "authoring_parameter_lookup_key_mismatch"
    )
    assert wrong_key_type.value.problems[0].code == (
        "authoring_parameter_lookup_key_type_mismatch"
    )


@pytest.mark.parametrize(
    ("key_type", "literal"),
    [
        (sc.ScalarType(sc.BoolType()), 1),
        (sc.ScalarType(sc.IntType()), True),
        (sc.ScalarType(sc.FloatType()), "1.0"),
        (sc.ScalarType(sc.StringType()), 1),
        (
            sc.ScalarType(sc.QuantityType(unit="GHz")),
            1.0,
        ),
        (
            sc.ScalarType(sc.StringType()),
            sc.Quantity(value=1.0, unit="GHz"),
        ),
    ],
)
def test_parameter_lookup_checks_every_literal_key_type(
    key_type: sc.ScalarType,
    literal: sc.ParameterKeyInput,
) -> None:
    with pytest.raises(CheckFailed) as error:
        _resolve_dependency(
            sc.parameter_lookup(
                "literal_key_parameters",
                key={"key": literal},
                column="value",
                value_type=sc.ScalarType(sc.StringType()),
            ),
            _config_with_literal_key_type(key_type),
        )

    assert error.value.problems[0].code == (
        "authoring_parameter_lookup_key_type_mismatch"
    )


def test_parameter_table_declaration_is_checked_against_catalog_schema() -> None:
    config = _config_with_parameter_table()
    valid_table = sc.TableType(
        columns=(
            sc.TableColumn(
                "device",
                sc.ScalarType(sc.EntityType()),
            ),
            sc.TableColumn(
                "frequency",
                sc.ScalarType(sc.QuantityType()),
            ),
        ),
    )
    _resolve_table_dependency(
        sc.parameter("device_parameters", valid_table),
        config,
    )

    incompatible_table = sc.TableType(
        columns=(
            sc.TableColumn(
                "frequency",
                sc.ScalarType(sc.StringType()),
            ),
        ),
    )
    with pytest.raises(CheckFailed) as error:
        _resolve_table_dependency(
            sc.parameter("device_parameters", incompatible_table),
            config,
        )

    assert error.value.problems[0].code == ("authoring_parameter_type_mismatch")


def test_unknown_parameter_table_has_authoring_problem() -> None:
    value_type = sc.TableType(
        columns=(
            sc.TableColumn(
                "device",
                sc.ScalarType(sc.EntityType()),
            ),
        )
    )

    with pytest.raises(CheckFailed) as error:
        _resolve_table_dependency(
            sc.parameter("missing_table", value_type),
            load_config(),
        )

    assert error.value.problems[0].code == "unknown_authoring_parameter"
    assert error.value.problems[0].location == model_location(
        "parameters", "missing_table"
    )
