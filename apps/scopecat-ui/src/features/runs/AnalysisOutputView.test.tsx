// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RunAnalysisOutput } from "../../types";
import { AnalysisOutputView } from "./AnalysisOutputView";

describe("AnalysisOutputView", () => {
  it("renders a typed table with authored labels, units, and scalar cells", () => {
    const output: RunAnalysisOutput = {
      kind: "table",
      title: "Fit parameters",
      metadata: { source: "notebook" },
      content: {
        columns: [
          { id: "frequency", label: "Frequency", unit: "GHz" },
          { id: "converged", label: "Converged" },
        ],
        rows: [{ cells: [5.1, true] }, { cells: [null, false] }],
      },
    };

    render(<AnalysisOutputView output={output} />);

    const table = screen.getByRole("table", { name: "Fit parameters" });
    expect(within(table).getByRole("columnheader", { name: "Frequency (GHz)" })).toBeVisible();
    expect(within(table).getByText("5.1")).toBeVisible();
    expect(within(table).getByText("True")).toBeVisible();
    expect(within(table).getByText("—")).toBeVisible();
    expect(screen.getByText("Metadata")).toBeVisible();
    expect(screen.getByText(/"source": "notebook"/)).toBeInTheDocument();
  });

  it("preserves neighboring large table numbers instead of tick-formatting them", () => {
    const output: RunAnalysisOutput = {
      kind: "table",
      title: "Counters",
      metadata: {},
      content: {
        columns: [{ id: "count", label: "Count" }],
        rows: [{ cells: [5_000_000_001] }, { cells: [5_000_000_002] }],
      },
    };

    render(<AnalysisOutputView output={output} />);

    expect(screen.getByText("5000000001")).toHaveAttribute("title", "5000000001");
    expect(screen.getByText("5000000002")).toHaveAttribute("title", "5000000002");
  });

  it("renders embedded multi-series figure data as an accessible SVG", () => {
    const output: RunAnalysisOutput = {
      kind: "figure",
      title: "Resonance fit",
      metadata: {},
      content: {
        kind: "line",
        x_axis: { label: "Bias", unit: "V" },
        y_axis: { label: "Frequency", unit: "GHz" },
        series: [
          { id: "fit", label: "Fit", x: [-0.1, 0, 0.1], y: [5.0, 5.1, 5.0] },
          { id: "reference", label: "Reference", x: [-0.1, 0.1], y: [5.05, 5.05] },
        ],
      },
    };

    const { container } = render(<AnalysisOutputView output={output} />);

    expect(
      screen.getByRole("img", {
        name: "Resonance fit: Frequency (GHz) by Bias (V)",
      }),
    ).toBeVisible();
    expect(screen.getAllByTestId("analysis-figure-series")).toHaveLength(2);
    expect(container.querySelectorAll("path")).toHaveLength(2);
    expect(container.querySelectorAll("circle")).toHaveLength(5);
    expect(screen.getByText("Fit")).toBeVisible();
    expect(screen.getByText("Reference")).toBeVisible();
  });

  it("scales opposite finite float extremes without invalid SVG coordinates", () => {
    const output: RunAnalysisOutput = {
      kind: "figure",
      title: "Extreme range",
      metadata: {},
      content: {
        kind: "line",
        x_axis: { label: "x" },
        y_axis: { label: "y" },
        series: [{ id: "extreme", x: [-1e308, 1e308], y: [1e308, -1e308] }],
      },
    };

    const { container } = render(<AnalysisOutputView output={output} />);

    expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
    expect(container.querySelectorAll("circle")).toHaveLength(2);
  });
});
