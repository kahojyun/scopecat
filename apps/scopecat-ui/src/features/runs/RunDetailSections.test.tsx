// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { RunExecutionSegmentPage } from "../../api-contract";
import { ExecutionSegmentsCard } from "./RunDetailSections";

afterEach(cleanup);

describe("ExecutionSegmentsCard", () => {
  it("shows resume boundaries in execution order", () => {
    const page: RunExecutionSegmentPage = {
      items: [
        segment({
          ordinal: 1,
          segment_id: "segment-2",
          executor_id: "executor-after-restart",
          start_point_count: 12,
        }),
        segment({
          ordinal: 0,
          segment_id: "segment-1",
          executor_id: "executor-before-restart",
          start_point_count: 0,
          ended_at: "2026-08-23T03:30:00Z",
          end_point_count: 12,
          result: "interrupted",
          certainty: "known",
          reason: "executor_lease_expired",
        }),
      ],
      next_cursor: null,
    };

    render(<ExecutionSegmentsCard page={page} error={null} pending={false} />);

    const card = screen.getByTestId("execution-segments-card");
    const items = within(card).getAllByRole("listitem");
    expect(within(items[0]!).getByText("Segment 1")).toBeVisible();
    expect(within(items[0]!).getByText("0 → 12")).toBeVisible();
    expect(within(items[0]!).getByText("Interrupted")).toBeVisible();
    expect(within(items[0]!).getByText(/Executor Lease Expired/)).toBeVisible();
    expect(within(items[1]!).getByText("Segment 2")).toBeVisible();
    expect(within(items[1]!).getByText("12 → active")).toBeVisible();
    expect(within(items[1]!).getByText("Active")).toBeVisible();
  });
});

function segment(
  overrides: Partial<RunExecutionSegmentPage["items"][number]>,
): RunExecutionSegmentPage["items"][number] {
  return {
    sequence: 1,
    segment_id: "segment",
    run_id: "run-1",
    ordinal: 0,
    executor_id: "executor",
    run_contract_fingerprint: "a".repeat(64),
    started_at: "2026-08-23T03:00:00Z",
    start_point_count: 0,
    ...overrides,
  };
}
