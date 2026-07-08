"""Runtime execution setup checks derived before the cursor starts."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat._execution import parse_expected_dataset_schema
from scopecat._runtime.evidence import (
    raw_measurement_schema as build_raw_measurement_schema,
)
from scopecat._runtime.graph import RuntimeGraph
from scopecat._runtime.instruments import describe_instruments
from scopecat._runtime.validation import (
    runtime_graph_diagnostics,
    validate_runtime_graph_instruments,
)
from scopecat.diagnostics import Diagnostic
from scopecat.instruments.sdk import InstrumentDescription, InstrumentDriver
from scopecat.results import MeasurementDatasetSchema


@dataclass(frozen=True)
class RuntimeExecutionSetup:
    """Validated execution context needed before advancing runtime points."""

    instruments_by_id: dict[str, InstrumentDriver]
    descriptions: list[InstrumentDescription]
    descriptions_by_id: dict[str, InstrumentDescription]
    raw_measurement_schema: MeasurementDatasetSchema | None
    diagnostics: list[Diagnostic]


def prepare_runtime_execution(
    *,
    graph: RuntimeGraph,
    instruments: list[InstrumentDriver],
    preflight_diagnostics: list[Diagnostic],
) -> RuntimeExecutionSetup:
    instruments_by_id = {
        instrument.instrument_id: instrument for instrument in instruments
    }
    descriptions, description_diagnostics = describe_instruments(instruments)
    descriptions_by_id = {
        description.instrument_id: description for description in descriptions
    }
    expected_schema, schema_diagnostics = parse_expected_dataset_schema(
        graph.expected_dataset_schema
    )
    raw_measurement_schema = build_raw_measurement_schema(expected_schema)
    diagnostics = (
        preflight_diagnostics
        + runtime_graph_diagnostics(graph)
        + description_diagnostics
        + schema_diagnostics
        + validate_runtime_graph_instruments(
            graph=graph,
            instruments_by_id=instruments_by_id,
            descriptions=descriptions,
            payloads=graph.payloads_by_id,
        )
    )
    return RuntimeExecutionSetup(
        instruments_by_id=instruments_by_id,
        descriptions=descriptions,
        descriptions_by_id=descriptions_by_id,
        raw_measurement_schema=raw_measurement_schema,
        diagnostics=diagnostics,
    )


__all__ = [
    "RuntimeExecutionSetup",
    "prepare_runtime_execution",
]
