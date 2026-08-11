import { afterEach, describe, expect, it, vi } from "vitest";
import { getHealth } from "./project-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("project daemon reads", () => {
  it("uses the daemon's one project identity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              status: "ok",
              project_id: "local:abc",
              project_name: "ramsey-lab",
              project_root: "/projects/ramsey-lab",
            }),
            { headers: { "Content-Type": "application/json" } },
          ),
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
});
