import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleOff, LoaderCircle, Radio, Send, Waves } from "lucide-react";
import type { ReviewCompileCommand, ReviewCoordinateSpec, ReviewSession } from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { EChart, type EChartsCoreOption } from "../../ui/EChart";
import { classes, primaryButton } from "../../ui/styles";
import { compileReviewPoint, getReview, getReviews } from "./review-api";

type PointMode = "planned" | "exact" | "free";
type CoordinateDraft = Record<string, string>;
type CoordinateInput = NonNullable<ReviewCompileCommand["coordinates"]>[string];
type ReviewResult = NonNullable<ReviewSession["latest_result"]>;
type ReviewCompiledPoint = ReviewResult["inspections"][number]["content"]["points"][number];
type ReviewFact = { id: string; unit?: string | null; [key: string]: unknown };

export function ReviewWorkspace({ daemonUnavailable }: { daemonUnavailable: boolean }) {
  const [selectedId, setSelectedId] = useState(reviewIdFromLocation);
  const reviews = useQuery({
    queryKey: ["reviews"],
    queryFn: ({ signal }) => getReviews(signal),
    enabled: !daemonUnavailable,
    refetchInterval: 1_000,
  });
  const selected =
    reviews.data?.items.find((session) => session.session_id === selectedId) ??
    reviews.data?.items.find((session) => session.active) ??
    reviews.data?.items[0];

  useEffect(() => {
    if (selected && selected.session_id !== selectedId) {
      setSelectedId(selected.session_id);
      replaceReviewLocation(selected.session_id);
    }
  }, [selected, selectedId]);

  if (reviews.isPending) return <WorkspaceMessage title="Loading reviews" pending />;
  if (reviews.isError) {
    return (
      <WorkspaceMessage title="Review sessions unavailable" detail={errorMessage(reviews.error)} />
    );
  }
  if (!selected) {
    return (
      <WorkspaceMessage
        title="No live experiment reviews"
        detail="Start one from Python with lab.prepare(experiment).review()."
      />
    );
  }

  return (
    <div className="grid min-h-[680px] grid-cols-[260px_minmax(0,1fr)] overflow-hidden rounded-lg border border-line bg-panel max-[900px]:grid-cols-1">
      <aside className="border-r border-line bg-panel-soft p-2.5 max-[900px]:border-r-0 max-[900px]:border-b">
        <div className="flex items-center justify-between px-2 py-2">
          <strong className="text-[0.68rem] tracking-[0.08em] text-text-dim uppercase">
            Review sessions
          </strong>
          <span className="text-[0.62rem] text-text-dim">{reviews.data.items.length}</span>
        </div>
        <div className="grid gap-1.5 max-[900px]:grid-cols-[repeat(auto-fit,minmax(210px,1fr))]">
          {reviews.data.items.map((session) => (
            <button
              className={classes(
                "grid cursor-pointer gap-1 rounded-md border border-transparent bg-transparent px-2.5 py-2.5 text-left text-text-soft hover:bg-panel",
                session.session_id === selected.session_id && "border-line-strong bg-panel",
              )}
              key={session.session_id}
              onClick={() => {
                setSelectedId(session.session_id);
                replaceReviewLocation(session.session_id);
              }}
              type="button"
            >
              <span className="flex items-center justify-between gap-2 text-[0.7rem] font-bold">
                <span className="truncate">{session.title}</span>
                <SessionState active={session.active} />
              </span>
              <span className="truncate font-mono text-[0.58rem] text-text-dim">
                {session.experiment_id}
              </span>
            </button>
          ))}
        </div>
      </aside>
      <ReviewDetail sessionId={selected.session_id} />
    </div>
  );
}

function ReviewDetail({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const review = useQuery({
    queryKey: ["review", sessionId],
    queryFn: ({ signal }) => getReview(sessionId, signal),
    refetchInterval: 500,
  });
  const compile = useMutation({
    mutationFn: (command: ReviewCompileCommand) => compileReviewPoint(sessionId, command),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["review", sessionId] });
      await queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
  });

  if (review.isPending) return <WorkspaceMessage title="Loading compiler view" pending />;
  if (review.isError) {
    return <WorkspaceMessage title="Review unavailable" detail={errorMessage(review.error)} />;
  }
  const session = review.data;
  return (
    <section className="min-w-0 p-4 max-[680px]:p-2.5">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <SessionState active={session.active} />
            <span className="text-[0.6rem] font-bold tracking-[0.07em] text-text-dim uppercase">
              {session.experiment_kind}
            </span>
          </div>
          <h2 className="m-0 text-[1.05rem] tracking-[-0.02em]">{session.title}</h2>
          <code className="text-[0.62rem] text-text-dim">{session.experiment_id}</code>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[0.63rem] text-text-dim">
          {session.pending_request_count > 0 && (
            <LoaderCircle className="animate-spin" size={13} aria-hidden="true" />
          )}
          {session.pending_request_count > 0
            ? `${session.pending_request_count} compilation pending`
            : session.active
              ? "Compiler ready"
              : "Compiler disconnected"}
        </span>
      </header>

      <PointCompiler
        compileError={compile.error}
        compiling={compile.isPending || session.pending_request_count > 0}
        onCompile={(command) => compile.mutate(command)}
        session={session}
      />
      <InspectionResult session={session} />
    </section>
  );
}

function PointCompiler({
  session,
  compiling,
  compileError,
  onCompile,
}: {
  session: ReviewSession;
  compiling: boolean;
  compileError: Error | null;
  onCompile: (command: ReviewCompileCommand) => void;
}) {
  const selectedPoint = session.latest_result?.point;
  const [mode, setMode] = useState<PointMode>(
    selectedPoint?.point_index == null ? "free" : "planned",
  );
  const [pointIndex, setPointIndex] = useState(selectedPoint?.point_index ?? 0);
  const [coordinates, setCoordinates] = useState<CoordinateDraft>(() =>
    coordinateDraft(session.coordinates, selectedPoint?.coordinates),
  );

  useEffect(() => {
    setCoordinates(coordinateDraft(session.coordinates, selectedPoint?.coordinates));
    setPointIndex(selectedPoint?.point_index ?? 0);
  }, [session.coordinates, selectedPoint?.coordinates, selectedPoint?.point_index]);

  const submit = () => {
    if (mode === "planned") {
      onCompile({ point_index: pointIndex, coordinate_mode: "exact" });
      return;
    }
    onCompile({
      coordinates: Object.fromEntries(
        session.coordinates.map((spec) => [
          spec.id,
          parseCoordinate(spec, coordinates[spec.id] ?? ""),
        ]),
      ),
      coordinate_mode: mode,
    });
  };

  return (
    <div className="mb-4 rounded-md border border-line bg-panel-soft p-3.5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <strong className="text-[0.72rem]">Compile point</strong>
          <p className="mt-1 mb-0 text-[0.62rem] leading-5 text-text-dim">
            Planned selection, strict coordinate matching, and off-grid compilation use the same
            pure compiler.
          </p>
        </div>
        <div className="flex gap-1 rounded-md border border-line bg-panel p-1" role="group">
          {(["planned", "exact", "free"] as const).map((item) => (
            <button
              className={classes(
                "cursor-pointer rounded px-2.5 py-1.5 text-[0.62rem] font-bold capitalize text-text-dim",
                mode === item && "bg-panel-strong text-text",
              )}
              key={item}
              onClick={() => setMode(item)}
              type="button"
            >
              {item === "free" ? "Off-grid" : item}
            </button>
          ))}
        </div>
      </div>

      {mode === "planned" ? (
        <label className="grid max-w-[420px] gap-1.5 text-[0.61rem] font-bold text-text-dim">
          Planned point
          <select
            className="rounded-md border border-line bg-panel px-2.5 py-2 text-[0.68rem] font-medium text-text-soft"
            onChange={(event) => setPointIndex(Number(event.target.value))}
            value={pointIndex}
          >
            {session.planned_points.map((point) => (
              <option key={point.point_index ?? "candidate"} value={point.point_index ?? 0}>
                #{(point.point_index ?? 0) + 1} · {formatCoordinates(point.coordinates)}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-2.5">
          {session.coordinates.map((spec) => (
            <CoordinateInput
              key={spec.id}
              spec={spec}
              value={coordinates[spec.id] ?? ""}
              onChange={(value) => setCoordinates((current) => ({ ...current, [spec.id]: value }))}
            />
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          className={primaryButton}
          disabled={compiling || !session.active}
          onClick={submit}
          type="button"
        >
          {compiling ? (
            <LoaderCircle className="animate-spin" size={14} aria-hidden="true" />
          ) : (
            <Send size={14} aria-hidden="true" />
          )}
          Compile waveform
        </button>
        {mode !== "planned" && (
          <span className="text-[0.61rem] text-text-dim">
            {mode === "exact"
              ? "Reject values outside the authored scan."
              : "Allow valid coordinates outside the authored scan."}
          </span>
        )}
        {compileError && (
          <span className="w-full text-[0.62rem] text-red" role="alert">
            {errorMessage(compileError)}
          </span>
        )}
      </div>
    </div>
  );
}

function CoordinateInput({
  spec,
  value,
  onChange,
}: {
  spec: ReviewCoordinateSpec;
  value: string;
  onChange: (value: string) => void;
}) {
  const datalistId = `review-coordinate-${spec.id}`;
  if (spec.kind === "bool") {
    return (
      <label className="grid gap-1.5 text-[0.61rem] font-bold text-text-dim">
        {spec.id}
        <select
          className="rounded-md border border-line bg-panel px-2.5 py-2 text-[0.68rem] text-text-soft"
          onChange={(event) => onChange(event.target.value)}
          value={value}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      </label>
    );
  }
  return (
    <label className="grid gap-1.5 text-[0.61rem] font-bold text-text-dim">
      <span className="flex justify-between gap-2">
        {spec.id}
        {spec.unit && <span className="font-medium text-text-dim">{spec.unit}</span>}
      </span>
      <input
        className="rounded-md border border-line bg-panel px-2.5 py-2 text-[0.68rem] font-medium text-text-soft"
        list={spec.planned_values.length > 0 ? datalistId : undefined}
        max={spec.maximum ?? undefined}
        min={spec.minimum ?? undefined}
        onChange={(event) => onChange(event.target.value)}
        step={spec.kind === "int" ? 1 : "any"}
        type={["int", "float", "quantity"].includes(spec.kind) ? "number" : "text"}
        value={value}
      />
      {spec.planned_values.length > 0 && (
        <datalist id={datalistId}>
          {spec.planned_values.map((planned, index) => (
            <option
              aria-label={`${spec.id} planned value ${index + 1}`}
              key={index}
              value={coordinateInputValue(planned)}
            />
          ))}
        </datalist>
      )}
    </label>
  );
}

function InspectionResult({ session }: { session: ReviewSession }) {
  const result = session.latest_result;
  if (!result) return <WorkspaceMessage title="No point compiled yet" />;
  if (result.error) return <WorkspaceMessage title="Compilation failed" detail={result.error} />;
  if (!result.point) return <WorkspaceMessage title="No selected point" />;
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-panel-soft px-3.5 py-2.5">
        <div>
          <span className="text-[0.59rem] font-bold tracking-[0.06em] text-text-dim uppercase">
            {result.point.point_index == null
              ? "Off-grid candidate"
              : `Planned point #${result.point.point_index + 1}`}
          </span>
          <div className="mt-1 text-[0.7rem] font-semibold text-text-soft">
            {formatCoordinates(result.point.coordinates)}
          </div>
        </div>
        {result.point.proposal_fingerprint && (
          <code className="max-w-[350px] truncate text-[0.56rem] text-text-dim">
            {result.point.proposal_fingerprint}
          </code>
        )}
      </div>
      {result.inspections.length === 0 ? (
        <WorkspaceMessage title="No target waveform inspection" />
      ) : (
        result.inspections.map((inspection) => (
          <div
            className="overflow-hidden rounded-md border border-line bg-panel-soft"
            key={inspection.operation_id}
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3.5 py-2.5">
              <div>
                <strong className="text-[0.7rem]">{inspection.target_id}</strong>
                <div className="mt-0.5 font-mono text-[0.56rem] text-text-dim">
                  {inspection.artifact_id}
                </div>
              </div>
              <span className="text-[0.58rem] text-text-dim">{inspection.content.kind}</span>
            </div>
            <div className="grid gap-3 p-3.5">
              <FactGrid facts={inspection.content.facts} />
              {inspection.content.points.map((point) => (
                <PointInspection key={point.realization_fingerprint} point={point} />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

function PointInspection({ point }: { point: ReviewCompiledPoint }) {
  const option = useMemo(() => waveformChartOption(point), [point]);
  return (
    <div className="grid gap-3 rounded-md border border-line bg-panel p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="text-[0.61rem] font-bold text-text-soft">Physical realization</span>
          <code className="mt-1 block max-w-[620px] truncate text-[0.55rem] text-text-dim">
            {point.realization_fingerprint}
          </code>
        </div>
        <span className="text-[0.6rem] text-text-dim">
          {point.waveform_count} waveform{point.waveform_count === 1 ? "" : "s"}
          {point.waveforms_truncated ? "+" : ""}
        </span>
      </div>
      <FactGrid facts={point.facts} />
      {point.waveforms.length > 0 && (
        <EChart
          ariaLabel="Compiled physical waveforms"
          height={320}
          option={option}
          pointCount={Math.max(...point.waveforms.map((waveform) => waveform.samples.length))}
          seriesCount={point.waveforms.length}
          seriesLabels={point.waveforms.map((waveform) => waveform.channel_id)}
        />
      )}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-2">
        {point.waveforms.map((waveform) => (
          <div
            className="rounded border border-line bg-panel-soft px-2.5 py-2"
            key={waveform.channel_id}
          >
            <strong className="block truncate text-[0.61rem] text-text-soft">
              {waveform.channel_id}
            </strong>
            <span className="mt-1 block text-[0.56rem] text-text-dim">
              peak {waveform.peak_abs.toPrecision(4)} · rms {waveform.rms.toPrecision(4)} ·{" "}
              {waveform.source_sample_count.toLocaleString()} samples
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function FactGrid({ facts }: { facts: ReviewFact[] }) {
  return (
    <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
      {facts.map((fact) => (
        <div className="rounded border border-line bg-panel-soft px-2.5 py-2" key={fact.id}>
          <dt className="text-[0.54rem] font-bold tracking-[0.04em] text-text-dim uppercase">
            {fact.id.replaceAll("_", " ")}
          </dt>
          <dd className="mt-1 ml-0 truncate text-[0.62rem] font-semibold text-text-soft">
            {formatValue(fact.value)} {fact.unit ?? ""}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function waveformChartOption(point: ReviewCompiledPoint): EChartsCoreOption {
  return {
    animation: false,
    backgroundColor: "transparent",
    grid: { left: 54, right: 18, top: 34, bottom: 42 },
    legend: { type: "scroll", top: 0, textStyle: { color: "#9eabb8", fontSize: 10 } },
    tooltip: { trigger: "axis" },
    xAxis: {
      name: "sample",
      nameLocation: "middle",
      nameGap: 28,
      type: "value",
      axisLabel: { color: "#7f8b97", fontSize: 10 },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } },
    },
    yAxis: {
      name: "amplitude",
      type: "value",
      axisLabel: { color: "#7f8b97", fontSize: 10 },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } },
    },
    series: point.waveforms.map((waveform) => ({
      data: waveform.sample_indices.map((index, offset) => [index, waveform.samples[offset]]),
      emphasis: { focus: "series" },
      name: waveform.channel_id,
      showSymbol: false,
      type: "line",
    })),
  };
}

function coordinateDraft(
  specs: ReviewCoordinateSpec[],
  current?: Record<string, unknown>,
): CoordinateDraft {
  return Object.fromEntries(
    specs.map((spec) => [
      spec.id,
      coordinateInputValue(current?.[spec.id] ?? spec.planned_values[0] ?? ""),
    ]),
  );
}

function parseCoordinate(spec: ReviewCoordinateSpec, encoded: string): CoordinateInput {
  if (spec.kind === "bool") return encoded === "true";
  if (spec.kind === "int") return Number.parseInt(encoded, 10);
  if (spec.kind === "float") return Number(encoded);
  if (spec.kind === "quantity") return { value: Number(encoded), unit: spec.unit ?? "" };
  if (spec.kind === "entity") return { id: encoded, metadata: {} };
  return encoded;
}

function coordinateInputValue(value: unknown): string {
  if (typeof value === "object" && value !== null && "value" in value) {
    return String(value.value);
  }
  if (typeof value === "object" && value !== null && "id" in value) {
    return String(value.id);
  }
  return String(value);
}

function formatCoordinates(coordinates: Record<string, unknown>): string {
  return Object.entries(coordinates)
    .map(([id, value]) => `${id}=${formatValue(value)}`)
    .join(" · ");
}

function formatValue(value: unknown): string {
  if (typeof value === "object" && value !== null && "value" in value && "unit" in value) {
    return `${String(value.value)} ${String(value.unit)}`;
  }
  if (typeof value === "object" && value !== null && "id" in value) return String(value.id);
  if (typeof value === "string") return value;
  if (value == null || typeof value === "number" || typeof value === "boolean")
    return String(value);
  return JSON.stringify(value);
}

function SessionState({ active }: { active: boolean }) {
  return (
    <span
      className={classes(
        "inline-flex items-center gap-1 text-[0.56rem] font-bold uppercase",
        active ? "text-accent" : "text-text-dim",
      )}
    >
      {active ? <Radio size={10} aria-hidden="true" /> : <CircleOff size={10} aria-hidden="true" />}
      {active ? "Live" : "Closed"}
    </span>
  );
}

function WorkspaceMessage({
  title,
  detail,
  pending = false,
}: {
  title: string;
  detail?: string;
  pending?: boolean;
}) {
  return (
    <div className="grid min-h-[420px] place-content-center justify-items-center p-8 text-center">
      <span className="mb-3 grid size-12 place-items-center rounded-xl border border-line bg-panel-soft text-text-dim">
        {pending ? <LoaderCircle className="animate-spin" /> : <Waves />}
      </span>
      <strong className="text-[0.8rem] text-text-soft">{title}</strong>
      {detail && (
        <p className="mt-2 max-w-[460px] text-[0.66rem] leading-5 text-text-dim">{detail}</p>
      )}
    </div>
  );
}

function reviewIdFromLocation(): string | undefined {
  const match = window.location.hash.match(/^#reviews\/(.+)$/);
  const encoded = match?.[1];
  return encoded ? decodeURIComponent(encoded) : undefined;
}

function replaceReviewLocation(sessionId: string): void {
  const location = new URL(window.location.href);
  location.hash = `reviews/${encodeURIComponent(sessionId)}`;
  window.history.replaceState(null, "", `${location.pathname}${location.search}${location.hash}`);
}
