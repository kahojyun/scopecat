import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleDot, LoaderCircle, Send } from "lucide-react";
import type {
  PointCoordinateSpec,
  RunInspectionFeed,
  RunPointEnqueueCommand,
  RunPointResolveCommand,
} from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { classes, primaryButton } from "../../ui/styles";
import type { ProjectRun } from "../../types";
import { formatInspectionCoordinates } from "../inspections/CompiledInspectionView";
import { enqueueRunPoint, getRunPointQueue, resolveRunPoint } from "./run-api";

type QueueCoordinate = RunPointEnqueueCommand["coordinates"][string];
type QueueMode = "exact" | "snap" | "free";
type CoordinateDraft = Record<string, string>;
export function RunPointQueueControl({
  run,
  inspections,
}: {
  run: ProjectRun;
  inspections: RunInspectionFeed["items"];
}) {
  const queryClient = useQueryClient();
  const adaptive = run.plan.pointCount === undefined;
  const active = run.status === "running" && adaptive && !run.pointPlan.closed;
  const queue = useQuery({
    queryKey: ["run-point-queue", run.runId],
    queryFn: ({ signal }) => getRunPointQueue(run.runId, signal),
    enabled: adaptive,
    refetchInterval: active ? 250 : false,
  });
  const enqueue = useMutation({
    mutationFn: async (command: RunPointEnqueueCommand) => {
      await resolveRunPoint(run.runId, {
        coordinate_mode: command.coordinate_mode,
        coordinates: command.coordinates,
      });
      return enqueueRunPoint(run.runId, command);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["run-point-queue", run.runId] });
      await queryClient.invalidateQueries({ queryKey: ["events", "run", run.runId] });
    },
  });
  const specs = run.plan.coordinateSpecs;
  const [mode, setMode] = useState<QueueMode>("exact");
  const [draft, setDraft] = useState<CoordinateDraft>({});
  const [inputError, setInputError] = useState<string>();
  useEffect(() => {
    setDraft((current) =>
      Object.fromEntries(
        specs.map((spec) => [spec.id, current[spec.id] ?? coordinateText(spec.sampled_values[0])]),
      ),
    );
  }, [specs]);

  const resolveCommand = useMemo<RunPointResolveCommand | undefined>(() => {
    if (mode === "exact") return undefined;
    try {
      return {
        coordinate_mode: mode,
        coordinates: Object.fromEntries(
          specs.map((spec) => [spec.id, parseCoordinate(spec, draft[spec.id] ?? "")]),
        ),
      };
    } catch {
      return undefined;
    }
  }, [draft, mode, specs]);
  const resolution = useQuery({
    queryKey: ["run-point-resolution", run.runId, resolveCommand],
    queryFn: ({ signal }) => {
      if (!resolveCommand) throw new Error("point selection is incomplete");
      return resolveRunPoint(run.runId, resolveCommand, signal);
    },
    enabled: active && resolveCommand !== undefined,
    retry: false,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    try {
      if (!resolveCommand) throw new Error("enter every point coordinate");
      setInputError(undefined);
      enqueue.mutate({
        request_id: `operator-point.${globalThis.crypto.randomUUID()}`,
        ...resolveCommand,
      });
    } catch (error) {
      setInputError(errorMessage(error));
    }
  };

  if (!adaptive) return null;
  return (
    <div className="mb-3 rounded-md border border-line bg-panel-soft p-3">
      <div className="mb-2.5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <strong className="text-[0.7rem]">Point inspection &amp; Queue</strong>
          <p className="mt-1 mb-0 text-[0.61rem] leading-5 text-text-dim">
            Inspect an exact compiled point, snap to known scan values, or queue a free physical
            coordinate for the running compiler.
          </p>
        </div>
        <div className="flex gap-1 rounded-md border border-line bg-panel p-1" role="group">
          {(["exact", "snap", "free"] as const).map((item) => (
            <button
              className={classes(
                "cursor-pointer rounded px-2.5 py-1.5 text-[0.61rem] font-bold capitalize text-text-dim",
                mode === item && "bg-panel-strong text-text",
              )}
              key={item}
              onClick={() => {
                setMode(item);
                setInputError(undefined);
              }}
              type="button"
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {mode === "exact" ? (
        <p className="m-0 rounded border border-dashed border-line px-3 py-2 text-[0.61rem] text-text-dim">
          {inspections.length > 0
            ? "Select a compiled point below to inspect its exact waveform and compare realizations."
            : "No compiled point is available yet. Use Snap or Free to add an operator candidate."}
        </p>
      ) : (
        <form onSubmit={submit}>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5">
            {specs.map((spec) => (
              <label className="grid gap-1 text-[0.59rem] font-bold text-text-dim" key={spec.id}>
                <span className="flex justify-between gap-2">
                  {spec.id}
                  {spec.unit && <span className="font-medium">{spec.unit}</span>}
                </span>
                <input
                  className="rounded-md border border-line bg-panel px-2.5 py-2 text-[0.66rem] font-medium text-text-soft"
                  list={
                    spec.sampled_values.length > 0 ? `run-point-${run.runId}-${spec.id}` : undefined
                  }
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, [spec.id]: event.target.value }))
                  }
                  type={numericCoordinate(spec) ? "number" : "text"}
                  value={draft[spec.id] ?? ""}
                />
                {spec.sampled_values.length > 0 && (
                  <datalist id={`run-point-${run.runId}-${spec.id}`}>
                    {spec.sampled_values.map((value, index) => (
                      <option key={index} value={coordinateText(value)}>
                        {coordinateText(value)}
                      </option>
                    ))}
                  </datalist>
                )}
              </label>
            ))}
          </div>
          {resolution.data && (
            <p className="mt-2 mb-0 text-[0.59rem] text-text-dim">
              {mode === "snap" ? "Will queue snapped point: " : "Will queue free point: "}
              <strong className="text-text-soft">
                {formatInspectionCoordinates(resolution.data.coordinates)}
              </strong>
            </p>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <button
              className={primaryButton}
              disabled={!active || enqueue.isPending || specs.length === 0}
              type="submit"
            >
              {enqueue.isPending ? (
                <LoaderCircle className="animate-spin" size={14} aria-hidden="true" />
              ) : (
                <Send size={14} aria-hidden="true" />
              )}
              Queue point
            </button>
            <span className="text-[0.59rem] text-text-dim">
              {!active
                ? run.pointPlan.closed
                  ? "The adaptive point plan is closed."
                  : "Queueing becomes available while the executor owns this run."
                : mode === "snap"
                  ? "Snapping is explicit; the resolved coordinates are shown before queueing."
                  : "Free coordinates are compiled without silent snapping."}
            </span>
            {(inputError || resolution.error || enqueue.error) && (
              <span className="w-full text-[0.61rem] text-red" role="alert">
                {inputError ?? errorMessage(resolution.error ?? enqueue.error)}
              </span>
            )}
          </div>
        </form>
      )}

      {queue.data && queue.data.items.length > 0 && (
        <div className="mt-3 grid gap-1.5 border-t border-line pt-2.5">
          {queue.data.items.map((item) => (
            <div
              className="flex flex-wrap items-center justify-between gap-2 rounded border border-line bg-panel px-2.5 py-2 text-[0.59rem]"
              key={item.request.request_id}
            >
              <span className="truncate text-text-soft">
                {formatInspectionCoordinates(item.request.coordinates)}
              </span>
              {item.request.coordinate_mode === "snap" &&
                JSON.stringify(item.request.requested_coordinates) !==
                  JSON.stringify(item.request.coordinates) && (
                  <span className="w-full text-text-dim">
                    Requested {formatInspectionCoordinates(item.request.requested_coordinates)}
                  </span>
                )}
              <span
                className={classes(
                  "inline-flex items-center gap-1 font-bold capitalize",
                  item.status === "accepted"
                    ? "text-accent"
                    : item.status === "rejected" || item.status === "cancelled"
                      ? "text-red"
                      : "text-blue",
                )}
              >
                <CircleDot size={10} aria-hidden="true" />
                {item.status}
                {item.accepted_point_index != null && ` · point #${item.accepted_point_index + 1}`}
              </span>
              {item.reason && <span className="w-full text-text-dim">{item.reason}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function coordinateText(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") {
    if ("value" in value && typeof value.value === "number") return String(value.value);
    if ("id" in value && typeof value.id === "string") return value.id;
    return "";
  }
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return `${value}`;
  return "";
}

function numericCoordinate(spec: PointCoordinateSpec): boolean {
  return spec.kind === "int" || spec.kind === "float" || spec.kind === "quantity";
}

function parseCoordinate(spec: PointCoordinateSpec, encoded: string): QueueCoordinate {
  if (!encoded.trim()) throw new Error(`${spec.id} requires a value`);
  if (spec.kind === "bool") {
    if (encoded !== "true" && encoded !== "false") throw new Error(`${spec.id} must be boolean`);
    return encoded === "true";
  }
  if (spec.kind === "int" || spec.kind === "float") {
    const value = Number(encoded);
    if (!Number.isFinite(value)) throw new Error(`${spec.id} must be numeric`);
    if (spec.kind === "int" && !Number.isInteger(value)) {
      throw new Error(`${spec.id} must be an integer`);
    }
    return value;
  }
  if (spec.kind === "quantity") {
    const value = Number(encoded);
    if (!Number.isFinite(value)) throw new Error(`${spec.id} must be numeric`);
    return { value, unit: spec.unit ?? "" };
  }
  if (spec.kind === "entity") return { id: encoded, metadata: {} };
  return encoded;
}
