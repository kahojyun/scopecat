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
  request,
} from "./api";
import type { ContentEntry } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("project daemon reads", () => {
  it("merges every HeadersInit form without replacing caller headers", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse({ ok: true })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await request("/api/test", undefined, {
      headers: new Headers([
        ["Accept", "application/problem+json"],
        ["X-Scopecat-Test", "present"],
      ]),
    });

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("Accept")).toBe("application/problem+json");
    expect(headers.get("X-Scopecat-Test")).toBe("present");
  });

  it("uses the daemon's one project identity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            schema_version: "scopecat.daemon_health.v2",
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
              state: "terminal",
              outcome: { result: "succeeded", certainty: "known" },
              admission: {
                run_id: "run/1",
                experiment_id: "ramsey",
                execution_mode: "managed",
                config_content_hash: "sha256:config",
              },
            },
            manifest: {
              run_id: "run/1",
              lifecycle: "terminal",
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

  it("reads persisted analyses and typed run content", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = String(input);
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
                      kind: "note",
                      title: "Conclusion",
                      content: "Converged",
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
      if (path.includes("/datasets/")) {
        return Promise.resolve(
          jsonResponse({
            dataset: dataTable(),
            content: {
              schema_version: "scopecat.data_table.v0",
              rows: [{ frequency: 5.1 }],
            },
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
    const table = await getRunContent("run/1", dataTable());

    expect(analyses[0]).toMatchObject({
      id: "analysis-fit",
      title: "Fit review",
      key: "fit",
      outputs: [{ kind: "note", title: "Conclusion", content: "Converged" }],
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
    expect(table).toMatchObject({
      format: "json",
      content: { rows: [{ frequency: 5.1 }] },
    });
    expect(fetchMock.mock.calls.map(([path]) => String(path))).toEqual([
      "/api/v1/runs/run%2F1/analyses",
      "/api/v1/runs/run%2F1/artifacts/fit-notes/text?expected_kind=attachment",
      "/api/v1/runs/run%2F1/artifacts/fit-result/json?expected_kind=result",
      "/api/v1/runs/run%2F1/records/analysis-fit/json?expected_kind=analysis",
      "/api/v1/runs/run%2F1/datasets/fit-table",
    ]);
  });

  it("uses the daemon's backward run cursor and run-scoped event query", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = String(input);
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
              sequence: path.includes("before=") ? 1 : 2,
              state: "accepted",
              admission: {
                run_id: path.includes("before=") ? "run-old" : "run-new",
                experiment_id: "ramsey",
                execution_mode: "managed",
              },
            },
          ],
          previous_cursor: path.includes("before=") ? null : 2,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getRuns()).resolves.toMatchObject({
      items: [{ runId: "run-new", sequence: 2 }],
      previousCursor: 2,
    });
    await expect(getOlderRuns(2)).resolves.toMatchObject({
      items: [{ runId: "run-old", sequence: 1 }],
      previousCursor: undefined,
    });
    await expect(getRunEvents("run/1")).resolves.toMatchObject([
      { id: 12, runId: "run/1", kind: "run_state_changed" },
    ]);
    expect(fetchMock.mock.calls.map(([path]) => String(path))).toEqual([
      "/api/v1/runs?limit=100&latest=true",
      "/api/v1/runs?limit=100&before=2",
      "/api/v1/events?limit=500&latest=true&run_id=run%2F1",
    ]);
  });

  it("requests measurement pages by their returned offset", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          items: [{ run_id: "run/1", point_index: 100 }],
          next_offset: 200,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getMeasurementPreview("run/1", 100)).resolves.toEqual({
      items: [{ run_id: "run/1", point_index: 100 }],
      nextOffset: 200,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/runs/run%2F1/measurements?limit=100&offset=100",
      expect.objectContaining({ signal: undefined }),
    );
  });
});

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

function dataTable(): ContentEntry {
  return {
    id: "fit-table",
    role: "dataset",
    kind: "data_table",
    label: "Fit table",
    detail: "data_table",
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
