import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Atom,
  Box,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Cpu,
  Database,
  Gauge,
  LoaderCircle,
  SquareStack,
  Unlock,
  XCircle,
} from "lucide-react";
import { canPreviewRunContent, getRunContent } from "../../api";
import { errorMessage, formatRelative, shorten, titleCase } from "../../lib/presentation";
import type {
  ContentEntry,
  MeasurementPreview,
  ProjectEvent,
  ProjectRun,
  RunAnalysis,
} from "../../types";
import { RunProposals } from "../proposals/RunProposals";

export function RunDetail({
  run,
  events,
  eventsError,
  eventsPending,
  measurements,
  measurementsError,
  measurementsPending,
  measurementsHasMore,
  measurementsLoadingMore,
  onLoadMoreMeasurements,
  analyses,
  analysesError,
  analysesPending,
  attentionError,
  attentionPending,
  onResolveAttention,
}: {
  run: ProjectRun;
  events: ProjectEvent[];
  eventsError: Error | null;
  eventsPending: boolean;
  measurements?: MeasurementPreview;
  measurementsError: Error | null;
  measurementsPending: boolean;
  measurementsHasMore: boolean;
  measurementsLoadingMore: boolean;
  onLoadMoreMeasurements: () => void;
  analyses?: RunAnalysis[];
  analysesError: Error | null;
  analysesPending: boolean;
  attentionError: Error | null;
  attentionPending: boolean;
  onResolveAttention: () => void;
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
          </div>
          <h2>{run.experimentId}</h2>
          <code title={run.runId}>{run.runId}</code>
        </div>
        <dl className="detail-meta">
          <div>
            <dt>Accepted</dt>
            <dd>
              {run.createdAt ? (
                <time dateTime={run.createdAt}>{formatDateTime(run.createdAt)}</time>
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
            <p>{run.attentionReason ?? "The daemon has not reported a reconciliation reason."}</p>
            <p>
              This run cannot be resumed safely. Reconcile its external state, then submit a new
              run.
            </p>
            <div className="attention-actions">
              <button
                className="danger"
                type="button"
                onClick={onResolveAttention}
                disabled={attentionPending}
              >
                <Unlock size={15} aria-hidden="true" />
                {attentionPending ? "Resolving…" : "Resolve and close"}
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
        <AnalysisCard analyses={analyses} error={analysesError} pending={analysesPending} />
        <ResourceCard run={run} />
        <TimelineCard events={events} error={eventsError} pending={eventsPending} />
        <DataCard
          run={run}
          measurements={measurements}
          error={measurementsError}
          pending={measurementsPending}
          hasMoreMeasurements={measurementsHasMore}
          loadingMoreMeasurements={measurementsLoadingMore}
          onLoadMoreMeasurements={onLoadMoreMeasurements}
        />
      </div>
    </>
  );
}

function ProgressCard({ run, events }: { run: ProjectRun; events: ProjectEvent[] }) {
  const expected = run.plan.pointCount;
  const completed = completedPoints(run, events);
  const terminal = ["succeeded", "failed", "cancelled"].includes(run.status);
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
              {run.status === "running" ? "Execution is active" : "No point total reported"}
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
          value={run.updatedAt ? formatRelative(run.updatedAt) : "Not reported"}
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
        <InlineEmpty title="Analyses unavailable" detail={errorMessage(error)} warning />
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
        accessory={<span className="count-badge">{run.resources.length}</span>}
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
        <InlineEmpty title="Events unavailable" detail={errorMessage(error)} warning />
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
                    {event.occurredAt ? formatDateTime(event.occurredAt) : "Timestamp not reported"}
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
  const selectedContent = run.contents.find((entry) => contentKey(entry) === selectedContentKey);
  const contentQuery = useQuery({
    queryKey: [
      "run-content",
      run.runId,
      selectedContent?.role,
      selectedContent?.id,
      selectedContent?.kind,
    ],
    queryFn: ({ signal }) => getRunContent(run.runId, selectedContent!, signal),
    enabled: selectedContent !== undefined && canPreviewRunContent(selectedContent),
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
            value={run.plan.pointCount !== undefined ? run.plan.pointCount.toLocaleString() : "—"}
          />
          <Fact label="Coordinates" value={String(run.plan.coordinateIds.length)} />
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
              className={contentKey(content) === selectedContentKey ? "selected" : undefined}
            >
              <button
                type="button"
                onClick={() => setSelectedContentKey(contentKey(content))}
                aria-current={contentKey(content) === selectedContentKey ? "true" : undefined}
              >
                <span className="content-role" aria-hidden="true">
                  {content.role === "dataset" ? <Database size={15} /> : <SquareStack size={15} />}
                </span>
                <span>
                  <strong>{content.label}</strong>
                  <small>
                    {titleCase(content.role)}
                    {content.detail ? ` · ${content.detail}` : ""}
                  </small>
                </span>
                {canPreviewRunContent(content) && <ChevronRight size={15} aria-hidden="true" />}
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
    return <InlineEmpty title="Content unavailable" detail={errorMessage(error)} warning />;
  }
  if (pending || content === undefined) {
    return (
      <InlineEmpty title="Reading content" detail={`Loading ${entry.label} from the daemon.`} />
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
      <InlineEmpty title="Measurement preview unavailable" detail={errorMessage(error)} warning />
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
            {loadingMore && <LoaderCircle className="spin" size={14} aria-hidden="true" />}
            {loadingMore ? "Loading measurements…" : "Load more measurements"}
          </button>
        </div>
      )}
    </div>
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

function completedPoints(run: ProjectRun, events: ProjectEvent[]): number {
  const completedPointIndices = new Set<number>();
  for (const event of events) {
    if (event.kind !== "execution_transition_committed" || event.payload.state !== "completed") {
      continue;
    }
    const evidence = event.payload.evidence;
    if (event.payload.stage === "point" && typeof evidence === "object" && evidence !== null) {
      const pointIndices = (evidence as Record<string, unknown>).point_indices;
      if (Array.isArray(pointIndices)) {
        for (const pointIndex of pointIndices) {
          if (typeof pointIndex === "number") completedPointIndices.add(pointIndex);
        }
      }
      const pointIndex = event.payload.point_index;
      if (typeof pointIndex === "number") completedPointIndices.add(pointIndex);
    }
    if (
      event.payload.stage === "append_measurement" &&
      typeof evidence === "object" &&
      evidence !== null
    ) {
      const record = evidence as Record<string, unknown>;
      const startIndex = record.start_index;
      const recordCount = record.record_count;
      if (typeof startIndex === "number" && typeof recordCount === "number") {
        for (let offset = 0; offset < recordCount; offset += 1) {
          completedPointIndices.add(startIndex + offset);
        }
      }
    }
  }
  // Only durable transition facts survive daemon reconnects.
  return Math.max(run.progressCompleted ?? 0, completedPointIndices.size);
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
  return <CircleDot size={14} />;
}

function eventDescription(event: ProjectEvent): string {
  const primitiveEntries = Object.entries(event.payload)
    .filter(
      ([key, value]) =>
        !["kind", "run_id"].includes(key) &&
        (typeof value === "string" || typeof value === "number" || typeof value === "boolean"),
    )
    .slice(0, 3);
  if (primitiveEntries.length === 0) {
    return "Durable project event committed by the daemon.";
  }
  return primitiveEntries.map(([key, value]) => `${titleCase(key)}: ${String(value)}`).join(" · ");
}

function humanizeEvent(kind: string): string {
  const specific: Record<string, string> = {
    run_admitted: "Run admitted",
    run_state_changed: "Run state changed",
    resource_claims_acquired: "Resources acquired",
    executor_lease_acquired: "Executor connected",
    executor_lease_expired: "Executor lost",
    transition_committed: "Execution transition",
  };
  return specific[kind] ?? titleCase(kind);
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
