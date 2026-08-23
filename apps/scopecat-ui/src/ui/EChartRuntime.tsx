import { useEffect, useRef } from "react";
import { CustomChart, LineChart, ScatterChart } from "echarts/charts";
import {
  DataZoomInsideComponent,
  GridComponent,
  LegendScrollComponent,
  TooltipComponent,
  VisualMapContinuousComponent,
} from "echarts/components";
import { init, use, type EChartsCoreOption } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

use([
  CustomChart,
  DataZoomInsideComponent,
  GridComponent,
  LegendScrollComponent,
  LineChart,
  ScatterChart,
  SVGRenderer,
  TooltipComponent,
  VisualMapContinuousComponent,
]);

export function EChartRuntime({ height, option }: { height: number; option: EChartsCoreOption }) {
  const elementRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof init> | null>(null);
  const heightRef = useRef(height);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    const chart = init(element, undefined, {
      height: element.clientHeight || heightRef.current,
      renderer: "svg",
      width: element.clientWidth || 640,
    });
    chartRef.current = chart;

    const resize = () => {
      chart.resize({
        height: element.clientHeight || heightRef.current,
        width: element.clientWidth || 640,
      });
    };
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(resize);
    observer?.observe(element);
    if (!observer) window.addEventListener("resize", resize);

    return () => {
      observer?.disconnect();
      if (!observer) window.removeEventListener("resize", resize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  useEffect(() => {
    heightRef.current = height;
    chartRef.current?.resize({
      height: elementRef.current?.clientHeight || height,
      width: elementRef.current?.clientWidth || 640,
    });
  }, [height]);

  return <div aria-hidden="true" ref={elementRef} style={{ height, width: "100%" }} />;
}
