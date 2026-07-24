// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import {
  getCatalog,
  getEvents,
  getHealth,
  getMeasurementPreview,
  getRun,
  getRunAnalyses,
  getRuns,
} from "./api";
import type { ProjectRun } from "./types";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getCatalog: vi.fn(),
  getEvents: vi.fn(),
  getHealth: vi.fn(),
  getMeasurementPreview: vi.fn(),
  getRun: vi.fn(),
  getRunAnalyses: vi.fn(),
  getRuns: vi.fn(),
}));

vi.mock("./ConfigWorkspace", () => ({
  ConfigWorkspace: ({
    onOpenRun,
  }: {
    onOpenRun?: (runId: string) => void;
  }) => (
    <>
      <button type="button" onClick={() => onOpenRun?.("run-2")}>
        Open listed producing run
      </button>
      <button type="button" onClick={() => onOpenRun?.("run-archive")}>
        Open unlisted producing run
      </button>
    </>
  ),
}));

vi.mock("./RunProposals", () => ({
  RunProposals: () => <div>Proposal details</div>,
}));

const RUNS = [projectRun("run-1"), projectRun("run-2")];

beforeEach(() => {
  window.history.replaceState(null, "", "#configuration");
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "EventSource",
    class {
      addEventListener() {}
      removeEventListener() {}
      close() {}
    },
  );
  vi.mocked(getHealth).mockResolvedValue({
    status: "ok",
    projectId: "local:test",
    projectName: "Test lab",
    projectRoot: "/tmp/test-lab",
    details: {},
  });
  vi.mocked(getRuns).mockResolvedValue(RUNS);
  vi.mocked(getRun).mockImplementation(async (runId) => projectRun(runId));
  vi.mocked(getEvents).mockResolvedValue([]);
  vi.mocked(getCatalog).mockResolvedValue({
    revision: "test",
    experiments: [],
  });
  vi.mocked(getMeasurementPreview).mockResolvedValue({ items: [] });
  vi.mocked(getRunAnalyses).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("config provenance navigation", () => {
  it("opens the producing run and selects it in the existing Runs view", async () => {
    renderApp();

    fireEvent.click(
      await screen.findByRole("button", { name: "Open listed producing run" }),
    );

    expect(
      screen.getByRole("button", { name: "Runs" }),
    ).toHaveAttribute("aria-current", "page");
    await waitFor(() =>
      expect(screen.getByTitle("Inspect run run-2")).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
    expect(window.location.hash).toBe("");
  });

  it("preserves a producing run that is outside the latest run index", async () => {
    renderApp();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open unlisted producing run",
      }),
    );

    expect(
      screen.getByRole("button", { name: "Runs" }),
    ).toHaveAttribute("aria-current", "page");
    expect(await screen.findByTitle("run-archive")).toHaveTextContent(
      "run-archive",
    );
    expect(screen.getByTitle("Inspect run run-1")).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByTitle("Inspect run run-2")).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("selects the first indexed run when no explicit run was requested", async () => {
    window.history.replaceState(null, "", "/");

    renderApp();

    await waitFor(() =>
      expect(screen.getByTitle("Inspect run run-1")).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
    expect(screen.getByTitle("run-1")).toHaveTextContent("run-1");
  });
});

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

function projectRun(runId: string): ProjectRun {
  return {
    runId,
    experimentId: "ramsey",
    executionMode: "managed",
    status: "succeeded",
    stateLabel: "Succeeded",
    updatedAt: "2026-07-24T08:00:00Z",
    plan: {
      coordinateIds: [],
      recordIds: [],
    },
    resources: [],
    contents: [],
  };
}
