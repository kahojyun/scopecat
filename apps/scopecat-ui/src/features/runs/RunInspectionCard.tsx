import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, CircleDot, Cpu, XCircle } from "lucide-react";
import type { RunInspectionFeed } from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { classes, countBadge, detailCard } from "../../ui/styles";
import type { ProjectRun } from "../../types";
import { CompiledInspectionView } from "../inspections/CompiledInspectionView";
import { RunDomainQueueControl } from "./RunDomainQueueControl";

type InspectionEvent = RunInspectionFeed["items"][number];

export function RunInspectionCard({
  feed,
  error,
  pending,
  completedPointCount,
  run,
}: {
  feed?: RunInspectionFeed;
  error: Error | null;
  pending: boolean;
  completedPointCount: number;
  run: ProjectRun;
}) {
  const items = useMemo(() => feed?.items ?? [], [feed?.items]);
  const [selectedProposal, setSelectedProposal] = useState<number>();
  const [comparisonProposal, setComparisonProposal] = useState<number>();
  useEffect(() => {
    setSelectedProposal((current) =>
      items.some((item) => item.proposal_index === current)
        ? current
        : items.at(-1)?.proposal_index,
    );
    setComparisonProposal((current) =>
      items.some((item) => item.proposal_index === current) ? current : undefined,
    );
  }, [items]);
  const selected = items.find((item) => item.proposal_index === selectedProposal);
  const comparison = items.find((item) => item.proposal_index === comparisonProposal);
  const comparable = useMemo(
    () =>
      items.filter(
        (item) =>
          item.outcome === "accepted" &&
          item.inspections.length > 0 &&
          item.proposal_index !== selected?.proposal_index,
      ),
    [items, selected?.proposal_index],
  );

  return (
    <article className={classes(detailCard, "col-span-full")} data-testid="run-inspection-card">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-text-soft">
          <Cpu size={17} aria-hidden="true" />
          <strong className="text-[0.76rem]">Compiled domain inspection</strong>
        </div>
        <span className={countBadge}>{feed?.total_proposal_count ?? items.length}</span>
      </div>
      <RunDomainQueueControl run={run} inspections={items} />
      {error ? (
        <EmptyInspection title="Inspection feed unavailable" detail={errorMessage(error)} warning />
      ) : pending && !feed ? (
        <EmptyInspection title="Reading optimizer decisions" />
      ) : items.length === 0 ? (
        <EmptyInspection
          title="No adaptive scan compiled"
          detail="Accepted optimizer and operator domains share this compiled waveform view."
        />
      ) : (
        <div className="grid grid-cols-[230px_minmax(0,1fr)] gap-3 max-[760px]:grid-cols-1">
          <div className="grid content-start gap-1.5">
            {feed?.items_truncated && (
              <span className="px-2 py-1 text-[0.56rem] text-text-dim">
                Showing the latest {items.length} proposals
              </span>
            )}
            {items.map((item) => (
              <button
                className={classes(
                  "grid cursor-pointer gap-1 rounded-md border border-line bg-panel px-2.5 py-2 text-left",
                  item.proposal_index === selected?.proposal_index &&
                    "border-line-strong bg-panel-strong",
                )}
                key={item.proposal_index}
                onClick={() => setSelectedProposal(item.proposal_index)}
                type="button"
              >
                <span className="flex items-center justify-between gap-2 text-[0.62rem] font-bold">
                  Proposal #{item.proposal_index + 1}
                  <EventStatus event={item} completedPointCount={completedPointCount} />
                </span>
                <span className="truncate text-[0.58rem] text-text-dim">
                  {formatDomainEvent(item)}
                </span>
              </button>
            ))}
          </div>
          {selected && (
            <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3 rounded-md border border-line bg-panel p-3">
                <div>
                  <strong className="text-[0.7rem]">
                    {selected.outcome === "accepted"
                      ? acceptedPointLabel(selected)
                      : "Rejected scan"}
                  </strong>
                  <div className="mt-1 text-[0.62rem] text-text-dim">
                    {formatDomainEvent(selected)}
                  </div>
                  {selected.reason && (
                    <p className="mt-1.5 mb-0 text-[0.61rem] text-red">{selected.reason}</p>
                  )}
                </div>
                {comparable.length > 0 && (
                  <label className="grid gap-1 text-[0.56rem] font-bold text-text-dim">
                    Compare with
                    <select
                      className="rounded border border-line bg-panel-soft px-2 py-1.5 text-[0.61rem] text-text-soft"
                      onChange={(event) =>
                        setComparisonProposal(
                          event.target.value === "" ? undefined : Number(event.target.value),
                        )
                      }
                      value={comparisonProposal ?? ""}
                    >
                      <option value="">None</option>
                      {comparable.map((item) => (
                        <option key={item.proposal_index} value={item.proposal_index}>
                          Proposal #{item.proposal_index + 1}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
              <div
                className={classes(
                  "grid gap-3",
                  comparison && "grid-cols-2 max-[1100px]:grid-cols-1",
                )}
              >
                <InspectionColumn event={selected} label="Selected" />
                {comparison && <InspectionColumn event={comparison} label="Comparison" />}
              </div>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function InspectionColumn({ event, label }: { event: InspectionEvent; label: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-2 text-[0.57rem] font-bold tracking-[0.06em] text-text-dim uppercase">
        {label}
      </div>
      <CompiledInspectionView
        inspections={event.inspections}
        emptyTitle={event.outcome === "rejected" ? "Candidate was not compiled" : undefined}
      />
    </div>
  );
}

function EventStatus({
  event,
  completedPointCount,
}: {
  event: InspectionEvent;
  completedPointCount: number;
}) {
  if (event.outcome === "rejected") {
    return (
      <span className="inline-flex items-center gap-1 text-red">
        <XCircle size={11} /> Rejected
      </span>
    );
  }
  const completed =
    event.accepted_points.length > 0 &&
    event.accepted_points.every(
      (point) => point.point_index != null && point.point_index < completedPointCount,
    );
  return completed ? (
    <span className="inline-flex items-center gap-1 text-accent">
      <CheckCircle2 size={11} /> Complete
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-blue">
      <CircleDot size={11} /> Compiled
    </span>
  );
}

function acceptedPointLabel(event: InspectionEvent): string {
  const indices = event.accepted_points
    .map((point) => point.point_index)
    .filter((index): index is number => index != null);
  if (indices.length === 0) return "Accepted scan";
  const first = indices[0]!;
  if (indices.length === 1) return `Run point #${first + 1}`;
  return `${indices.length} run points #${first + 1}–${indices.at(-1)! + 1}`;
}

function formatDomainEvent(event: InspectionEvent): string {
  const axes = event.fragment.axes
    .map((axis) => {
      const source = axis.source;
      if (source.kind === "values") {
        return `${axis.axis_id} [${source.values.map(coordinateText).join(", ")}]`;
      }
      if (source.kind === "range") {
        return `${axis.axis_id} ${coordinateText(source.start)}→${coordinateText(source.stop)} (${source.points})`;
      }
      return `${axis.axis_id} around ${coordinateText(source.center)} span ${coordinateText(source.span)} (${source.points})`;
    })
    .join(" × ");
  const regions =
    event.region_ids.length === 1 ? event.region_ids[0] : `${event.region_ids.length} regions`;
  return `${axes} · ${regions}`;
}

function coordinateText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object" && "value" in value && typeof value.value === "number") {
    const unit = "unit" in value && typeof value.unit === "string" ? ` ${value.unit}` : "";
    return `${value.value}${unit}`;
  }
  if (typeof value === "object") {
    return "id" in value && typeof value.id === "string" ? value.id : "";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return `${value}`;
  }
  return "";
}

function EmptyInspection({
  title,
  detail,
  warning = false,
}: {
  title: string;
  detail?: string;
  warning?: boolean;
}) {
  return (
    <div className="rounded-md border border-dashed border-line p-4 text-center">
      <strong className={classes("text-[0.68rem] text-text-soft", warning && "text-red")}>
        {title}
      </strong>
      {detail && <p className="mt-1.5 mb-0 text-[0.61rem] text-text-dim">{detail}</p>}
    </div>
  );
}
