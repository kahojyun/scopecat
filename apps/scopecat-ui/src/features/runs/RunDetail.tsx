import { AlertTriangle, Unlock } from "lucide-react";
import type { MeasurementTracePreview, RunInspectionFeed } from "../../api-contract";
import { errorMessage, formatDateTime, shorten } from "../../lib/presentation";
import { classes } from "../../ui/styles";
import type {
  MeasurementPreview,
  MeasurementSlicePreview,
  ProjectEvent,
  ProjectRun,
  RunAnalysis,
} from "../../types";
import { RunProposals } from "../proposals/RunProposals";
import { RunInspectionCard } from "./RunInspectionCard";
import type { MeasurementTraceQueryPlan } from "./measurement-visualization";
import {
  AnalysisCard,
  DataCard,
  ProgressCard,
  ResourceCard,
  TimelineCard,
} from "./RunDetailSections";

export function RunDetail({
  run,
  events,
  eventsError,
  eventsPending,
  inspections,
  inspectionsError,
  inspectionsPending,
  measurements,
  measurementsError,
  measurementsPending,
  measurementSlice,
  measurementSliceError,
  measurementSlicePending,
  tracePlans,
  selectedTracePlanId,
  tracePreview,
  traceError,
  tracePending,
  onTracePlanChange,
  measurementFixedAxisIndices,
  onMeasurementFixedAxisIndexChange,
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
  inspections?: RunInspectionFeed;
  inspectionsError: Error | null;
  inspectionsPending: boolean;
  measurements?: MeasurementPreview;
  measurementsError: Error | null;
  measurementsPending: boolean;
  measurementSlice?: MeasurementSlicePreview;
  measurementSliceError: Error | null;
  measurementSlicePending: boolean;
  tracePlans: MeasurementTraceQueryPlan[];
  selectedTracePlanId?: string;
  tracePreview?: MeasurementTracePreview;
  traceError: Error | null;
  tracePending: boolean;
  onTracePlanChange: (planId: string) => void;
  measurementFixedAxisIndices: Record<string, number>;
  onMeasurementFixedAxisIndexChange: (axisId: string, index: number) => void;
  analyses?: RunAnalysis[];
  analysesError: Error | null;
  analysesPending: boolean;
  attentionError: Error | null;
  attentionPending: boolean;
  onResolveAttention: () => void;
}) {
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
          </div>
          <h2 className="mb-[7px] text-[clamp(1.2rem,1.8vw,1.55rem)] font-[650] tracking-[-0.035em] [overflow-wrap:anywhere]">
            {run.displayName ?? run.experimentId}
          </h2>
          <div className="flex max-w-[min(60vw,620px)] items-center gap-2 overflow-hidden text-[0.68rem] text-text-dim max-[680px]:max-w-full">
            {run.displayName && (
              <code
                className="overflow-hidden text-ellipsis whitespace-nowrap"
                title={run.experimentId}
              >
                {run.experimentId}
              </code>
            )}
            {run.displayName && <span aria-hidden="true">·</span>}
            <code className="overflow-hidden text-ellipsis whitespace-nowrap" title={run.runId}>
              {run.runId}
            </code>
          </div>
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
        <ProgressCard run={run} events={events} measurements={measurements} />
        <RunInspectionCard
          feed={inspections}
          error={inspectionsError}
          pending={inspectionsPending}
          completedPointCount={Math.max(run.progressCompleted ?? 0, measurements?.recordCount ?? 0)}
          run={run}
          measurements={measurements}
        />
        <RunProposals key={run.runId} runId={run.runId} />
        <AnalysisCard
          analyses={analyses}
          error={analysesError}
          pending={analysesPending}
          runId={run.runId}
        />
        <ResourceCard run={run} />
        <TimelineCard events={events} error={eventsError} pending={eventsPending} />
        <DataCard
          run={run}
          measurements={measurements}
          error={measurementsError}
          pending={measurementsPending}
          measurementSlice={measurementSlice}
          measurementSliceError={measurementSliceError}
          measurementSlicePending={measurementSlicePending}
          tracePlans={tracePlans}
          selectedTracePlanId={selectedTracePlanId}
          tracePreview={tracePreview}
          traceError={traceError}
          tracePending={tracePending}
          onTracePlanChange={onTracePlanChange}
          measurementFixedAxisIndices={measurementFixedAxisIndices}
          onMeasurementFixedAxisIndexChange={onMeasurementFixedAxisIndexChange}
        />
      </div>
    </>
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
