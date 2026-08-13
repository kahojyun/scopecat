import { useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { MeasurementTracePreview } from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import type { MeasurementPreview, MeasurementSlicePreview } from "../../types";
import { EChart } from "../../ui/EChart";
import { measurementChartOption } from "./chart-options";
import {
  measurementTable,
  measurementSlicePlan,
  measurementSliceAxisValue,
  measurementSliceAxisValueIsDuplicated,
  measurementTraceChart,
  measurementTraceStatus,
  planMeasurementCharts,
  type MeasurementChartPlan,
  type MeasurementSliceAxis,
  type MeasurementTraceQueryPlan,
} from "./measurement-visualization";

const MAX_SLICE_SELECT_OPTIONS = 256;

export function MeasurementDataPreview({
  preview,
  slice,
  sliceError,
  slicePending,
  fixedAxisIndices,
  onFixedAxisIndexChange,
  tracePlans = [],
  selectedTracePlanId,
  tracePreview,
  tracePending = false,
  traceError = null,
  onTracePlanChange,
}: {
  preview: MeasurementPreview;
  slice?: MeasurementSlicePreview;
  sliceError: Error | null;
  slicePending: boolean;
  fixedAxisIndices: Record<string, number>;
  onFixedAxisIndexChange: (axisId: string, index: number) => void;
  tracePlans?: MeasurementTraceQueryPlan[];
  selectedTracePlanId?: string;
  tracePreview?: MeasurementTracePreview;
  tracePending?: boolean;
  traceError?: Error | null;
  onTracePlanChange?: (planId: string) => void;
}) {
  const slicePlan = useMemo(() => measurementSlicePlan(preview.schema), [preview.schema]);
  const chartSchema = slice?.schema ?? preview.schema;
  const charts = useMemo(() => {
    if (!slicePlan) return planMeasurementCharts(preview.items, preview.schema);
    return planMeasurementCharts(
      slice?.truncated ? [] : (slice?.items ?? []),
      chartSchema,
      fixedAxisIndices,
    );
  }, [chartSchema, fixedAxisIndices, preview.items, preview.schema, slice, slicePlan]);
  const [requestedChartId, setRequestedChartId] = useState<string>();
  const selectedChart = charts.find((chart) => chart.id === requestedChartId) ?? charts[0];
  const selectedTracePlan =
    tracePlans.find((plan) => plan.id === selectedTracePlanId) ?? tracePlans[0];
  const traceChart = useMemo(
    () => (tracePending || traceError ? undefined : measurementTraceChart(tracePreview)),
    [traceError, tracePending, tracePreview],
  );
  const table = useMemo(
    () => measurementTable(preview.items, preview.schema),
    [preview.items, preview.schema],
  );
  return (
    <div className="mt-3 overflow-hidden rounded-md border border-line bg-panel">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2 text-[0.61rem] font-bold tracking-[0.06em] text-text-dim uppercase">
        <strong className="text-[0.65rem] text-text-soft">Measurement data</strong>
        <span>
          {preview.recordCount ?? preview.items.length}
          {preview.truncated ? "+" : ""} records · {preview.schema ? "Schema" : "Live"}
        </span>
      </div>

      {preview.livePointIndex !== undefined && (
        <div className="border-b border-line bg-blue-soft px-3 py-2 text-[0.61rem] text-blue">
          Point {preview.livePointIndex + 1} is visible from daemon memory and is not durable yet.
        </div>
      )}

      {slicePlan && (
        <div
          className="flex flex-wrap items-end justify-between gap-2 border-b border-line bg-panel-soft px-3 py-2"
          data-testid="measurement-slice-controls"
        >
          <div className="flex flex-wrap items-end gap-2">
            {slicePlan.fixedAxes.map((axis) => {
              const selectedIndex = fixedAxisIndices[axis.id] ?? 0;
              return (
                <label
                  className="grid gap-1 text-[0.56rem] font-bold tracking-[0.04em] text-text-dim uppercase"
                  key={axis.id}
                >
                  {axis.label} slice
                  {axis.size <= MAX_SLICE_SELECT_OPTIONS ? (
                    <select
                      aria-label={`${axis.label} slice`}
                      className="min-w-28 rounded border border-line bg-panel px-2 py-1 text-[0.62rem] font-medium tracking-normal text-text-soft normal-case"
                      value={selectedIndex}
                      onChange={(event) =>
                        onFixedAxisIndexChange(axis.id, Number(event.target.value))
                      }
                    >
                      {Array.from({ length: axis.size }, (_value, index) => (
                        <option key={index} value={index}>
                          {sliceAxisOption(axis, index)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <>
                      <input
                        aria-label={`${axis.label} slice index`}
                        className="w-28 rounded border border-line bg-panel px-2 py-1 text-[0.62rem] font-medium tracking-normal text-text-soft normal-case"
                        max={axis.size}
                        min={1}
                        type="number"
                        value={selectedIndex + 1}
                        onChange={(event) => {
                          const index = Number(event.target.value) - 1;
                          if (Number.isInteger(index) && index >= 0 && index < axis.size) {
                            onFixedAxisIndexChange(axis.id, index);
                          }
                        }}
                      />
                      <span className="max-w-52 truncate font-medium tracking-normal text-text-soft normal-case">
                        {sliceAxisOption(axis, selectedIndex)} · {axis.size.toLocaleString()} values
                      </span>
                    </>
                  )}
                </label>
              );
            })}
          </div>
          <span className="inline-flex items-center gap-1.5 text-[0.58rem] text-text-dim">
            {slicePending && <LoaderCircle className="animate-spin" size={12} aria-hidden="true" />}
            {sliceStatus(slice, sliceError, slicePending)}
          </span>
        </div>
      )}

      {tracePlans.length > 0 && (
        <div className="border-b border-line p-2.5" data-testid="measurement-trace-preview">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2 text-[0.59rem] text-text-dim">
            <label className="flex items-center gap-2 font-bold tracking-[0.04em] uppercase">
              Trace
              <select
                aria-label="Measurement trace"
                className="max-w-[min(70vw,420px)] rounded border border-line bg-panel px-2 py-1 text-[0.62rem] font-medium tracking-normal text-text-soft normal-case"
                onChange={(event) => onTracePlanChange?.(event.target.value)}
                value={selectedTracePlan?.id ?? ""}
              >
                {tracePlans.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.label}
                  </option>
                ))}
              </select>
            </label>
            <span
              className="inline-flex items-center gap-1.5"
              role={traceError ? "alert" : "status"}
            >
              {tracePending && (
                <LoaderCircle className="animate-spin" size={12} aria-hidden="true" />
              )}
              {tracePreviewStatus(tracePreview, traceError, tracePending)}
            </span>
          </div>
          {traceChart && <MeasurementChart chart={traceChart} />}
          {!tracePending && !traceError && tracePreview && !traceChart && (
            <p className="m-0 text-[0.62rem] text-text-dim">
              No durable or available series were returned for this bounded selection.
            </p>
          )}
        </div>
      )}

      {charts.length > 0 ? (
        <div className="border-b border-line p-2.5" data-testid="measurement-charts">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2 text-[0.59rem] text-text-dim">
            <span>
              {charts.length} chart {charts.length === 1 ? "candidate" : "candidates"}
            </span>
            {charts.length > 1 && (
              <label className="flex items-center gap-2 font-bold tracking-[0.04em] uppercase">
                Chart
                <select
                  aria-label="Measurement chart"
                  className="max-w-[min(70vw,420px)] rounded border border-line bg-panel px-2 py-1 text-[0.62rem] font-medium tracking-normal text-text-soft normal-case"
                  onChange={(event) => setRequestedChartId(event.target.value)}
                  value={selectedChart?.id ?? ""}
                >
                  {charts.map((chart) => (
                    <option key={chart.id} value={chart.id}>
                      {chartOptionLabel(chart)}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {selectedChart && <MeasurementChart chart={selectedChart} />}
        </div>
      ) : tracePlans.length === 0 ? (
        <p className="m-0 border-b border-line px-3 py-2.5 text-[0.67rem] leading-normal text-text-dim">
          {emptyChartMessage({
            usesSemanticSlice: slicePlan !== undefined,
            slice,
            sliceError,
            slicePending,
            preview,
          })}
        </p>
      ) : null}

      {(slicePlan || tracePlans.length > 0) && (
        <p className="m-0 border-b border-line bg-panel-soft px-3 py-1.5 text-[0.56rem] text-text-dim">
          Heatmaps and point-scalar plots use the selected durable slice when available. Trace
          previews are bounded by the server for the selected authored domain; the table and raw
          view remain run-wide.
        </p>
      )}

      <div className="overflow-x-auto" data-testid="measurement-table">
        <table className="w-full min-w-max border-collapse text-left text-[0.66rem]">
          <thead className="bg-panel-soft text-[0.59rem] tracking-[0.06em] text-text-dim uppercase">
            <tr>
              {table.columns.map((column) => (
                <th
                  className="border-b border-line px-3 py-2 font-bold"
                  key={column.id}
                  scope="col"
                >
                  {column.label}
                  {column.role !== "point" && (
                    <span className="ml-1.5 text-[0.52rem] text-text-dim">{column.role}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr className="border-b border-line last:border-b-0" key={row.id}>
                {row.cells.map((cell, index) =>
                  index === 0 ? (
                    <th
                      className="px-3 py-2 font-mono font-medium text-text-soft"
                      key={index}
                      scope="row"
                    >
                      {cell}
                    </th>
                  ) : (
                    <td
                      className="max-w-[260px] truncate px-3 py-2 text-text-soft"
                      key={index}
                      title={cell}
                    >
                      {cell}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="border-t border-line text-[0.64rem] text-text-dim">
        <summary className="cursor-pointer px-3 py-2 font-bold hover:text-text-soft">
          Raw records
        </summary>
        <pre
          className="m-0 max-h-[320px] overflow-auto border-t border-line bg-panel-soft p-3 text-[0.63rem] leading-[1.5] text-text-soft"
          data-testid="measurement-preview"
        >
          {JSON.stringify(preview.items, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function tracePreviewStatus(
  preview: MeasurementTracePreview | undefined,
  error: Error | null,
  pending: boolean,
): string {
  if (error) return `Trace unavailable: ${errorMessage(error)}`;
  if (pending) return "Reading bounded trace preview…";
  if (!preview) return "Waiting for bounded trace preview";
  return measurementTraceStatus(preview);
}

function sliceStatus(
  slice: MeasurementSlicePreview | undefined,
  error: Error | null,
  pending: boolean,
): string {
  if (error) return `Slice unavailable: ${errorMessage(error)}`;
  if (pending) return "Reading selected slice…";
  if (!slice) return "Waiting for selected slice";
  if (slice.truncated) {
    return `Slice has ${slice.selectedPointCount.toLocaleString()} points; automatic plots are limited to 4,096`;
  }
  return `${slice.items.length.toLocaleString()} of ${slice.selectedPointCount.toLocaleString()} slice points durable`;
}

function emptyChartMessage({
  usesSemanticSlice,
  slice,
  sliceError,
  slicePending,
  preview,
}: {
  usesSemanticSlice: boolean;
  slice?: MeasurementSlicePreview;
  sliceError: Error | null;
  slicePending: boolean;
  preview: MeasurementPreview;
}): string {
  if (usesSemanticSlice) {
    if (sliceError) return "The selected product-grid slice could not be read.";
    if (slicePending || !slice) return "Reading the selected product-grid slice before plotting.";
    if (slice.truncated) {
      return "The selected slice is too large for an automatic plot. Use a projected Arrow reader for analysis.";
    }
    if (slice.items.length < slice.selectedPointCount) {
      return `The selected slice is incomplete: ${slice.items.length.toLocaleString()} of ${slice.selectedPointCount.toLocaleString()} points are durable. The plot will appear when the grid is complete.`;
    }
  }
  if (preview.items.length === 0) {
    return "The schema is ready; plots will appear as measurement records become durable.";
  }
  return "No safe automatic plot is available for these variable shapes. The typed table remains available below.";
}

function sliceAxisOption(axis: MeasurementSliceAxis, index: number): string {
  const scalar = measurementSliceAxisValue(axis, index);
  if (!scalar) return `Index ${index + 1}`;
  const value =
    typeof scalar.value === "object"
      ? `${scalar.value.real}${scalar.value.imag < 0 ? "" : "+"}${scalar.value.imag}i`
      : String(scalar.value);
  const unit = scalar.unit ?? axis.unit;
  const duplicate = measurementSliceAxisValueIsDuplicated(axis, index);
  return `${value}${unit ? ` ${unit}` : ""}${duplicate ? ` · Index ${index + 1}` : ""}`;
}

function MeasurementChart({ chart }: { chart: MeasurementChartPlan }) {
  const points = chart.series.flatMap((series) => series.points);
  const option = useMemo(() => measurementChartOption(chart), [chart]);
  const fixedCoordinates =
    chart.kind === "heatmap" ? fixedCoordinatesLabel(chart.fixedCoordinates) : undefined;
  const chartDescription = chart.colorLabel
    ? `${chart.title}: ${chart.yLabel} by ${chart.xLabel}, colored by ${chart.colorLabel}`
    : `${chart.title}: ${chart.yLabel} by ${chart.xLabel}`;
  const accessibleTitle = fixedCoordinates
    ? `${chartDescription}, fixed at ${fixedCoordinates}`
    : chartDescription;
  return (
    <figure className="m-0 min-w-0 rounded-md border border-line bg-panel-soft p-2.5">
      <figcaption className="mb-1.5 flex flex-wrap items-start justify-between gap-2">
        <span>
          <strong className="block text-[0.7rem] text-text-soft">{chart.title}</strong>
          <span className="text-[0.58rem] text-text-dim">
            {chart.xLabel} → {chart.yLabel}
            {chart.colorLabel ? ` · color: ${chart.colorLabel}` : ""}
            {fixedCoordinates ? ` · fixed: ${fixedCoordinates}` : ""}
          </span>
        </span>
        <span className="rounded border border-line px-1.5 py-1 text-[0.52rem] font-bold tracking-[0.05em] text-text-dim uppercase">
          {chart.kind.replace("-", " ")}
        </span>
      </figcaption>
      <EChart
        ariaLabel={accessibleTitle}
        height={chart.colorLabel ? 270 : 240}
        option={option}
        pointCount={points.length}
        seriesLabels={chart.series.map((series) => series.label)}
        seriesCount={chart.series.length}
      />
      {chart.note && <p className="mt-1.5 mb-0 text-[0.56rem] text-text-dim">{chart.note}</p>}
    </figure>
  );
}

function chartOptionLabel(chart: MeasurementChartPlan): string {
  const color = chart.colorLabel ? ` · color: ${chart.colorLabel}` : "";
  const fixed =
    chart.kind === "heatmap" && chart.fixedCoordinates.length > 0
      ? ` · fixed: ${fixedCoordinatesLabel(chart.fixedCoordinates)}`
      : "";
  return `${chart.title} — x: ${chart.xLabel} · y: ${chart.yLabel}${color}${fixed}`;
}

function fixedCoordinatesLabel(
  coordinates: Extract<MeasurementChartPlan, { kind: "heatmap" }>["fixedCoordinates"],
): string | undefined {
  if (coordinates.length === 0) return undefined;
  return coordinates
    .map(
      (coordinate) =>
        `${coordinate.label}=${fixedCoordinateValueLabel(coordinate)}${coordinate.value !== undefined && coordinate.unit ? ` ${coordinate.unit}` : ""}`,
    )
    .join(", ");
}

function fixedCoordinateValueLabel(
  coordinate: Extract<MeasurementChartPlan, { kind: "heatmap" }>["fixedCoordinates"][number],
): string {
  const value = coordinate.value;
  if (value === undefined) return `Index ${coordinate.index! + 1}`;
  const rendered =
    typeof value === "boolean"
      ? value
        ? "true"
        : "false"
      : typeof value === "number"
        ? shortNumber(value)
        : typeof value === "string"
          ? JSON.stringify(value)
          : `${shortNumber(value.real)} ${value.imag < 0 ? "−" : "+"} ${shortNumber(Math.abs(value.imag))}i`;
  return coordinate.disambiguateIndex ? `${rendered} (Index ${coordinate.index! + 1})` : rendered;
}

function shortNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(value);
}
