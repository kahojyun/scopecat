import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getHealth,
  getMeasurementPreview,
  getOlderRuns,
  getRun,
  getRunAnalyses,
  getRunContent,
  getRunEvents,
  getRuns,
} from "./api";
import type { MeasurementRecord } from "./api-contract";
import { requestPath } from "./test/http";
import type { ContentEntry } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("project daemon reads", () => {
  it("uses the daemon's one project identity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            status: "ok",
            project_id: "local:abc",
            project_name: "ramsey-lab",
            project_root: "/projects/ramsey-lab",
          }),
        ),
      ),
    );

    await expect(getHealth()).resolves.toMatchObject({
      status: "ok",
      projectId: "local:abc",
      projectName: "ramsey-lab",
      projectRoot: "/projects/ramsey-lab",
    });
  });

  it("normalizes current manifest contents for the run browser", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            control: {
              state: "closed",
              admission: {
                run_id: "run/1",
                plan: {
                  experiment_id: "ramsey",
                  experiment_kind: "scratch",
                  point_count: 1,
                },
              },
            },
            manifest: {
              run_id: "run/1",
              config_content_hash: "sha256:config",
              outcome: { result: "succeeded", certainty: "known" },
              contents: [
                {
                  role: "artifact",
                  id: "fit-notes",
                  kind: "attachment",
                  title: "Fit notes",
                  media_type: "text/markdown",
                  filename: "fit.md",
                  content_hash: "sha256:notes",
                },
                {
                  role: "record",
                  id: "analysis-fit",
                  kind: "analysis",
                  content_hash: "sha256:analysis",
                },
              ],
            },
            resources: [],
          }),
        ),
      ),
    );

    const run = await getRun("run/1");

    expect(run).toMatchObject({
      status: "succeeded",
      result: "succeeded",
      certainty: "known",
    });
    expect(run.contents).toEqual([
      {
        id: "fit-notes",
        role: "artifact",
        kind: "attachment",
        label: "Fit notes",
        detail: "text/markdown",
        mediaType: "text/markdown",
        filename: "fit.md",
      },
      {
        id: "analysis-fit",
        role: "record",
        kind: "analysis",
        label: "Record 2",
        detail: "analysis",
        mediaType: undefined,
        filename: undefined,
      },
    ]);
  });

  it("prioritizes scheduler attention over a terminal outcome", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            control: {
              state: "attention_required",
              attention_reason: "executor_lease_expired",
              admission: {
                run_id: "run/attention",
                plan: {
                  experiment_id: "ramsey",
                  experiment_kind: "scratch",
                  point_count: 1,
                },
              },
            },
            manifest: {
              run_id: "run/attention",
              config_content_hash: "sha256:config",
              outcome: { result: "failed", certainty: "indeterminate" },
              contents: [],
            },
            resources: [],
          }),
        ),
      ),
    );

    await expect(getRun("run/attention")).resolves.toMatchObject({
      status: "attention_required",
      attentionReason: "executor_lease_expired",
    });
  });

  it("derives nonterminal status from scheduler ownership", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            items: [runSummary("run/queued", "queued"), runSummary("run/leased", "leased")],
            next_cursor: null,
          }),
        ),
      ),
    );

    await expect(getRuns()).resolves.toMatchObject({
      items: [
        { runId: "run/leased", status: "running" },
        { runId: "run/queued", status: "accepted" },
      ],
    });
  });

  it("reads persisted analyses and typed run content", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = requestPath(input);
      if (path.endsWith("/analyses")) {
        return Promise.resolve(
          jsonResponse({
            run_id: "run/1",
            items: [
              {
                entry: { id: "analysis-fit" },
                analysis: {
                  title: "Fit review",
                  key: "fit",
                  outputs: [
                    {
                      kind: "table",
                      title: "Fit parameters",
                      content: [{ converged: true }],
                    },
                  ],
                },
              },
            ],
          }),
        );
      }
      if (path.includes("/artifacts/")) {
        if (path.includes("/json")) {
          return Promise.resolve(
            jsonResponse({
              artifact: jsonArtifact(),
              content: { converged: true },
            }),
          );
        }
        return Promise.resolve(
          jsonResponse({
            artifact: textArtifact(),
            content: "Converged\n",
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          record: {
            role: "record",
            id: "analysis-fit",
            kind: "analysis",
            content_hash: "sha256:analysis",
          },
          content: { title: "Fit review" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const analyses = await getRunAnalyses("run/1");
    const text = await getRunContent("run/1", textArtifact());
    const json = await getRunContent("run/1", jsonArtifact());
    const record = await getRunContent("run/1", {
      id: "analysis-fit",
      role: "record",
      kind: "analysis",
      label: "Fit review",
      detail: "analysis",
    });

    expect(analyses[0]).toMatchObject({
      id: "analysis-fit",
      title: "Fit review",
      key: "fit",
      outputs: [
        {
          kind: "table",
          title: "Fit parameters",
          content: [{ converged: true }],
        },
      ],
    });
    expect(text).toMatchObject({ format: "text", content: "Converged\n" });
    expect(json).toMatchObject({
      format: "json",
      content: { converged: true },
    });
    expect(record).toMatchObject({
      format: "json",
      content: { title: "Fit review" },
    });
    expect(fetchMock.mock.calls.map(([path]) => requestPath(path))).toEqual([
      "/api/v1/runs/run%2F1/analyses",
      "/api/v1/runs/run%2F1/artifacts/fit-notes/text?expected_kind=attachment",
      "/api/v1/runs/run%2F1/artifacts/fit-result/json?expected_kind=result",
      "/api/v1/runs/run%2F1/records/analysis-fit/json?expected_kind=analysis",
    ]);
  });

  it("uses the daemon's backward run cursor and run-scoped event query", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = requestPath(input);
      if (path.includes("/events?")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                event_id: 12,
                run_id: "run/1",
                kind: "run_state_changed",
                payload: { state: "running" },
              },
            ],
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          items: [
            {
              control: {
                sequence: path.includes("before=") ? 1 : 2,
                state: "queued",
                admission: {
                  run_id: path.includes("before=") ? "run-old" : "run-new",
                  plan: {
                    experiment_id: "ramsey",
                    experiment_kind: "scratch",
                    point_count: 1,
                  },
                },
              },
              manifest: {
                run_id: path.includes("before=") ? "run-old" : "run-new",
                contents: [],
              },
            },
          ],
          next_cursor: path.includes("before=") ? null : 2,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getRuns()).resolves.toMatchObject({
      items: [{ runId: "run-new", sequence: 2 }],
      nextCursor: 2,
    });
    await expect(getOlderRuns(2)).resolves.toMatchObject({
      items: [{ runId: "run-old", sequence: 1 }],
      nextCursor: undefined,
    });
    await expect(getRunEvents("run/1")).resolves.toMatchObject([
      { id: 12, runId: "run/1", kind: "run_state_changed" },
    ]);
    expect(fetchMock.mock.calls.map(([path]) => requestPath(path))).toEqual([
      "/api/v1/runs?limit=100",
      "/api/v1/runs?limit=100&before=2",
      "/api/v1/events?limit=500&latest=true&run_id=run%2F1",
    ]);
  });

  it("requests measurement pages by their returned offset", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) =>
      Promise.resolve(
        jsonResponse({
          items: [measurementRecord("run/1", 100)],
          dataset_schema: measurementSchema(),
          next_offset: 200,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getMeasurementPreview("run/1", 100)).resolves.toEqual({
      items: [measurementRecord("run/1", 100)],
      schema: measurementSchema(),
      nextOffset: 200,
    });
    expect(requestPath(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/runs/run%2F1/measurements?limit=100&offset=100",
    );
  });
});

function measurementSchema() {
  return {
    format_version: "scopecat.measurement_dataset_schema.v6" as const,
    dataset_id: "raw-measurements",
    record_schema: "scopecat.measurement_record.v4" as const,
    dimensions: [{ id: "point", kind: "point", size: 1 }],
    variables: [],
  };
}

function measurementRecord(runId: string, pointIndex: number): MeasurementRecord {
  return {
    run_id: runId,
    logical_point_id: `point-${pointIndex}`,
    point_index: pointIndex,
    coordinates: {},
    observables: {},
  };
}

function runSummary(runId: string, state: "queued" | "leased") {
  return {
    control: {
      sequence: state === "leased" ? 2 : 1,
      state,
      admission: {
        run_id: runId,
        plan: {
          experiment_id: "ramsey",
          experiment_kind: "scratch",
          point_count: 1,
        },
      },
    },
    manifest: {
      run_id: runId,
      contents: [],
    },
  };
}

function textArtifact(): ContentEntry {
  return {
    id: "fit-notes",
    role: "artifact",
    kind: "attachment",
    label: "Fit notes",
    detail: "text/markdown",
    mediaType: "text/markdown",
    filename: "fit.md",
  };
}

function jsonArtifact(): ContentEntry {
  return {
    id: "fit-result",
    role: "artifact",
    kind: "result",
    label: "Fit result",
    detail: "application/json",
    mediaType: "application/json",
    filename: "fit.json",
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
