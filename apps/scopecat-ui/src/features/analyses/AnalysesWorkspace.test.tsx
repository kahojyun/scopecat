// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectAnalysis } from "../../types";
import { AnalysesWorkspace } from "./AnalysesWorkspace";
import { getProjectAnalyses } from "./analysis-api";

vi.mock("./analysis-api", () => ({
  getProjectAnalyses: vi.fn(),
  getProjectAnalysisArtifactDownload: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getProjectAnalyses).mockResolvedValue([projectAnalysis()]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AnalysesWorkspace", () => {
  it("shows cross-run provenance and opens an exact input run", async () => {
    const openRun = vi.fn();
    renderWorkspace(openRun);

    expect(await screen.findByRole("heading", { name: "Project analyses" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Candidate verification" })).toBeVisible();
    expect(screen.getByText("Revision 2")).toBeVisible();
    expect(screen.getByText("sha256:publication")).toHaveAttribute("title", "sha256:publication");
    expect(screen.getByText("verification.v1")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "run-candidate" }));

    expect(openRun).toHaveBeenCalledWith("run-candidate");
  });

  it("explains how to create the first project analysis", async () => {
    vi.mocked(getProjectAnalyses).mockResolvedValue([]);

    renderWorkspace(vi.fn());

    expect(await screen.findByText("No project analyses saved")).toBeVisible();
    expect(screen.getByText(/lab\.analyze\(step\)/)).toBeVisible();
  });
});

function renderWorkspace(onOpenRun: (runId: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AnalysesWorkspace daemonUnavailable={false} onOpenRun={onOpenRun} />
    </QueryClientProvider>,
  );
}

function projectAnalysis(): ProjectAnalysis {
  return {
    id: "analysis-candidate-verification-r2",
    title: "Candidate verification",
    key: "candidate-verification",
    stepId: "candidate-verification",
    revision: 2,
    publicationHash: "sha256:publication",
    subject: "project",
    contents: [],
    inputs: [
      {
        id: "candidate",
        run_id: "run-candidate",
        target: "datasets/raw-measurements",
        kind: "measurement_dataset",
        content_hash: "sha256:measurements",
        codec: "scopecat.measurements.arrow.v1",
        role: "candidate",
      },
    ],
    executions: [],
    outputs: [
      {
        kind: "fact",
        id: "decision",
        title: "Decision",
        content: {
          schema_id: "verification.v1",
          schema_codec: "scopecat.analysis-fact-schema.v1",
          schema_hash: "sha256:schema",
          codec: "scopecat.python-json.v1",
          value: { accepted: true },
        },
        metadata: {},
      },
    ],
  };
}
