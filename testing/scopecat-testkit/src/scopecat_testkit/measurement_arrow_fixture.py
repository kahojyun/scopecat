"""Cross-language fixture for the UI measurement Arrow decoder."""

from __future__ import annotations

from datetime import UTC, datetime

from scopecat.kernel.entity import EntityRef
from scopecat.measurements.recording_arrow import encode_measurement_append
from scopecat.records.measurement import (
    EntityAcquisitionEvidence,
    InstrumentAcquisitionEvidence,
    MeasurementAcquisitionEvidenceCatalog,
    MeasurementArray,
    MeasurementArrayAvailability,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementEntityAcquisition,
    MeasurementEntityIndex,
    MeasurementEntityProductSource,
    MeasurementPartitionedArray,
    MeasurementPointCloudPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementSegmentedArray,
    MeasurementUnavailable,
    MeasurementVariable,
)
from scopecat.records.measurement_recording import MeasurementDatasetAppend


def ui_measurement_arrow_fixture() -> bytes:
    """Encode one representative live record with the production codec."""

    run_id = "run-arrow-v10"
    event = InstrumentAcquisitionEvidence(
        command_id="collect-readout",
        instrument_id="scope",
        interface_id="test.waveform/v1",
        component_path=("channel", "1"),
        acquisition_id="readout-0",
        result_id="trace",
        started_at=datetime(2026, 8, 15, 9, 30, tzinfo=UTC),
        completed_at=datetime(2026, 8, 15, 9, 30, 1, tzinfo=UTC),
    )
    record = MeasurementRecord(
        run_id=run_id,
        logical_point_id="point-7",
        point_index=7,
        coordinates={
            "bias": MeasurementScalar.create(
                dtype="float64",
                unit="V",
                value=0.25,
                metadata={"source": "setpoint"},
            )
        },
        observables={
            "trace": MeasurementPartitionedArray.create(
                dtype="float64",
                unit="V",
                axis=0,
                partitions=(
                    MeasurementArray.create(
                        dtype="float64",
                        unit="V",
                        values=[1.5],
                    ),
                    MeasurementArray.create(
                        dtype="float64",
                        unit="V",
                        values=[0.0],
                        availability=MeasurementArrayAvailability.create(
                            valid=[False],
                            reason="invalid",
                            metadata={"sample": 1},
                        ),
                    ),
                ),
                metadata={"channel": 1},
            ),
            "entity_trace": MeasurementSegmentedArray.create(
                dtype="float64",
                unit="V",
                segments=(
                    MeasurementArray.create(
                        dtype="float64",
                        unit="V",
                        values=[4.0, 0.0],
                        availability=MeasurementArrayAvailability.create(
                            valid=[True, False],
                            reason="overload",
                            metadata={"entity": "q0"},
                        ),
                        metadata={"entity": "q0"},
                    ),
                    MeasurementUnavailable.create(
                        reason="missing",
                        dtype="float64",
                        unit="V",
                        shape=(None,),
                        metadata={"entity": "q1"},
                    ),
                ),
                metadata={"layout": "entity-ragged"},
            ),
            "missing": MeasurementUnavailable.create(
                reason="overload",
                dtype="float64",
                unit="V",
                shape=(None,),
                metadata={"status_register": 4},
            ),
        },
        acquisition_evidence=MeasurementAcquisitionEvidenceCatalog.create(
            {
                "trace": event,
                "entity_trace": EntityAcquisitionEvidence(
                    dimension_id="qubit",
                    acquisition=MeasurementEntityAcquisition(
                        policy="best_effort",
                        cohort_id="readout-batch",
                    ),
                    values=(event.model_copy(update={"result_id": "q0"}), None),
                ),
            }
        ),
        metadata={"note": "Python Arrow v10 fixture"},
    )
    append = MeasurementDatasetAppend(
        run_id=run_id,
        header_content_hash="sha256:ui-arrow-fixture",
        acquisition_start=7,
        records=(record,),
    )
    return encode_measurement_append(append, ui_measurement_arrow_fixture_schema())


def ui_measurement_arrow_fixture_schema() -> MeasurementDatasetSchema:
    """Return the schema embedded in :func:`ui_measurement_arrow_fixture`."""

    entities = (
        EntityRef(id="q0", kind="qubit", metadata={"label": "Q0"}),
        EntityRef(id="q1", kind="qubit", metadata={"label": "Q1"}),
    )
    return MeasurementDatasetSchema(
        dataset_id="ui-live-fixture",
        point_domain=MeasurementPointCloudPointDomain(columns=()),
        dimensions=(
            MeasurementDimension(id="point", kind="point", size=8),
            MeasurementDimension(id="sample", kind="record_axis", size=2),
            MeasurementDimension(
                id="qubit",
                kind="entity",
                size=2,
                index=MeasurementEntityIndex(values=entities),
            ),
            MeasurementDimension(
                id="entity_sample",
                kind="record_axis",
                size=None,
            ),
            MeasurementDimension(id="ragged", kind="record_axis", size=None),
        ),
        variables=(
            MeasurementVariable(
                id="bias",
                role="coordinate",
                dtype="float64",
                unit="V",
                dims=("point",),
            ),
            MeasurementVariable(
                id="trace",
                role="observable",
                dtype="float64",
                unit="V",
                dims=("point", "sample"),
            ),
            MeasurementVariable(
                id="entity_trace",
                role="observable",
                dtype="float64",
                unit="V",
                dims=("point", "qubit", "entity_sample"),
                entity_acquisition=MeasurementEntityAcquisition(
                    policy="best_effort",
                    cohort_id="readout-batch",
                ),
                source_entity_products=MeasurementEntityProductSource(
                    dimension_id="qubit",
                    product_ids=("readout/q0", "readout/q1"),
                ),
            ),
            MeasurementVariable(
                id="missing",
                role="observable",
                dtype="float64",
                unit="V",
                dims=("point", "ragged"),
            ),
        ),
        primary_coordinates=("bias",),
        primary_observables=("trace", "entity_trace"),
    )


__all__ = ["ui_measurement_arrow_fixture", "ui_measurement_arrow_fixture_schema"]
