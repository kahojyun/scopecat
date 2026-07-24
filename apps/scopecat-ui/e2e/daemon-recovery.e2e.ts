import { spawnSync, type SpawnSyncReturns } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  expect,
  test as base,
  type Page,
} from "@playwright/test";

interface DaemonEndpointRecord {
  base_url: string;
}

interface ProjectDaemon {
  baseUrl: string;
}

interface ActiveConfigView {
  config: Record<string, unknown>;
}

interface RunAdmission {
  run_id: string;
}

interface RunDetail {
  control: {
    state: string;
    attention_reason?: string | null;
    outcome?: {
      problems?: Array<{ code?: string }>;
    } | null;
  };
  manifest: Record<string, unknown> & {
    lifecycle: string;
  };
  resources: Array<{
    resource: { id: string; kind: string };
    status: string;
  }>;
}

interface AttentionResolutionReceipt {
  state: string;
  released_resource_count: number;
}

interface EventPage {
  items: Array<{
    kind: string;
    payload: Record<string, unknown>;
  }>;
}

interface AbandonedRun {
  experimentId: string;
  resourceId: string;
  runId: string;
}

interface HttpResponse {
  json(): Promise<unknown>;
  ok(): boolean;
  status(): number;
  text(): Promise<string>;
  url(): string;
}

const UI_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(UI_ROOT, "../..");

const test = base.extend<{}, { daemon: ProjectDaemon }>({
  daemon: [
    async ({}, use) => {
      const projectRoot = await mkdtemp(
        join(tmpdir(), "scopecat-ui-recovery-e2e-"),
      );
      let initialized = false;
      try {
        runUv(["scopecat", "init", projectRoot], REPOSITORY_ROOT);
        initialized = true;
        runUv(
          ["scopecat", "start", projectRoot, "--port", "0"],
          projectRoot,
        );
        const endpoint = await readEndpoint(projectRoot);
        await use({ baseUrl: endpoint.base_url });
      } finally {
        if (initialized) {
          await stopAndRemoveProject(projectRoot);
        } else {
          await rm(projectRoot, { recursive: true, force: true });
        }
      }
    },
    { scope: "worker", timeout: 120_000 },
  ],
});

test("recovers naturally expired delegated executors from the GUI", async ({
  daemon,
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto(daemon.baseUrl);

  const active = await checkedJson<ActiveConfigView>(
    await page.request.get(
      `${daemon.baseUrl}/api/v1/config-registry/active`,
    ),
    "GET",
  );
  const releaseRun = await startAbandonedRun(
    page,
    daemon.baseUrl,
    active.config,
    "release-requeue",
  );
  const abortRun = await startAbandonedRun(
    page,
    daemon.baseUrl,
    active.config,
    "abort",
  );

  await expect(page.getByTitle(`Inspect run ${releaseRun.runId}`)).toContainText(
    "Running",
  );
  await expect(page.getByTitle(`Inspect run ${abortRun.runId}`)).toContainText(
    "Running",
  );
  await assertResourceStatus(page, releaseRun, "Active");
  await assertResourceStatus(page, abortRun, "Active");

  await expect
    .poll(
      async () => {
        const [releaseDetail, abortDetail] = await Promise.all([
          getRunDetail(page, daemon.baseUrl, releaseRun.runId),
          getRunDetail(page, daemon.baseUrl, abortRun.runId),
        ]);
        return [
          releaseDetail.control.state,
          abortDetail.control.state,
        ];
      },
      {
        message: "both abandoned executor leases should expire",
        timeout: 45_000,
        intervals: [1_000],
      },
    )
    .toEqual(["attention_required", "attention_required"]);

  await selectAttentionRun(page, releaseRun);
  await assertResourceStatus(page, releaseRun, "Quarantined");
  const releaseReceipt = await resolveAttention(
    page,
    releaseRun.runId,
    "Release resources",
  );
  expect(releaseReceipt).toMatchObject({
    state: "attention_required",
    released_resource_count: 1,
  });
  await expect(page.getByRole("alert")).toContainText(
    "executor_lease_expired",
  );
  await assertSelectedResourceStatus(page, releaseRun.resourceId, "Required");

  const requeueReceipt = await resolveAttention(
    page,
    releaseRun.runId,
    "Requeue",
  );
  expect(requeueReceipt).toMatchObject({
    state: "accepted",
    released_resource_count: 0,
  });
  await expect(page.locator(".detail-header .status-pill")).toHaveText(
    "Accepted",
  );
  await expect(page.getByRole("alert")).toHaveCount(0);
  await assertSelectedResourceStatus(page, releaseRun.resourceId, "Required");

  const requeued = await getRunDetail(
    page,
    daemon.baseUrl,
    releaseRun.runId,
  );
  expect(requeued.control.state).toBe("accepted");
  expect(requeued.manifest.lifecycle).toBe("accepted");
  expect(requeued.resources[0]?.status).toBe("required");
  await expectExpiredLeaseEvents(page, daemon.baseUrl, releaseRun.runId);

  await selectAttentionRun(page, abortRun);
  await assertResourceStatus(page, abortRun, "Quarantined");
  const abortReceipt = await resolveAttention(
    page,
    abortRun.runId,
    "Abort run",
  );
  expect(abortReceipt).toMatchObject({
    state: "terminal",
    released_resource_count: 1,
  });
  await expect(page.locator(".detail-header .status-pill")).toHaveText(
    "Failed",
  );
  await expect(page.getByRole("alert")).toHaveCount(0);
  await assertSelectedResourceStatus(page, abortRun.resourceId, "Released");

  const aborted = await getRunDetail(page, daemon.baseUrl, abortRun.runId);
  expect(aborted.control.state).toBe("terminal");
  expect(aborted.manifest.lifecycle).toBe("terminal");
  expect(aborted.control.outcome?.problems?.[0]?.code).toBe(
    "daemon.operator_aborted",
  );
  expect(aborted.resources[0]?.status).toBe("released");
  await expectExpiredLeaseEvents(page, daemon.baseUrl, abortRun.runId);
});

async function startAbandonedRun(
  page: Page,
  baseUrl: string,
  config: Record<string, unknown>,
  suffix: string,
): Promise<AbandonedRun> {
  const experimentId = `scopecat.e2e.${suffix}`;
  const resourceId = `scope-${suffix}`;
  const executorId = `e2e-${suffix}`;
  const admission = await checkedJson<RunAdmission>(
    await page.request.post(`${baseUrl}/api/v1/runs`, {
      data: {
        execution_mode: "delegated",
        submission_id: `e2e-${suffix}`,
        executor_id: executorId,
        config,
        request: {
          id: `e2e-${suffix}`,
        },
        plan: {
          experiment_id: experimentId,
          experiment_kind: "scratch",
          point_count: 1,
          run_resource_claims: [
            {
              id: resourceId,
              kind: "instrument",
            },
          ],
        },
      },
    }),
    "POST",
  );
  const accepted = await getRunDetail(page, baseUrl, admission.run_id);
  await expectResponseOk(
    await page.request.post(
      `${baseUrl}/api/v1/runs/${encodeURIComponent(admission.run_id)}` +
        "/executor/start",
      {
        data: {
          run_id: admission.run_id,
          executor_id: executorId,
          manifest: {
            ...accepted.manifest,
            lifecycle: "running",
          },
        },
      },
    ),
    "POST",
  );
  return { experimentId, resourceId, runId: admission.run_id };
}

async function selectAttentionRun(
  page: Page,
  run: AbandonedRun,
): Promise<void> {
  await page.getByTitle(`Inspect run ${run.runId}`).click();
  await expect(
    page.locator(".detail-header").getByRole("heading", {
      name: run.experimentId,
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".detail-header .status-pill")).toHaveText(
    "Needs attention",
  );
  await expect(page.getByRole("alert")).toContainText(
    "Operator attention required",
  );
  await expect(page.getByRole("alert")).toContainText(
    "executor_lease_expired",
  );
}

async function assertResourceStatus(
  page: Page,
  run: AbandonedRun,
  status: string,
): Promise<void> {
  await page.getByTitle(`Inspect run ${run.runId}`).click();
  await assertSelectedResourceStatus(page, run.resourceId, status);
}

async function assertSelectedResourceStatus(
  page: Page,
  resourceId: string,
  status: string,
): Promise<void> {
  const resource = page
    .locator(".resource-card li")
    .filter({ hasText: resourceId });
  await expect(resource).toContainText(status);
}

async function resolveAttention(
  page: Page,
  runId: string,
  buttonName: string,
): Promise<AttentionResolutionReceipt> {
  page.once("dialog", (dialog) => dialog.accept());
  const response = page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "POST" &&
      new URL(candidate.url()).pathname ===
        `/api/v1/runs/${encodeURIComponent(runId)}/attention`,
  );
  await page.getByRole("button", { name: buttonName, exact: true }).click();
  return checkedJson<AttentionResolutionReceipt>(await response, "POST");
}

async function getRunDetail(
  page: Page,
  baseUrl: string,
  runId: string,
): Promise<RunDetail> {
  return checkedJson<RunDetail>(
    await page.request.get(
      `${baseUrl}/api/v1/runs/${encodeURIComponent(runId)}`,
    ),
    "GET",
  );
}

async function expectExpiredLeaseEvents(
  page: Page,
  baseUrl: string,
  runId: string,
): Promise<void> {
  const events = await checkedJson<EventPage>(
    await page.request.get(`${baseUrl}/api/v1/events`, {
      params: {
        limit: 100,
        latest: "true",
        run_id: runId,
      },
    }),
    "GET",
  );
  const kinds = events.items.map((event) => event.kind);
  expect(kinds).toContain("resources_quarantined");
  expect(kinds).toContain("resources_released");
  const lost = events.items.find(
    (event) => event.kind === "executor_lease_lost",
  );
  expect(lost?.payload.reason).toBe("executor_lease_expired");
}

async function checkedJson<T>(
  response: HttpResponse,
  method: string,
): Promise<T> {
  await expectResponseOk(response, method);
  return (await response.json()) as T;
}

async function expectResponseOk(
  response: HttpResponse,
  method: string,
): Promise<void> {
  if (!response.ok()) {
    throw new Error(
      `${method} ${response.url()} returned ` +
        `${response.status()}: ${await response.text()}`,
    );
  }
}

async function readEndpoint(
  projectRoot: string,
): Promise<DaemonEndpointRecord> {
  const source = await readFile(
    join(projectRoot, ".scopecat/daemon.json"),
    "utf8",
  );
  const record = JSON.parse(source) as Partial<DaemonEndpointRecord>;
  if (
    typeof record.base_url !== "string" ||
    new URL(record.base_url).port === "0"
  ) {
    throw new Error(`Invalid daemon endpoint record: ${source}`);
  }
  return record as DaemonEndpointRecord;
}

function runUv(
  arguments_: string[],
  cwd: string,
  allowFailure = false,
): SpawnSyncReturns<string> {
  const environment = { ...process.env };
  delete environment.SCOPECAT_DAEMON_URL;
  const result = spawnSync(
    "uv",
    ["run", "--locked", "--project", REPOSITORY_ROOT, ...arguments_],
    {
      cwd,
      encoding: "utf8",
      env: environment,
      timeout: 30_000,
    },
  );
  if (!allowFailure && (result.error || result.status !== 0)) {
    throw new Error(
      [
        `uv ${arguments_.join(" ")} failed with status ${result.status}`,
        result.error?.message,
        result.stdout,
        result.stderr,
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  return result;
}

async function stopAndRemoveProject(projectRoot: string): Promise<void> {
  const stopped = runUv(
    ["scopecat", "stop", projectRoot],
    projectRoot,
    true,
  );
  if (stopped.error || stopped.status !== 0) {
    const daemonLog = await readFile(
      join(projectRoot, ".scopecat/daemon.log"),
      "utf8",
    ).catch(() => "");
    throw new Error(
      [
        `Could not stop test daemon; project retained at ${projectRoot}`,
        stopped.error?.message,
        stopped.stdout,
        stopped.stderr,
        daemonLog && `Daemon log:\n${daemonLog}`,
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  await rm(projectRoot, { recursive: true, force: true });
}
