from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.authoring._resolution import resolve_experiment
from scopecat.errors import CheckFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterDefinition,
    SeriesParameterValue,
    TableParameterValue,
)
from scopecat.problems import model_location
from tests.support.authoring import load_config


def _identity(value: object) -> object:
    return value


def _resolve_dependency(
    value: sc.ValueRef,
    config: ConfigProfileSnapshot,
) -> None:
    dependency = sc.compute(
        "consume-parameter-dependency",
        fn=_identity,
        inputs={"value": value},
        output_type=value.value_type,
    )
    module = sc.module("test.parameter-contract").computes(dependency).build()
    _resolve_module(module, config)


def _resolve_module(
    module: sc.ExperimentModule,
    config: ConfigProfileSnapshot,
) -> None:
    invocation = (
        module.template(
            "test.parameter-contract",
            kind="parameter_contract",
        )
        .build()
        .bind()
    )
    resolve_experiment(
        invocation,
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )


def _config_with_parameter_table() -> ConfigProfileSnapshot:
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
                    value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
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


def test_series_parameter_is_first_class_in_authoring_and_resolution() -> None:
    config = load_config()
    series_type = sc.SeriesType(sc.ScalarType(sc.FloatType()))
    definition = ParameterDefinition(id="frequency_offsets", value_type=series_type)
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
                SeriesParameterValue(id="frequency_offsets", items=(0.0, 0.1)),
            )
        }
    )

    _resolve_dependency(
        sc.parameter("frequency_offsets", series_type),
        config.model_copy(
            update={"system": system, "parameter_snapshot": parameter_snapshot}
        ),
    )


def test_parameter_contract_survives_nested_module_composition() -> None:
    frequency = sc.input(
        "frequency",
        sc.ScalarType(sc.StringType()),
    )
    dependency = sc.compute(
        "consume-child-frequency",
        fn=_identity,
        inputs={"value": frequency},
        output_type=frequency.value_type,
    )
    child = (
        sc.module("test.parameter-contract-child")
        .inputs(frequency)
        .computes(dependency)
        .build()
    )
    parent = (
        sc.module("test.parameter-contract-parent")
        .use(
            child(
                frequency=sc.parameter(
                    "drive_frequency",
                    sc.ScalarType(sc.StringType()),
                )
            )
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve_module(parent, load_config())

    assert error.value.problems[0].code == "authoring_parameter_type_mismatch"


def test_parameter_contract_survives_scan_lowering() -> None:
    module = sc.module("test.parameter-contract-scan").build()
    invocation = (
        module.template(
            "test.parameter-contract-scan",
            kind="parameter_contract",
        )
        .scan(
            sc.point(
                "frequency",
                sc.ScalarType(sc.QuantityType()),
            ),
            center=sc.parameter(
                "drive_frequency",
                sc.ScalarType(sc.QuantityType(unit="ns")),
            ),
            span=sc.Quantity(value=100, unit="MHz"),
            points=3,
        )
        .build()
        .bind()
    )

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            invocation,
            workspace=Path("/tmp/scopecat-test"),
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
        sc.point("scanned_value", point_type),
        sc.param_row("device_parameters", device="q0"),
        column,
        values,
    )
    module = sc.module("test.parameter-contract-scan-target").build()
    invocation = (
        module.template(
            "test.parameter-contract-scan-target",
            kind="parameter_contract",
        )
        .scan(scan)
        .build()
        .bind()
    )

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            invocation,
            workspace=Path("/tmp/scopecat-test"),
            config_profile=_config_with_parameter_table(),
        )

    assert error.value.problems[0].code == expected_code


def test_parameter_scan_retains_row_key_parameter_contracts() -> None:
    scan = sc.param_axis(
        sc.point(
            "scanned_frequency",
            sc.ScalarType(sc.QuantityType(unit="GHz")),
        ),
        sc.param_row(
            "device_parameters",
            device=sc.parameter(
                "drive_frequency",
                sc.ScalarType(sc.StringType()),
            ),
        ),
        "frequency",
        [5.0],
        unit="GHz",
    )
    module = sc.module("test.parameter-contract-scan-key").build()
    invocation = (
        module.template(
            "test.parameter-contract-scan-key",
            kind="parameter_contract",
        )
        .scan(scan)
        .build()
        .bind()
    )

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            invocation,
            workspace=Path("/tmp/scopecat-test"),
            config_profile=_config_with_parameter_table(),
        )

    assert error.value.problems[0].code == "authoring_parameter_type_mismatch"


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
    typed_device = sc.input(
        "device",
        sc.ScalarType(sc.EntityType(entity_kind="logical_device")),
    )
    lookup = sc.parameter_lookup(
        "device_parameters",
        key={"device": typed_device},
        column="frequency",
        value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
    )
    dependency = sc.compute(
        "consume-typed-parameter-key",
        fn=_identity,
        inputs={"value": lookup},
        output_type=lookup.value_type,
    )
    module = (
        sc.module("test.typed-parameter-key")
        .inputs(typed_device)
        .computes(dependency)
        .build()
    )
    invocation = (
        module.template("test.typed-parameter-key", kind="parameter_contract")
        .build()
        .bind(device="q0")
    )
    resolve_experiment(
        invocation,
        workspace=Path("/tmp/scopecat-test"),
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
        _resolve_dependency(
            sc.parameter_lookup(
                "device_parameters",
                key={
                    "device": sc.input(
                        "device",
                        sc.ScalarType(sc.EntityType(entity_kind="logical_coupler")),
                    )
                },
                column="frequency",
                value_type=sc.ScalarType(sc.QuantityType(unit="GHz")),
            ),
            config,
        )

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
        (sc.ScalarType(sc.StringType()), None),
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
    _resolve_dependency(
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
        allow_extra_columns=True,
    )
    with pytest.raises(CheckFailed) as error:
        _resolve_dependency(
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
        _resolve_dependency(
            sc.parameter("missing_table", value_type),
            load_config(),
        )

    assert error.value.problems[0].code == "unknown_authoring_parameter"
    assert error.value.problems[0].location == model_location(
        "parameters", "missing_table"
    )


def test_table_row_callback_retains_source_and_added_parameter_contracts() -> None:
    table = sc.parameter(
        "device_parameters",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "device",
                    sc.ScalarType(sc.EntityType(entity_kind="logical_device")),
                ),
                sc.TableColumn(
                    "frequency",
                    sc.ScalarType(sc.QuantityType()),
                ),
            )
        ),
    )
    derived = table.with_columns(
        lambda row: {
            "invalid_frequency": sc.parameter_lookup(
                "device_parameters",
                key={"device": row["device"]},
                column="frequency",
                value_type=sc.ScalarType(sc.StringType()),
            )
        }
    )

    with pytest.raises(CheckFailed) as error:
        _resolve_dependency(derived, _config_with_parameter_table())

    assert error.value.problems[0].code == ("authoring_parameter_column_type_mismatch")
