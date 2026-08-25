import type {
  SampleAnalysisPage,
  SampleAnalysisView,
  SamplePage,
  SampleView,
} from "../../api-contract";
import { apiClient, apiData } from "../../api-client";
import type { ProjectRunPage } from "../../types";
import { getRuns } from "../runs/run-api";

export async function getSamples(signal?: AbortSignal): Promise<SamplePage> {
  return apiData(
    apiClient.GET("/api/v1/samples", {
      params: { query: { limit: 500 } },
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

export async function getSampleRuns(
  sampleId: string,
  signal?: AbortSignal,
): Promise<ProjectRunPage> {
  return getRuns(signal, sampleId);
}

export async function getSampleAnalyses(
  sampleId: string,
  signal?: AbortSignal,
): Promise<SampleAnalysisPage> {
  return apiData(
    apiClient.GET("/api/v1/samples/{sample_id}/analyses", {
      params: {
        path: { sample_id: sampleId },
        query: { limit: 100 },
      },
      signal,
    }),
  );
}

export async function getSampleAnalysis(
  sampleId: string,
  selector: string,
  signal?: AbortSignal,
): Promise<SampleAnalysisView> {
  return apiData(
    apiClient.GET("/api/v1/samples/{sample_id}/analyses/{selector}", {
      params: { path: { sample_id: sampleId, selector } },
      signal,
    }),
  );
}
