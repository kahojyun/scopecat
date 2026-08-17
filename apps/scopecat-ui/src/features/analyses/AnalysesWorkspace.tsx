import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Atom, CircleOff, LoaderCircle } from "lucide-react";
import { errorMessage } from "../../lib/presentation";
import type { ProjectAnalysis } from "../../types";
import { classes, countBadge } from "../../ui/styles";
import { AnalysisPublicationView } from "./AnalysisPublicationView";
import {
  getProjectAnalysis,
  getProjectAnalysisArtifactDownload,
  getProjectAnalysisSummaries,
} from "./analysis-api";

export function AnalysesWorkspace({
  daemonUnavailable,
  onOpenRun,
  onSelectAnalysis,
  selectedAnalysisId,
}: {
  daemonUnavailable: boolean;
  onOpenRun: (runId: string) => void;
  onSelectAnalysis: (analysisId: string) => void;
  selectedAnalysisId?: string;
}) {
  const analyses = useQuery({
    queryKey: ["analyses", "project"],
    queryFn: ({ signal }) => getProjectAnalysisSummaries(signal),
    enabled: !daemonUnavailable,
  });
  const selectedSummary =
    analyses.data?.find((analysis) => analysis.id === selectedAnalysisId) ?? analyses.data?.at(-1);
  const selectedAnalysis = useQuery({
    queryKey: ["analyses", "project", selectedSummary?.id, "detail"],
    queryFn: ({ signal }) => getProjectAnalysis(selectedSummary!.id, signal),
    enabled: !daemonUnavailable && selectedSummary !== undefined,
  });

  useEffect(() => {
    if (selectedSummary && selectedSummary.id !== selectedAnalysisId) {
      onSelectAnalysis(selectedSummary.id);
    }
  }, [onSelectAnalysis, selectedAnalysisId, selectedSummary]);

  if (daemonUnavailable) {
    return (
      <WorkspaceMessage
        icon={<CircleOff />}
        title="Connect to the local daemon"
        detail="Project analysis publications are read directly from the daemon-owned project store."
      />
    );
  }
  if (analyses.isPending) {
    return (
      <WorkspaceMessage
        icon={<LoaderCircle className="animate-spin" />}
        title="Loading project analyses"
        detail="Reading immutable cross-run publications and their provenance."
      />
    );
  }
  if (analyses.isError) {
    return (
      <WorkspaceMessage
        icon={<CircleOff />}
        title="Project analyses unavailable"
        detail={errorMessage(analyses.error)}
      />
    );
  }
  if (!selectedSummary) {
    return (
      <WorkspaceMessage
        icon={<Atom />}
        title="No project analyses saved"
        detail="Publish a cross-run analysis from Python with lab.analyze(step)."
      />
    );
  }

  return (
    <section
      className="grid min-h-[680px] grid-cols-[285px_minmax(0,1fr)] overflow-hidden rounded-lg border border-line bg-panel max-[900px]:grid-cols-1"
      aria-labelledby="analyses-heading"
    >
      <aside className="border-r border-line bg-panel-soft p-2.5 max-[900px]:border-r-0 max-[900px]:border-b">
        <div className="flex items-center justify-between px-2 py-2">
          <h2
            className="m-0 text-[0.68rem] tracking-[0.08em] text-text-dim uppercase"
            id="analyses-heading"
          >
            Project analyses
          </h2>
          <span className={countBadge}>{analyses.data.length}</span>
        </div>
        <div className="grid gap-1.5 max-[900px]:grid-cols-[repeat(auto-fit,minmax(220px,1fr))]">
          {analyses.data.map((analysis) => (
            <button
              className={classes(
                "grid cursor-pointer gap-1 rounded-md border border-transparent bg-transparent px-2.5 py-2.5 text-left text-text-soft hover:bg-panel",
                analysis.id === selectedSummary.id && "border-line-strong bg-panel",
              )}
              key={analysis.id}
              onClick={() => onSelectAnalysis(analysis.id)}
              type="button"
              title={`Inspect analysis ${analysis.id}`}
            >
              <span className="flex items-start justify-between gap-2 text-[0.7rem] font-bold">
                <span className="line-clamp-2">{analysis.title}</span>
                <span className="flex-none rounded border border-line px-1.5 py-0.5 text-[0.55rem] text-text-dim">
                  r{analysis.revision}
                </span>
              </span>
              <span className="truncate font-mono text-[0.58rem] text-text-dim">
                {analysis.key ?? analysis.id}
              </span>
              <span className="text-[0.56rem] text-text-dim">
                {analysis.inputCount} input{analysis.inputCount === 1 ? "" : "s"} ·{" "}
                {analysis.outputCount} output{analysis.outputCount === 1 ? "" : "s"}
              </span>
            </button>
          ))}
        </div>
      </aside>

      <div className="min-w-0 p-4 max-[680px]:p-2.5">
        {selectedAnalysis.isPending ? (
          <WorkspaceMessage
            icon={<LoaderCircle className="animate-spin" />}
            title="Loading analysis detail"
            detail={`Reading ${selectedSummary.id} and its exact output provenance.`}
          />
        ) : selectedAnalysis.isError ? (
          <WorkspaceMessage
            icon={<CircleOff />}
            title="Analysis detail unavailable"
            detail={errorMessage(selectedAnalysis.error)}
          />
        ) : selectedAnalysis.data ? (
          <AnalysisDetail analysis={selectedAnalysis.data} onOpenRun={onOpenRun} />
        ) : null}
      </div>
    </section>
  );
}

function AnalysisDetail({
  analysis: selected,
  onOpenRun,
}: {
  analysis: ProjectAnalysis;
  onOpenRun: (runId: string) => void;
}) {
  return (
    <>
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-[0.58rem] font-bold tracking-[0.07em] text-text-dim uppercase">
            <span>Project analysis</span>
            <span>Revision {selected.revision}</span>
            {selected.stepId ? <span>{selected.stepId}</span> : null}
          </div>
          <h3 className="m-0 text-[1.05rem] tracking-[-0.02em]">{selected.title}</h3>
          <code className="text-[0.62rem] text-text-dim">{selected.id}</code>
        </div>
        <span className={countBadge}>{selected.outputs.length} outputs</span>
      </header>

      <dl className="mb-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 rounded-md border border-line bg-panel-soft p-3 text-[0.61rem]">
        <dt className="font-bold text-text-dim">Key</dt>
        <dd className="m-0 font-mono text-text-soft">{selected.key ?? "—"}</dd>
        <dt className="font-bold text-text-dim">Publication</dt>
        <dd className="m-0 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-text-soft">
          <span title={selected.publicationHash}>{selected.publicationHash}</span>
        </dd>
      </dl>

      <AnalysisPublicationView
        analysis={selected}
        getArtifactDownload={(selector) =>
          getProjectAnalysisArtifactDownload(selected.id, selector)
        }
        onOpenRun={onOpenRun}
      />
    </>
  );
}

function WorkspaceMessage({
  icon,
  title,
  detail,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="grid min-h-[590px] place-content-center justify-items-center text-center">
      <span
        className="mb-4 grid size-[55px] place-items-center rounded-[14px] border border-line bg-panel-soft text-text-soft [&>svg]:w-[23px]"
        aria-hidden="true"
      >
        {icon}
      </span>
      <h2 className="m-0 text-base">{title}</h2>
      <p className="mt-2 mb-0 max-w-[430px] text-[0.73rem] leading-[1.55] text-text-dim">
        {detail}
      </p>
    </div>
  );
}
