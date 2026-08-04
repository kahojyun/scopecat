import type { RunAnalysisOutput } from "../../types";

const SERIES_COLORS = [
  "#8ab4f8",
  "#c7a6ff",
  "#67d8b5",
  "#f2c66d",
  "#ff8c88",
  "#83d2f0",
  "#f69bc8",
  "#a9d66e",
  "#f4a261",
  "#9fa8ff",
  "#5fd1c8",
  "#d5a6bd",
  "#b8c0ff",
  "#ffb86b",
  "#76c893",
  "#e5989b",
];

export function AnalysisOutputView({ output }: { output: RunAnalysisOutput }) {
  let content;
  if (output.kind === "table") {
    content = <AnalysisTableView content={output.content} title={output.title} />;
  } else if (output.kind === "figure") {
    content = <AnalysisFigureView content={output.content} title={output.title} />;
  } else {
    content = (
      <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 p-[9px] text-[0.62rem]">
        <dt className="font-bold text-text-dim">Proposal</dt>
        <dd className="m-0 min-w-0 text-text-soft">
          <code>{output.content.proposal_id}</code>
        </dd>
        <dt className="font-bold text-text-dim">Record</dt>
        <dd className="m-0 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-text-soft">
          <code title={output.content.record_ref}>{output.content.record_ref}</code>
        </dd>
      </dl>
    );
  }

  return (
    <>
      {content}
      <AnalysisMetadataView metadata={output.metadata} />
    </>
  );
}

type TableContent = Extract<RunAnalysisOutput, { kind: "table" }>["content"];

function AnalysisTableView({ content, title }: { content: TableContent; title: string }) {
  return (
    <div className="max-h-72 overflow-auto" data-testid="analysis-table">
      <table className="w-full border-collapse text-left text-[0.61rem]" aria-label={title}>
        <thead className="sticky top-0 z-[1] bg-panel-strong text-text-dim">
          <tr>
            {content.columns.map((column) => (
              <th
                className="border-b border-line px-2.5 py-2 font-extrabold tracking-[0.025em] whitespace-nowrap"
                key={column.id}
                scope="col"
              >
                {column.label ?? column.id}
                {column.unit ? (
                  <>
                    {" "}
                    <span className="font-medium text-text-dim">({column.unit})</span>
                  </>
                ) : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(content.rows ?? []).map((row, rowIndex) => (
            <tr className="odd:bg-[rgb(255_255_255_/_1.4%)]" key={rowIndex}>
              {row.cells.map((cell, cellIndex) => (
                <td
                  className="border-b border-line px-2.5 py-2 font-mono text-text-soft last:border-r-0"
                  key={`${rowIndex}:${content.columns[cellIndex]?.id ?? cellIndex}`}
                  title={typeof cell === "number" ? exactNumber(cell) : undefined}
                >
                  {formatCell(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {(content.rows ?? []).length === 0 ? (
        <p className="m-0 p-3 text-[0.61rem] text-text-dim">No rows</p>
      ) : null}
    </div>
  );
}

type FigureContent = Extract<RunAnalysisOutput, { kind: "figure" }>["content"];

function AnalysisFigureView({ content, title }: { content: FigureContent; title: string }) {
  const width = 640;
  const height = 250;
  const margin = { top: 18, right: 20, bottom: 43, left: 58 };
  const points = content.series.flatMap((series) =>
    series.x.map((x, index) => ({ x, y: series.y[index]! })),
  );
  const [xMin, xMax] = paddedExtent(points.map((point) => point.x));
  const [yMin, yMax] = paddedExtent(points.map((point) => point.y));
  const x = (value: number) =>
    margin.left + normalizedPosition(value, xMin, xMax) * (width - margin.left - margin.right);
  const y = (value: number) =>
    height -
    margin.bottom -
    normalizedPosition(value, yMin, yMax) * (height - margin.top - margin.bottom);
  const xLabel = axisLabel(content.x_axis);
  const yLabel = axisLabel(content.y_axis);
  const description = `${title}: ${yLabel} by ${xLabel}`;

  return (
    <figure className="m-0 p-[9px]" data-testid="analysis-figure">
      <figcaption className="mb-1.5 flex flex-wrap items-center justify-between gap-2 text-[0.58rem] text-text-dim">
        <span>
          {xLabel} → {yLabel}
        </span>
        <span className="rounded border border-line px-1.5 py-1 font-bold tracking-[0.05em] uppercase">
          {content.kind}
        </span>
      </figcaption>
      <svg
        aria-label={description}
        className="block h-auto w-full rounded-md bg-panel-soft"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <title>{description}</title>
        {ticks(xMin, xMax).map((tick) => (
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
              y={height - 22}
            >
              {shortNumber(tick)}
            </text>
          </g>
        ))}
        {ticks(yMin, yMax).map((tick) => (
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
        {content.series.map((series, seriesIndex) => {
          const color = SERIES_COLORS[seriesIndex % SERIES_COLORS.length]!;
          const seriesPoints = series.x.map((xValue, pointIndex) => ({
            x: xValue,
            y: series.y[pointIndex]!,
          }));
          const path = seriesPoints
            .map(
              (point, pointIndex) => `${pointIndex === 0 ? "M" : "L"}${x(point.x)},${y(point.y)}`,
            )
            .join(" ");
          return (
            <g data-testid="analysis-figure-series" key={series.id}>
              {content.kind === "line" && seriesPoints.length > 1 ? (
                <path d={path} fill="none" stroke={color} strokeWidth="2" />
              ) : null}
              {seriesPoints.map((point, pointIndex) => (
                <circle
                  cx={x(point.x)}
                  cy={y(point.y)}
                  fill={color}
                  key={`${series.id}:${pointIndex}`}
                  r={content.kind === "line" ? 2.5 : 3.75}
                >
                  <title>{`${series.label ?? series.id}: ${shortNumber(point.x)}, ${shortNumber(point.y)}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      {content.series.length > 1 ? (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[0.55rem] text-text-dim">
          {content.series.map((series, index) => (
            <span className="inline-flex items-center gap-1" key={series.id}>
              <span
                aria-hidden="true"
                className="inline-block size-2 rounded-full"
                style={{ background: SERIES_COLORS[index % SERIES_COLORS.length] }}
              />
              {series.label ?? series.id}
            </span>
          ))}
        </div>
      ) : null}
    </figure>
  );
}

function formatCell(value: boolean | number | string | null): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "True" : "False";
  return typeof value === "number" ? exactNumber(value) : value;
}

function exactNumber(value: number): string {
  return Object.is(value, -0) ? "-0" : String(value);
}

function axisLabel(axis: FigureContent["x_axis"]): string {
  return axis.unit ? `${axis.label} (${axis.unit})` : axis.label;
}

function paddedExtent(values: number[]): [number, number] {
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  if (minimum !== maximum) return [minimum, maximum];
  const padding = Math.abs(minimum) * 0.05 || 1;
  const lower = minimum - padding;
  const upper = maximum + padding;
  if (Number.isFinite(lower) && Number.isFinite(upper)) return [lower, upper];
  const inward = minimum * 0.95;
  return minimum < 0 ? [minimum, inward] : [inward, minimum];
}

function ticks(minimum: number, maximum: number): number[] {
  return Array.from({ length: 5 }, (_, index) => interpolate(minimum, maximum, index / 4));
}

function normalizedPosition(value: number, minimum: number, maximum: number): number {
  const scale = Math.max(Math.abs(minimum), Math.abs(maximum));
  if (scale === 0) return 0.5;
  const scaledMinimum = minimum / scale;
  return (value / scale - scaledMinimum) / (maximum / scale - scaledMinimum);
}

function interpolate(minimum: number, maximum: number, ratio: number): number {
  const scale = Math.max(Math.abs(minimum), Math.abs(maximum));
  if (scale === 0) return 0;
  return ((minimum / scale) * (1 - ratio) + (maximum / scale) * ratio) * scale;
}

function shortNumber(value: number): string {
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude >= 10_000 || magnitude < 0.001) return value.toExponential(2);
  return Number(value.toPrecision(4)).toString();
}

export function AnalysisMetadataView({ metadata }: { metadata: Record<string, unknown> }) {
  if (Object.keys(metadata).length === 0) return null;
  return (
    <details className="border-t border-line px-[9px] py-[7px] text-[0.58rem] text-text-dim">
      <summary className="cursor-pointer font-bold">Metadata</summary>
      <pre className="mt-1.5 mb-0 max-h-36 overflow-auto whitespace-pre-wrap text-[0.58rem] text-text-soft">
        {JSON.stringify(metadata, null, 2)}
      </pre>
    </details>
  );
}
