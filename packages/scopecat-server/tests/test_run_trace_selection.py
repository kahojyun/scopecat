from scopecat.records.measurement import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementPointCloudPointDomain,
)

from scopecat_server.services.runs import _trace_preview_point_indices


def test_open_point_cloud_trace_uses_current_durable_record_count() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        point_domain=MeasurementPointCloudPointDomain(columns=()),
        dimensions=(MeasurementDimension(id="point", kind="point", size=None),),
    )

    indices, selected_count = _trace_preview_point_indices(
        schema,
        {},
        offset=1,
        limit=2,
        available_point_count=5,
    )

    assert indices == (1, 2)
    assert selected_count == 5
