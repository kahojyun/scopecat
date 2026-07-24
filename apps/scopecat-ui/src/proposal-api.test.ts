import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activateProposalCandidate,
  getRunParameterProposals,
  latestProposalDecision,
  reviewParameterProposal,
} from "./proposal-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parameter proposal reads", () => {
  it("normalizes proposal deltas and durable decisions", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          run_id: "run/a",
          items: [
            {
              proposal: {
                id: "drive-frequency",
                source_run_id: "run/a",
                base_config_id: "baseline",
                base_config_content_hash: "sha256:base",
                reason: "Peak moved",
                confidence: 0.92,
                proposed_at: "2026-07-23T10:00:00Z",
                deltas: [
                  {
                    parameter_id: "q0.drive.frequency",
                    before: { value: 5.0 },
                    after: { value: 5.1 },
                  },
                ],
              },
              decisions: [
                {
                  event_id: "decision-1",
                  run_id: "run/a",
                  proposal_id: "drive-frequency",
                  decision: "approved",
                  actor: "Ada",
                  note: "Peak is clean",
                  decided_at: "2026-07-23T10:02:00Z",
                },
              ],
            },
          ],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getRunParameterProposals("run/a");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/runs/run%2Fa/parameter-proposals",
    );
    expect(result).toEqual({
      runId: "run/a",
      items: [
        {
          id: "drive-frequency",
          sourceRunId: "run/a",
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
          decisions: [
            {
              eventId: "decision-1",
              decision: "approved",
              actor: "Ada",
              note: "Peak is clean",
              decidedAt: "2026-07-23T10:02:00Z",
            },
          ],
        },
      ],
    });
    expect(latestProposalDecision(result.items[0]!)).toMatchObject({
      eventId: "decision-1",
      decision: "approved",
    });
  });
});

describe("parameter proposal commands", () => {
  it("sends the run and proposal identity with a review decision", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(jsonResponse({})),
    );
    vi.stubGlobal("fetch", fetchMock);

    await reviewParameterProposal("run/a", "proposal b", {
      decision: "rejected",
      reviewer: "Grace",
      note: "Needs another sweep",
    });

    expectRequest(
      fetchMock,
      "/api/v1/runs/run%2Fa/parameter-proposals/proposal%20b/review",
      {
        run_id: "run/a",
        proposal_id: "proposal b",
        decision: "rejected",
        reviewer: "Grace",
        note: "Needs another sweep",
      },
    );
  });

  it("sends generation-checked candidate activation evidence", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(jsonResponse({})),
    );
    vi.stubGlobal("fetch", fetchMock);

    await activateProposalCandidate({
      runId: "run-a",
      proposalIds: ["drive-frequency"],
      registeredBy: "Ada",
      operator: "Ada",
      expectedGeneration: 4,
      note: "Promote calibrated frequency",
    });

    expectRequest(fetchMock, "/api/v1/config-registry/candidates/activate", {
      run_id: "run-a",
      proposal_ids: ["drive-frequency"],
      registered_by: "Ada",
      operator: "Ada",
      expected_generation: 4,
      note: "Promote calibrated frequency",
    });
  });

  it("surfaces a daemon conflict detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({ detail: "active generation changed" }, 409),
        ),
      ),
    );

    await expect(
      activateProposalCandidate({
        runId: "run-a",
        proposalIds: ["drive-frequency"],
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

function expectRequest(
  fetchMock: ReturnType<typeof vi.fn>,
  path: string,
  body: Record<string, unknown>,
) {
  const call = fetchMock.mock.calls[0];
  expect(call?.[0]).toBe(path);
  expect(call?.[1]).toMatchObject({
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
  });
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(body);
}
