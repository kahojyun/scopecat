// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import {
  getEvents,
  getHealth,
  getMeasurementPreview,
  getOlderRuns,
  getRun,
  getRunAnalyses,
  getRunEvents,
  getRuns,
} from "./api";
import type { MeasurementRecord } from "./api-contract";
import type { ProjectRun } from "./types";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getEvents: vi.fn(),
  getHealth: vi.fn(),
  getMeasurementPreview: vi.fn(),
  getOlderRuns: vi.fn(),
  getRun: vi.fn(),
  getRunAnalyses: vi.fn(),
  getRunEvents: vi.fn(),
  getRuns: vi.fn(),
}));

vi.mock("./features/config/ConfigWorkspace", () => ({
  ConfigWorkspace: ({ onOpenRun }: { onOpenRun?: (runId: string) => void }) => (
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

vi.mock("./features/instruments/InstrumentsWorkspace", () => ({
  InstrumentsWorkspace: () => <div>Instrument workspace</div>,
}));

vi.mock("./features/proposals/RunProposals", () => ({
  RunProposals: () => <div>Proposal details</div>,
}));

const RUNS = [projectRun("run-1"), projectRun("run-2")];
let projectEventListener: ((event: Event) => void) | undefined;
let openEventListener: ((event: Event) => void) | undefined;

beforeEach(() => {
  projectEventListener = undefined;
  openEventListener = undefined;
  window.history.replaceState(null, "", "#configuration");
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "EventSource",
    class {
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
        const callback = (event: Event) => {
          if (typeof listener === "function") {
            listener(event);
          } else {
            listener.handleEvent(event);
          }
        };
        if (type === "open") openEventListener = callback;
        if (type === "project") projectEventListener = callback;
      }
      removeEventListener(type: string) {
        if (type === "open") openEventListener = undefined;
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
  it("restores and updates the Instruments hash route", async () => {
    window.history.replaceState(null, "", "/#instruments");
    renderApp();

    expect(await screen.findByText("Instrument workspace")).toBeVisible();
    expect(screen.getByRole("button", { name: "Instruments" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(getRuns).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Configuration" }));
    expect(window.location.hash).toBe("#configuration");
    fireEvent.click(screen.getByRole("button", { name: "Instruments" }));
    expect(window.location.hash).toBe("#instruments");
  });

  it("invalidates instrument queries after project events", async () => {
    window.history.replaceState(null, "", "/#instruments");
    const queryClient = createQueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    renderApp(queryClient);
    await screen.findByText("Instrument workspace");
    await waitFor(() => expect(projectEventListener).toBeDefined());

    act(() => emitProjectEvent("run-1", "instrument_session_opened"));

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["instruments"] }));
  });

  it("does not mount the run browser while configuration is active", async () => {
    renderApp();

    await screen.findByRole("button", { name: "Open listed producing run" });
    expect(getRuns).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#configuration");
    expect(screen.getByRole("button", { name: "Configuration" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("opens the producing run and selects it in the existing Runs view", async () => {
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "Open listed producing run" }));

    expect(screen.getByRole("button", { name: "Runs" })).toHaveAttribute("aria-current", "page");
    await waitFor(() =>
      expect(screen.getByTitle("Inspect run run-2")).toHaveAttribute("aria-current", "true"),
    );
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("?run=run-2");
    await waitFor(() =>
      expect(getRunEvents).toHaveBeenCalledWith("run-2", expect.any(AbortSignal)),
    );
  });

  it("preserves a producing run that is outside the latest run index", async () => {
    renderApp();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open unlisted producing run",
      }),
    );

    expect(screen.getByRole("button", { name: "Runs" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByTitle("run-archive")).toHaveTextContent("run-archive");
    expect(screen.getByTitle("Inspect run run-1")).not.toHaveAttribute("aria-current");
    expect(screen.getByTitle("Inspect run run-2")).not.toHaveAttribute("aria-current");
  });

  it("selects the first indexed run when no explicit run was requested", async () => {
    window.history.replaceState(null, "", "/");

    renderApp();

    await waitFor(() =>
      expect(screen.getByTitle("Inspect run run-1")).toHaveAttribute("aria-current", "true"),
    );
    expect(screen.getByTitle("run-1")).toHaveTextContent("run-1");
    expect(window.location.search).toBe("?run=run-1");
  });

  it("restores the selected run from the URL", async () => {
    window.history.replaceState(null, "", "/?run=run-2#configuration");

    renderApp();

    expect(screen.getByRole("button", { name: "Configuration" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(screen.getByRole("button", { name: "Runs" }));
    await waitFor(() =>
      expect(screen.getByTitle("Inspect run run-2")).toHaveAttribute("aria-current", "true"),
    );
    expect(screen.getByTitle("run-2")).toHaveTextContent("run-2");
  });

  it("loads and merges older run pages", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(getRuns).mockResolvedValue({
      items: RUNS.map((run, index) => ({ ...run, sequence: index + 20 })),
      nextCursor: 20,
    });
    vi.mocked(getOlderRuns).mockResolvedValue({
      items: [
        { ...projectRun("run-old"), sequence: 2 },
        { ...projectRun("run-1"), sequence: 1 },
      ],
    });

    renderApp();
    expect(await screen.findByText("0 active in loaded runs")).toBeVisible();
    expect(screen.getByText("No flags in loaded runs")).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "Load older runs" }));

    expect(await screen.findByTitle("Inspect run run-old")).toBeVisible();
    expect(getOlderRuns).toHaveBeenCalledWith(20);
    expect(screen.getAllByTitle("Inspect run run-1")).toHaveLength(1);
    expect(
      screen.getAllByTitle(/^Inspect run /).map((button) => button.getAttribute("title")),
    ).toEqual(["Inspect run run-2", "Inspect run run-1", "Inspect run run-old"]);
    expect(screen.queryByRole("button", { name: "Load older runs" })).not.toBeInTheDocument();
  });

  it("groups loaded staged runs and finds them by sequence id", async () => {
    window.history.replaceState(null, "", "/");
    const stagedRuns = [
      { ...stagedRun("run-stage-3", "adaptive-sequence", 2, "run-stage-2"), sequence: 30 },
      { ...projectRun("run-regular"), sequence: 29 },
      { ...stagedRun("run-stage-2", "adaptive-sequence", 1, "run-stage-1"), sequence: 28 },
      { ...stagedRun("run-stage-1", "adaptive-sequence", 0), sequence: 27 },
    ];
    vi.mocked(getRuns).mockResolvedValue({ items: stagedRuns });
    vi.mocked(getRun).mockImplementation(
      async (runId) => stagedRuns.find((run) => run.runId === runId) ?? projectRun(runId),
    );

    renderApp();

    const group = await screen.findByRole("region", {
      name: "Sequence adaptive-sequence",
    });
    expect(screen.getAllByTestId("run-sequence-group")).toHaveLength(1);
    expect(within(group).getByText("3 stages shown")).toBeVisible();
    expect(within(group).getByText("Stage 3")).toBeVisible();
    expect(within(group).getByText("Stage 2")).toBeVisible();
    expect(within(group).getByText("Stage 1")).toBeVisible();
    expect(screen.getByTitle("Inspect run run-regular")).toBeVisible();

    fireEvent.change(screen.getByPlaceholderText("Search runs or sequences"), {
      target: { value: "adaptive-sequence" },
    });
    expect(screen.queryByTitle("Inspect run run-regular")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Sequence adaptive-sequence" })).toBeVisible();
    expect(getRuns).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(getRun).toHaveBeenCalledTimes(1));
  });

  it("merges one staged sequence across loaded run pages", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(getRuns).mockResolvedValue({
      items: [{ ...stagedRun("run-stage-2", "paged-sequence", 1, "run-stage-1"), sequence: 20 }],
      nextCursor: 20,
    });
    vi.mocked(getOlderRuns).mockResolvedValue({
      items: [{ ...stagedRun("run-stage-1", "paged-sequence", 0), sequence: 19 }],
    });
    vi.mocked(getRun).mockImplementation(async (runId) =>
      runId === "run-stage-2"
        ? stagedRun("run-stage-2", "paged-sequence", 1, "run-stage-1")
        : stagedRun("run-stage-1", "paged-sequence", 0),
    );

    renderApp();

    const initial = await screen.findByRole("region", { name: "Sequence paged-sequence" });
    expect(within(initial).getByText("1 stage shown")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Load older runs" }));

    const merged = await screen.findByRole("region", { name: "Sequence paged-sequence" });
    expect(within(merged).getByText("2 stages shown")).toBeVisible();
    expect(screen.getAllByTestId("run-sequence-group")).toHaveLength(1);
  });

  it("opens an unloaded previous stage from run detail lineage", async () => {
    window.history.replaceState(null, "", "/?run=run-stage-2");
    const current = stagedRun("run-stage-2", "detail-sequence", 1, "run-stage-1-unloaded");
    const previous = stagedRun("run-stage-1-unloaded", "detail-sequence", 0);
    vi.mocked(getRuns).mockResolvedValue({ items: [current] });
    vi.mocked(getRun).mockImplementation(async (runId) =>
      runId === current.runId ? current : previous,
    );

    renderApp();

    const lineage = await screen.findByTestId("run-stage-lineage");
    expect(lineage).toHaveAttribute("title", "Sequence detail-sequence, stage 2");
    expect(lineage).toHaveTextContent("Stage 2");
    fireEvent.click(screen.getByRole("button", { name: "Previous stage" }));

    await waitFor(() =>
      expect(getRun).toHaveBeenCalledWith("run-stage-1-unloaded", expect.any(AbortSignal)),
    );
    expect(await screen.findByTitle("run-stage-1-unloaded")).toHaveTextContent(
      "run-stage-1-unloaded",
    );
    expect(window.location.search).toBe("?run=run-stage-1-unloaded");
  });

  it("discards loaded history when the latest page head moves", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(getRuns)
      .mockResolvedValueOnce({
        items: RUNS.map((run, index) => ({ ...run, sequence: index + 20 })),
        nextCursor: 20,
      })
      .mockResolvedValue({
        items: RUNS.map((run, index) => ({ ...run, sequence: index + 30 })),
        nextCursor: 30,
      });
    vi.mocked(getOlderRuns).mockResolvedValue({
      items: [{ ...projectRun("run-old"), sequence: 2 }],
    });

    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Load older runs" }));
    expect(await screen.findByTitle("Inspect run run-old")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Refresh project data" }));

    await waitFor(() => expect(screen.queryByTitle("Inspect run run-old")).not.toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: "Load older runs" }));
    await waitFor(() =>
      expect(vi.mocked(getOlderRuns).mock.calls.map(([cursor]) => cursor)).toEqual([20, 30]),
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

    expect((await screen.findAllByText("Online", { exact: true }))[0]).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh project data" }));

    expect(await screen.findByText("Disconnected", { exact: true })).toBeVisible();
    expect(screen.getByText("Daemon unavailable.")).toBeVisible();
  });

  it("uses durable transitions without treating a started point as complete", async () => {
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
        kind: "execution_transition_committed",
        payload: {
          stage: "compute",
          state: "started",
          point_index: 2,
          evidence: {},
        },
      },
      {
        id: 2,
        runId: "run-1",
        kind: "execution_transition_committed",
        payload: {
          stage: "append_measurement",
          state: "completed",
          evidence: { start_index: 0, record_count: 1 },
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
    vi.mocked(getMeasurementPreview).mockImplementation(async (_runId, offset = 0) =>
      offset === 0
        ? {
            items: [measurementRecord(0, 1, "dataset-a")],
            nextOffset: 1,
          }
        : {
            items: [measurementRecord(0, 2, "dataset-b")],
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
    expect(getMeasurementPreview).toHaveBeenCalledWith("run-1", 1, expect.any(AbortSignal));
    expect(screen.getByTestId("measurement-preview")).toHaveTextContent(
      '"dataset_id": "dataset-b"',
    );
    expect(screen.getByText(/2 records/)).toBeVisible();
  });

  it("resets measurement pages for the event's run", async () => {
    window.history.replaceState(null, "", "/?run=run-1");
    vi.mocked(getMeasurementPreview).mockImplementation(async (_runId, offset = 0) => ({
      items: [measurementRecord(offset, offset)],
      nextOffset: offset === 0 ? 1 : undefined,
    }));

    const queryClient = createQueryClient();
    renderApp(queryClient);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Load more measurements",
      }),
    );
    await waitFor(() => expect(getMeasurementPreview).toHaveBeenCalledTimes(2));
    expect(projectEventListener).toBeDefined();
    queryClient.setQueryData(["measurements", "run-2"], {
      pages: [{ items: [measurementRecord(9, 9)] }],
      pageParams: [0],
    });

    act(() => {
      emitProjectEvent("run-2", "measurement_dataset_initialized");
    });
    await waitFor(() =>
      expect(queryClient.getQueryData(["measurements", "run-2"])).toBeUndefined(),
    );
    expect(getMeasurementPreview).toHaveBeenCalledTimes(2);

    act(() => {
      emitProjectEvent("run-1", "measurements_sealed");
    });
    await waitFor(() => expect(getMeasurementPreview).toHaveBeenCalledTimes(3));
    expect(vi.mocked(getMeasurementPreview).mock.calls.map(([, offset]) => offset)).toEqual([
      0, 1, 0,
    ]);
    expect(screen.getByRole("button", { name: "Load more measurements" })).toBeVisible();
  });

  it("refreshes canonical queries whenever SSE connects", async () => {
    window.history.replaceState(null, "", "/?run=run-1");
    renderApp();

    expect(await screen.findByRole("heading", { name: "Recent events" })).toBeVisible();
    await waitFor(() => expect(openEventListener).toBeDefined());
    const initialCounts = canonicalQueryCallCounts();

    act(() => {
      emitSseOpen();
    });
    await waitFor(() =>
      expect(canonicalQueryCallCounts()).toEqual(initialCounts.map((count) => count + 1)),
    );
    const connectedCounts = canonicalQueryCallCounts();

    act(() => {
      emitSseOpen();
    });
    await waitFor(() =>
      expect(canonicalQueryCallCounts()).toEqual(connectedCounts.map((count) => count + 1)),
    );
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

    expect(await screen.findByRole("heading", { name: "Recent events" })).toBeVisible();
    expect(
      screen.getByText("Showing the latest 500 events; older events are not loaded."),
    ).toBeVisible();
  });
});

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function renderApp(queryClient = createQueryClient()) {
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

function stagedRun(
  runId: string,
  sequenceId: string,
  index: number,
  previousRunId?: string,
): ProjectRun {
  return {
    ...projectRun(runId),
    stage: { sequenceId, index, previousRunId },
  };
}

function measurementRecord(
  pointIndex: number,
  signal: number,
  datasetId?: string,
): MeasurementRecord {
  return {
    run_id: "run-1",
    logical_point_id: `${datasetId ?? "point"}-${pointIndex}`,
    point_index: pointIndex,
    coordinates: {},
    observables: {
      signal: {
        kind: "scalar",
        dtype: "float64",
        unit: "ratio",
        value: signal,
      },
    },
    metadata: datasetId ? { dataset_id: datasetId } : {},
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

function emitSseOpen(): void {
  if (!openEventListener) throw new Error("SSE open listener is not ready");
  openEventListener(new Event("open"));
}

function canonicalQueryCallCounts(): number[] {
  return [
    vi.mocked(getRuns).mock.calls.length,
    vi.mocked(getEvents).mock.calls.length,
    vi.mocked(getRun).mock.calls.length,
    vi.mocked(getRunEvents).mock.calls.length,
    vi.mocked(getMeasurementPreview).mock.calls.length,
    vi.mocked(getRunAnalyses).mock.calls.length,
  ];
}
