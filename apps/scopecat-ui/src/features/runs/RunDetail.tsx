import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Atom,
  Box,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Cpu,
  Database,
  Gauge,
  SquareStack,
  Unlock,
  XCircle,
} from "lucide-react";
import { canPreviewRunContent, getRunContent } from "../../api";
import { errorMessage, formatRelative, shorten, titleCase } from "../../lib/presentation";
import { classes, countBadge, detailCard } from "../../ui/styles";
import type {
  ContentEntry,
  MeasurementPreview,
  ProjectEvent,
  ProjectRun,
  RunAnalysis,
} from "../../types";
import { RunProposals } from "../proposals/RunProposals";
import { MeasurementDataPreview } from "./MeasurementDataPreview";

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
  onSelectRun,
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
  onSelectRun: (runId: string) => void;
  onResolveAttention: () => void;
}) {
  const previousRunId = run.stage?.previousRunId;
  return (
    <>
      <header
        className="flex items-start justify-between gap-7 border-b border-line px-0.5 pb-[17px] max-[680px]:block"
        data-testid="run-detail-header"
      >
        <div className="min-w-0">
          <div className="mb-2.5 flex flex-wrap items-center gap-2.5 text-[0.68rem] font-bold text-text-dim">
            <span
              className={classes(
                "inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[0.62rem] font-extrabold tracking-[0.04em] uppercase",
                runStatusBadge[run.status],
              )}
              data-testid="run-status"
            >
              <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
              {run.stateLabel}
            </span>
            {run.stage && (
              <span
                className="inline-flex min-w-0 items-center gap-1.5 rounded-full border border-[rgb(128_163_207_/_18%)] bg-accent-soft px-2 py-1 text-[0.62rem] font-bold text-accent"
                data-testid="run-stage-lineage"
                title={`Sequence ${run.stage.sequenceId}, stage ${run.stage.index + 1}`}
              >
                <span>Sequence</span>
                <code className="max-w-40 overflow-hidden text-ellipsis whitespace-nowrap">
                  {shorten(run.stage.sequenceId, 18)}
                </code>
                <span aria-hidden="true">·</span>
                <span>Stage {run.stage.index + 1}</span>
              </span>
            )}
            {previousRunId && (
              <button
                className="inline-flex min-h-7 cursor-pointer items-center gap-1 rounded-[7px] border border-line bg-transparent px-2 text-[0.62rem] font-bold text-text-soft hover:border-line-strong hover:bg-panel-strong hover:text-text"
                type="button"
                title={`Open previous stage ${previousRunId}`}
                onClick={() => onSelectRun(previousRunId)}
              >
                <ArrowLeft size={13} aria-hidden="true" />
                Previous stage
              </button>
            )}
          </div>
          <h2 className="mb-[7px] text-[clamp(1.2rem,1.8vw,1.55rem)] font-[650] tracking-[-0.035em] [overflow-wrap:anywhere]">
            {run.experimentId}
          </h2>
          <code
            className="block max-w-[min(60vw,620px)] overflow-hidden text-[0.68rem] text-ellipsis whitespace-nowrap text-text-dim max-[680px]:max-w-full"
            title={run.runId}
          >
            {run.runId}
          </code>
        </div>
        <dl className="mt-1 flex flex-none gap-7 max-[1100px]:gap-[18px] max-[680px]:mt-5 max-[680px]:grid max-[680px]:grid-cols-2 max-[460px]:grid-cols-1">
          <div className="grid gap-1.5">
            <dt className="text-[0.6rem] font-extrabold tracking-[0.09em] text-text-dim uppercase">
              Accepted
            </dt>
            <dd className="m-0 text-[0.69rem] text-text-soft">
              {run.createdAt ? (
                <time dateTime={run.createdAt}>{formatDateTime(run.createdAt)}</time>
              ) : (
                "Not reported"
              )}
            </dd>
          </div>
          <div className="grid gap-1.5">
            <dt className="text-[0.6rem] font-extrabold tracking-[0.09em] text-text-dim uppercase">
              Config
            </dt>
            <dd className="m-0 text-[0.69rem] text-text-soft">
              <code title={run.configHash}>
                {run.configHash ? shorten(run.configHash, 15) : "Not reported"}
              </code>
            </dd>
          </div>
        </dl>
      </header>

      {run.status === "attention_required" && (
        <div
          className="mt-[18px] flex items-start gap-[11px] rounded-md border border-[rgb(237_201_111_/_23%)] bg-yellow-soft px-3.5 py-[13px]"
          role="alert"
        >
          <AlertTriangle className="flex-none text-yellow" size={19} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <strong className="text-[0.77rem] text-[#fae4ad]">Operator attention required</strong>
            <p className="mt-1 mb-0 text-[0.71rem] leading-normal text-[#c4b994]">
              {run.attentionReason ?? "The daemon has not reported a reconciliation reason."}
            </p>
            <p className="mt-1 mb-0 text-[0.71rem] leading-normal text-[#c4b994]">
              This run cannot be resumed safely. Reconcile its external state, then submit a new
              run.
            </p>
            <div className="mt-[11px] flex flex-wrap gap-[7px]">
              <button
                className="inline-flex min-h-[31px] cursor-pointer items-center gap-1.5 rounded-[7px] border border-[rgb(255_140_136_/_35%)] bg-red-soft px-2.5 text-red hover:not-disabled:bg-panel-strong hover:not-disabled:text-text disabled:cursor-wait disabled:opacity-55"
                type="button"
                onClick={onResolveAttention}
                disabled={attentionPending}
              >
                <Unlock size={15} aria-hidden="true" />
                {attentionPending ? "Resolving…" : "Resolve and close"}
              </button>
            </div>
            {attentionError && (
              <p className="mt-1 mb-0 text-[0.71rem] leading-normal text-red" role="status">
                {errorMessage(attentionError)}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="mt-[18px] grid grid-cols-[minmax(0,1.55fr)_minmax(250px,0.85fr)] gap-3 max-[1100px]:grid-cols-[minmax(0,1.25fr)_minmax(230px,0.9fr)] max-[680px]:grid-cols-[minmax(0,1fr)]">
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
    <article className={classes(detailCard, "col-span-full max-[680px]:col-auto")}>
      <CardHeading
        icon={<Gauge size={17} />}
        title="Execution progress"
        accessory={
          percentage !== undefined ? (
            <strong className="font-mono text-[0.78rem] text-accent">{percentage}%</strong>
          ) : (
            <span className={countBadge}>{run.stateLabel}</span>
          )
        }
      />
      {hasProgress ? (
        <>
          <progress
            className="h-2 w-full appearance-none overflow-hidden rounded-full border-0 bg-panel-strong [&::-moz-progress-bar]:rounded-full [&::-moz-progress-bar]:bg-accent [&::-webkit-progress-bar]:rounded-full [&::-webkit-progress-bar]:bg-panel-strong [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:bg-accent"
            max={expected}
            value={progressValue}
            aria-label={`${progressValue ?? 0} of ${expected} points complete`}
          />
          <div className="mt-[7px] flex justify-between text-[0.65rem] text-text-dim max-[460px]:flex-wrap max-[460px]:gap-2 [&_strong]:text-text-soft">
            <span>
              <strong>{progressValue ?? 0}</strong> / {expected} points
            </span>
            <span>{events.length} durable events</span>
          </div>
        </>
      ) : (
        <div className="flex min-h-[54px] items-center gap-3 rounded-[9px] border border-dashed border-line bg-[rgb(255_255_255_/_1%)] p-3 text-text-dim">
          <Activity className="flex-none text-blue" size={23} aria-hidden="true" />
          <div>
            <strong className="text-[0.75rem] text-text-soft">
              {run.status === "running" ? "Execution is active" : "No point total reported"}
            </strong>
            <p className="mt-1 mb-0 text-[0.67rem] leading-[1.45]">
              {events.length > 0
                ? `${events.length} durable events received from this run.`
                : "Progress will appear when the daemon publishes plan or execution events."}
            </p>
          </div>
        </div>
      )}
      <div className="mt-[13px] grid grid-cols-3 gap-2 max-[460px]:grid-cols-1">
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
    <article className={detailCard} data-testid="resource-card">
      <CardHeading
        icon={<Atom size={17} />}
        title="Analyses"
        accessory={<span className={countBadge}>{analyses?.length ?? 0}</span>}
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
        <div className="grid gap-2">
          {analyses.map((analysis) => (
            <details
              className="overflow-hidden rounded-[8px] border border-line bg-[rgb(255_255_255_/_1.2%)]"
              key={analysis.id}
            >
              <summary className="flex cursor-pointer items-center justify-between gap-2.5 p-2.5">
                <span className="grid min-w-0 gap-[3px]">
                  <strong className="overflow-hidden text-[0.7rem] text-ellipsis whitespace-nowrap">
                    {analysis.title}
                  </strong>
                  <small className="text-[0.6rem] text-text-dim">
                    {analysis.key ?? analysis.id}
                    {analysis.stepId ? ` · ${analysis.stepId}` : ""}
                  </small>
                </span>
                <span className={countBadge}>{analysis.outputs.length}</span>
              </summary>
              <div className="grid gap-2 px-2.5 pb-2.5">
                {analysis.outputs.map((output, index) => (
                  <section
                    className="overflow-hidden rounded-[7px] border border-line bg-panel"
                    key={`${output.kind}:${output.title}:${index}`}
                  >
                    <header className="flex items-center justify-between gap-2.5 border-b border-line px-[9px] py-[7px]">
                      <strong className="text-[0.65rem]">{output.title}</strong>
                      <span className="text-[0.56rem] font-[750] text-text-dim uppercase">
                        {titleCase(output.kind)}
                      </span>
                    </header>
                    <pre className="m-0 max-h-60 overflow-auto p-[9px] text-[0.6rem] leading-normal text-[#aebfd0]">
                      {formatPreviewContent(output.content)}
                    </pre>
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
    <article className={detailCard}>
      <CardHeading
        icon={<Cpu size={17} />}
        title="Resources"
        accessory={<span className={countBadge}>{run.resources.length}</span>}
      />
      {run.resources.length > 0 ? (
        <ul className="m-0 grid list-none gap-[7px] p-0">
          {run.resources.map((resource) => (
            <li
              className="flex min-w-0 items-center gap-[9px] rounded-[8px] border border-line bg-[rgb(255_255_255_/_1.2%)] p-[9px]"
              data-testid={`resource-${resource.id}`}
              key={`${resource.kind}:${resource.id}`}
            >
              <span
                className="grid size-7 flex-none place-items-center rounded-[7px] bg-blue-soft text-blue"
                aria-hidden="true"
              >
                <Box size={15} />
              </span>
              <span className="grid min-w-0 flex-1 gap-0.5">
                <strong className="overflow-hidden text-[0.7rem] font-[650] text-ellipsis whitespace-nowrap">
                  {resource.id}
                </strong>
                <small className="overflow-hidden text-[0.6rem] text-ellipsis whitespace-nowrap text-text-dim">
                  {titleCase(resource.kind)}
                </small>
              </span>
              <span
                className={classes(
                  "flex-none rounded-[5px] border px-[5px] py-[3px] text-[0.56rem] font-extrabold uppercase",
                  leaseStatusClass(resource.status),
                )}
              >
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
    <article
      className={classes(detailCard, "row-span-2 max-[680px]:row-auto")}
      data-testid="timeline-card"
    >
      <CardHeading
        icon={<Activity size={17} />}
        title="Recent events"
        accessory={<span className={countBadge}>{events.length}</span>}
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
            <p className="mt-0 mb-3 text-[0.64rem] leading-[1.45] text-text-dim">
              Showing the latest 500 events; older events are not loaded.
            </p>
          )}
          <ol className="m-0 grid max-h-[540px] list-none overflow-auto p-0 pr-[3px] [scrollbar-color:#344252_transparent] [scrollbar-width:thin] max-[680px]:max-h-[430px]">
            {events.map((event) => (
              <li
                className="relative grid grid-cols-[29px_minmax(0,1fr)] gap-2.5 pb-[17px] not-last:before:absolute not-last:before:top-[27px] not-last:before:bottom-[-1px] not-last:before:left-[13px] not-last:before:w-px not-last:before:bg-line not-last:before:content-['']"
                key={event.id}
              >
                <span
                  className="z-[1] grid size-[27px] place-items-center rounded-[8px] border border-line bg-panel text-accent"
                  aria-hidden="true"
                >
                  {eventIcon(event.kind)}
                </span>
                <div>
                  <div className="flex items-baseline justify-between gap-2.5 pt-0.5">
                    <strong className="text-[0.71rem] font-[650]">
                      {humanizeEvent(event.kind)}
                    </strong>
                    <span className="font-mono text-[0.57rem] text-text-dim">#{event.id}</span>
                  </div>
                  <p className="my-1 text-[0.64rem] leading-[1.45] text-text-dim">
                    {eventDescription(event)}
                  </p>
                  <time className="text-[0.58rem] text-[#5f6d7a]" dateTime={event.occurredAt}>
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
    <article
      className={classes(detailCard, "[&>.run-inline-empty]:mt-2.5")}
      data-testid="data-card"
    >
      <CardHeading
        icon={<Database size={17} />}
        title="Data contents"
        accessory={<span className={countBadge}>{run.contents.length}</span>}
      />
      {hasPlanMetadata && (
        <div className="mb-[13px] grid grid-cols-3 gap-2 rounded-[8px] border border-line bg-[rgb(255_255_255_/_1%)] p-2.5 max-[460px]:grid-cols-1">
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
        <ul className="mt-2.5 grid list-none gap-[7px] p-0">
          {run.contents.map((content) => (
            <li
              key={contentKey(content)}
              className={classes(
                "flex min-w-0 items-center gap-[9px] rounded-[8px] border border-line bg-[rgb(255_255_255_/_1.2%)]",
                contentKey(content) === selectedContentKey &&
                  "border-[rgb(128_163_207_/_25%)] bg-accent-soft",
              )}
            >
              <button
                className="flex w-full cursor-pointer items-center gap-[9px] border-0 bg-transparent p-[9px] text-left text-inherit [&>svg]:flex-none [&>svg]:text-text-dim"
                type="button"
                onClick={() => setSelectedContentKey(contentKey(content))}
                aria-current={contentKey(content) === selectedContentKey ? "true" : undefined}
              >
                <span
                  className="grid size-7 flex-none place-items-center rounded-[7px] bg-blue-soft text-blue"
                  aria-hidden="true"
                >
                  {content.role === "dataset" ? <Database size={15} /> : <SquareStack size={15} />}
                </span>
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <strong className="overflow-hidden text-[0.7rem] font-[650] text-ellipsis whitespace-nowrap">
                    {content.label}
                  </strong>
                  <small className="overflow-hidden text-[0.6rem] text-ellipsis whitespace-nowrap text-text-dim">
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
    <div className={previewPanel}>
      <div className={previewHeading}>
        <strong className="text-[0.65rem] text-text-soft">{entry.label}</strong>
        <span>{format === "text" ? "Text" : "JSON"}</span>
      </div>
      <pre className={previewContent}>{formatPreviewContent(content)}</pre>
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
    <MeasurementDataPreview
      preview={preview}
      hasMore={hasMore}
      loadingMore={loadingMore}
      onLoadMore={onLoadMore}
    />
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
    <div className="mb-[15px] grid min-h-[26px] grid-cols-[26px_minmax(0,1fr)_auto] items-center gap-[7px]">
      <span
        className="grid size-[26px] place-items-center rounded-[7px] border border-line bg-panel text-accent"
        aria-hidden="true"
      >
        {icon}
      </span>
      <h3 className="m-0 text-[0.78rem] font-bold">{title}</h3>
      {accessory && <div className="text-[0.68rem] text-text-dim">{accessory}</div>}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 gap-1">
      <span className="text-[0.6rem] font-bold tracking-[0.05em] text-text-dim uppercase">
        {label}
      </span>
      <strong className="overflow-hidden text-[0.72rem] font-[650] text-ellipsis whitespace-nowrap text-text-soft">
        {value}
      </strong>
    </div>
  );
}

function TagGroup({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="mb-3">
      <span className="mb-1.5 block text-[0.58rem] font-extrabold tracking-[0.06em] text-text-dim uppercase">
        {label}
      </span>
      <div className="flex flex-wrap gap-[5px]">
        {values.map((value) => (
          <code
            className="rounded-[5px] border border-line bg-[rgb(182_156_255_/_7%)] px-1.5 py-1 text-[0.59rem] text-purple"
            key={value}
          >
            {value}
          </code>
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
    <div
      className={classes(
        "run-inline-empty flex items-start gap-[9px] rounded-[8px] border border-dashed border-line p-3 text-text-dim [&>svg]:mt-px [&>svg]:flex-none",
        warning && "border-[rgb(255_140_136_/_20%)] bg-red-soft [&>svg]:text-red",
      )}
    >
      {warning ? (
        <XCircle size={17} aria-hidden="true" />
      ) : (
        <CircleDot size={17} aria-hidden="true" />
      )}
      <div>
        <strong className="block text-[0.69rem] text-text-soft">{title}</strong>
        <p className="mt-1 mb-0 text-[0.62rem] leading-[1.45]">{detail}</p>
      </div>
    </div>
  );
}

const runStatusBadge: Record<ProjectRun["status"], string> = {
  accepted: "border-[rgb(120_184_255_/_20%)] bg-blue-soft text-blue",
  running: "border-[rgb(128_163_207_/_20%)] bg-accent-soft text-accent",
  attention_required: "border-[rgb(237_201_111_/_20%)] bg-yellow-soft text-yellow",
  succeeded: "border-[rgb(128_163_207_/_20%)] bg-accent-soft text-accent",
  failed: "border-[rgb(255_140_136_/_20%)] bg-red-soft text-red",
  cancelled: "border-[rgb(255_140_136_/_20%)] bg-red-soft text-red",
};

const previewPanel = "mt-3 overflow-hidden rounded-[8px] border border-line bg-panel";
const previewHeading =
  "flex items-center justify-between border-b border-line px-2.5 py-2 text-[0.6rem] text-text-dim";
const previewContent =
  "m-0 max-h-[260px] overflow-auto p-2.5 text-[0.6rem] leading-normal text-[#aebfd0] [scrollbar-color:#344252_transparent] [scrollbar-width:thin]";

function leaseStatusClass(status?: string): string {
  if (status === "quarantined") {
    return "border-[rgb(237_201_111_/_20%)] bg-yellow-soft text-yellow";
  }
  if (status === "required") {
    return "border-[rgb(120_184_255_/_20%)] bg-blue-soft text-blue";
  }
  if (status === "released") {
    return "border-line bg-panel text-text-dim";
  }
  return "border-[rgb(128_163_207_/_18%)] bg-accent-soft text-accent";
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
