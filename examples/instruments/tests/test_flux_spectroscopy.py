from __future__ import annotations

from pathlib import Path

import pytest
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.instrument_host import compose_test_instruments

import scopecat as sc
from instrument_demo.configuration import (
    RESONANCE_FREQUENCY_PARAMETER_ID,
    RESONATOR_LINEWIDTH_PARAMETER_ID,
    bootstrap_config,
)
from instrument_demo.provider import FLUX_SOURCE_ID, InstrumentDemoProvider
from instrument_demo.workflows.flux_spectroscopy import (
    BIAS_POINTS,
    TRACE_POINTS,
    flux_spectroscopy_template,
)
from instrument_demo.workflows.flux_spectroscopy_analysis import (
    fit_flux_spectroscopy,
    flux_spectroscopy_analysis,
)
from scopecat.kernel.errors import RunIndeterminate
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementScalar,
)
from scopecat.records.parameter import ScalarParameterValue
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverOutcome,
    DriverReadback,
)
from scopecat_instruments.virtual import VirtualNetworkAnalyzer


def test_flux_spectroscopy_runs_fits_saves_and_proposes(tmp_path: Path) -> None:
    provider = InstrumentDemoProvider(seed=7)
    config = bootstrap_config()
    composition = compose_test_instruments(config=config, provider=provider)
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )

    prepared = lab.prepare(flux_spectroscopy_template())
    preview = prepared.preview()
    run = prepared.run()

    assert preview.point_count == BIAS_POINTS
    assert preview.coordinate_ids == ("dc_bias",)
    assert preview.primary_observables == ("s_parameter", "temperature")
    assert preview.schema is not None
    assert preview.schema.primary_coordinates == ["dc_bias", "frequency"]
    dimensions = {dimension.id: dimension for dimension in preview.schema.dimensions}
    assert dimensions["shared/capture/frequency_sample"].label == "frequency_sample"
    variables = {variable.id: variable for variable in preview.schema.variables}
    assert variables["dc_bias"].role == "coordinate"
    assert variables["dc_bias"].dims == ["point"]
    assert variables["frequency"].role == "coordinate"
    assert variables["frequency"].dims == [
        "point",
        "shared/capture/frequency_sample",
    ]
    assert variables["s_parameter"].role == "observable"
    assert variables["s_parameter"].dims == [
        "point",
        "shared/capture/frequency_sample",
    ]
    assert variables["temperature"].role == "observable"
    assert variables["temperature"].dims == ["point"]
    preview_records = {record.id: record for record in preview.records}
    assert preview_records["frequency"].role == "coordinate"
    assert preview_records["frequency"].dims == (
        "point",
        "shared/capture/frequency_sample",
    )
    assert preview_records["s_parameter"].role == "observable"
    assert preview_records["s_parameter"].dims == (
        "point",
        "shared/capture/frequency_sample",
    )
    assert preview_records["temperature"].role == "observable"
    assert preview_records["temperature"].dims == ("point",)
    assert run.manifest.status == "completed"
    records = run.data().measurements().dataset.records
    assert len(records) == BIAS_POINTS
    assert all(
        set(record.coordinates) == {"dc_bias", "frequency"}
        and set(record.observables) == {"s_parameter", "temperature"}
        for record in records
    )
    assert all(
        isinstance(record.coordinates["frequency"], MeasurementArray)
        and record.coordinates["frequency"].shape == (TRACE_POINTS,)
        and record.coordinates["frequency"].dtype == "float64"
        and record.coordinates["frequency"].unit == "Hz"
        and isinstance(record.observables["s_parameter"], MeasurementArray)
        and record.observables["s_parameter"].shape == (TRACE_POINTS,)
        and record.observables["s_parameter"].dtype == "complex128"
        and record.observables["s_parameter"].unit == "ratio"
        and all(
            isinstance(sample, ComplexComponents)
            for sample in record.observables["s_parameter"].values
        )
        and isinstance(record.observables["temperature"], MeasurementScalar)
        and record.observables["temperature"].unit == "K"
        for record in records
    )
    assert not provider.world.dc_source(FLUX_SOURCE_ID).output_enabled

    fits = fit_flux_spectroscopy(records)
    sweet_spot = max(
        fits,
        key=lambda fit: float(fit.resonance_frequency.to("Hz").value),
    )
    assert float(sweet_spot.dc_bias.to("V").value) == pytest.approx(0.0, abs=1.0e-12)
    assert float(sweet_spot.resonance_frequency.to("GHz").value) == pytest.approx(
        5.06,
        abs=0.001,
    )
    assert float(sweet_spot.linewidth.to("MHz").value) == pytest.approx(
        1.0,
        rel=0.2,
    )

    analysis = run.analyze(flux_spectroscopy_analysis())
    saved = analysis.save()
    candidate = lab.resolve_config(config=analysis.candidate_config())
    assert saved.record.id == "analysis-instrument_demo-flux_spectroscopy-analysis"
    assert [output.kind for output in analysis.outputs] == [
        "table",
        "table",
        "figure",
        "parameter_change_proposal",
    ]
    fitted_frequency = _scalar_quantity(
        candidate,
        RESONANCE_FREQUENCY_PARAMETER_ID,
    )
    fitted_linewidth = _scalar_quantity(
        candidate,
        RESONATOR_LINEWIDTH_PARAMETER_ID,
    )
    assert float(fitted_frequency.to("GHz").value) == pytest.approx(5.06, abs=0.001)
    assert float(fitted_linewidth.to("MHz").value) == pytest.approx(1.0, rel=0.2)
    active_frequency = _scalar_quantity(
        lab.resolve_config(),
        RESONANCE_FREQUENCY_PARAMETER_ID,
    )
    assert float(active_frequency.to("GHz").value) == pytest.approx(5.0)


def test_flux_spectroscopy_failure_aborts_with_bias_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_collect(
        _driver: VirtualNetworkAnalyzer,
        _request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        raise RuntimeError("injected VNA acquisition failure")

    monkeypatch.setattr(VirtualNetworkAnalyzer, "collect", fail_collect)
    provider = InstrumentDemoProvider(seed=7)
    config = bootstrap_config()
    composition = compose_test_instruments(config=config, provider=provider)
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )

    with pytest.raises(RunIndeterminate):
        lab.prepare(flux_spectroscopy_template()).run()

    [run] = lab.runs()
    assert run.manifest.status == "unknown"
    assert not provider.world.dc_source(FLUX_SOURCE_ID).output_enabled


def _scalar_quantity(
    config: ConfigProfileSnapshot,
    parameter_id: str,
) -> sc.Quantity:
    value = config.parameter_snapshot.get(parameter_id)
    assert isinstance(value, ScalarParameterValue)
    assert isinstance(value.value, sc.Quantity)
    return value.value
