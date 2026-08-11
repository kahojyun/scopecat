import { afterEach, describe, expect, it, vi } from "vitest";
import { requestHeaders, requestJson, requestMethod, requestPath } from "../../test/http";
import { acceptProposal, getRunParameterProposals } from "./api";

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
                evidence_output_ids: ["selected-fit", "fit-quality"],
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

    expect(requestPath(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/runs/run%2Fa/parameter-proposals",
    );
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
          evidenceOutputIds: ["selected-fit", "fit-quality"],
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
  it("accepts and publishes a proposal in one generation-checked request", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);

    await acceptProposal({
      runId: "run-a",
      proposalId: "drive-frequency",
      actor: "Ada",
      expectedGeneration: 4,
      note: "Promote calibrated frequency",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await expectRequest(fetchMock, "/api/v1/config-registry/default", {
      source: {
        kind: "candidate_config",
        run_id: "run-a",
        proposal_id: "drive-frequency",
      },
      actor: "Ada",
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
      acceptProposal({
        runId: "run-a",
        proposalId: "drive-frequency",
        actor: "Ada",
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

async function expectRequest(
  fetchMock: ReturnType<typeof vi.fn>,
  path: string,
  body: Record<string, unknown>,
) {
  const call = fetchMock.mock.calls[0];
  expect(requestPath(call?.[0])).toBe(path);
  expect(requestMethod(call?.[0], call?.[1])).toBe("POST");
  const headers = requestHeaders(call?.[0], call?.[1]);
  expect(headers.get("Accept")).toBe("application/json");
  expect(headers.get("Content-Type")).toBe("application/json");
  await expect(requestJson(call?.[0], call?.[1])).resolves.toEqual(body);
}
