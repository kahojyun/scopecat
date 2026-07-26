import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import { Atom, LayoutDashboard, LoaderCircle, RefreshCw, Settings2, Unplug } from "lucide-react";
import { getEvents, getHealth } from "./api";
import { RunsWorkspace } from "./features/runs/RunsWorkspace";
import { titleCase } from "./lib/presentation";

type ProjectView = "runs" | "configuration";

const ConfigWorkspace = lazy(async () => {
  const module = await import("./features/config/ConfigWorkspace");
  return { default: module.ConfigWorkspace };
});

export default function App() {
  const queryClient = useQueryClient();
  const activeQueries = useIsFetching();
  const [view, setView] = useState<ProjectView>(() =>
    window.location.hash === "#configuration" ? "configuration" : "runs",
  );
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(selectedRunFromUrl);
  const eventCursor = useRef(0);

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 5_000,
  });
  const eventsQuery = useQuery({
    queryKey: ["events"],
    queryFn: ({ signal }) => getEvents(signal),
  });

  useEffect(() => {
    const latest = eventsQuery.data?.at(-1)?.id;
    if (latest !== undefined) {
      eventCursor.current = Math.max(eventCursor.current, latest);
    }
  }, [eventsQuery.data]);

  useEffect(() => {
    if (!healthQuery.isSuccess) return;
    const events = new EventSource(`/api/v1/events/stream?after=${eventCursor.current}`);
    let refreshTimer: number | undefined;
    const measurementRunsToReset = new Set<string>();
    const invalidateCanonicalQueries = () => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      void queryClient.invalidateQueries({ queryKey: ["events"] });
      void queryClient.invalidateQueries({ queryKey: ["run"] });
      void queryClient.invalidateQueries({ queryKey: ["analyses"] });
      void queryClient.invalidateQueries({ queryKey: ["run-content"] });
      void queryClient.invalidateQueries({ queryKey: ["config"] });
      void queryClient.invalidateQueries({
        queryKey: ["parameter-proposals"],
      });
    };
    const refreshAfterConnection = () => {
      invalidateCanonicalQueries();
      void queryClient.resetQueries({ queryKey: ["measurements"] });
    };
    const refresh = (event: Event) => {
      const measurementRunId = measurementEventRunId(event);
      if (measurementRunId !== undefined) {
        measurementRunsToReset.add(measurementRunId);
      }
      if (refreshTimer !== undefined) return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        const resetMeasurementRuns = [...measurementRunsToReset];
        measurementRunsToReset.clear();
        invalidateCanonicalQueries();
        for (const runId of resetMeasurementRuns) {
          void queryClient.resetQueries({
            queryKey: ["measurements", runId],
            exact: true,
          });
        }
      }, 100);
    };
    events.addEventListener("open", refreshAfterConnection);
    events.addEventListener("project", refresh);
    return () => {
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      events.removeEventListener("open", refreshAfterConnection);
      events.removeEventListener("project", refresh);
      events.close();
    };
  }, [healthQuery.isSuccess, queryClient]);

  const daemonReachable = healthQuery.isSuccess;
  const daemonUnavailable = healthQuery.isError;
  const lastUpdated = Math.max(healthQuery.dataUpdatedAt, eventsQuery.dataUpdatedAt);

  const refresh = () => {
    void queryClient.invalidateQueries();
  };
  const selectView = (selected: ProjectView) => {
    setView(selected);
    replaceNavigation(selected, selectedRunId);
    window.scrollTo({ top: 0, left: 0 });
  };
  const selectRun = useCallback((runId: string) => {
    setSelectedRunId(runId);
    replaceNavigation("runs", runId);
  }, []);
  const openConfigSourceRun = (runId: string) => {
    setSelectedRunId(runId);
    setView("runs");
    replaceNavigation("runs", runId);
    window.scrollTo({ top: 0, left: 0 });
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Scopecat project console">
          <span className="brand-mark" aria-hidden="true">
            <Atom size={20} strokeWidth={1.8} />
          </span>
          <span>
            <strong>Scopecat</strong>
            <small>Project console</small>
          </span>
        </a>
        <nav className="workspace-nav" aria-label="Project sections">
          <button
            type="button"
            className={view === "runs" ? "active" : undefined}
            aria-current={view === "runs" ? "page" : undefined}
            onClick={() => selectView("runs")}
          >
            <LayoutDashboard size={15} aria-hidden="true" />
            Runs
          </button>
          <button
            type="button"
            className={view === "configuration" ? "active" : undefined}
            aria-current={view === "configuration" ? "page" : undefined}
            onClick={() => selectView("configuration")}
          >
            <Settings2 size={15} aria-hidden="true" />
            Configuration
          </button>
        </nav>
        <div className="topbar-actions">
          <ConnectionState
            reachable={daemonReachable}
            pending={healthQuery.isPending}
            status={healthQuery.data?.status}
          />
          <button
            className="icon-button"
            type="button"
            onClick={refresh}
            aria-label="Refresh project data"
            title="Refresh project data"
          >
            <RefreshCw
              size={17}
              className={activeQueries > 0 ? "spin" : undefined}
              aria-hidden="true"
            />
          </button>
        </div>
      </header>

      <main>
        <section className="workspace-context" aria-labelledby="workspace-title">
          <div className="workspace-identity">
            <h1 id="workspace-title">{healthQuery.data?.projectName ?? "Scopecat project"}</h1>
            {healthQuery.data?.projectRoot && (
              <code className="project-root">{healthQuery.data.projectRoot}</code>
            )}
          </div>
          <div className="sync-note" aria-live="polite">
            {lastUpdated > 0
              ? `Updated ${formatClock(new Date(lastUpdated).toISOString())}`
              : "Waiting for daemon"}
          </div>
        </section>

        {daemonUnavailable && (
          <div className="connection-banner" role="status">
            <Unplug size={18} aria-hidden="true" />
            <span>
              <strong>Daemon unavailable.</strong> Start the local Scopecat daemon, then refresh
              this page. No cached project data is shown.
            </span>
          </div>
        )}

        {view === "runs" ? (
          <RunsWorkspace
            selectedRunId={selectedRunId}
            onSelectRun={selectRun}
            health={healthQuery.data}
            healthPending={healthQuery.isPending}
            healthReachable={daemonReachable}
            daemonUnavailable={daemonUnavailable}
          />
        ) : (
          <Suspense
            fallback={
              <DetailEmpty
                icon={<LoaderCircle className="spin" />}
                title="Loading configuration"
                detail="The configuration workspace is being prepared."
              />
            }
          >
            <ConfigWorkspace
              daemonUnavailable={daemonUnavailable}
              onOpenRun={openConfigSourceRun}
            />
          </Suspense>
        )}
      </main>
    </div>
  );
}

function ConnectionState({
  reachable,
  pending,
  status,
}: {
  reachable: boolean;
  pending: boolean;
  status?: string;
}) {
  const label = pending
    ? "Connecting"
    : reachable
      ? titleCase(status ?? "connected")
      : "Disconnected";
  return (
    <span className={`connection-state ${reachable ? "connected" : "disconnected"}`} role="status">
      <span className="connection-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

function DetailEmpty({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="detail-empty">
      <span aria-hidden="true">{icon}</span>
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

function selectedRunFromUrl(): string | undefined {
  return new URL(window.location.href).searchParams.get("run") || undefined;
}

function replaceNavigation(view: ProjectView, runId?: string): void {
  const location = new URL(window.location.href);
  if (runId) {
    location.searchParams.set("run", runId);
  } else {
    location.searchParams.delete("run");
  }
  location.hash = view === "configuration" ? "configuration" : "";
  window.history.replaceState(null, "", `${location.pathname}${location.search}${location.hash}`);
}

function measurementEventRunId(event: Event): string | undefined {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
    return undefined;
  }
  try {
    const payload: unknown = JSON.parse(event.data);
    if (typeof payload !== "object" || payload === null) return undefined;
    const source = payload as Record<string, unknown>;
    if (source.kind !== "measurements_appended" && source.kind !== "measurements_sealed") {
      return undefined;
    }
    return typeof source.run_id === "string" ? source.run_id : undefined;
  } catch {
    return undefined;
  }
}

function formatClock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}
