import { lazy, Suspense, useId } from "react";
import type { EChartsCoreOption } from "echarts/core";

const EChartRuntime = lazy(async () => {
  const module = await import("./EChartRuntime");
  return { default: module.EChartRuntime };
});

export const ECHARTS_SERIES_COLORS = [
  "#80a3cf",
  "#cfad68",
  "#a497c7",
  "#d77e79",
  "#b8c0c7",
  "#77b6a8",
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
  "#8ab4f8",
  "#c7a6ff",
  "#67d8b5",
  "#f2c66d",
  "#ff8c88",
  "#4cc9f0",
  "#b8de6f",
  "#f28482",
  "#90caf9",
  "#ce93d8",
  "#80cbc4",
  "#ffcc80",
  "#ef9a9a",
  "#9fa8da",
  "#a5d6a7",
];

export function EChart({
  ariaLabel,
  chartKind,
  height,
  option,
  pointCount,
  seriesLabels,
  seriesCount,
  testId,
}: {
  ariaLabel: string;
  chartKind: string;
  height: number;
  option: EChartsCoreOption;
  pointCount: number;
  seriesLabels: string[];
  seriesCount: number;
  testId?: string;
}) {
  const descriptionId = useId();

  return (
    <>
      <div
        aria-describedby={descriptionId}
        aria-label={ariaLabel}
        data-chart-kind={chartKind}
        data-point-count={pointCount}
        data-series-count={seriesCount}
        data-testid={testId}
        role="img"
      >
        <Suspense fallback={<div aria-hidden="true" style={{ height }} />}>
          <EChartRuntime height={height} option={option} />
        </Suspense>
      </div>
      <span className="sr-only" id={descriptionId}>
        {seriesCount.toLocaleString()} data series with {pointCount.toLocaleString()} plotted{" "}
        {pointCount === 1 ? "point" : "points"}.
        {seriesLabels.length > 0 ? ` Series: ${seriesLabels.join(", ")}.` : ""}
      </span>
    </>
  );
}

export type { EChartsCoreOption };
