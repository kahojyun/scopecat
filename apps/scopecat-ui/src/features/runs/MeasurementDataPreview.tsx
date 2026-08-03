import { useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";
import type { MeasurementPreview } from "../../types";
import { classes, secondaryButton } from "../../ui/styles";
import {
  measurementTable,
  planMeasurementCharts,
  type MeasurementChartPlan,
} from "./measurement-visualization";

const SERIES_COLORS = [
  "var(--color-accent)",
  "var(--color-yellow)",
  "var(--color-purple)",
  "var(--color-red)",
  "var(--color-text-soft)",
  "#77b6a8",
];

export function MeasurementDataPreview({
  preview,
  hasMore,
  loadingMore,
  onLoadMore,
}: {
  preview: MeasurementPreview;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}) {
  const charts = useMemo(
    () => planMeasurementCharts(preview.items, preview.schema),
    [preview.items, preview.schema],
  );
  const [requestedChartId, setRequestedChartId] = useState<string>();
  const selectedChart = charts.find((chart) => chart.id === requestedChartId) ?? charts[0];
  const table = useMemo(
    () => measurementTable(preview.items, preview.schema),
    [preview.items, preview.schema],
  );
  return (
    <div className="mt-3 overflow-hidden rounded-md border border-line bg-panel">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2 text-[0.61rem] font-bold tracking-[0.06em] text-text-dim uppercase">
        <strong className="text-[0.65rem] text-text-soft">Measurement data</strong>
        <span>
          {preview.items.length}
          {preview.nextOffset !== undefined ? "+" : ""} records ·{" "}
          {preview.schema ? "Schema" : "Live"}
        </span>
      </div>

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
      ) : (
        <p className="m-0 border-b border-line px-3 py-2.5 text-[0.67rem] leading-normal text-text-dim">
          No safe automatic plot is available for these variable shapes. The typed table remains
          available below.
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

      {hasMore && (
        <div className="flex justify-center border-t border-line px-2.5 py-[9px]">
          <button
            className={classes(secondaryButton, "w-full")}
            type="button"
            disabled={loadingMore}
            onClick={onLoadMore}
          >
            {loadingMore && <LoaderCircle className="animate-spin" size={14} aria-hidden="true" />}
            {loadingMore ? "Loading measurements…" : "Load more measurements"}
          </button>
        </div>
      )}
    </div>
  );
}

function MeasurementChart({ chart }: { chart: MeasurementChartPlan }) {
  const width = 640;
  const height = 230;
  const margin = { top: 16, right: 18, bottom: 38, left: 54 };
  const points = chart.series.flatMap((series) => series.points);
  const xBoundaries = chart.kind === "heatmap" ? cellBoundaries(chart.grid.xValues) : undefined;
  const yBoundaries = chart.kind === "heatmap" ? cellBoundaries(chart.grid.yValues) : undefined;
  const [xMin, xMax] = xBoundaries
    ? [xBoundaries[0]!, xBoundaries.at(-1)!]
    : paddedExtent(points.map((point) => point.x));
  const [yMin, yMax] = yBoundaries
    ? [yBoundaries[0]!, yBoundaries.at(-1)!]
    : paddedExtent(points.map((point) => point.y));
  const x = (value: number) =>
    margin.left + ((value - xMin) / (xMax - xMin)) * (width - margin.left - margin.right);
  const y = (value: number) =>
    height -
    margin.bottom -
    ((value - yMin) / (yMax - yMin)) * (height - margin.top - margin.bottom);
  const xTicks = ticks(xMin, xMax);
  const yTicks = ticks(yMin, yMax);
  const colorValues = points.flatMap((point) => (point.color === undefined ? [] : [point.color]));
  const colorExtent = colorValues.length > 0 ? rawExtent(colorValues) : undefined;
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
      <svg
        aria-label={accessibleTitle}
        className="block h-auto w-full"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <title>{accessibleTitle}</title>
        {xTicks.map((tick) => (
          <g key={`x:${tick}`}>
            <line
              stroke="var(--color-line)"
              strokeWidth="1"
              x1={x(tick)}
              x2={x(tick)}
              y1={margin.top}
              y2={height - margin.bottom}
            />
            <text
              fill="var(--color-text-dim)"
              fontSize="10"
              textAnchor="middle"
              x={x(tick)}
              y={height - 18}
            >
              {shortNumber(tick)}
            </text>
          </g>
        ))}
        {yTicks.map((tick) => (
          <g key={`y:${tick}`}>
            <line
              stroke="var(--color-line)"
              strokeWidth="1"
              x1={margin.left}
              x2={width - margin.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              dominantBaseline="middle"
              fill="var(--color-text-dim)"
              fontSize="10"
              textAnchor="end"
              x={margin.left - 7}
              y={y(tick)}
            >
              {shortNumber(tick)}
            </text>
          </g>
        ))}
        {chart.series.map((series, index) => {
          const color = SERIES_COLORS[index % SERIES_COLORS.length] ?? "var(--color-accent)";
          const path = series.points
            .map(
              (point, pointIndex) => `${pointIndex === 0 ? "M" : "L"}${x(point.x)},${y(point.y)}`,
            )
            .join(" ");
          return (
            <g key={series.id}>
              {chart.kind === "line" && series.points.length > 1 && (
                <path d={path} fill="none" stroke={color} strokeWidth="2" />
              )}
              {chart.kind === "heatmap" &&
                colorExtent &&
                series.points.map((point, pointIndex) => {
                  const xIndex = chart.grid.xValues.indexOf(point.x);
                  const yIndex = chart.grid.yValues.indexOf(point.y);
                  const xStart = xBoundaries?.[xIndex];
                  const xEnd = xBoundaries?.[xIndex + 1];
                  const yStart = yBoundaries?.[yIndex];
                  const yEnd = yBoundaries?.[yIndex + 1];
                  if (
                    point.color === undefined ||
                    xStart === undefined ||
                    xEnd === undefined ||
                    yStart === undefined ||
                    yEnd === undefined
                  ) {
                    return null;
                  }
                  return (
                    <rect
                      data-testid="heatmap-cell"
                      fill={colorScale(point.color, colorExtent[0], colorExtent[1])}
                      height={y(yStart) - y(yEnd)}
                      key={`${series.id}:${pointIndex}`}
                      stroke="var(--color-panel-soft)"
                      strokeWidth="1"
                      width={x(xEnd) - x(xStart)}
                      x={x(xStart)}
                      y={y(yEnd)}
                    >
                      <title>
                        {`${series.label}: ${shortNumber(point.x)}, ${shortNumber(point.y)}, ${chart.colorLabel}: ${shortNumber(point.color)}`}
                      </title>
                    </rect>
                  );
                })}
              {chart.kind !== "heatmap" &&
                series.points.map((point, pointIndex) => (
                  <circle
                    cx={x(point.x)}
                    cy={y(point.y)}
                    fill={
                      colorExtent && point.color !== undefined
                        ? colorScale(point.color, colorExtent[0], colorExtent[1])
                        : color
                    }
                    key={`${series.id}:${pointIndex}`}
                    r={chart.kind === "line" ? 2.5 : chart.kind === "color-scatter" ? 4 : 3.5}
                  >
                    <title>
                      {`${series.label}: ${shortNumber(point.x)}, ${shortNumber(point.y)}${point.color === undefined || !chart.colorLabel ? "" : `, ${chart.colorLabel}: ${shortNumber(point.color)}`}`}
                    </title>
                  </circle>
                ))}
            </g>
          );
        })}
      </svg>
      {colorExtent && chart.colorLabel && (
        <div className="mt-1 flex items-center gap-2 text-[0.55rem] text-text-dim">
          <span>{shortNumber(colorExtent[0])}</span>
          <span
            aria-hidden="true"
            className="h-2 min-w-20 flex-1 rounded-sm"
            style={{
              background:
                "linear-gradient(90deg, hsl(260 70% 52%), hsl(155 65% 42%), hsl(50 85% 52%))",
            }}
          />
          <span>{shortNumber(colorExtent[1])}</span>
          <span className="font-medium text-text-soft">{chart.colorLabel}</span>
        </div>
      )}
      {chart.series.length > 1 && (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[0.55rem] text-text-dim">
          {chart.series.map((series, index) => (
            <span className="inline-flex items-center gap-1" key={series.id}>
              <span
                className="inline-block size-2 rounded-full"
                style={{ background: SERIES_COLORS[index % SERIES_COLORS.length] }}
              />
              {series.label}
            </span>
          ))}
        </div>
      )}
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
        `${coordinate.label}=${fixedCoordinateValueLabel(coordinate.value)}${coordinate.unit ? ` ${coordinate.unit}` : ""}`,
    )
    .join(", ");
}

function fixedCoordinateValueLabel(
  value: Extract<MeasurementChartPlan, { kind: "heatmap" }>["fixedCoordinates"][number]["value"],
): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return shortNumber(value);
  if (typeof value === "string") return JSON.stringify(value);
  const sign = value.imag < 0 ? "−" : "+";
  return `${shortNumber(value.real)} ${sign} ${shortNumber(Math.abs(value.imag))}i`;
}

function rawExtent(values: number[]): [number, number] {
  return [Math.min(...values), Math.max(...values)];
}

function colorScale(value: number, minimum: number, maximum: number): string {
  const position = maximum === minimum ? 0.5 : (value - minimum) / (maximum - minimum);
  const bounded = Math.min(1, Math.max(0, position));
  const hue = bounded < 0.5 ? 260 - bounded * 210 : 155 - (bounded - 0.5) * 210;
  const saturation = bounded < 0.5 ? 70 - bounded * 10 : 65 + (bounded - 0.5) * 40;
  const lightness = bounded < 0.5 ? 52 - bounded * 20 : 42 + (bounded - 0.5) * 20;
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
}

function paddedExtent(values: number[]): [number, number] {
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  if (minimum !== maximum) {
    const padding = (maximum - minimum) * 0.04;
    return [minimum - padding, maximum + padding];
  }
  const padding = Math.abs(minimum) * 0.04 || 1;
  return [minimum - padding, maximum + padding];
}

function cellBoundaries(values: number[]): number[] {
  const first = values[0]!;
  if (values.length === 1) {
    const halfWidth = Math.abs(first) * 0.04 || 1;
    return [first - halfWidth, first + halfWidth];
  }
  const second = values[1]!;
  const last = values.at(-1)!;
  const beforeLast = values.at(-2)!;
  return [
    first - (second - first) / 2,
    ...values.slice(0, -1).map((value, index) => (value + values[index + 1]!) / 2),
    last + (last - beforeLast) / 2,
  ];
}

function ticks(minimum: number, maximum: number): number[] {
  return Array.from({ length: 4 }, (_item, index) => minimum + ((maximum - minimum) * index) / 3);
}

function shortNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(value);
}
