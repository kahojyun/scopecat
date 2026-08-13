import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleDot, LoaderCircle, Send } from "lucide-react";
import type {
  MeasurementValue,
  RunInspectionFeed,
  RunPointEnqueueCommand,
} from "../../api-contract";
import { errorMessage } from "../../lib/presentation";
import { classes, primaryButton } from "../../ui/styles";
import type { MeasurementPreview, ProjectRun } from "../../types";
import { formatInspectionCoordinates } from "../inspections/CompiledInspectionView";
import { enqueueRunPoint, getRunPointQueue } from "./run-api";

type QueueCoordinate = RunPointEnqueueCommand["coordinates"][string];
type QueueMode = "exact" | "snap" | "free";
type CoordinateDraft = Record<string, string>;
type ProductGridAxis = Extract<
  NonNullable<MeasurementPreview["schema"]>["point_domain"],
  { kind: "product_grid" }
>["axes"][number];

interface AxisInputSpec {
  id: string;
  unit?: string;
  values: QueueCoordinate[];
}

export function RunPointQueueControl({
  run,
  measurements,
  inspections,
}: {
  run: ProjectRun;
  measurements?: MeasurementPreview;
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
    mutationFn: (command: RunPointEnqueueCommand) => enqueueRunPoint(run.runId, command),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["run-point-queue", run.runId] });
      await queryClient.invalidateQueries({ queryKey: ["events", "run", run.runId] });
    },
  });
  const specs = useMemo(() => coordinateSpecs(run, measurements), [measurements, run]);
  const [mode, setMode] = useState<QueueMode>("exact");
  const [draft, setDraft] = useState<CoordinateDraft>({});
  const [inputError, setInputError] = useState<string>();
  useEffect(() => {
    setDraft((current) =>
      Object.fromEntries(
        specs.map((spec) => [spec.id, current[spec.id] ?? coordinateText(spec.values[0])]),
      ),
    );
  }, [specs]);

  const parsed = useMemo(() => {
    if (mode === "exact") return undefined;
    try {
      const coordinates = Object.fromEntries(
        specs.map((spec) => [spec.id, parseCoordinate(spec, draft[spec.id] ?? "")]),
      );
      return mode === "snap" ? snapCoordinates(specs, coordinates) : coordinates;
    } catch {
      return undefined;
    }
  }, [draft, mode, specs]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    try {
      const coordinates = Object.fromEntries(
        specs.map((spec) => [spec.id, parseCoordinate(spec, draft[spec.id] ?? "")]),
      );
      const selected = mode === "snap" ? snapCoordinates(specs, coordinates) : coordinates;
      setInputError(undefined);
      enqueue.mutate({
        operation_id: `operator-point.${globalThis.crypto.randomUUID()}`,
        coordinates: selected,
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
                  list={spec.values.length > 0 ? `run-point-${run.runId}-${spec.id}` : undefined}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, [spec.id]: event.target.value }))
                  }
                  type={numericCoordinate(spec.values[0]) ? "number" : "text"}
                  value={draft[spec.id] ?? ""}
                />
                {spec.values.length > 0 && (
                  <datalist id={`run-point-${run.runId}-${spec.id}`}>
                    {spec.values.map((value, index) => (
                      <option key={index} value={coordinateText(value)}>
                        {coordinateText(value)}
                      </option>
                    ))}
                  </datalist>
                )}
              </label>
            ))}
          </div>
          {parsed && (
            <p className="mt-2 mb-0 text-[0.59rem] text-text-dim">
              {mode === "snap" ? "Will queue snapped point: " : "Will queue free point: "}
              <strong className="text-text-soft">{formatInspectionCoordinates(parsed)}</strong>
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
            {(inputError || enqueue.error) && (
              <span className="w-full text-[0.61rem] text-red" role="alert">
                {inputError ?? errorMessage(enqueue.error)}
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
              key={item.operation_id}
            >
              <span className="truncate text-text-soft">
                {formatInspectionCoordinates(item.candidate.coordinates)}
              </span>
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

function coordinateSpecs(
  run: ProjectRun,
  measurements: MeasurementPreview | undefined,
): AxisInputSpec[] {
  const schemaAxes =
    measurements?.schema?.point_domain.kind === "product_grid"
      ? measurements.schema.point_domain.axes
      : [];
  return run.plan.coordinateIds.map((id) => {
    const axis = schemaAxes.find((item) => item.id === id);
    const values = [
      ...(axis ? axisValues(axis) : []),
      ...(measurements?.items.map((record) => measurementCoordinate(record.coordinates[id])) ?? []),
    ].filter((value): value is QueueCoordinate => value !== undefined);
    return {
      id,
      unit: coordinateUnit(values[0]),
      values: uniqueCoordinates(values),
    };
  });
}

function axisValues(axis: ProductGridAxis): QueueCoordinate[] {
  const source = axis.source;
  if (source.kind === "values") {
    return source.values
      .map(measurementCoordinate)
      .filter((value): value is QueueCoordinate => value !== undefined);
  }
  const start = source.kind === "range" ? source.start : linearEdge(source.center, source.span, -1);
  const stop = source.kind === "range" ? source.stop : linearEdge(source.center, source.span, 1);
  if (axis.size <= 1) return [measurementCoordinate(start)].filter(isCoordinate);
  const startValue = numericMeasurement(start);
  const stopValue = numericMeasurement(stop);
  if (startValue === undefined || stopValue === undefined) return [];
  return Array.from({ length: axis.size }, (_, index) =>
    scalarCoordinate(start, startValue + ((stopValue - startValue) * index) / (axis.size - 1)),
  );
}

function linearEdge(
  center: Extract<MeasurementValue, { kind: "scalar" }>,
  span: Extract<MeasurementValue, { kind: "scalar" }>,
  direction: -1 | 1,
) {
  const centerValue = numericMeasurement(center);
  const spanValue = numericMeasurement(span);
  if (centerValue === undefined || spanValue === undefined) return center;
  return { ...center, value: centerValue + (direction * spanValue) / 2 };
}

function measurementCoordinate(
  value: MeasurementValue | null | undefined,
): QueueCoordinate | undefined {
  if (!value || value.kind !== "scalar" || typeof value.value === "object") return undefined;
  return scalarCoordinate(value, value.value);
}

function scalarCoordinate(
  scalar: Extract<MeasurementValue, { kind: "scalar" }>,
  value: boolean | number | string,
): QueueCoordinate {
  return scalar.unit && typeof value === "number" ? { value, unit: scalar.unit } : value;
}

function numericMeasurement(
  scalar: Extract<MeasurementValue, { kind: "scalar" }>,
): number | undefined {
  return typeof scalar.value === "number" ? scalar.value : undefined;
}

function uniqueCoordinates(values: QueueCoordinate[]): QueueCoordinate[] {
  return [...new Map(values.map((value) => [JSON.stringify(value), value])).values()];
}

function coordinateText(value: QueueCoordinate | undefined): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") return "value" in value ? String(value.value) : value.id;
  return String(value);
}

function coordinateUnit(value: QueueCoordinate | undefined): string | undefined {
  return typeof value === "object" && value !== null && "unit" in value ? value.unit : undefined;
}

function numericCoordinate(value: QueueCoordinate | undefined): boolean {
  return typeof value === "number" || coordinateUnit(value) !== undefined;
}

function parseCoordinate(spec: AxisInputSpec, encoded: string): QueueCoordinate {
  if (!encoded.trim()) throw new Error(`${spec.id} requires a value`);
  const exemplar = spec.values[0];
  if (typeof exemplar === "boolean") {
    if (encoded !== "true" && encoded !== "false") throw new Error(`${spec.id} must be boolean`);
    return encoded === "true";
  }
  if (typeof exemplar === "number") {
    const value = Number(encoded);
    if (!Number.isFinite(value)) throw new Error(`${spec.id} must be numeric`);
    return value;
  }
  if (typeof exemplar === "object" && exemplar !== null && "unit" in exemplar) {
    const value = Number(encoded);
    if (!Number.isFinite(value)) throw new Error(`${spec.id} must be numeric`);
    return { value, unit: exemplar.unit };
  }
  return encoded;
}

function snapCoordinates(
  specs: AxisInputSpec[],
  coordinates: Record<string, QueueCoordinate>,
): Record<string, QueueCoordinate> {
  return Object.fromEntries(
    specs.map((spec) => {
      if (spec.values.length === 0) {
        throw new Error(`${spec.id} has no known scan values; use Free mode`);
      }
      const requested = coordinates[spec.id];
      const requestedNumber = coordinateNumber(requested);
      if (requestedNumber === undefined) {
        const exact = spec.values.find(
          (value) => coordinateText(value) === coordinateText(requested),
        );
        if (exact === undefined) throw new Error(`${spec.id} has no matching scan value`);
        return [spec.id, exact];
      }
      return [
        spec.id,
        spec.values.reduce((nearest, value) => {
          const candidate = coordinateNumber(value);
          if (candidate === undefined) return nearest;
          return Math.abs(candidate - requestedNumber) <
            Math.abs((coordinateNumber(nearest) ?? Number.POSITIVE_INFINITY) - requestedNumber)
            ? value
            : nearest;
        }),
      ];
    }),
  );
}

function coordinateNumber(value: QueueCoordinate | undefined): number | undefined {
  if (typeof value === "number") return value;
  if (typeof value === "object" && value !== null && "unit" in value) return value.value;
  return undefined;
}

function isCoordinate(value: QueueCoordinate | undefined): value is QueueCoordinate {
  return value !== undefined;
}
