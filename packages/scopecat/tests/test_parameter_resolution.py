from scopecat._parameter_resolution import (
    resolve_config_parameters,
    validate_parameter_snapshot,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    Quantity,
    ScalarParameterValue,
    SeriesParameterValue,
    TableParameterValue,
)
from scopecat.problems import ModelLocation, Problem
from scopecat.value_types import Bool, Float, Scalar, Series, String, Table, TableColumn
from scopecat.value_types import Quantity as QuantityType
from tests.support.authoring import load_config


def test_resolve_config_parameters_reports_missing_unknown_and_invalid_values() -> None:
    resolved = resolve_config_parameters(
        _config(
            catalog=ParameterCatalog(
                id="catalog",
                definitions=[
                    ParameterDefinition(
                        id="drive_frequency",
                        value_type=Scalar(
                            QuantityType(unit="GHz", minimum=4.0, maximum=6.0)
                        ),
                    ),
                    ParameterDefinition(
                        id="readout_frequency",
                        value_type=Scalar(QuantityType(unit="GHz")),
                    ),
                ],
            ),
            parameter_snapshot=ParameterSnapshot(
                id="snapshot",
                values=[
                    ScalarParameterValue(
                        id="drive_frequency",
                        value=Quantity(value=7000, unit="MHz"),
                    ),
                    ScalarParameterValue(
                        id="orphan",
                        value=Quantity(value=5.0, unit="GHz"),
                    ),
                ],
            ),
        )
    )

    assert _codes(resolved.problems) == [
        "missing_parameter_value",
        "invalid_parameter_quantity",
        "unknown_parameter_definition",
    ]
    assert resolved.problems[0].location == ModelLocation(
        root="parameter_snapshot",
        path=("values",),
    )
    assert resolved.data.scalars == {}


def test_resolve_config_parameters_normalizes_scalar_series_and_table() -> None:
    catalog = ParameterCatalog(
        id="catalog",
        definitions=[
            ParameterDefinition(
                id="gain",
                value_type=Scalar(Float(minimum=0.0, maximum=1.0)),
            ),
            ParameterDefinition(
                id="enabled",
                value_type=Scalar(Bool()),
            ),
            ParameterDefinition(
                id="notes",
                value_type=Series(Scalar(String()), min_length=1),
            ),
            ParameterDefinition(
                id="channels",
                value_type=Table(
                    columns=(
                        TableColumn("id", Scalar(String(pattern=r"ch-\d+"))),
                        TableColumn("gain", Scalar(Float(minimum=0.0, maximum=1.0))),
                    ),
                    primary_key=("id",),
                ),
            ),
        ],
    )
    snapshot = ParameterSnapshot(
        id="snapshot",
        values=[
            ScalarParameterValue(id="gain", value=1),
            ScalarParameterValue(id="enabled", value=True),
            SeriesParameterValue(id="notes", items=["ready"]),
            TableParameterValue(
                id="channels",
                rows=[{"id": "ch-1", "gain": 0.5}],
            ),
        ],
    )

    resolved = resolve_config_parameters(
        _config(catalog=catalog, parameter_snapshot=snapshot)
    )

    assert resolved.problems == ()
    assert resolved.data.scalars == {"gain": 1.0, "enabled": True}
    assert resolved.data.series_values("notes") == ["ready"]
    assert resolved.data.table_rows("channels") == [{"id": "ch-1", "gain": 0.5}]
    assert validate_parameter_snapshot(catalog, snapshot) == ()


def test_validate_parameter_snapshot_checks_shape_length_and_table_keys() -> None:
    catalog = ParameterCatalog(
        id="catalog",
        definitions=[
            ParameterDefinition(
                id="series",
                value_type=Series(Scalar(String()), min_length=2),
            ),
            ParameterDefinition(
                id="table",
                value_type=Table(
                    columns=(TableColumn("id", Scalar(String())),),
                    primary_key=("id",),
                ),
            ),
        ],
    )

    shape_problems = validate_parameter_snapshot(
        catalog,
        ParameterSnapshot(
            id="wrong-shape",
            values=[
                ScalarParameterValue(id="series", value="value"),
                TableParameterValue(
                    id="table",
                    rows=[{"id": "same"}, {"id": "same"}],
                ),
            ],
        ),
    )
    assert _codes(shape_problems) == [
        "parameter_shape_mismatch",
        "duplicate_parameter_table_primary_key",
    ]

    length_problems = validate_parameter_snapshot(
        catalog,
        ParameterSnapshot(
            id="short",
            values=[
                SeriesParameterValue(id="series", items=["only"]),
                TableParameterValue(id="table", rows=[{"id": "unique"}]),
            ],
        ),
    )
    assert _codes(length_problems) == ["parameter_length_out_of_bounds"]


def test_parameter_problem_locations_preserve_dotted_ids_as_segments() -> None:
    catalog = ParameterCatalog(
        id="catalog",
        definitions=[
            ParameterDefinition(
                id="drive.frequency",
                value_type=Scalar(Float()),
            ),
            ParameterDefinition(
                id="calibration",
                value_type=Table(
                    columns=(TableColumn("readout.gain", Scalar(Float())),),
                ),
            ),
        ],
    )
    snapshot = ParameterSnapshot(
        id="snapshot",
        values=[
            ScalarParameterValue(id="drive.frequency", value="invalid"),
            TableParameterValue(
                id="calibration",
                rows=[{"readout.gain": "invalid"}],
            ),
        ],
    )

    problems = validate_parameter_snapshot(catalog, snapshot)

    assert [problem.location for problem in problems] == [
        ModelLocation(
            root="parameter_snapshot",
            path=("values", "drive.frequency", "value"),
        ),
        ModelLocation(
            root="parameter_snapshot",
            path=("values", "calibration", "rows", 0, "readout.gain"),
        ),
    ]


def _config(
    *,
    catalog: ParameterCatalog,
    parameter_snapshot: ParameterSnapshot,
) -> ConfigProfileSnapshot:
    config = load_config()
    system = config.system.model_copy(update={"parameter_catalog": catalog})
    return config.model_copy(
        update={"system": system, "parameter_snapshot": parameter_snapshot}
    )


def _codes(problems: tuple[Problem, ...]) -> list[str]:
    return [problem.code for problem in problems]
