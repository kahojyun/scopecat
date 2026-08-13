import { useMemo } from "react";
import { EChart, type EChartsCoreOption } from "../../ui/EChart";

type InspectionFact = { id: string; unit?: string | null; value?: unknown };
type CompiledWaveform = {
  channel_id: string;
  instrument_id: string;
  peak_abs: number;
  rms: number;
  source_sample_count: number;
  sample_indices: number[];
  samples: number[];
};
type CompiledPoint = {
  realization_fingerprint: string;
  facts: InspectionFact[];
  waveform_count: number;
  waveforms_truncated: boolean;
  waveforms: CompiledWaveform[];
};
type PresentedInspection = {
  operation_id: string;
  target_id: string;
  artifact_id: string;
  content: {
    kind: string;
    facts: InspectionFact[];
    points: CompiledPoint[];
  };
};

export function CompiledInspectionView({
  inspections,
  emptyTitle = "No target waveform inspection",
}: {
  inspections: readonly PresentedInspection[];
  emptyTitle?: string;
}) {
  if (inspections.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line p-4 text-center text-[0.65rem] text-text-dim">
        {emptyTitle}
      </div>
    );
  }
  return (
    <div className="grid gap-3">
      {inspections.map((inspection) => (
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
      ))}
    </div>
  );
}

function PointInspection({ point }: { point: CompiledPoint }) {
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

function FactGrid({ facts }: { facts: InspectionFact[] }) {
  return (
    <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
      {facts.map((fact) => (
        <div className="rounded border border-line bg-panel-soft px-2.5 py-2" key={fact.id}>
          <dt className="text-[0.54rem] font-bold tracking-[0.04em] text-text-dim uppercase">
            {fact.id.replaceAll("_", " ")}
          </dt>
          <dd className="mt-1 ml-0 truncate text-[0.62rem] font-semibold text-text-soft">
            {formatInspectionValue(fact.value)} {fact.unit ?? ""}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function waveformChartOption(point: CompiledPoint): EChartsCoreOption {
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

export function formatInspectionCoordinates(coordinates: Record<string, unknown>): string {
  return Object.entries(coordinates)
    .map(([id, value]) => `${id}=${formatInspectionValue(value)}`)
    .join(" · ");
}

export function formatInspectionValue(value: unknown): string {
  if (typeof value === "object" && value !== null && "value" in value && "unit" in value) {
    return `${String(value.value)} ${String(value.unit)}`;
  }
  if (typeof value === "object" && value !== null && "id" in value) return String(value.id);
  if (typeof value === "string") return value;
  if (value == null || typeof value === "number" || typeof value === "boolean")
    return String(value);
  return JSON.stringify(value);
}
