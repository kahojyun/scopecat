import { useMemo } from "react";
import type { RunAnalysisOutput } from "../../types";
import { EChart, ECHARTS_SERIES_COLORS, type EChartsCoreOption } from "../../ui/EChart";

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
  const points = content.series.flatMap((series) =>
    series.x.map((x, index) => ({ x, y: series.y[index]! })),
  );
  const xLabel = axisLabel(content.x_axis);
  const yLabel = axisLabel(content.y_axis);
  const description = `${title}: ${yLabel} by ${xLabel}`;
  const option = useMemo(() => analysisFigureOption(content), [content]);

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
      <div className="rounded-md bg-panel-soft">
        <EChart
          ariaLabel={description}
          chartKind={content.kind}
          height={270}
          option={option}
          pointCount={points.length}
          seriesLabels={content.series.map((series) => series.label ?? series.id)}
          seriesCount={content.series.length}
          testId="analysis-echart"
        />
      </div>
    </figure>
  );
}

function analysisFigureOption(content: FigureContent): EChartsCoreOption {
  const multipleSeries = content.series.length > 1;
  const axis = (name: string) => ({
    axisLabel: { color: "#818b94", formatter: numericAxisLabel },
    axisLine: { lineStyle: { color: "#3b444d" } },
    axisPointer: { label: { formatter: numericAxisPointerLabel } },
    name,
    nameGap: 36,
    nameLocation: "middle" as const,
    nameTextStyle: { color: "#818b94", fontSize: 10 },
    scale: true,
    splitLine: { lineStyle: { color: "#2b3137" } },
    type: "value" as const,
  });

  return {
    animation: false,
    color: ECHARTS_SERIES_COLORS,
    dataZoom: [
      {
        filterMode: "none",
        moveOnMouseWheel: false,
        type: "inside",
        xAxisIndex: 0,
        zoomOnMouseWheel: "shift",
      },
      {
        filterMode: "none",
        moveOnMouseWheel: false,
        type: "inside",
        yAxisIndex: 0,
        zoomOnMouseWheel: "shift",
      },
    ],
    grid: { bottom: 52, left: 66, right: 20, top: multipleSeries ? 42 : 18 },
    legend: multipleSeries
      ? {
          data: content.series.map((series) => series.label ?? series.id),
          itemHeight: 8,
          itemWidth: 12,
          pageTextStyle: { color: "#818b94" },
          textStyle: { color: "#818b94", fontSize: 10 },
          top: 0,
          type: "scroll",
        }
      : { show: false },
    series: content.series.map((series, index) => {
      const color = ECHARTS_SERIES_COLORS[index % ECHARTS_SERIES_COLORS.length];
      return {
        data: series.x.map((x, pointIndex) => [x, series.y[pointIndex]!]),
        id: series.id,
        itemStyle: { color },
        lineStyle: { color, width: 2 },
        name: series.label ?? series.id,
        showSymbol: true,
        symbolSize: content.kind === "line" ? 5 : 7.5,
        type: content.kind,
      };
    }),
    tooltip: {
      axisPointer: { type: "cross" },
      confine: true,
      trigger: content.kind === "line" ? "axis" : "item",
    },
    xAxis: axis(axisLabel(content.x_axis)),
    yAxis: axis(axisLabel(content.y_axis)),
  };
}

function numericAxisLabel(value: number): string {
  return shortNumber(value);
}

function numericAxisPointerLabel({ value }: { value: number }): string {
  return shortNumber(value);
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
