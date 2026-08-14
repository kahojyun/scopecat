import type { ReviewCompileCommand, ReviewSession, ReviewSessionList } from "../../api-contract";
import { apiClient, apiData } from "../../api-client";

export async function getReviews(signal?: AbortSignal): Promise<ReviewSessionList> {
  return apiData(apiClient.GET("/api/v1/reviews", { signal }));
}

export async function getReview(sessionId: string, signal?: AbortSignal): Promise<ReviewSession> {
  return apiData(
    apiClient.GET("/api/v1/reviews/{session_id}", {
      params: { path: { session_id: sessionId } },
      signal,
    }),
  );
}

export async function compileReviewPoint(
  sessionId: string,
  command: ReviewCompileCommand,
): Promise<void> {
  await apiData(
    apiClient.POST("/api/v1/reviews/{session_id}/compile", {
      params: { path: { session_id: sessionId } },
      body: command,
    }),
  );
}
