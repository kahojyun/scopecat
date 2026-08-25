import { afterEach, describe, expect, it, vi } from "vitest";
import { requestPath } from "../../test/http";
import { getSampleAnalyses, getSampleRuns, getSamples } from "./sample-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sample daemon reads", () => {
  it("loads the bounded sample registry", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(jsonResponse({ items: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getSamples();

    expect(requestPath(fetchMock.mock.calls[0]![0])).toBe("/api/v1/samples?limit=500");
  });

  it("filters run history by stable sample identity", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(jsonResponse({ items: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getSampleRuns("chip/a17");

    expect(requestPath(fetchMock.mock.calls[0]![0])).toBe(
      "/api/v1/runs?limit=100&sample_id=chip%2Fa17",
    );
  });

  it("loads sample-scoped analysis summaries", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(jsonResponse({ sample_id: "chip/a17", items: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getSampleAnalyses("chip/a17");

    expect(requestPath(fetchMock.mock.calls[0]![0])).toBe(
      "/api/v1/samples/chip%2Fa17/analyses?limit=100",
    );
  });
});

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
