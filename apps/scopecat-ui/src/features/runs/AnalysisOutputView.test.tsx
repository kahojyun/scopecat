// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunAnalysisOutput } from "../../types";
import { AnalysisOutputView } from "./AnalysisOutputView";
import { analysisFigureOption } from "./chart-options";

vi.mock("../../ui/EChartRuntime", () => ({ EChartRuntime: () => null }));

afterEach(cleanup);

describe("AnalysisOutputView", () => {
  it("renders a typed table with authored labels, units, and scalar cells", () => {
    const output = {
      kind: "table",
      id: "fit-parameters",
      title: "Fit parameters",
      metadata: { source: "notebook" },
      content: {
        source: { kind: "dataset", output_id: "fits" },
        columns: ["frequency", "converged"],
        preview: {
          columns: [
            { id: "frequency", label: "Frequency", unit: "GHz" },
            { id: "converged", label: "Converged" },
          ],
          rows: [{ cells: [5.1, true] }, { cells: [null, false] }],
        },
      },
    } satisfies Extract<RunAnalysisOutput, { kind: "table" }>;

    render(<AnalysisOutputView output={output} runId="run-1" />);

    const table = screen.getByRole("table", { name: "Fit parameters" });
    expect(within(table).getByRole("columnheader", { name: "Frequency (GHz)" })).toBeVisible();
    expect(within(table).getByText("5.1")).toBeVisible();
    expect(within(table).getByText("True")).toBeVisible();
    expect(within(table).getByText("—")).toBeVisible();
    expect(screen.getByText("Metadata")).toBeVisible();
    expect(screen.getByText(/"source": "notebook"/)).toBeInTheDocument();
  });

  it("preserves neighboring large table numbers instead of tick-formatting them", () => {
    const output = {
      kind: "table",
      id: "counters",
      title: "Counters",
      metadata: {},
      content: {
        source: { kind: "dataset", output_id: "counts" },
        columns: ["count"],
        preview: {
          columns: [{ id: "count", label: "Count" }],
          rows: [{ cells: [5_000_000_001] }, { cells: [5_000_000_002] }],
        },
      },
    } satisfies Extract<RunAnalysisOutput, { kind: "table" }>;

    render(<AnalysisOutputView output={output} runId="run-1" />);

    expect(screen.getByText("5000000001")).toHaveAttribute("title", "5000000001");
    expect(screen.getByText("5000000002")).toHaveAttribute("title", "5000000002");
  });

  it("renders a content-addressed analysis dataset reference", () => {
    const output = {
      kind: "dataset",
      id: "fits",
      title: "Fit data",
      metadata: {},
      content: {
        dataset_id: "analysis-fit-fits",
        codec: "scopecat.derived-dataset.arrow-ipc.v2",
        content_hash: `sha256:${"a".repeat(64)}`,
      },
    } satisfies Extract<RunAnalysisOutput, { kind: "dataset" }>;

    render(<AnalysisOutputView output={output} runId="run-1" />);

    expect(screen.getByText("analysis-fit-fits")).toBeVisible();
    expect(screen.getByText("scopecat.derived-dataset.arrow-ipc.v2")).toBeVisible();
  });

  it("renders typed facts and analysis-owned artifact references", () => {
    const fact: RunAnalysisOutput = {
      kind: "fact",
      id: "resonance",
      title: "Fitted resonance",
      metadata: {},
      content: {
        schema_id: "scopecat.quantity.v1",
        schema_codec: "scopecat.analysis-fact-schema.v1",
        schema_hash: `sha256:${"c".repeat(64)}`,
        codec: "scopecat.python-json.v1",
        value: { value: 5.1, unit: "GHz" },
      },
    };
    const artifact: RunAnalysisOutput = {
      kind: "artifact",
      id: "fit-report",
      title: "Fit report",
      metadata: {},
      content: {
        artifact_id: "analysis-fit-fit-report",
        content_hash: `sha256:${"b".repeat(64)}`,
        filename: "fit-report.md",
        media_type: "text/markdown",
      },
    };

    const { rerender } = render(<AnalysisOutputView output={fact} runId="run-1" />);
    expect(screen.getByText("scopecat.quantity.v1")).toBeVisible();
    expect(screen.getByText(/"unit": "GHz"/)).toBeVisible();

    rerender(<AnalysisOutputView output={artifact} runId="run-1" />);
    expect(screen.getByText("analysis-fit-fit-report")).toBeVisible();
    expect(screen.getByText("fit-report.md")).toBeVisible();
    expect(screen.getByText("text/markdown")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download file" })).toBeVisible();
  });

  it("renders embedded multi-series figure data as an accessible ECharts figure", () => {
    const output = {
      kind: "figure",
      id: "resonance-fit",
      title: "Resonance fit",
      metadata: {},
      content: {
        source: { kind: "dataset", output_id: "fits" },
        projection: { kind: "line", x: "bias", y: "frequency" },
        preview: {
          kind: "line",
          x_axis: { label: "Bias", unit: "V" },
          y_axis: { label: "Frequency", unit: "GHz" },
          series: [
            { id: "fit", label: "Fit", x: [-0.1, 0, 0.1], y: [5.0, 5.1, 5.0] },
            { id: "reference", label: "Reference", x: [-0.1, 0.1], y: [5.05, 5.05] },
          ],
        },
      },
    } satisfies Extract<RunAnalysisOutput, { kind: "figure" }>;

    render(<AnalysisOutputView output={output} runId="run-1" />);

    expect(
      screen.getByRole("img", {
        name: "Resonance fit: Frequency (GHz) by Bias (V)",
      }),
    ).toBeVisible();
    expect(screen.getByText(/Series: Fit, Reference/)).toBeInTheDocument();
  });

  it("preserves opposite finite float extremes in the ECharts option", () => {
    const output = {
      kind: "figure",
      id: "extreme-range",
      title: "Extreme range",
      metadata: {},
      content: {
        source: { kind: "dataset", output_id: "extremes" },
        projection: { kind: "line", x: "x", y: "y" },
        preview: {
          kind: "line",
          x_axis: { label: "x" },
          y_axis: { label: "y" },
          series: [{ id: "extreme", x: [-1e308, 1e308], y: [1e308, -1e308] }],
        },
      },
    } satisfies Extract<RunAnalysisOutput, { kind: "figure" }>;

    const option = analysisFigureOption(output.content.preview);
    const [series] = option.series as Array<{ data: number[][]; type: string }>;

    expect(series).toMatchObject({ type: "line" });
    expect(series?.data).toEqual([
      [-1e308, 1e308],
      [1e308, -1e308],
    ]);
    expect(series?.data.flat().every(Number.isFinite)).toBe(true);
  });
});
