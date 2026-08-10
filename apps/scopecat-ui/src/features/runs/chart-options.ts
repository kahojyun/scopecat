import type { CustomSeriesRenderItem, EChartsCoreOption } from "echarts";
import type { RunAnalysisOutput } from "../../types";
import type { MeasurementChartPlan } from "./measurement-visualization";

export type AnalysisFigureContent = Extract<
  RunAnalysisOutput,
  { kind: "figure" }
>["content"]["preview"];

const SERIES_COLORS = [
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

export function analysisAxisLabel(axis: AnalysisFigureContent["x_axis"]): string {
  return axis.unit ? `${axis.label} (${axis.unit})` : axis.label;
}

export function analysisFigureOption(content: AnalysisFigureContent): EChartsCoreOption {
  const multipleSeries = content.series.length > 1;
  const axis = (name: string) => valueAxis(name, analysisShortNumber, 36);

  return {
    animation: false,
    color: SERIES_COLORS,
    dataZoom: insideDataZoom(),
    grid: { bottom: 52, left: 66, right: 20, top: multipleSeries ? 42 : 18 },
    legend: multipleSeries
      ? scrollLegend(content.series.map((series) => series.label ?? series.id))
      : { show: false },
    series: content.series.map((series, index) => {
      const color = SERIES_COLORS[index % SERIES_COLORS.length];
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
    xAxis: axis(analysisAxisLabel(content.x_axis)),
    yAxis: axis(analysisAxisLabel(content.y_axis)),
  };
}

export function measurementChartOption(chart: MeasurementChartPlan): EChartsCoreOption {
  const heatmap = chart.kind === "heatmap";
  const points = chart.series.flatMap((series) => series.points);
  const colorValues = points.flatMap((point) => (point.color === undefined ? [] : [point.color]));
  const colorExtent = colorValues.length > 0 ? rawExtent(colorValues) : undefined;
  const multipleSeries = chart.series.length > 1;
  const xBoundaries = heatmap ? cellBoundaries(chart.grid.xValues) : undefined;
  const yBoundaries = heatmap ? cellBoundaries(chart.grid.yValues) : undefined;

  return {
    animation: false,
    color: SERIES_COLORS,
    dataZoom: heatmap ? undefined : insideDataZoom(),
    grid: {
      bottom: colorExtent ? 82 : 50,
      left: 64,
      right: 20,
      top: multipleSeries ? 42 : 16,
    },
    legend: multipleSeries
      ? scrollLegend(chart.series.map((series) => series.label))
      : { show: false },
    series: chart.series.map((series, seriesIndex) => {
      const color = SERIES_COLORS[seriesIndex % SERIES_COLORS.length];
      if (chart.kind === "heatmap") {
        return heatmapSeries(chart, series, xBoundaries!, yBoundaries!);
      }
      return {
        data: series.points.map((point) =>
          point.color === undefined ? [point.x, point.y] : [point.x, point.y, point.color],
        ),
        id: series.id,
        itemStyle: chart.kind === "color-scatter" ? undefined : { color },
        lineStyle: { color, width: 2 },
        name: series.label,
        showSymbol: true,
        symbolSize: chart.kind === "line" ? 5 : chart.kind === "color-scatter" ? 8 : 7,
        type: chart.kind === "line" ? "line" : "scatter",
      };
    }),
    tooltip: {
      axisPointer: { type: "cross" },
      confine: true,
      trigger: chart.kind === "line" ? "axis" : "item",
    },
    visualMap:
      colorExtent && chart.colorLabel
        ? {
            calculable: true,
            bottom: 0,
            dimension: heatmap ? 4 : 2,
            inRange: { color: ["#7041c8", "#269c78", "#d2b11b"] },
            left: "center",
            max: colorExtent[1],
            min: colorExtent[0],
            orient: "horizontal",
            precision: 4,
            text: [chart.colorLabel, ""],
            textStyle: { color: "#818b94", fontSize: 9 },
          }
        : undefined,
    xAxis:
      xBoundaries === undefined
        ? valueAxis(chart.xLabel, measurementShortNumber, 34)
        : boundedValueAxis(chart.xLabel, xBoundaries, 34),
    yAxis:
      yBoundaries === undefined
        ? valueAxis(chart.yLabel, measurementShortNumber, 34)
        : boundedValueAxis(chart.yLabel, yBoundaries, 48),
  };
}

function heatmapSeries(
  chart: Extract<MeasurementChartPlan, { kind: "heatmap" }>,
  series: Extract<MeasurementChartPlan, { kind: "heatmap" }>["series"][number],
  xBoundaries: number[],
  yBoundaries: number[],
) {
  const xCells = new Map(
    chart.grid.xValues.map((value, index) => [
      value,
      [xBoundaries[index]!, xBoundaries[index + 1]!],
    ]),
  );
  const yCells = new Map(
    chart.grid.yValues.map((value, index) => [
      value,
      [yBoundaries[index]!, yBoundaries[index + 1]!],
    ]),
  );
  return {
    clip: true,
    coordinateSystem: "cartesian2d",
    data: series.points.flatMap((point) => {
      const xCell = xCells.get(point.x);
      const yCell = yCells.get(point.y);
      return point.color === undefined || xCell === undefined || yCell === undefined
        ? []
        : [[xCell[0], xCell[1], yCell[0], yCell[1], point.color, point.x, point.y]];
    }),
    dimensions: [
      "x start",
      "x end",
      "y start",
      "y end",
      chart.colorLabel ?? "value",
      chart.xLabel,
      chart.yLabel,
    ],
    encode: { tooltip: [5, 6, 4], x: [0, 1], y: [2, 3] },
    id: series.id,
    name: series.label,
    progressive: 2_000,
    renderItem: renderHeatmapCell,
    type: "custom",
  };
}

const renderHeatmapCell: CustomSeriesRenderItem = (_params, api) => {
  const firstCorner = api.coord([api.value(0), api.value(2)]);
  const secondCorner = api.coord([api.value(1), api.value(3)]);
  return {
    emphasis: { style: { lineWidth: 1, stroke: "#edf0f2" } },
    shape: {
      height: Math.abs(secondCorner[1]! - firstCorner[1]!),
      width: Math.abs(secondCorner[0]! - firstCorner[0]!),
      x: Math.min(firstCorner[0]!, secondCorner[0]!),
      y: Math.min(firstCorner[1]!, secondCorner[1]!),
    },
    style: {
      fill: api.visual("color"),
      lineWidth: 0.5,
      stroke: "#14181b",
    },
    type: "rect",
  };
};

function boundedValueAxis(name: string, boundaries: number[], nameGap: number) {
  return {
    ...valueAxis(name, measurementShortNumber, nameGap),
    max: boundaries.at(-1),
    min: boundaries[0],
  };
}

function valueAxis(name: string, formatter: (value: number) => string, nameGap: number) {
  return {
    axisLabel: { color: "#818b94", formatter },
    axisLine: { lineStyle: { color: "#3b444d" } },
    axisPointer: { label: { formatter: ({ value }: { value: number }) => formatter(value) } },
    name,
    nameGap,
    nameLocation: "middle" as const,
    nameTextStyle: { color: "#818b94", fontSize: 10 },
    scale: true,
    splitLine: { lineStyle: { color: "#2b3137" } },
    type: "value" as const,
  };
}

function scrollLegend(labels: string[]) {
  return {
    data: labels,
    itemHeight: 8,
    itemWidth: 12,
    pageTextStyle: { color: "#818b94" },
    textStyle: { color: "#818b94", fontSize: 10 },
    top: 0,
    type: "scroll" as const,
  };
}

function insideDataZoom() {
  const shared = {
    filterMode: "none" as const,
    moveOnMouseWheel: false,
    type: "inside" as const,
    zoomOnMouseWheel: "shift" as const,
  };
  return [
    { ...shared, xAxisIndex: 0 },
    { ...shared, yAxisIndex: 0 },
  ];
}

export function cellBoundaries(values: number[]): number[] {
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

function rawExtent(values: number[]): [number, number] {
  return [Math.min(...values), Math.max(...values)];
}

function measurementShortNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(value);
}

function analysisShortNumber(value: number): string {
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude >= 10_000 || magnitude < 0.001) return value.toExponential(2);
  return Number(value.toPrecision(4)).toString();
}
