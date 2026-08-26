import type {
  SampleAnalysisPage,
  SamplePage,
  SampleRevision,
  SampleRevisionPage,
  SampleView,
} from "../../api-contract";
import { apiClient, apiData } from "../../api-client";
import type { AnalysisPublication, ProjectRunPage } from "../../types";
import { analysisOutput } from "../analyses/analysis-model";
import { getOlderRuns, getRuns } from "../runs/run-api";

export async function getSamples(before?: number, signal?: AbortSignal): Promise<SamplePage> {
  return apiData(
    apiClient.GET("/api/v1/samples", {
      params: { query: { limit: 100, before } },
      signal,
    }),
  );
}

export async function getSample(sampleId: string, signal?: AbortSignal): Promise<SampleView> {
  return apiData(
    apiClient.GET("/api/v1/samples/{sample_id}", {
      params: { path: { sample_id: sampleId } },
      signal,
    }),
  );
}

export async function getSampleRevisions(
  sampleId: string,
  before?: number,
  signal?: AbortSignal,
): Promise<SampleRevisionPage> {
  return apiData(
    apiClient.GET("/api/v1/samples/{sample_id}/revisions", {
      params: { path: { sample_id: sampleId }, query: { limit: 100, before } },
      signal,
    }),
  );
}

export async function getSampleRevision(
  sampleId: string,
  revision: number,
  signal?: AbortSignal,
): Promise<SampleRevision> {
  return apiData(
    apiClient.GET("/api/v1/samples/{sample_id}/revisions/{revision}", {
      params: { path: { sample_id: sampleId, revision } },
      signal,
    }),
  );
}

export async function getSampleRuns(
  sampleId: string,
  before?: number,
  signal?: AbortSignal,
): Promise<ProjectRunPage> {
  return before === undefined ? getRuns(signal, sampleId) : getOlderRuns(before, signal, sampleId);
}

export async function getSampleAnalyses(
  sampleId: string,
  before?: number,
  signal?: AbortSignal,
): Promise<SampleAnalysisPage> {
  return apiData(
    apiClient.GET("/api/v1/samples/{sample_id}/analyses", {
      params: {
        path: { sample_id: sampleId },
        query: { limit: 100, before },
      },
      signal,
    }),
  );
}

export async function getSampleAnalysis(
  sampleId: string,
  selector: string,
  signal?: AbortSignal,
): Promise<AnalysisPublication> {
  const view = await apiData(
    apiClient.GET("/api/v1/samples/{sample_id}/analyses/{selector}", {
      params: { path: { sample_id: sampleId, selector } },
      signal,
    }),
  );
  return {
    id: view.entry.id,
    title: view.analysis.title,
    key: view.analysis.key ?? undefined,
    stepId: view.analysis.step_id ?? undefined,
    revision: view.analysis.revision,
    publicationHash: view.analysis.publication_hash,
    publishedAt: view.published_at,
    subject: "sample",
    inputs: view.analysis.inputs ?? [],
    executions: view.analysis.executions ?? [],
    outputs: view.analysis.outputs.map(analysisOutput),
  } satisfies AnalysisPublication;
}

export async function getSampleAnalysisArtifactDownload(
  sampleId: string,
  analysisId: string,
  selector: string,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  const response = await apiData(
    apiClient.GET("/api/v1/samples/{sample_id}/analyses/{analysis_id}/contents/{selector}/bytes", {
      params: {
        path: {
          sample_id: sampleId,
          analysis_id: analysisId,
          selector,
        },
      },
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
