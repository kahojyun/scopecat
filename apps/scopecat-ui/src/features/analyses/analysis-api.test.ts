import { afterEach, describe, expect, it, vi } from "vitest";
import { requestPath } from "../../test/http";
import {
  getProjectAnalysis,
  getProjectAnalysisArtifactDownload,
  getProjectAnalysisSummaries,
} from "./analysis-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("project analysis API", () => {
  it("loads bounded project publication summaries", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          items: [projectAnalysisSummary("analysis-verify", 1)],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const [analysis] = await getProjectAnalysisSummaries();

    expect(requestPath(fetchMock.mock.calls[0]![0])).toBe("/api/v1/analyses");
    expect(analysis).toMatchObject({
      id: "analysis-verify",
      key: "verify",
      revision: 1,
      publicationHash: "sha256:publication-1",
      inputCount: 1,
      outputCount: 1,
    });
  });

  it("loads exact inputs and outputs from the selected detail endpoint", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(jsonResponse(projectAnalysisView("analysis-verify", 1))),
    );
    vi.stubGlobal("fetch", fetchMock);

    const analysis = await getProjectAnalysis("analysis-verify");

    expect(requestPath(fetchMock.mock.calls[0]![0])).toBe("/api/v1/analyses/analysis-verify");
    expect(analysis?.inputs[0]).toMatchObject({
      id: "baseline",
      run_id: "run-baseline",
      role: "baseline",
    });
    expect(analysis?.outputs[0]).toMatchObject({
      id: "decision",
      kind: "fact",
      content: { value: { accepted: true } },
    });
  });

  it("downloads project-owned artifacts through the analysis namespace", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          analysis_id: "analysis-verify",
          entry: {
            role: "artifact",
            id: "analysis-verify-report",
            kind: "analysis_artifact",
            filename: "verification.md",
            media_type: "text/markdown",
            content_hash: "sha256:report",
          },
          content_base64: btoa("# Verified\n"),
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const download = await getProjectAnalysisArtifactDownload(
      "analysis-verify",
      "analysis-verify-report",
    );

    expect(requestPath(fetchMock.mock.calls[0]![0])).toBe(
      "/api/v1/analyses/analysis-verify/contents/analysis-verify-report/bytes",
    );
    expect(download.filename).toBe("verification.md");
    expect(download.blob.type).toBe("text/markdown");
    await expect(download.blob.text()).resolves.toBe("# Verified\n");
  });
});

function projectAnalysisSummary(id: string, revision: number) {
  return {
    entry: {
      role: "record",
      id,
      kind: "analysis",
      media_type: "application/json",
      content_hash: `sha256:record-${revision}`,
    },
    title: "Candidate verification",
    key: "verify",
    revision,
    publication_hash: `sha256:publication-${revision}`,
    step_id: "candidate-verification",
    input_count: 1,
    output_count: 1,
  };
}

function projectAnalysisView(id: string, revision: number) {
  const recordEntry = {
    role: "record",
    id,
    kind: "analysis",
    media_type: "application/json",
    content_hash: `sha256:record-${revision}`,
  };
  return {
    entry: recordEntry,
    contents: [recordEntry],
    analysis: {
      subject: { kind: "project" },
      title: "Candidate verification",
      key: "verify",
      revision,
      publication_hash: `sha256:publication-${revision}`,
      step_id: "candidate-verification",
      inputs: [
        {
          id: "baseline",
          run_id: "run-baseline",
          target: "datasets/raw-measurements",
          kind: "measurement_dataset",
          content_hash: "sha256:measurements",
          codec: "scopecat.measurements.arrow.v1",
          role: "baseline",
        },
      ],
      executions: [],
      outputs: [
        {
          kind: "fact",
          id: "decision",
          title: "Decision",
          content: {
            schema_id: "verification.v1",
            schema_codec: "scopecat.analysis-fact-schema.v1",
            schema_hash: "sha256:schema",
            codec: "scopecat.python-json.v1",
            value: { accepted: true },
          },
          metadata: {},
        },
      ],
    },
  };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
