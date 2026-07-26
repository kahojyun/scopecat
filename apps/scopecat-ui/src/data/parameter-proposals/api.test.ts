import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activateProposalCandidate,
  approveParameterProposal,
  getRunParameterProposals,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parameter proposal reads", () => {
  it("normalizes proposal deltas and durable approval", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          run_id: "run/a",
          items: [
            {
              proposal: {
                id: "drive-frequency",
                source_run_id: "run/a",
                analysis_record_id: "analysis-fit",
                base_config_id: "baseline",
                base_config_content_hash: "sha256:base",
                reason: "Peak moved",
                confidence: 0.92,
                proposed_at: "2026-07-23T10:00:00Z",
                deltas: [
                  {
                    parameter_id: "q0.drive.frequency",
                    before: scalarValue(5.0),
                    after: scalarValue(5.1),
                  },
                ],
              },
              approval: {
                run_id: "run/a",
                proposal_id: "drive-frequency",
                actor: "nightly-calibration",
                note: "Peak is clean",
                approved_at: "2026-07-23T10:02:00Z",
              },
            },
          ],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getRunParameterProposals("run/a");

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/runs/run%2Fa/parameter-proposals");
    expect(result).toEqual({
      runId: "run/a",
      items: [
        {
          id: "drive-frequency",
          sourceRunId: "run/a",
          analysisRecordId: "analysis-fit",
          baseConfigId: "baseline",
          baseContentHash: "sha256:base",
          reason: "Peak moved",
          confidence: 0.92,
          proposedAt: "2026-07-23T10:00:00Z",
          deltas: [
            {
              parameterId: "q0.drive.frequency",
              before: 5,
              after: 5.1,
            },
          ],
          approval: {
            actor: "nightly-calibration",
            note: "Peak is clean",
            approvedAt: "2026-07-23T10:02:00Z",
          },
        },
      ],
    });
  });
});

describe("parameter proposal commands", () => {
  it("uses the path as approval identity and records the actor", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);

    await approveParameterProposal("run/a", "proposal b", {
      reviewer: "Grace",
      note: "Evidence reviewed",
    });

    expectRequest(fetchMock, "/api/v1/runs/run%2Fa/parameter-proposals/proposal%20b/approval", {
      actor: "Grace",
      note: "Evidence reviewed",
    });
  });

  it("sends generation-checked candidate activation evidence", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);

    await activateProposalCandidate({
      runId: "run-a",
      proposalId: "drive-frequency",
      registeredBy: "Ada",
      operator: "Ada",
      expectedGeneration: 4,
      note: "Promote calibrated frequency",
    });

    expectRequest(fetchMock, "/api/v1/config-registry/candidates/activate", {
      run_id: "run-a",
      proposal_id: "drive-frequency",
      registered_by: "Ada",
      operator: "Ada",
      expected_generation: 4,
      note: "Promote calibrated frequency",
    });
  });

  it("surfaces a daemon conflict detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "active generation changed" }, 409))),
    );

    await expect(
      activateProposalCandidate({
        runId: "run-a",
        proposalId: "drive-frequency",
        registeredBy: "Ada",
        operator: "Ada",
        expectedGeneration: 4,
        note: "",
      }),
    ).rejects.toThrow("active generation changed");
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function scalarValue(value: number) {
  return {
    id: "q0.drive.frequency",
    shape: "scalar",
    value,
  };
}

function expectRequest(
  fetchMock: ReturnType<typeof vi.fn>,
  path: string,
  body: Record<string, unknown>,
) {
  const call = fetchMock.mock.calls[0];
  expect(call?.[0]).toBe(path);
  expect(call?.[1]?.method).toBe("POST");
  const headers = new Headers(call?.[1]?.headers);
  expect(headers.get("Accept")).toBe("application/json");
  expect(headers.get("Content-Type")).toBe("application/json");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(body);
}
