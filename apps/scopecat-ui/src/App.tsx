import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Atom,
  Ban,
  BookOpen,
  Box,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Cpu,
  Database,
  FlaskConical,
  Gauge,
  Layers3,
  LayoutDashboard,
  ListFilter,
  LoaderCircle,
  Radio,
  RefreshCw,
  Search,
  Server,
  Settings2,
  ShieldAlert,
  SquareStack,
  Unlock,
  Unplug,
  Play,
  XCircle,
} from "lucide-react";
import { ConfigWorkspace } from "./ConfigWorkspace";
import { RunProposals } from "./RunProposals";
import {
  canPreviewRunContent,
  getCatalog,
  getEvents,
  getHealth,
  getMeasurementPreview,
  getOlderRuns,
  getRun,
  getRunAnalyses,
  getRunContent,
  getRunEvents,
  getRuns,
  resolveAttention,
  type AttentionAction,
} from "./api";
import type {
  ContentEntry,
  ExperimentCatalog,
  MeasurementPreview,
  ProjectEvent,
  ProjectHealth,
  ProjectRun,
  ProjectRunPage,
  RunAnalysis,
} from "./types";

type FilterKey = "all" | "active" | "attention" | "complete";
type ProjectView = "runs" | "configuration";
interface OlderRunHistory {
  headCursor: number;
  pages: ProjectRunPage[];
}
interface OlderRunPageRequest {
  headCursor: number;
  before: number;
}

const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "attention", label: "Attention" },
  { key: "complete", label: "Finished" },
];

export default function App() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<ProjectView>(() =>
    window.location.hash === "#configuration" ? "configuration" : "runs",
  );
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(
    selectedRunFromUrl,
  );
  const [olderRunHistory, setOlderRunHistory] =
    useState<OlderRunHistory>();
  const eventCursor = useRef(0);
  const latestRunHeadCursor = useRef<number | undefined>(undefined);
  const selectedRunIdRef = useRef(selectedRunId);
  selectedRunIdRef.current = selectedRunId;

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 5_000,
  });
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: ({ signal }) => getRuns(signal),
    refetchInterval: 2_500,
  });
  const runHeadCursor = runsQuery.data?.previousCursor;
  latestRunHeadCursor.current = runHeadCursor;
  const olderRunsMutation = useMutation({
    mutationFn: ({ before }: OlderRunPageRequest) => getOlderRuns(before),
    onSuccess: (page, request) => {
      if (latestRunHeadCursor.current !== request.headCursor) return;
      setOlderRunHistory((current) =>
        current?.headCursor === request.headCursor
          ? { ...current, pages: [...current.pages, page] }
          : { headCursor: request.headCursor, pages: [page] },
      );
    },
  });
  const eventsQuery = useQuery({
    queryKey: ["events"],
    queryFn: ({ signal }) => getEvents(signal),
    refetchInterval: 2_500,
  });
  const catalogQuery = useQuery({
    queryKey: ["catalog"],
    queryFn: ({ signal }) => getCatalog(signal),
    refetchInterval: 30_000,
  });
  const runDetailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: ({ signal }) => getRun(selectedRunId!, signal),
    enabled: selectedRunId !== undefined,
  });
  const selectedEventsQuery = useQuery({
    queryKey: ["events", "run", selectedRunId],
    queryFn: ({ signal }) => getRunEvents(selectedRunId!, signal),
    enabled: selectedRunId !== undefined,
  });
  const measurementsQuery = useInfiniteQuery({
    queryKey: ["measurements", selectedRunId],
    queryFn: ({ signal, pageParam }) =>
      getMeasurementPreview(selectedRunId!, pageParam, signal),
    enabled: selectedRunId !== undefined,
    initialPageParam: 0,
    getNextPageParam: (page) => page.nextOffset,
  });
  const analysesQuery = useQuery({
    queryKey: ["analyses", selectedRunId],
    queryFn: ({ signal }) => getRunAnalyses(selectedRunId!, signal),
    enabled: selectedRunId !== undefined,
  });
  const attentionMutation = useMutation({
    mutationFn: ({
      runId,
      action,
    }: {
      runId: string;
      action: AttentionAction;
    }) => resolveAttention(runId, action),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["runs"] }),
        queryClient.invalidateQueries({ queryKey: ["events"] }),
        queryClient.invalidateQueries({ queryKey: ["run"] }),
      ]);
    },
  });

  useEffect(() => {
    const latest = eventsQuery.data?.at(-1)?.id;
    if (latest !== undefined) {
      eventCursor.current = Math.max(eventCursor.current, latest);
    }
  }, [eventsQuery.data]);

  useEffect(() => {
    if (!eventsQuery.isSuccess) return;
    const events = new EventSource(
      `/api/v1/events/stream?after=${eventCursor.current}`,
    );
    let refreshTimer: number | undefined;
    const measurementRunsToReset = new Set<string>();
    const refresh = (event: Event) => {
      const measurementRunId = measurementEventRunId(event);
      if (
        measurementRunId !== undefined &&
        measurementRunId === selectedRunIdRef.current
      ) {
        measurementRunsToReset.add(measurementRunId);
      }
      if (refreshTimer !== undefined) return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        const resetMeasurementRuns = [...measurementRunsToReset];
        measurementRunsToReset.clear();
        void queryClient.invalidateQueries({ queryKey: ["runs"] });
        void queryClient.invalidateQueries({ queryKey: ["events"] });
        void queryClient.invalidateQueries({ queryKey: ["run"] });
        for (const runId of resetMeasurementRuns) {
          void queryClient.resetQueries({
            queryKey: ["measurements", runId],
            exact: true,
          });
        }
        void queryClient.invalidateQueries({ queryKey: ["analyses"] });
        void queryClient.invalidateQueries({ queryKey: ["run-content"] });
        void queryClient.invalidateQueries({ queryKey: ["config"] });
        void queryClient.invalidateQueries({
          queryKey: ["parameter-proposals"],
        });
      }, 100);
    };
    events.addEventListener("project", refresh);
    return () => {
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      events.removeEventListener("project", refresh);
      events.close();
    };
  }, [eventsQuery.isSuccess, queryClient]);

  const olderRunPages =
    olderRunHistory && olderRunHistory.headCursor === runHeadCursor
      ? olderRunHistory.pages
      : [];
  const runs = useMemo(
    () => {
      const indexedRuns = mergeRunPages([
        ...olderRunPages,
        ...(runsQuery.data ? [runsQuery.data] : []),
      ]);
      return runDetailQuery.data
        ? indexedRuns.map((run) =>
            run.runId === runDetailQuery.data.runId
              ? runDetailQuery.data
              : run,
          )
        : indexedRuns;
    },
    [olderRunPages, runDetailQuery.data, runsQuery.data],
  );
  const previousRunCursor =
    olderRunPages.length > 0
      ? olderRunPages.at(-1)?.previousCursor
      : runHeadCursor;
  const measurements = useMemo(
    () => mergeMeasurementPages(measurementsQuery.data?.pages ?? []),
    [measurementsQuery.data?.pages],
  );
  const catalog = catalogQuery.data;
  const filteredRuns = useMemo(
    () => filterRuns(runs, filter, search),
    [runs, filter, search],
  );

  useEffect(() => {
    setOlderRunHistory((current) =>
      current && current.headCursor !== runHeadCursor ? undefined : current,
    );
  }, [runHeadCursor]);

  useEffect(() => {
    if (runs.length > 0 && selectedRunId === undefined) {
      const firstRunId = runs[0]?.runId;
      setSelectedRunId(firstRunId);
      replaceNavigation(view, firstRunId);
    }
  }, [runs, selectedRunId, view]);

  const selectedRun =
    runDetailQuery.data ??
    runs.find((run) => run.runId === selectedRunId);
  const selectedEvents = selectedEventsQuery.data ?? [];
  const activeCount = runs.filter((run) =>
    ["accepted", "running"].includes(run.status),
  ).length;
  const attentionCount = runs.filter(
    (run) => run.status === "attention_required",
  ).length;
  const daemonReachable = healthQuery.isSuccess;
  const daemonUnavailable = healthQuery.isError;
  const refreshing =
    healthQuery.isFetching ||
    runsQuery.isFetching ||
    eventsQuery.isFetching ||
    catalogQuery.isFetching;
  const lastUpdated = Math.max(
    healthQuery.dataUpdatedAt,
    runsQuery.dataUpdatedAt,
    eventsQuery.dataUpdatedAt,
    catalogQuery.dataUpdatedAt,
  );

  const refresh = () => {
    void queryClient.invalidateQueries();
  };
  const selectView = (selected: ProjectView) => {
    setView(selected);
    replaceNavigation(selected, selectedRunId);
    window.scrollTo({ top: 0, left: 0 });
  };
  const selectRun = (runId: string) => {
    setSelectedRunId(runId);
    replaceNavigation("runs", runId);
  };
  const openConfigSourceRun = (runId: string) => {
    setSelectedRunId(runId);
    setSearch("");
    setFilter("all");
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
              className={refreshing ? "spin" : undefined}
              aria-hidden="true"
            />
          </button>
        </div>
      </header>

      <main>
        <section className="workspace-heading" aria-labelledby="workspace-title">
          <div>
            <p className="eyebrow">
              {view === "runs"
                ? "Local control plane"
                : "Durable configuration"}
            </p>
            <h1 id="workspace-title">
              {healthQuery.data?.projectName ?? "Scopecat project"}
            </h1>
            {healthQuery.data?.projectRoot && (
              <code className="project-root">
                {healthQuery.data.projectRoot}
              </code>
            )}
            <p className="workspace-subtitle">
              {view === "runs"
                ? "Observe experiments, resources, and durable execution events."
                : "Review active state, immutable snapshots, and registry history."}
            </p>
          </div>
          <div className="sync-note" aria-live="polite">
            <Radio size={14} aria-hidden="true" />
            {lastUpdated > 0
              ? `Updated ${formatClock(new Date(lastUpdated).toISOString())}`
              : "Waiting for daemon"}
          </div>
        </section>

        {daemonUnavailable && (
          <div className="connection-banner" role="status">
            <Unplug size={18} aria-hidden="true" />
            <span>
              <strong>Daemon unavailable.</strong> Start the local Scopecat
              daemon, then refresh this page. No cached project data is shown.
            </span>
          </div>
        )}

        {view === "runs" ? (
          <>
            <section className="status-grid" aria-label="Project status">
          <StatusCard
            icon={<Server size={18} />}
            label="Daemon"
            value={
              healthQuery.isSuccess
                ? titleCase(healthQuery.data.status)
                : healthQuery.isPending
                  ? "Checking"
                  : "Unavailable"
            }
            detail={healthDetail(healthQuery.data)}
            tone={healthQuery.isSuccess ? "good" : "muted"}
          />
          <StatusCard
            icon={<FlaskConical size={18} />}
            label="Runs"
            value={
              runsQuery.isSuccess
                ? `${runs.length}${previousRunCursor !== undefined ? "+" : ""}`
                : "—"
            }
            detail={
              runsQuery.isSuccess
                ? previousRunCursor !== undefined
                  ? `${activeCount} active in loaded runs`
                  : `${activeCount} active`
                : "No run data received"
            }
            tone={activeCount > 0 ? "active" : "muted"}
          />
          <StatusCard
            icon={<ShieldAlert size={18} />}
            label="Attention"
            value={runsQuery.isSuccess ? String(attentionCount) : "—"}
            detail={
              attentionCount > 0
                ? "Operator review needed"
                : previousRunCursor !== undefined
                  ? "No flags in loaded runs"
                  : "No flagged runs"
            }
            tone={
              attentionCount > 0
                ? "warning"
                : previousRunCursor !== undefined
                  ? "muted"
                  : "good"
            }
          />
          <StatusCard
            icon={<BookOpen size={18} />}
            label="Catalog"
            value={
              catalogQuery.isSuccess
                ? String(catalog?.experiments.length ?? 0)
                : "—"
            }
            detail={
              catalog?.revision
                ? `Revision ${shorten(catalog.revision, 10)}`
                : "No revision reported"
            }
            tone="muted"
          />
            </section>

            <div className="console-grid">
          <aside className="run-browser" aria-labelledby="runs-heading">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Run browser</p>
                <h2 id="runs-heading">Experiments</h2>
              </div>
              {runsQuery.isFetching && (
                <LoaderCircle
                  className="spin subtle-icon"
                  size={17}
                  aria-label="Refreshing runs"
                />
              )}
            </div>

            <label className="search-field">
              <Search size={16} aria-hidden="true" />
              <span className="visually-hidden">
                Search by run, experiment, mode, or resource
              </span>
              <input
                type="search"
                placeholder="Search runs"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>

            <div className="filter-row" aria-label="Filter runs">
              <ListFilter size={15} aria-hidden="true" />
              {FILTERS.map((item) => (
                <button
                  key={item.key}
                  className={filter === item.key ? "filter active" : "filter"}
                  type="button"
                  aria-pressed={filter === item.key}
                  onClick={() => setFilter(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div className="run-list">
              {runsQuery.isPending && (
                <PanelMessage
                  icon={<LoaderCircle className="spin" />}
                  title="Reading project"
                  detail="Waiting for the daemon to return its run index."
                />
              )}
              {runsQuery.isError && (
                <PanelMessage
                  icon={<Unplug />}
                  title="Run list unavailable"
                  detail={errorMessage(runsQuery.error)}
                />
              )}
              {runsQuery.isSuccess && runs.length === 0 && (
                <PanelMessage
                  icon={<FlaskConical />}
                  title="No runs yet"
                  detail="Submitted experiments will appear here."
                />
              )}
              {runsQuery.isSuccess &&
                runs.length > 0 &&
                filteredRuns.length === 0 && (
                  <PanelMessage
                    icon={<Search />}
                    title="No matching runs"
                    detail="Try another status or search term."
                  />
                )}
              {filteredRuns.map((run) => (
                <RunListItem
                  key={run.runId}
                  run={run}
                  selected={run.runId === selectedRunId}
                  onSelect={() => selectRun(run.runId)}
                />
              ))}
              {olderRunsMutation.isError && (
                <p className="run-pagination-error" role="status">
                  {errorMessage(olderRunsMutation.error)}
                </p>
              )}
              {runsQuery.isSuccess &&
                runHeadCursor !== undefined &&
                previousRunCursor !== undefined && (
                <div className="run-pagination">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={olderRunsMutation.isPending}
                    onClick={() =>
                      olderRunsMutation.mutate({
                        headCursor: runHeadCursor,
                        before: previousRunCursor,
                      })
                    }
                  >
                    {olderRunsMutation.isPending ? (
                      <LoaderCircle
                        className="spin"
                        size={14}
                        aria-hidden="true"
                      />
                    ) : (
                      <ChevronRight size={14} aria-hidden="true" />
                    )}
                    {olderRunsMutation.isPending
                      ? "Loading older runs…"
                      : "Load older runs"}
                  </button>
                </div>
              )}
            </div>
          </aside>

          <section className="run-detail" aria-label="Selected run details">
            {daemonUnavailable ? (
              <DetailEmpty
                icon={<Unplug />}
                title="Connect to the local daemon"
                detail="Project status and run data are read directly from the daemon. This console does not maintain an offline copy."
              />
            ) : selectedRun ? (
              <RunDetail
                run={selectedRun}
                events={selectedEvents}
                eventsError={selectedEventsQuery.error}
                eventsPending={selectedEventsQuery.isPending}
                catalog={catalog}
                catalogError={catalogQuery.error}
                measurements={measurements}
                measurementsError={measurementsQuery.error}
                measurementsPending={measurementsQuery.isPending}
                measurementsHasMore={measurementsQuery.hasNextPage}
                measurementsLoadingMore={measurementsQuery.isFetchingNextPage}
                onLoadMoreMeasurements={() => {
                  void measurementsQuery.fetchNextPage();
                }}
                analyses={analysesQuery.data}
                analysesError={analysesQuery.error}
                analysesPending={analysesQuery.isPending}
                attentionAction={attentionMutation.variables?.action}
                attentionError={attentionMutation.error}
                attentionPending={attentionMutation.isPending}
                onResolveAttention={(action) => {
                  if (!confirmAttentionAction(action)) return;
                  attentionMutation.mutate({
                    runId: selectedRun.runId,
                    action,
                  });
                }}
              />
            ) : runsQuery.isPending ? (
              <DetailEmpty
                icon={<LoaderCircle className="spin" />}
                title="Loading run details"
                detail="The project run index is being read."
              />
            ) : (
              <DetailEmpty
                icon={<CircleDot />}
                title="No run selected"
                detail="Choose a run to inspect its progress, resource claims, events, and data contents."
              />
            )}
          </section>
            </div>
          </>
        ) : (
          <ConfigWorkspace
            daemonUnavailable={daemonUnavailable}
            onOpenRun={openConfigSourceRun}
          />
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
    <span
      className={`connection-state ${reachable ? "connected" : "disconnected"}`}
      role="status"
    >
      <span className="connection-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

function StatusCard({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: "good" | "active" | "warning" | "muted";
}) {
  return (
    <article className={`status-card ${tone}`}>
      <div className="status-card-icon" aria-hidden="true">
        {icon}
      </div>
      <div>
        <span className="status-label">{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function RunListItem({
  run,
  selected,
  onSelect,
}: {
  run: ProjectRun;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={selected ? "run-item selected" : "run-item"}
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      title={`Inspect run ${run.runId}`}
    >
      <span className={`status-indicator status-${run.status}`} aria-hidden />
      <span className="run-item-copy">
        <span className="run-item-topline">
          <strong>{run.experimentId}</strong>
          <time dateTime={run.updatedAt}>
            {run.updatedAt ? formatRelative(run.updatedAt) : "No timestamp"}
          </time>
        </span>
        <span className="run-item-meta">
          <code>{shorten(run.runId, 18)}</code>
          <span>·</span>
          <span>{titleCase(run.executionMode)}</span>
        </span>
        <span className={`run-state status-${run.status}`}>
          {run.stateLabel}
        </span>
      </span>
      <ChevronRight size={16} className="run-chevron" aria-hidden="true" />
    </button>
  );
}

function RunDetail({
  run,
  events,
  eventsError,
  eventsPending,
  catalog,
  catalogError,
  measurements,
  measurementsError,
  measurementsPending,
  measurementsHasMore,
  measurementsLoadingMore,
  onLoadMoreMeasurements,
  analyses,
  analysesError,
  analysesPending,
  attentionAction,
  attentionError,
  attentionPending,
  onResolveAttention,
}: {
  run: ProjectRun;
  events: ProjectEvent[];
  eventsError: Error | null;
  eventsPending: boolean;
  catalog?: ExperimentCatalog;
  catalogError: Error | null;
  measurements?: MeasurementPreview;
  measurementsError: Error | null;
  measurementsPending: boolean;
  measurementsHasMore: boolean;
  measurementsLoadingMore: boolean;
  onLoadMoreMeasurements: () => void;
  analyses?: RunAnalysis[];
  analysesError: Error | null;
  analysesPending: boolean;
  attentionAction?: AttentionAction;
  attentionError: Error | null;
  attentionPending: boolean;
  onResolveAttention: (action: AttentionAction) => void;
}) {
  return (
    <>
      <header className="detail-header">
        <div className="detail-title">
          <div className="detail-kicker">
            <span className={`status-pill status-${run.status}`}>
              <span aria-hidden="true" />
              {run.stateLabel}
            </span>
            <span>{titleCase(run.executionMode)} execution</span>
          </div>
          <h2>{run.experimentId}</h2>
          <code title={run.runId}>{run.runId}</code>
        </div>
        <dl className="detail-meta">
          <div>
            <dt>Accepted</dt>
            <dd>
              {run.createdAt ? (
                <time dateTime={run.createdAt}>
                  {formatDateTime(run.createdAt)}
                </time>
              ) : (
                "Not reported"
              )}
            </dd>
          </div>
          <div>
            <dt>Config</dt>
            <dd>
              <code title={run.configHash}>
                {run.configHash ? shorten(run.configHash, 15) : "Not reported"}
              </code>
            </dd>
          </div>
        </dl>
      </header>

      {run.status === "attention_required" && (
        <div className="attention-callout" role="alert">
          <AlertTriangle size={19} aria-hidden="true" />
          <div>
            <strong>Operator attention required</strong>
            <p>
              {run.attentionReason ??
                "The daemon has not reported a reconciliation reason."}
            </p>
            <div className="attention-actions">
              <button
                type="button"
                onClick={() => onResolveAttention("release")}
                disabled={attentionPending}
              >
                <Unlock size={15} aria-hidden="true" />
                {attentionPending && attentionAction === "release"
                  ? "Releasing…"
                  : "Release resources"}
              </button>
              <button
                className="primary"
                type="button"
                onClick={() => onResolveAttention("requeue")}
                disabled={attentionPending}
              >
                <Play size={15} aria-hidden="true" />
                {attentionPending && attentionAction === "requeue"
                  ? "Requeuing…"
                  : "Requeue"}
              </button>
              <button
                className="danger"
                type="button"
                onClick={() => onResolveAttention("abort")}
                disabled={attentionPending}
              >
                <Ban size={15} aria-hidden="true" />
                {attentionPending && attentionAction === "abort"
                  ? "Aborting…"
                  : "Abort run"}
              </button>
            </div>
            {attentionError && (
              <p className="attention-error" role="status">
                {errorMessage(attentionError)}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="detail-grid">
        <ProgressCard run={run} events={events} />
        <RunProposals key={run.runId} runId={run.runId} />
        <AnalysisCard
          analyses={analyses}
          error={analysesError}
          pending={analysesPending}
        />
        <ResourceCard run={run} />
        <TimelineCard
          events={events}
          error={eventsError}
          pending={eventsPending}
        />
        <DataCard
          run={run}
          measurements={measurements}
          error={measurementsError}
          pending={measurementsPending}
          hasMoreMeasurements={measurementsHasMore}
          loadingMoreMeasurements={measurementsLoadingMore}
          onLoadMoreMeasurements={onLoadMoreMeasurements}
        />
        <CatalogCard
          currentExperimentId={run.experimentId}
          catalog={catalog}
          error={catalogError}
        />
      </div>
    </>
  );
}

function ProgressCard({
  run,
  events,
}: {
  run: ProjectRun;
  events: ProjectEvent[];
}) {
  const expected = run.plan.pointCount;
  const completed = completedPoints(run, events);
  const terminal = [
    "succeeded",
    "failed",
    "cancelled",
    "terminal",
  ].includes(run.status);
  const hasProgress = expected !== undefined && expected > 0;
  const progressValue = hasProgress
    ? terminal && run.status === "succeeded"
      ? expected
      : Math.min(completed, expected)
    : undefined;
  const percentage =
    progressValue !== undefined && expected
      ? Math.round((progressValue / expected) * 100)
      : undefined;

  return (
    <article className="detail-card progress-card">
      <CardHeading
        icon={<Gauge size={17} />}
        title="Execution progress"
        accessory={
          percentage !== undefined ? (
            <strong className="progress-percentage">{percentage}%</strong>
          ) : (
            <span className="quiet-label">{run.stateLabel}</span>
          )
        }
      />
      {hasProgress ? (
        <>
          <progress
            max={expected}
            value={progressValue}
            aria-label={`${progressValue ?? 0} of ${expected} points complete`}
          />
          <div className="progress-copy">
            <span>
              <strong>{progressValue ?? 0}</strong> / {expected} points
            </span>
            <span>{events.length} durable events</span>
          </div>
        </>
      ) : (
        <div className="progress-empty">
          <Activity size={23} aria-hidden="true" />
          <div>
            <strong>
              {run.status === "running"
                ? "Execution is active"
                : "No point total reported"}
            </strong>
            <p>
              {events.length > 0
                ? `${events.length} durable events received from this run.`
                : "Progress will appear when the daemon publishes plan or execution events."}
            </p>
          </div>
        </div>
      )}
      <div className="progress-facts">
        <Fact
          label="Last update"
          value={
            run.updatedAt ? formatRelative(run.updatedAt) : "Not reported"
          }
        />
        <Fact label="Result" value={titleCase(run.result ?? "Pending")} />
        <Fact label="Certainty" value={titleCase(run.certainty ?? "Pending")} />
      </div>
    </article>
  );
}

function AnalysisCard({
  analyses,
  error,
  pending,
}: {
  analyses?: RunAnalysis[];
  error: Error | null;
  pending: boolean;
}) {
  return (
    <article className="detail-card analysis-card">
      <CardHeading
        icon={<Atom size={17} />}
        title="Analyses"
        accessory={<span className="count-badge">{analyses?.length ?? 0}</span>}
      />
      {error ? (
        <InlineEmpty
          title="Analyses unavailable"
          detail={errorMessage(error)}
          warning
        />
      ) : pending ? (
        <InlineEmpty
          title="Reading analyses"
          detail="Waiting for the daemon's persisted analysis records."
        />
      ) : !analyses || analyses.length === 0 ? (
        <InlineEmpty
          title="No analyses saved"
          detail="Notebook and automated analysis outputs will appear here."
        />
      ) : (
        <div className="analysis-list">
          {analyses.map((analysis) => (
            <details key={analysis.id}>
              <summary>
                <span>
                  <strong>{analysis.title}</strong>
                  <small>
                    {analysis.key ?? analysis.id}
                    {analysis.stepId ? ` · ${analysis.stepId}` : ""}
                  </small>
                </span>
                <span className="count-badge">{analysis.outputs.length}</span>
              </summary>
              <div className="analysis-outputs">
                {analysis.outputs.map((output, index) => (
                  <section key={`${output.kind}:${output.title}:${index}`}>
                    <header>
                      <strong>{output.title}</strong>
                      <span>{titleCase(output.kind)}</span>
                    </header>
                    <pre>{formatPreviewContent(output.content)}</pre>
                  </section>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </article>
  );
}

function ResourceCard({ run }: { run: ProjectRun }) {
  return (
    <article className="detail-card resource-card">
      <CardHeading
        icon={<Cpu size={17} />}
        title="Resources"
        accessory={
          <span className="count-badge">{run.resources.length}</span>
        }
      />
      {run.resources.length > 0 ? (
        <ul className="resource-list">
          {run.resources.map((resource) => (
            <li key={`${resource.kind}:${resource.id}`}>
              <span className="resource-icon" aria-hidden="true">
                <Box size={15} />
              </span>
              <span>
                <strong>{resource.id}</strong>
                <small>{titleCase(resource.kind)}</small>
              </span>
              <span className={`lease-state ${resource.status ?? "claimed"}`}>
                {titleCase(resource.status ?? "claimed")}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <InlineEmpty
          title="No resource claims"
          detail="This run has not announced exclusive hardware resources."
        />
      )}
    </article>
  );
}

function TimelineCard({
  events,
  error,
  pending,
}: {
  events: ProjectEvent[];
  error: Error | null;
  pending: boolean;
}) {
  return (
    <article className="detail-card timeline-card">
      <CardHeading
        icon={<Activity size={17} />}
        title="Recent events"
        accessory={<span className="count-badge">{events.length}</span>}
      />
      {error ? (
        <InlineEmpty
          title="Events unavailable"
          detail={errorMessage(error)}
          warning
        />
      ) : pending ? (
        <InlineEmpty
          title="Reading events"
          detail="Waiting for this run's durable event timeline."
        />
      ) : events.length === 0 ? (
        <InlineEmpty
          title="No events reported"
          detail="The daemon has not returned durable events for this run."
        />
      ) : (
        <>
          {events.length === 500 && (
            <p className="timeline-limit-note">
              Showing the latest 500 events; older events are not loaded.
            </p>
          )}
          <ol className="timeline">
            {events.map((event) => (
              <li key={event.id}>
                <span className="timeline-marker" aria-hidden="true">
                  {eventIcon(event.kind)}
                </span>
                <div>
                  <div className="event-heading">
                    <strong>{humanizeEvent(event.kind)}</strong>
                    <span>#{event.id}</span>
                  </div>
                  <p>{eventDescription(event)}</p>
                  <time dateTime={event.occurredAt}>
                    {event.occurredAt
                      ? formatDateTime(event.occurredAt)
                      : "Timestamp not reported"}
                  </time>
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </article>
  );
}

function DataCard({
  run,
  measurements,
  error,
  pending,
  hasMoreMeasurements,
  loadingMoreMeasurements,
  onLoadMoreMeasurements,
}: {
  run: ProjectRun;
  measurements?: MeasurementPreview;
  error: Error | null;
  pending: boolean;
  hasMoreMeasurements: boolean;
  loadingMoreMeasurements: boolean;
  onLoadMoreMeasurements: () => void;
}) {
  const [selectedContentKey, setSelectedContentKey] = useState<string>();
  useEffect(() => {
    setSelectedContentKey((current) => {
      if (run.contents.some((entry) => contentKey(entry) === current)) {
        return current;
      }
      const preferred = run.contents.find(canPreviewRunContent) ?? run.contents[0];
      return preferred ? contentKey(preferred) : undefined;
    });
  }, [run.runId, run.contents]);
  const selectedContent = run.contents.find(
    (entry) => contentKey(entry) === selectedContentKey,
  );
  const contentQuery = useQuery({
    queryKey: [
      "run-content",
      run.runId,
      selectedContent?.role,
      selectedContent?.id,
      selectedContent?.kind,
    ],
    queryFn: ({ signal }) => getRunContent(run.runId, selectedContent!, signal),
    enabled:
      selectedContent !== undefined && canPreviewRunContent(selectedContent),
  });
  const hasPlanMetadata =
    run.plan.pointCount !== undefined ||
    run.plan.coordinateIds.length > 0 ||
    run.plan.recordIds.length > 0;
  return (
    <article className="detail-card data-card">
      <CardHeading
        icon={<Database size={17} />}
        title="Data contents"
        accessory={<span className="count-badge">{run.contents.length}</span>}
      />
      {hasPlanMetadata && (
        <div className="data-metrics">
          <Fact
            label="Planned points"
            value={
              run.plan.pointCount !== undefined
                ? run.plan.pointCount.toLocaleString()
                : "—"
            }
          />
          <Fact
            label="Coordinates"
            value={String(run.plan.coordinateIds.length)}
          />
          <Fact label="Records" value={String(run.plan.recordIds.length)} />
        </div>
      )}
      {run.plan.coordinateIds.length > 0 && (
        <TagGroup label="Coordinates" values={run.plan.coordinateIds} />
      )}
      {run.plan.recordIds.length > 0 && (
        <TagGroup label="Record types" values={run.plan.recordIds} />
      )}
      {run.contents.length > 0 ? (
        <ul className="content-list">
          {run.contents.map((content) => (
            <li
              key={contentKey(content)}
              className={
                contentKey(content) === selectedContentKey
                  ? "selected"
                  : undefined
              }
            >
              <button
                type="button"
                onClick={() => setSelectedContentKey(contentKey(content))}
                aria-current={
                  contentKey(content) === selectedContentKey ? "true" : undefined
                }
              >
                <span className="content-role" aria-hidden="true">
                  {content.role === "dataset" ? (
                    <Database size={15} />
                  ) : (
                    <SquareStack size={15} />
                  )}
                </span>
                <span>
                  <strong>{content.label}</strong>
                  <small>
                    {titleCase(content.role)}
                    {content.detail ? ` · ${content.detail}` : ""}
                  </small>
                </span>
                {canPreviewRunContent(content) && (
                  <ChevronRight size={15} aria-hidden="true" />
                )}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <InlineEmpty
          title="No materialized contents"
          detail="Dataset, record, and artifact metadata will appear after the daemon publishes it."
        />
      )}
      {selectedContent && (
        <RunContentPanel
          entry={selectedContent}
          content={contentQuery.data?.content}
          format={contentQuery.data?.format}
          error={contentQuery.error}
          pending={contentQuery.isPending}
        />
      )}
      <MeasurementRecords
        preview={measurements}
        error={error}
        pending={pending}
        hasMore={hasMoreMeasurements}
        loadingMore={loadingMoreMeasurements}
        onLoadMore={onLoadMoreMeasurements}
      />
    </article>
  );
}

function RunContentPanel({
  entry,
  content,
  format,
  error,
  pending,
}: {
  entry: ContentEntry;
  content?: unknown;
  format?: "text" | "json";
  error: Error | null;
  pending: boolean;
}) {
  if (!canPreviewRunContent(entry)) {
    if (entry.role === "dataset") {
      return (
        <InlineEmpty
          title={
            entry.kind === "measurement_dataset"
              ? "Measurement dataset"
              : "Dataset preview unavailable"
          }
          detail={
            entry.kind === "measurement_dataset"
              ? "Use the bounded measurement preview below while records are still arriving."
              : `The daemon does not expose ${entry.kind} through the typed dataset preview.`
          }
        />
      );
    }
    return (
      <InlineEmpty
        title="Binary artifact"
        detail={`${entry.filename ?? entry.id} is recorded, but has no text or JSON preview.`}
      />
    );
  }
  if (error) {
    return (
      <InlineEmpty
        title="Content unavailable"
        detail={errorMessage(error)}
        warning
      />
    );
  }
  if (pending || content === undefined) {
    return (
      <InlineEmpty
        title="Reading content"
        detail={`Loading ${entry.label} from the daemon.`}
      />
    );
  }
  return (
    <div className="content-preview">
      <div className="measurement-preview-heading">
        <strong>{entry.label}</strong>
        <span>{format === "text" ? "Text" : "JSON"}</span>
      </div>
      <pre>{formatPreviewContent(content)}</pre>
    </div>
  );
}

function MeasurementRecords({
  preview,
  error,
  pending,
  hasMore,
  loadingMore,
  onLoadMore,
}: {
  preview?: MeasurementPreview;
  error: Error | null;
  pending: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}) {
  if (error) {
    return (
      <InlineEmpty
        title="Measurement preview unavailable"
        detail={errorMessage(error)}
        warning
      />
    );
  }
  if (pending) {
    return (
      <InlineEmpty
        title="Reading measurements"
        detail="Waiting for the daemon's bounded record preview."
      />
    );
  }
  if (!preview || preview.items.length === 0) {
    return (
      <InlineEmpty
        title="No measurement records"
        detail="Measurements appear here as the executor commits them."
      />
    );
  }
  return (
    <div className="measurement-preview">
      <div className="measurement-preview-heading">
        <strong>Measurement preview</strong>
        <span>
          {preview.items.length}
          {preview.nextOffset !== undefined ? "+" : ""} records
        </span>
      </div>
      <pre>{JSON.stringify(preview.items, null, 2)}</pre>
      {hasMore && (
        <div className="measurement-pagination">
          <button
            className="secondary-button"
            type="button"
            disabled={loadingMore}
            onClick={onLoadMore}
          >
            {loadingMore && (
              <LoaderCircle className="spin" size={14} aria-hidden="true" />
            )}
            {loadingMore ? "Loading measurements…" : "Load more measurements"}
          </button>
        </div>
      )}
    </div>
  );
}

function CatalogCard({
  currentExperimentId,
  catalog,
  error,
}: {
  currentExperimentId: string;
  catalog?: ExperimentCatalog;
  error: Error | null;
}) {
  return (
    <article className="detail-card catalog-card">
      <CardHeading
        icon={<Layers3 size={17} />}
        title="Experiment catalog"
        accessory={
          <span className="count-badge">{catalog?.experiments.length ?? 0}</span>
        }
      />
      {error ? (
        <InlineEmpty
          title="Catalog unavailable"
          detail={errorMessage(error)}
          warning
        />
      ) : !catalog ? (
        <InlineEmpty
          title="Reading catalog"
          detail="Waiting for registration metadata."
        />
      ) : catalog.experiments.length === 0 ? (
        <InlineEmpty
          title="No registered experiments"
          detail="Scratch runs can still be executed from a connected notebook."
        />
      ) : (
        <ul className="catalog-list">
          {catalog.experiments.slice(0, 6).map((experiment) => (
            <li
              key={`${experiment.id}:${experiment.version}`}
              className={
                experiment.id === currentExperimentId ? "current" : undefined
              }
            >
              <span className="catalog-symbol" aria-hidden="true">
                <FlaskConical size={15} />
              </span>
              <span>
                <strong>{experiment.title}</strong>
                <small>
                  {experiment.id} · v{experiment.version}
                </small>
              </span>
              {experiment.id === currentExperimentId && (
                <CheckCircle2
                  size={16}
                  aria-label="Selected run experiment"
                />
              )}
            </li>
          ))}
        </ul>
      )}
      {catalog?.revision && (
        <p className="catalog-revision">
          Catalog revision <code>{shorten(catalog.revision, 18)}</code>
        </p>
      )}
    </article>
  );
}

function CardHeading({
  icon,
  title,
  accessory,
}: {
  icon: ReactNode;
  title: string;
  accessory?: ReactNode;
}) {
  return (
    <div className="card-heading">
      <span aria-hidden="true">{icon}</span>
      <h3>{title}</h3>
      {accessory && <div className="card-accessory">{accessory}</div>}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TagGroup({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="tag-group">
      <span>{label}</span>
      <div>
        {values.map((value) => (
          <code key={value}>{value}</code>
        ))}
      </div>
    </div>
  );
}

function PanelMessage({
  icon,
  title,
  detail,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="panel-message">
      <span aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

function DetailEmpty({
  icon,
  title,
  detail,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="detail-empty">
      <span aria-hidden="true">{icon}</span>
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

function InlineEmpty({
  title,
  detail,
  warning = false,
}: {
  title: string;
  detail: string;
  warning?: boolean;
}) {
  return (
    <div className={warning ? "inline-empty warning" : "inline-empty"}>
      {warning ? (
        <XCircle size={17} aria-hidden="true" />
      ) : (
        <CircleDot size={17} aria-hidden="true" />
      )}
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
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
  window.history.replaceState(
    null,
    "",
    `${location.pathname}${location.search}${location.hash}`,
  );
}

function mergeRunPages(pages: ProjectRunPage[]): ProjectRun[] {
  const runs = new Map<string, ProjectRun>();
  for (const page of pages) {
    for (const run of page.items) runs.set(run.runId, run);
  }
  return [...runs.values()].sort((left, right) => {
    if (left.sequence !== undefined && right.sequence !== undefined) {
      return right.sequence - left.sequence;
    }
    return (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "");
  });
}

function mergeMeasurementPages(
  pages: MeasurementPreview[],
): MeasurementPreview | undefined {
  if (pages.length === 0) return undefined;
  const items = pages.flatMap((page) => page.items);
  return { items, nextOffset: pages.at(-1)?.nextOffset };
}

function filterRuns(
  runs: ProjectRun[],
  filter: FilterKey,
  search: string,
): ProjectRun[] {
  const query = search.trim().toLocaleLowerCase();
  return runs.filter((run) => {
    const matchesFilter =
      filter === "all" ||
      (filter === "active" &&
        ["accepted", "running"].includes(run.status)) ||
      (filter === "attention" && run.status === "attention_required") ||
      (filter === "complete" &&
        ["succeeded", "failed", "cancelled", "terminal"].includes(run.status));
    if (!matchesFilter) return false;
    if (!query) return true;
    return [
      run.runId,
      run.experimentId,
      run.executionMode,
      ...run.resources.flatMap((resource) => [resource.id, resource.kind]),
    ]
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });
}

function completedPoints(
  run: ProjectRun,
  events: ProjectEvent[],
): number {
  let completed = run.progressCompleted ?? 0;
  for (const event of events) {
    const progress = event.payload.progress;
    if (typeof progress !== "object" || progress === null) continue;
    const value = (progress as Record<string, unknown>).completed_points;
    if (typeof value === "number" && Number.isFinite(value)) {
      completed = Math.max(completed, value);
    }
  }
  return completed;
}

function measurementEventRunId(event: Event): string | undefined {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
    return undefined;
  }
  try {
    const payload: unknown = JSON.parse(event.data);
    if (typeof payload !== "object" || payload === null) return undefined;
    const source = payload as Record<string, unknown>;
    if (
      source.kind !== "measurements_appended" &&
      source.kind !== "measurements_sealed"
    ) {
      return undefined;
    }
    return typeof source.run_id === "string" ? source.run_id : undefined;
  } catch {
    return undefined;
  }
}

function eventIcon(kind: string): ReactNode {
  if (kind.includes("admit") || kind.includes("accept")) {
    return <CheckCircle2 size={14} />;
  }
  if (kind.includes("resource") || kind.includes("lease")) {
    return <Cpu size={14} />;
  }
  if (kind.includes("state") || kind.includes("transition")) {
    return <Activity size={14} />;
  }
  if (kind.includes("catalog")) return <BookOpen size={14} />;
  return <CircleDot size={14} />;
}

function eventDescription(event: ProjectEvent): string {
  const primitiveEntries = Object.entries(event.payload)
    .filter(
      ([key, value]) =>
        !["kind", "schema_version", "run_id"].includes(key) &&
        (typeof value === "string" ||
          typeof value === "number" ||
          typeof value === "boolean"),
    )
    .slice(0, 3);
  if (primitiveEntries.length === 0) {
    return "Durable project event committed by the daemon.";
  }
  return primitiveEntries
    .map(([key, value]) => `${titleCase(key)}: ${String(value)}`)
    .join(" · ");
}

function humanizeEvent(kind: string): string {
  const specific: Record<string, string> = {
    run_admitted: "Run admitted",
    run_state_changed: "Run state changed",
    resource_claims_acquired: "Resources acquired",
    executor_lease_acquired: "Executor connected",
    executor_lease_renewed: "Executor heartbeat",
    executor_lease_expired: "Executor lost",
    transition_committed: "Execution transition",
    catalog_changed: "Catalog changed",
  };
  return specific[kind] ?? titleCase(kind);
}

function healthDetail(health?: ProjectHealth): string {
  if (!health) return "No health response";
  return `Project ${shorten(health.projectId, 18)}`;
}

function contentKey(entry: ContentEntry): string {
  return `${entry.role}:${entry.id}`;
}

function formatPreviewContent(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? String(value);
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
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

function formatRelative(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  const seconds = Math.round((date.valueOf() - Date.now()) / 1_000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

function shorten(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  const edge = Math.max(3, Math.floor((maxLength - 1) / 2));
  return `${value.slice(0, edge)}…${value.slice(-edge)}`;
}

function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed.";
}

function confirmAttentionAction(action: AttentionAction): boolean {
  const messages: Record<AttentionAction, string> = {
    release:
      "Release this run's quarantined resources? Reconcile external hardware state first.",
    requeue:
      "Release quarantined resources and allow this run to execute again?",
    abort:
      "Abort this run and release its quarantined resources? This cannot be resumed.",
  };
  return window.confirm(messages[action]);
}
