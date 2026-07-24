// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
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
  getOlderRuns,
  getRun,
  getRunAnalyses,
  getRunEvents,
  getRuns,
} from "./api";
import type { ProjectRun } from "./types";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getCatalog: vi.fn(),
  getEvents: vi.fn(),
  getHealth: vi.fn(),
  getMeasurementPreview: vi.fn(),
  getOlderRuns: vi.fn(),
  getRun: vi.fn(),
  getRunAnalyses: vi.fn(),
  getRunEvents: vi.fn(),
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
let projectEventListener: ((event: Event) => void) | undefined;

beforeEach(() => {
  projectEventListener = undefined;
  window.history.replaceState(null, "", "#configuration");
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "EventSource",
    class {
      addEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject,
      ) {
        if (type !== "project") return;
        projectEventListener = (event) => {
          if (typeof listener === "function") {
            listener(event);
          } else {
            listener.handleEvent(event);
          }
        };
      }
      removeEventListener(type: string) {
        if (type === "project") projectEventListener = undefined;
      }
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
  vi.mocked(getRuns).mockResolvedValue({ items: RUNS });
  vi.mocked(getOlderRuns).mockResolvedValue({ items: [] });
  vi.mocked(getRun).mockImplementation(async (runId) => projectRun(runId));
  vi.mocked(getEvents).mockResolvedValue([]);
  vi.mocked(getRunEvents).mockResolvedValue([]);
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
  it("keeps the configuration URL while selecting the initial run", async () => {
    renderApp();

    await waitFor(() => expect(window.location.search).toBe("?run=run-1"));
    expect(window.location.hash).toBe("#configuration");
    expect(
      screen.getByRole("button", { name: "Configuration" }),
    ).toHaveAttribute("aria-current", "page");
  });

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
    expect(window.location.search).toBe("?run=run-2");
    await waitFor(() =>
      expect(getRunEvents).toHaveBeenCalledWith(
        "run-2",
        expect.any(AbortSignal),
      ),
    );
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
    expect(window.location.search).toBe("?run=run-1");
  });

  it("restores the selected run from the URL", async () => {
    window.history.replaceState(null, "", "/?run=run-2#configuration");

    renderApp();

    expect(
      screen.getByRole("button", { name: "Configuration" }),
    ).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Runs" }));
    await waitFor(() =>
      expect(screen.getByTitle("Inspect run run-2")).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
    expect(screen.getByTitle("run-2")).toHaveTextContent("run-2");
  });

  it("loads and merges older run pages", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(getRuns).mockResolvedValue({
      items: RUNS.map((run, index) => ({ ...run, sequence: index + 20 })),
      previousCursor: 20,
    });
    vi.mocked(getOlderRuns).mockResolvedValue({
      items: [
        { ...projectRun("run-old"), sequence: 2 },
        { ...projectRun("run-1"), sequence: 1 },
      ],
    });

    renderApp();
    expect(
      await screen.findByText("0 active in loaded runs"),
    ).toBeVisible();
    expect(screen.getByText("No flags in loaded runs")).toBeVisible();
    fireEvent.click(
      await screen.findByRole("button", { name: "Load older runs" }),
    );

    expect(await screen.findByTitle("Inspect run run-old")).toBeVisible();
    expect(getOlderRuns).toHaveBeenCalledWith(20);
    expect(screen.getAllByTitle("Inspect run run-1")).toHaveLength(1);
    expect(
      screen
        .getAllByTitle(/^Inspect run /)
        .map((button) => button.getAttribute("title")),
    ).toEqual([
      "Inspect run run-2",
      "Inspect run run-1",
      "Inspect run run-old",
    ]);
    expect(
      screen.queryByRole("button", { name: "Load older runs" }),
    ).not.toBeInTheDocument();
  });

  it("discards loaded history when the latest page head moves", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(getRuns)
      .mockResolvedValueOnce({
        items: RUNS.map((run, index) => ({ ...run, sequence: index + 20 })),
        previousCursor: 20,
      })
      .mockResolvedValue({
        items: RUNS.map((run, index) => ({ ...run, sequence: index + 30 })),
        previousCursor: 30,
      });
    vi.mocked(getOlderRuns).mockResolvedValue({
      items: [{ ...projectRun("run-old"), sequence: 2 }],
    });

    renderApp();
    fireEvent.click(
      await screen.findByRole("button", { name: "Load older runs" }),
    );
    expect(await screen.findByTitle("Inspect run run-old")).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: "Refresh project data" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByTitle("Inspect run run-old"),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Load older runs" }),
    );
    await waitFor(() =>
      expect(vi.mocked(getOlderRuns).mock.calls.map(([cursor]) => cursor)).toEqual(
        [20, 30],
      ),
    );
  });

  it("reports a lost daemon even while slower queries still hold data", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(getHealth)
      .mockResolvedValueOnce({
        status: "online",
        projectId: "local:test",
        projectName: "Test lab",
        projectRoot: "/tmp/test-lab",
        details: {},
      })
      .mockRejectedValue(new Error("daemon stopped"));
    vi.mocked(getRuns)
      .mockResolvedValueOnce({ items: RUNS })
      .mockRejectedValue(new Error("daemon stopped"));

    renderApp();

    expect(
      (await screen.findAllByText("Online", { exact: true }))[0],
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh project data" }),
    );

    expect(
      await screen.findByText("Disconnected", { exact: true }),
    ).toBeVisible();
    expect(screen.getByText("Daemon unavailable.")).toBeVisible();
  });

  it("uses runtime progress instead of treating a started point as complete", async () => {
    window.history.replaceState(null, "", "/?run=run-1");
    const running = {
      ...projectRun("run-1"),
      status: "running" as const,
      stateLabel: "Running",
      plan: {
        coordinateIds: [],
        recordIds: [],
        pointCount: 3,
      },
    };
    vi.mocked(getRuns).mockResolvedValue({ items: [running] });
    vi.mocked(getRun).mockResolvedValue(running);
    vi.mocked(getRunEvents).mockResolvedValue([
      {
        id: 1,
        runId: "run-1",
        kind: "runtime_transition",
        payload: {
          stage: "compute",
          state: "started",
          point_index: 2,
          progress: { completed_points: 0, total_points: 3 },
        },
      },
      {
        id: 2,
        runId: "run-1",
        kind: "runtime_transition",
        payload: {
          stage: "point",
          state: "completed",
          point_index: 0,
          progress: { completed_points: 1, total_points: 3 },
        },
      },
    ]);

    renderApp();

    expect(
      await screen.findByRole("progressbar", {
        name: "1 of 3 points complete",
      }),
    ).toBeVisible();
    expect(screen.getByText("33%")).toBeVisible();
  });

  it("keeps distinct measurement records that share a point index", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(getMeasurementPreview).mockImplementation(
      async (_runId, offset = 0) =>
        offset === 0
          ? {
              items: [
                {
                  dataset_id: "dataset-a",
                  point_index: 0,
                  observables: { signal: 1 },
                },
              ],
              nextOffset: 1,
            }
          : {
              items: [
                {
                  dataset_id: "dataset-b",
                  point_index: 0,
                  observables: { signal: 2 },
                },
              ],
            },
    );

    renderApp();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Load more measurements",
      }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Load more measurements" }),
      ).not.toBeInTheDocument(),
    );
    expect(getMeasurementPreview).toHaveBeenCalledWith(
      "run-1",
      1,
      expect.any(AbortSignal),
    );
    expect(screen.getByText(/"dataset_id": "dataset-b"/)).toBeVisible();
    expect(screen.getByText("2 records")).toBeVisible();
  });

  it("resets only the selected run's measurement pages on measurement events", async () => {
    window.history.replaceState(null, "", "/?run=run-1");
    vi.mocked(getMeasurementPreview).mockImplementation(
      async (_runId, offset = 0) => ({
        items: [{ point_index: offset }],
        nextOffset: offset === 0 ? 1 : undefined,
      }),
    );

    renderApp();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Load more measurements",
      }),
    );
    await waitFor(() => expect(getMeasurementPreview).toHaveBeenCalledTimes(2));
    expect(projectEventListener).toBeDefined();

    act(() => {
      emitProjectEvent("run-2", "measurements_appended");
    });
    await new Promise((resolve) => window.setTimeout(resolve, 150));
    expect(getMeasurementPreview).toHaveBeenCalledTimes(2);

    act(() => {
      emitProjectEvent("run-1", "measurements_sealed");
    });
    await waitFor(() => expect(getMeasurementPreview).toHaveBeenCalledTimes(3));
    expect(
      vi
        .mocked(getMeasurementPreview)
        .mock.calls.map(([, offset]) => offset),
    ).toEqual([0, 1, 0]);
    expect(
      screen.getByRole("button", { name: "Load more measurements" }),
    ).toBeVisible();
  });

  it("labels the bounded run event timeline honestly", async () => {
    window.history.replaceState(null, "", "/?run=run-1");
    vi.mocked(getRunEvents).mockResolvedValue(
      Array.from({ length: 500 }, (_, index) => ({
        id: index + 1,
        runId: "run-1",
        kind: "transition_committed",
        payload: { point_index: index },
      })),
    );

    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Recent events" }),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Showing the latest 500 events; older events are not loaded.",
      ),
    ).toBeVisible();
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

function emitProjectEvent(runId: string, kind: string): void {
  if (!projectEventListener) throw new Error("project SSE listener is not ready");
  projectEventListener(
    new MessageEvent("project", {
      data: JSON.stringify({ event_id: 42, run_id: runId, kind, payload: {} }),
    }),
  );
}
