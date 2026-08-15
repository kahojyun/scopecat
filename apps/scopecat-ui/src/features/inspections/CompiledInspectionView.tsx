import { useEffect, useMemo, useState } from "react";
import type { ProgramInspectionQuery, ReviewSession } from "../../api-contract";
import { EChart, type EChartsCoreOption } from "../../ui/EChart";

type PresentedInspection = NonNullable<ReviewSession["latest_result"]>["inspections"][number];
type PresentedPoint = PresentedInspection["content"]["points"][number];
type PresentedFact = PresentedInspection["content"]["facts"][number];
type PresentedProgram = NonNullable<PresentedInspection["content"]["program"]>;
type PresentedLayer = PresentedProgram["layers"][number];
type PresentedNode = PresentedLayer["nodes"][number];

export function CompiledInspectionView({
  inspections,
  emptyTitle = "No target waveform inspection",
  onProgramQuery,
}: {
  inspections: readonly PresentedInspection[];
  emptyTitle?: string;
  onProgramQuery?: (query: ProgramInspectionQuery) => void;
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
            {inspection.content.program && (
              <ProgramInspectionView
                inspection={inspection.content.program}
                onQuery={onProgramQuery}
              />
            )}
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

function ProgramInspectionView({
  inspection,
  onQuery,
}: {
  inspection: PresentedProgram;
  onQuery?: (query: ProgramInspectionQuery) => void;
}) {
  const [layerId, setLayerId] = useState(inspection.layers.at(-1)?.id ?? "");
  const layer = inspection.layers.find((candidate) => candidate.id === layerId);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectedNode = layer?.nodes.find((node) => node.id === selectedNodeId);
  const [textFilter, setTextFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [entityFilter, setEntityFilter] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");

  useEffect(() => {
    const defaultLayer = inspection.layers.at(-1)?.id ?? "";
    setLayerId((current) =>
      inspection.layers.some((candidate) => candidate.id === current) ? current : defaultLayer,
    );
    setSelectedNodeId(null);
    const query = inspection.query;
    setTextFilter(query?.text ?? "");
    setKindFilter(query?.kind ?? "");
    setEntityFilter(query?.entity_id ?? "");
    setResourceFilter(query?.resource_id ?? "");
  }, [inspection]);

  const submitQuery = (offset = 0) => {
    if (!layer || !onQuery) return;
    onQuery({
      layer_id: layer.id,
      offset,
      limit: layer.page.limit,
      ...(textFilter.trim() && { text: textFilter.trim() }),
      ...(kindFilter.trim() && { kind: kindFilter.trim() }),
      ...(entityFilter.trim() && { entity_id: entityFilter.trim() }),
      ...(resourceFilter.trim() && { resource_id: resourceFilter.trim() }),
    });
    setSelectedNodeId(null);
  };

  return (
    <section className="overflow-hidden rounded-md border border-line bg-panel">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2.5">
        <div>
          <strong className="block text-[0.7rem]">Quantum program</strong>
          <code className="text-[0.56rem] text-text-dim">{inspection.program_id}</code>
        </div>
        <span className="text-[0.56rem] text-text-dim">{inspection.dialect_id}</span>
      </header>
      <div className="flex flex-wrap gap-1 border-b border-line bg-panel-soft p-2" role="tablist">
        {inspection.layers.map((candidate) => (
          <button
            aria-selected={candidate.id === layer?.id}
            className={`cursor-pointer rounded px-2.5 py-1.5 text-[0.6rem] font-bold ${
              candidate.id === layer?.id
                ? "bg-panel-strong text-text"
                : "bg-transparent text-text-dim hover:text-text-soft"
            }`}
            key={candidate.id}
            onClick={() => {
              setLayerId(candidate.id);
              setSelectedNodeId(null);
              setTextFilter("");
              setKindFilter("");
              setEntityFilter("");
              setResourceFilter("");
              onQuery?.({
                layer_id: candidate.id,
                offset: 0,
                limit: candidate.page.limit,
              });
            }}
            role="tab"
            type="button"
          >
            {candidate.label}
            <span className="ml-1.5 font-normal opacity-70">
              {candidate.node_count.toLocaleString()}
              {candidate.nodes_truncated ? "+" : ""}
            </span>
          </button>
        ))}
      </div>
      {layer && (
        <>
          <ProgramQueryBar
            entity={entityFilter}
            kind={kindFilter}
            onEntityChange={setEntityFilter}
            onKindChange={setKindFilter}
            onResourceChange={setResourceFilter}
            onSubmit={() => submitQuery()}
            resource={resourceFilter}
            text={textFilter}
            onTextChange={setTextFilter}
          />
          <div className="grid grid-cols-[minmax(230px,0.8fr)_minmax(300px,1.4fr)] max-[760px]:grid-cols-1">
            <ProgramNodeList
              layer={layer}
              selectedNodeId={selectedNodeId}
              onNext={
                layer.page.next_offset == null
                  ? undefined
                  : () => submitQuery(layer.page.next_offset ?? 0)
              }
              onPrevious={
                layer.page.offset === 0
                  ? undefined
                  : () => submitQuery(Math.max(0, layer.page.offset - layer.page.limit))
              }
              onSelect={setSelectedNodeId}
            />
            <div className="min-w-0 border-l border-line p-3 max-[760px]:border-t max-[760px]:border-l-0">
              {layer.facts.length > 0 && (
                <div className="mb-3">
                  <FactGrid facts={layer.facts} />
                </div>
              )}
              {layer.id === "scheduled" && <ProgramTimeline layer={layer} />}
              <ProgramNodeInspector inspection={inspection} layer={layer} node={selectedNode} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function ProgramQueryBar({
  text,
  kind,
  entity,
  resource,
  onTextChange,
  onKindChange,
  onEntityChange,
  onResourceChange,
  onSubmit,
}: {
  text: string;
  kind: string;
  entity: string;
  resource: string;
  onTextChange: (value: string) => void;
  onKindChange: (value: string) => void;
  onEntityChange: (value: string) => void;
  onResourceChange: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="grid grid-cols-[minmax(150px,1.4fr)_repeat(3,minmax(100px,0.7fr))_auto] gap-1.5 border-b border-line bg-panel-soft p-2 max-[900px]:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <input
        aria-label="Program node search"
        className="min-w-0 rounded border border-line bg-panel px-2 py-1.5 text-[0.58rem] text-text outline-none focus:border-line-strong"
        onChange={(event) => onTextChange(event.target.value)}
        placeholder="Search labels and IDs"
        type="search"
        value={text}
      />
      <input
        aria-label="Program node kind"
        className="min-w-0 rounded border border-line bg-panel px-2 py-1.5 text-[0.58rem] text-text outline-none focus:border-line-strong"
        onChange={(event) => onKindChange(event.target.value)}
        placeholder="kind"
        value={kind}
      />
      <input
        aria-label="Program entity"
        className="min-w-0 rounded border border-line bg-panel px-2 py-1.5 text-[0.58rem] text-text outline-none focus:border-line-strong"
        onChange={(event) => onEntityChange(event.target.value)}
        placeholder="entity"
        value={entity}
      />
      <input
        aria-label="Program resource"
        className="min-w-0 rounded border border-line bg-panel px-2 py-1.5 text-[0.58rem] text-text outline-none focus:border-line-strong"
        onChange={(event) => onResourceChange(event.target.value)}
        placeholder="resource"
        value={resource}
      />
      <button
        className="cursor-pointer rounded border border-line bg-panel-strong px-3 py-1.5 text-[0.58rem] font-bold text-text-soft hover:text-text max-[900px]:col-span-2"
        type="submit"
      >
        Query layer
      </button>
    </form>
  );
}

function ProgramNodeList({
  layer,
  selectedNodeId,
  onSelect,
  onPrevious,
  onNext,
}: {
  layer: PresentedLayer;
  selectedNodeId: string | null;
  onSelect: (id: string) => void;
  onPrevious?: () => void;
  onNext?: () => void;
}) {
  const nodes = new Map(layer.nodes.map((node) => [node.id, node]));
  const depth = (node: PresentedNode) => {
    let current = node.parent_id ? nodes.get(node.parent_id) : undefined;
    let value = 0;
    while (current && value < 12) {
      value += 1;
      current = current.parent_id ? nodes.get(current.parent_id) : undefined;
    }
    return value;
  };
  const pageStart = layer.page.returned_node_count === 0 ? 0 : layer.page.offset + 1;
  const pageEnd = layer.page.offset + layer.page.returned_node_count;
  return (
    <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto]">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2 text-[0.54rem] text-text-dim">
        <span>
          {layer.page.matching_node_count.toLocaleString()} matching ·{" "}
          {layer.node_count.toLocaleString()} total
        </span>
        <span>
          {pageStart.toLocaleString()}–{pageEnd.toLocaleString()}
        </span>
      </div>
      <div className="max-h-[390px] overflow-auto p-2" aria-label={`${layer.label} nodes`}>
        {layer.nodes.map((node) => (
          <button
            aria-pressed={selectedNodeId === node.id}
            className={`flex w-full cursor-pointer items-center gap-2 rounded border-0 px-2 py-1.5 text-left ${
              selectedNodeId === node.id
                ? "bg-panel-strong text-text"
                : "bg-transparent text-text-soft hover:bg-panel-soft"
            }`}
            key={node.id}
            onClick={() => onSelect(node.id)}
            style={{ paddingLeft: `${8 + depth(node) * 13}px` }}
            type="button"
          >
            <span className="w-16 shrink-0 truncate font-mono text-[0.49rem] text-text-dim">
              {node.kind}
            </span>
            <span className="min-w-0 flex-1 truncate text-[0.61rem] font-semibold">
              {node.label}
            </span>
            {node.child_count > 0 && (
              <span className="text-[0.52rem] text-text-dim">{node.child_count}</span>
            )}
          </button>
        ))}
        {layer.nodes.length === 0 && (
          <div className="p-4 text-center text-[0.56rem] text-text-dim">
            No nodes match this layer query.
          </div>
        )}
      </div>
      {(onPrevious || onNext) && (
        <div className="flex items-center justify-between gap-2 border-t border-line p-2">
          <button
            className="cursor-pointer rounded border border-line bg-panel-soft px-2.5 py-1.5 text-[0.56rem] font-bold text-text-dim disabled:cursor-default disabled:opacity-35"
            disabled={!onPrevious}
            onClick={onPrevious}
            type="button"
          >
            Previous
          </button>
          <span className="text-[0.53rem] text-text-dim">
            Server-paged · {layer.page.limit.toLocaleString()} per page
          </span>
          <button
            className="cursor-pointer rounded border border-line bg-panel-soft px-2.5 py-1.5 text-[0.56rem] font-bold text-text-dim disabled:cursor-default disabled:opacity-35"
            disabled={!onNext}
            onClick={onNext}
            type="button"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function ProgramTimeline({ layer }: { layer: PresentedLayer }) {
  const events = layer.nodes.filter(
    (node) => node.start_seconds != null && node.duration_seconds != null,
  );
  const duration = Math.max(
    ...events.map((node) => Number(node.start_seconds) + Number(node.duration_seconds)),
    0,
  );
  const lanes = Array.from(new Set(events.flatMap((node) => node.entity_ids))).slice(0, 16);
  if (events.length === 0 || duration <= 0) return null;
  return (
    <div className="mb-3 rounded border border-line bg-panel-soft p-2.5">
      <div className="mb-2 flex items-center justify-between text-[0.56rem] text-text-dim">
        <strong className="text-text-soft">Timeline</strong>
        <span>{duration.toExponential(3)} s</span>
      </div>
      <div className="grid gap-1">
        {lanes.map((lane) => (
          <div className="grid grid-cols-[70px_minmax(0,1fr)] items-center gap-2" key={lane}>
            <span className="truncate font-mono text-[0.52rem] text-text-dim">{lane}</span>
            <div className="relative h-4 overflow-hidden rounded bg-panel">
              {events
                .filter((event) => event.entity_ids.includes(lane))
                .map((event) => (
                  <span
                    className="absolute top-0.5 h-3 min-w-[2px] rounded bg-accent/70"
                    key={event.id}
                    style={{
                      left: `${(Number(event.start_seconds) / duration) * 100}%`,
                      width: `${Math.max((Number(event.duration_seconds) / duration) * 100, 0.25)}%`,
                    }}
                    title={event.label}
                  />
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProgramNodeInspector({
  inspection,
  layer,
  node,
}: {
  inspection: PresentedProgram;
  layer: PresentedLayer;
  node: PresentedNode | undefined;
}) {
  if (!node) {
    return (
      <div className="rounded border border-dashed border-line p-4 text-center text-[0.6rem] text-text-dim">
        Select a node to inspect its entities, results, timing, and lowering lineage.
      </div>
    );
  }
  const incoming = inspection.links.filter(
    (link) => link.target_layer_id === layer.id && link.target_node_id === node.id,
  );
  const outgoing = inspection.links.filter(
    (link) => link.source_layer_id === layer.id && link.source_node_id === node.id,
  );
  const loadedNodes = new Map(layer.nodes.map((candidate) => [candidate.id, candidate]));
  const ancestors: PresentedNode[] = [];
  let parent = node.parent_id ? loadedNodes.get(node.parent_id) : undefined;
  while (parent && ancestors.length < 8) {
    ancestors.unshift(parent);
    parent = parent.parent_id ? loadedNodes.get(parent.parent_id) : undefined;
  }
  return (
    <div className="grid gap-2.5">
      <div>
        {ancestors.length > 0 && (
          <div className="mb-1 truncate text-[0.51rem] text-text-dim">
            {ancestors.map((ancestor) => ancestor.label).join(" / ")}
          </div>
        )}
        <span className="text-[0.53rem] font-bold tracking-[0.06em] text-text-dim uppercase">
          {node.kind}
        </span>
        <strong className="mt-1 block text-[0.68rem]">{node.label}</strong>
        <code className="mt-1 block truncate text-[0.52rem] text-text-dim">{node.id}</code>
      </div>
      {node.facts.length > 0 && <FactGrid facts={node.facts} />}
      <div className="flex flex-wrap gap-1.5">
        <ReferenceChips ids={node.entity_ids} label="entity" total={node.entity_count} />
        <ReferenceChips ids={node.resource_ids} label="resource" total={node.resource_count} />
        <ReferenceChips ids={node.result_ids} label="result" total={node.result_count} />
      </div>
      {(node.start_seconds != null || node.duration_seconds != null) && (
        <div className="text-[0.57rem] text-text-dim">
          start {node.start_seconds ?? "—"} s · duration {node.duration_seconds ?? "—"} s
        </div>
      )}
      {(incoming.length > 0 || outgoing.length > 0) && (
        <div className="grid gap-1 rounded border border-line bg-panel-soft p-2 text-[0.54rem] text-text-dim">
          <strong className="text-text-soft">Lowering lineage</strong>
          {[...incoming, ...outgoing].slice(0, 6).map((link) => {
            const isIncoming = link.target_layer_id === layer.id;
            return (
              <div
                className="grid grid-cols-[auto_minmax(0,1fr)] gap-1.5"
                key={`${link.source_layer_id}:${link.source_node_id}:${link.target_layer_id}:${link.target_node_id}`}
              >
                <span>{isIncoming ? "from" : "to"}</span>
                <code className="truncate">
                  {isIncoming
                    ? `${link.source_layer_id} / ${link.source_node_id}`
                    : `${link.target_layer_id} / ${link.target_node_id}`}{" "}
                  ({link.relation})
                </code>
              </div>
            );
          })}
          {incoming.length + outgoing.length > 6 && (
            <span>+{incoming.length + outgoing.length - 6} more links</span>
          )}
        </div>
      )}
    </div>
  );
}

function ReferenceChips({
  ids,
  label,
  total,
}: {
  ids: string[];
  label: "entity" | "resource" | "result";
  total: number;
}) {
  const visible = ids.slice(0, 12);
  return (
    <>
      {visible.map((id) => (
        <span className="rounded bg-panel-strong px-2 py-1 text-[0.55rem]" key={`${label}:${id}`}>
          {label} {id}
        </span>
      ))}
      {total > visible.length && (
        <span className="rounded border border-line px-2 py-1 text-[0.55rem] text-text-dim">
          +{(total - visible.length).toLocaleString()} {label}s
        </span>
      )}
    </>
  );
}

function PointInspection({ point }: { point: PresentedPoint }) {
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

function FactGrid({ facts }: { facts: PresentedFact[] }) {
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

function waveformChartOption(point: PresentedPoint): EChartsCoreOption {
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
