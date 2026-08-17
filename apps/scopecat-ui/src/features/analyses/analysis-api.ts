import type {
  ProjectAnalysisPage as ProjectAnalysisPageView,
  ProjectAnalysisSummary as ProjectAnalysisSummaryView,
  ProjectAnalysisView,
} from "../../api-contract";
import { apiClient, apiData } from "../../api-client";
import type {
  ProjectAnalysis,
  ProjectAnalysisSummary,
  ProjectAnalysisSummaryPage,
} from "../../types";
import { analysisOutput } from "./analysis-model";

export async function getProjectAnalysisSummaries(
  signal?: AbortSignal,
): Promise<ProjectAnalysisSummaryPage> {
  return normalizeProjectAnalyses(
    await apiData(
      apiClient.GET("/api/v1/analyses", {
        params: { query: { limit: 100 } },
        signal,
      }),
    ),
  );
}

export async function getOlderProjectAnalysisSummaries(
  before: number,
  signal?: AbortSignal,
): Promise<ProjectAnalysisSummaryPage> {
  return normalizeProjectAnalyses(
    await apiData(
      apiClient.GET("/api/v1/analyses", {
        params: { query: { limit: 100, before } },
        signal,
      }),
    ),
  );
}

export async function getProjectAnalysis(
  selector: string,
  signal?: AbortSignal,
): Promise<ProjectAnalysis> {
  const response = await apiData(
    apiClient.GET("/api/v1/analyses/{selector}", {
      params: { path: { selector } },
      signal,
    }),
  );
  return normalizeProjectAnalysis(response);
}

export async function getProjectAnalysisArtifactDownload(
  analysisId: string,
  selector: string,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  const response = await apiData(
    apiClient.GET("/api/v1/analyses/{analysis_id}/contents/{selector}/bytes", {
      params: { path: { analysis_id: analysisId, selector } },
      signal,
    }),
  );
  const binary = atob(response.content_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return {
    blob: new Blob([bytes], {
      type: response.entry.media_type ?? "application/octet-stream",
    }),
    filename: response.entry.filename ?? selector,
  };
}

function normalizeProjectAnalyses(response: ProjectAnalysisPageView): ProjectAnalysisSummaryPage {
  return {
    items: response.items.map(normalizeProjectAnalysisSummary),
    nextCursor: response.next_cursor ?? undefined,
  };
}

function normalizeProjectAnalysisSummary(
  summary: ProjectAnalysisSummaryView,
): ProjectAnalysisSummary {
  return {
    id: summary.entry.id,
    title: summary.title,
    key: summary.key,
    stepId: summary.step_id ?? undefined,
    revision: summary.revision,
    publicationHash: summary.publication_hash,
    inputCount: summary.input_count,
    outputCount: summary.output_count,
  };
}

function normalizeProjectAnalysis(view: ProjectAnalysisView): ProjectAnalysis {
  const { analysis, entry } = view;
  return {
    id: entry.id,
    title: analysis.title,
    key: analysis.key ?? undefined,
    stepId: analysis.step_id ?? undefined,
    revision: analysis.revision,
    publicationHash: analysis.publication_hash,
    subject: "project",
    inputs: analysis.inputs ?? [],
    executions: analysis.executions ?? [],
    outputs: analysis.outputs.map(analysisOutput),
  };
}
