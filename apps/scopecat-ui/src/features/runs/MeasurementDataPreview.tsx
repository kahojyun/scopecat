import { useMemo } from "react";
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
        <div
          className="grid gap-2.5 border-b border-line p-2.5 xl:grid-cols-2"
          data-testid="measurement-charts"
        >
          {charts.map((chart) => (
            <MeasurementChart chart={chart} key={chart.id} />
          ))}
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
  const [xMin, xMax] = paddedExtent(points.map((point) => point.x));
  const [yMin, yMax] = paddedExtent(points.map((point) => point.y));
  const x = (value: number) =>
    margin.left + ((value - xMin) / (xMax - xMin)) * (width - margin.left - margin.right);
  const y = (value: number) =>
    height -
    margin.bottom -
    ((value - yMin) / (yMax - yMin)) * (height - margin.top - margin.bottom);
  const xTicks = ticks(xMin, xMax);
  const yTicks = ticks(yMin, yMax);
  return (
    <figure className="m-0 min-w-0 rounded-md border border-line bg-panel-soft p-2.5">
      <figcaption className="mb-1.5 flex flex-wrap items-start justify-between gap-2">
        <span>
          <strong className="block text-[0.7rem] text-text-soft">{chart.title}</strong>
          <span className="text-[0.58rem] text-text-dim">
            {chart.xLabel} → {chart.yLabel}
          </span>
        </span>
        <span className="rounded border border-line px-1.5 py-1 text-[0.52rem] font-bold tracking-[0.05em] text-text-dim uppercase">
          {chart.kind}
        </span>
      </figcaption>
      <svg
        aria-label={`${chart.title}: ${chart.yLabel} by ${chart.xLabel}`}
        className="block h-auto w-full"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <title>{`${chart.title}: ${chart.yLabel} by ${chart.xLabel}`}</title>
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
              {series.points.map((point, pointIndex) => (
                <circle
                  cx={x(point.x)}
                  cy={y(point.y)}
                  fill={color}
                  key={`${series.id}:${pointIndex}`}
                  r={chart.kind === "scatter" ? 3.5 : 2.5}
                >
                  <title>{`${series.label}: ${shortNumber(point.x)}, ${shortNumber(point.y)}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
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

function ticks(minimum: number, maximum: number): number[] {
  return Array.from({ length: 4 }, (_item, index) => minimum + ((maximum - minimum) * index) / 3);
}

function shortNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(value);
}
