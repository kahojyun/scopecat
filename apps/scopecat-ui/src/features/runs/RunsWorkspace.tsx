import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  CircleDot,
  FlaskConical,
  ListFilter,
  LoaderCircle,
  Search,
  Unplug,
} from "lucide-react";
import {
  getMeasurementPreview,
  getOlderRuns,
  getRun,
  getRunAnalyses,
  getRunEvents,
  getRuns,
  resolveAttention,
} from "../../api";
import { errorMessage, formatRelative, shorten, titleCase } from "../../lib/presentation";
import type { MeasurementPreview, ProjectHealth, ProjectRun, ProjectRunPage } from "../../types";
import { useConfirmationDialog, type ConfirmationRequest } from "../../ui/ConfirmationDialog";
import { RunDetail } from "./RunDetail";

type FilterKey = "all" | "active" | "attention" | "complete";
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

export function RunsWorkspace({
  selectedRunId,
  onSelectRun,
  health,
  healthPending,
  healthReachable,
  daemonUnavailable,
}: {
  selectedRunId?: string;
  onSelectRun: (runId: string) => void;
  health?: ProjectHealth;
  healthPending: boolean;
  healthReachable: boolean;
  daemonUnavailable: boolean;
}) {
  const queryClient = useQueryClient();
  const { requestConfirmation, confirmationDialog } = useConfirmationDialog();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [olderRunHistory, setOlderRunHistory] = useState<OlderRunHistory>();
  const latestRunHeadCursor = useRef<number | undefined>(undefined);
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
    queryFn: ({ signal, pageParam }) => getMeasurementPreview(selectedRunId!, pageParam, signal),
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
    mutationFn: (runId: string) => resolveAttention(runId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["runs"] }),
        queryClient.invalidateQueries({ queryKey: ["events"] }),
        queryClient.invalidateQueries({ queryKey: ["run"] }),
      ]);
    },
  });

  const olderRunPages = useMemo(
    () =>
      olderRunHistory && olderRunHistory.headCursor === runHeadCursor ? olderRunHistory.pages : [],
    [olderRunHistory, runHeadCursor],
  );
  const runs = useMemo(() => {
    const indexedRuns = mergeRunPages([
      ...olderRunPages,
      ...(runsQuery.data ? [runsQuery.data] : []),
    ]);
    return runDetailQuery.data
      ? indexedRuns.map((run) =>
          run.runId === runDetailQuery.data.runId ? runDetailQuery.data : run,
        )
      : indexedRuns;
  }, [olderRunPages, runDetailQuery.data, runsQuery.data]);
  const previousRunCursor =
    olderRunPages.length > 0 ? olderRunPages.at(-1)?.previousCursor : runHeadCursor;
  const measurements = useMemo(
    () => mergeMeasurementPages(measurementsQuery.data?.pages ?? []),
    [measurementsQuery.data?.pages],
  );
  const filteredRuns = useMemo(() => filterRuns(runs, filter, search), [runs, filter, search]);

  useEffect(() => {
    setOlderRunHistory((current) =>
      current && current.headCursor !== runHeadCursor ? undefined : current,
    );
  }, [runHeadCursor]);

  useEffect(() => {
    if (runs.length > 0 && selectedRunId === undefined) {
      const firstRunId = runs[0]?.runId;
      if (firstRunId !== undefined) onSelectRun(firstRunId);
    }
  }, [runs, selectedRunId, onSelectRun]);

  const selectedRun = runDetailQuery.data ?? runs.find((run) => run.runId === selectedRunId);
  const selectedEvents = selectedEventsQuery.data ?? [];
  const activeCount = runs.filter((run) => ["accepted", "running"].includes(run.status)).length;
  const attentionCount = runs.filter((run) => run.status === "attention_required").length;

  return (
    <>
      <section className="status-strip" aria-label="Project status">
        <StatusItem
          label="Daemon"
          value={
            healthReachable
              ? titleCase(health?.status ?? "connected")
              : healthPending
                ? "Checking"
                : "Unavailable"
          }
          detail={healthDetail(health)}
          tone={healthReachable ? "good" : "muted"}
        />
        <StatusItem
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
        <StatusItem
          label="Attention"
          value={runsQuery.isSuccess ? String(attentionCount) : "—"}
          detail={
            attentionCount > 0
              ? "Operator review needed"
              : previousRunCursor !== undefined
                ? "No flags in loaded runs"
                : "No flagged runs"
          }
          tone={attentionCount > 0 ? "warning" : previousRunCursor !== undefined ? "muted" : "good"}
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
              <LoaderCircle className="spin subtle-icon" size={17} aria-label="Refreshing runs" />
            )}
          </div>

          <label className="search-field">
            <Search size={16} aria-hidden="true" />
            <span className="visually-hidden">Search by run, experiment, mode, or resource</span>
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
            {runsQuery.isSuccess && runs.length > 0 && filteredRuns.length === 0 && (
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
                onSelect={() => onSelectRun(run.runId)}
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
                      <LoaderCircle className="spin" size={14} aria-hidden="true" />
                    ) : (
                      <ChevronRight size={14} aria-hidden="true" />
                    )}
                    {olderRunsMutation.isPending ? "Loading older runs…" : "Load older runs"}
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
              attentionError={attentionMutation.error}
              attentionPending={attentionMutation.isPending}
              onResolveAttention={() => {
                const confirmation = attentionConfirmation();
                requestConfirmation({
                  ...confirmation,
                  onConfirm: () => attentionMutation.mutate(selectedRun.runId),
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
      {confirmationDialog}
    </>
  );
}

function StatusItem({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "good" | "active" | "warning" | "muted";
}) {
  return (
    <article className={`status-item ${tone}`}>
      <span className="status-label">{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
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
        </span>
        <span className={`run-state status-${run.status}`}>{run.stateLabel}</span>
      </span>
      <ChevronRight size={16} className="run-chevron" aria-hidden="true" />
    </button>
  );
}

function PanelMessage({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="panel-message">
      <span aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
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

function mergeMeasurementPages(pages: MeasurementPreview[]): MeasurementPreview | undefined {
  if (pages.length === 0) return undefined;
  const items = pages.flatMap((page) => page.items);
  return { items, nextOffset: pages.at(-1)?.nextOffset };
}

function filterRuns(runs: ProjectRun[], filter: FilterKey, search: string): ProjectRun[] {
  const query = search.trim().toLocaleLowerCase();
  return runs.filter((run) => {
    const matchesFilter =
      filter === "all" ||
      (filter === "active" && ["accepted", "running"].includes(run.status)) ||
      (filter === "attention" && run.status === "attention_required") ||
      (filter === "complete" && ["succeeded", "failed", "cancelled"].includes(run.status));
    if (!matchesFilter) return false;
    if (!query) return true;
    return [
      run.runId,
      run.experimentId,
      ...run.resources.flatMap((resource) => [resource.id, resource.kind]),
    ]
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });
}

function healthDetail(health?: ProjectHealth): string {
  if (!health) return "No health response";
  return `Project ${shorten(health.projectId, 18)}`;
}

function attentionConfirmation(): Omit<ConfirmationRequest, "onConfirm"> {
  return {
    title: "Resolve and close this run?",
    description:
      "Confirm the external hardware state is reconciled, release its resources, and close the run.",
    confirmLabel: "Resolve and close",
    intent: "danger",
  };
}
