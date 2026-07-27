import { spawn, spawnSync, type ChildProcess, type SpawnSyncReturns } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test as base, type Page } from "@playwright/test";

interface DaemonEndpointRecord {
  base_url: string;
}

interface ProjectDaemon {
  baseUrl: string;
  projectRoot: string;
}

interface ConfigRegistryView {
  activation: {
    entry_id: string;
    generation: number;
  };
}

interface ConfigActivationHistoryView {
  items: unknown[];
}

interface ProcessCompletion {
  code: number | null;
  signal: NodeJS.Signals | null;
  stdout: string;
  stderr: string;
}

interface ControlledExperiment {
  acceptedReady: string;
  releaseAccepted: string;
  runningReady: string;
  releaseRunning: string;
  measurementReady: string;
  releaseMeasurement: string;
  child: ChildProcess;
  completion: Promise<ProcessCompletion>;
}

interface CandidateAnalysis {
  runId: string;
  proposalId: string;
  analysisId: string;
}

const UI_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(UI_ROOT, "../..");
const UI_DIST = resolve(UI_ROOT, "dist");
const LIVE_EXPERIMENT_ID = "quantum_lab_demo.workflows.readout_frequency";
const CONTROLLED_EXPERIMENT_SOURCE = `\
"""Exercise durable run states while a browser observes the daemon."""

from __future__ import annotations

import time
from pathlib import Path

import scopecat as sc
from quantum_lab_demo import quantum_lab_bootstrap_config, quantum_lab_system
from quantum_lab_demo.workflows.readout_frequency import (
    readout_frequency_template,
)

PROJECT_ROOT = Path(__file__).resolve().parent
CONTROL_ROOT = PROJECT_ROOT / ".scopecat"
ACCEPTED_READY = CONTROL_ROOT / "e2e-accepted-ready"
RELEASE_ACCEPTED = CONTROL_ROOT / "e2e-release-accepted"
RUNNING_READY = CONTROL_ROOT / "e2e-running-ready"
RELEASE_RUNNING = CONTROL_ROOT / "e2e-release-running"
MEASUREMENT_READY = CONTROL_ROOT / "e2e-measurement-ready"
RELEASE_MEASUREMENT = CONTROL_ROOT / "e2e-release-measurement"


def wait_for_release(path: Path) -> None:
    deadline = time.monotonic() + 45
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {path.name}")
        time.sleep(0.02)


config = quantum_lab_bootstrap_config()


def build_system(selected):
    return quantum_lab_system(config=selected)


project = sc.open_project(PROJECT_ROOT)
with project.connect(build_system=build_system) as lab:
    client = lab._client
    original_submit = client.submit_run
    original_start = client.start_executor
    original_append = client.append_measurements
    prepared = lab.prepare(
        readout_frequency_template(qubit="q0"),
        config=config,
    )

    def gated_submit(submission):
        admission = original_submit(submission)
        ACCEPTED_READY.write_text(admission.run_id, encoding="utf-8")
        wait_for_release(RELEASE_ACCEPTED)
        return admission

    def gated_start(run_id, request):
        lease = original_start(run_id, request)
        RUNNING_READY.write_text(run_id, encoding="utf-8")
        wait_for_release(RELEASE_RUNNING)
        return lease

    append_count = [0]

    def gated_append(run_id, command):
        receipt = original_append(run_id, command)
        append_count[0] += 1
        if append_count[0] == 1:
            MEASUREMENT_READY.write_text(run_id, encoding="utf-8")
            wait_for_release(RELEASE_MEASUREMENT)
        return receipt

    client.submit_run = gated_submit
    client.start_executor = gated_start
    client.append_measurements = gated_append
    try:
        run = prepared.run(name="Live state browser E2E")
    finally:
        client.submit_run = original_submit
        client.start_executor = original_start
        client.append_measurements = original_append
    summary = {"run_id": run.id, "status": run.manifest.status}

print(summary)
`;

const CANDIDATE_ANALYSIS_SOURCE = `\
"""Create one durable notebook analysis for GUI acceptance."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import scopecat as sc

project_root = Path(sys.argv[1])
with sc.open_project(project_root).connect() as lab:
    baseline = lab.runs()[0]
    analysis = baseline.analysis("notebook repetition fit").propose(
        "repetitions-fit",
        sc.replace_scalar_parameter("repetitions", 384),
        reason="stable high-confidence notebook fit",
        confidence=0.98,
    )
    saved = analysis.save()
    analysis.candidate_config()

print(
    "E2E_CANDIDATE="
    + json.dumps(
        {
            "run_id": baseline.id,
            "proposal_id": analysis.parameter_proposals[0].id,
            "analysis_id": saved.record.id,
        }
    )
)
`;

const test = base.extend<{}, { daemon: ProjectDaemon }>({
  daemon: [
    async ({}, use) => {
      const projectRoot = await mkdtemp(join(tmpdir(), "scopecat-ui-e2e-"));
      let initialized = false;
      try {
        runUv(["scopecat", "init", projectRoot], REPOSITORY_ROOT);
        initialized = true;
        runUv(
          ["scopecat", "start", projectRoot, "--port", "0", "--static-dir", UI_DIST],
          projectRoot,
        );
        const endpoint = await readEndpoint(projectRoot);
        const firstRun = runUv(
          ["python", join(projectRoot, "notebooks/01_first_run.py")],
          projectRoot,
        );
        expect(firstRun.stdout).toContain("'status': 'completed'");

        await use({
          baseUrl: endpoint.base_url,
          projectRoot,
        });
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

test("starter project closes the notebook, run, and config loop", async ({ daemon, page }) => {
  await page.goto(daemon.baseUrl);

  await expect(
    page.getByRole("heading", {
      name: "scopecat_lab.first_run",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("Succeeded", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Configuration" }).click();
  await expect(page.getByRole("heading", { name: "Default configuration" })).toBeVisible();

  const initialRegistry = await readRegistry(page, daemon.baseUrl);
  const initialHistory = await readActivationHistory(page, daemon.baseUrl);
  const initialEntryId = initialRegistry.activation.entry_id;
  await expect(page.getByTestId("active-config-entry")).toHaveText(initialEntryId);
  await expect(page.getByRole("button", { name: "Undo" })).toBeDisabled();

  await page.getByRole("button", { name: "Edit parameters" }).click();
  const repetitions = page.getByRole("spinbutton", { name: "repetitions" });
  await expect(repetitions).toHaveValue("128");
  await repetitions.fill("256");

  const setDefaultResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/config-registry/drafts/set-default"),
  );
  await page.getByRole("button", { name: "Set as default" }).click();
  await expectResponseOk(await setDefaultResponse, "POST");

  await expect(page.getByText("Runtime-derived default")).toBeVisible();
  await expect(page.locator(".parameter-atom")).toHaveText("256");
  const editedRegistry = await readRegistry(page, daemon.baseUrl);
  const editedHistory = await readActivationHistory(page, daemon.baseUrl);
  expect(editedRegistry.activation.entry_id).not.toBe(initialEntryId);
  expect(editedRegistry.activation.generation).toBe(initialRegistry.activation.generation + 1);
  expect(editedHistory.items).toHaveLength(initialHistory.items.length + 1);

  const rollbackResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/config-registry/rollback"),
  );
  await page.getByRole("button", { name: "Undo" }).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Restore default", exact: true })
    .click();
  await expectResponseOk(await rollbackResponse, "POST");

  await expect(page.getByTestId("active-config-entry")).toHaveText(initialEntryId);
  await expect(page.getByText("Runtime-derived default")).toHaveCount(0);
  const rolledBackRegistry = await readRegistry(page, daemon.baseUrl);
  const rolledBackHistory = await readActivationHistory(page, daemon.baseUrl);
  expect(rolledBackRegistry.activation.entry_id).toBe(initialEntryId);
  expect(rolledBackRegistry.activation.generation).toBe(editedRegistry.activation.generation + 1);
  expect(rolledBackHistory.items).toHaveLength(editedHistory.items.length + 1);
});

test("accepts a notebook candidate in the GUI and preserves its provenance", async ({
  daemon,
  page,
}) => {
  const candidate = await createCandidateAnalysis(daemon.projectRoot);
  const initialRegistry = await readRegistry(page, daemon.baseUrl);

  await page.goto(`${daemon.baseUrl}/?run=${encodeURIComponent(candidate.runId)}`);
  const proposals = page.locator(".run-proposals-card");
  await expect(proposals.getByText(candidate.proposalId, { exact: true })).toBeVisible();
  await expect(proposals.getByText("98% confidence", { exact: true })).toBeVisible();
  await proposals.getByPlaceholder("Evidence or rationale").fill("fit accepted from the GUI");

  const acceptResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/config-registry/candidates/activate"),
  );
  await proposals.getByRole("button", { name: "Accept as default" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Accept as default" }).click();
  await expectResponseOk(await acceptResponse, "POST");
  await expect(proposals.getByRole("button", { name: "Default set" })).toBeVisible();

  const acceptedRegistry = await readRegistry(page, daemon.baseUrl);
  expect(acceptedRegistry.activation.entry_id).not.toBe(initialRegistry.activation.entry_id);
  expect(acceptedRegistry.activation.generation).toBe(initialRegistry.activation.generation + 1);

  await page.getByRole("button", { name: "Configuration" }).click();
  await expect(page.getByText("Runtime-derived default")).toBeVisible();
  await expect(page.getByText("Analysis candidate", { exact: true })).toBeVisible();
  await expect(page.getByText(candidate.analysisId, { exact: true })).toBeVisible();
  await expect(page.getByText("Approved · Human · local-operator", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open producing run" }).click();

  await expect(page.getByRole("button", { name: "Runs" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText(candidate.runId, { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("run")).toBe(candidate.runId);

  await page.getByRole("button", { name: "Configuration" }).click();
  const rollbackResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/config-registry/rollback"),
  );
  await page.getByRole("button", { name: "Undo" }).click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Restore default", exact: true })
    .click();
  await expectResponseOk(await rollbackResponse, "POST");
  await expect(page.getByTestId("active-config-entry")).toHaveText(
    initialRegistry.activation.entry_id,
  );
});

test("open console reconnects SSE and follows a live notebook run", async ({ daemon, page }) => {
  let streamCount = 0;
  const streamRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/events/stream?")) {
      streamRequests.push(request.url());
    }
  });
  await page.route("**/api/v1/events/stream?*", async (route) => {
    streamCount += 1;
    if (streamCount === 1) {
      const url = new URL(route.request().url());
      url.searchParams.set("after", "0");
      url.searchParams.set("follow", "false");
      await route.continue({ url: url.toString() });
      return;
    }
    await route.continue();
  });
  await page.goto(daemon.baseUrl);
  // Chromium reconnects after the finite first response; transport tests cover
  // Last-Event-ID cursor precedence independently of browser routing.
  await expect.poll(() => streamRequests.length).toBeGreaterThanOrEqual(2);
  await expect(page.getByText("Ok", { exact: true }).first()).toBeVisible();

  const experiment = await startControlledExperiment(daemon.projectRoot);
  try {
    const runId = await waitForMarker(experiment.acceptedReady, experiment);
    const runItem = page.locator("button.run-item").filter({ hasText: LIVE_EXPERIMENT_ID });
    await expect(runItem).toContainText("Accepted");
    await runItem.click();

    const detail = page.locator(".run-detail");
    const state = detail.locator(".status-pill");
    const timeline = detail.locator(".timeline-card");
    await expect(detail.getByText(runId, { exact: true })).toBeVisible();
    await expect(state).toHaveText("Accepted");
    await expect(timeline.getByText("Run admitted", { exact: true })).toBeVisible();

    await writeFile(experiment.releaseAccepted, "", "utf8");
    await waitForMarker(experiment.runningReady, experiment);
    await expect(state).toHaveText("Running");
    await expect(timeline.getByText(/From: queued.*To: leased/)).toBeVisible();

    await writeFile(experiment.releaseRunning, "", "utf8");
    await waitForMarker(experiment.measurementReady, experiment);
    await expect(state).toHaveText("Running");
    const dataCard = detail.locator(".data-card");
    await expect(dataCard.getByText("Measurement preview", { exact: true })).toBeVisible();
    await expect(dataCard.getByText("1 records", { exact: true })).toBeVisible();
    await expect(dataCard.locator(".measurement-preview pre")).toContainText('"point_index": 0');
    // The point closes only after the held append call returns its durable receipt.
    await expect(
      detail.getByRole("progressbar", {
        name: "0 of 5 points complete",
      }),
    ).toBeVisible();

    await writeFile(experiment.releaseMeasurement, "", "utf8");
    const completion = await experiment.completion;
    expectProcessOk(completion);
    await expect(state).toHaveText("Succeeded");
    await expect(dataCard.getByText("5 records", { exact: true })).toBeVisible();
    await expect(timeline.getByText(/From: leased.*To: closed/)).toBeVisible();
  } finally {
    await finishControlledExperiment(experiment);
  }
});

async function readRegistry(page: Page, baseUrl: string): Promise<ConfigRegistryView> {
  const response = await page.request.get(`${baseUrl}/api/v1/config-registry`);
  await expectResponseOk(response, "GET");
  return (await response.json()) as ConfigRegistryView;
}

async function readActivationHistory(
  page: Page,
  baseUrl: string,
): Promise<ConfigActivationHistoryView> {
  const response = await page.request.get(`${baseUrl}/api/v1/config-registry/activations`);
  await expectResponseOk(response, "GET");
  return (await response.json()) as ConfigActivationHistoryView;
}

async function createCandidateAnalysis(projectRoot: string): Promise<CandidateAnalysis> {
  const script = join(projectRoot, "e2e_candidate_analysis.py");
  await writeFile(script, CANDIDATE_ANALYSIS_SOURCE, "utf8");
  const result = runUv(["python", script, projectRoot], projectRoot);
  const marker = result.stdout.split(/\r?\n/).find((line) => line.startsWith("E2E_CANDIDATE="));
  if (marker === undefined) {
    throw new Error(`Candidate analysis did not report its identity:\n${result.stdout}`);
  }
  const parsed = JSON.parse(marker.slice("E2E_CANDIDATE=".length)) as {
    run_id: string;
    proposal_id: string;
    analysis_id: string;
  };
  return {
    runId: parsed.run_id,
    proposalId: parsed.proposal_id,
    analysisId: parsed.analysis_id,
  };
}

async function expectResponseOk(
  response: {
    ok(): boolean;
    status(): number;
    text(): Promise<string>;
    url(): string;
  },
  method: string,
): Promise<void> {
  if (!response.ok()) {
    throw new Error(
      `${method} ${response.url()} returned ${response.status()}: ${await response.text()}`,
    );
  }
}

async function readEndpoint(projectRoot: string): Promise<DaemonEndpointRecord> {
  const source = await readFile(join(projectRoot, ".scopecat/daemon.json"), "utf8");
  const record = JSON.parse(source) as Partial<DaemonEndpointRecord>;
  if (typeof record.base_url !== "string" || new URL(record.base_url).port === "0") {
    throw new Error(`Invalid daemon endpoint record: ${source}`);
  }
  return record as DaemonEndpointRecord;
}

function runUv(arguments_: string[], cwd: string, allowFailure = false): SpawnSyncReturns<string> {
  const environment = { ...process.env };
  delete environment.SCOPECAT_DAEMON_URL;
  const result = spawnSync("uv", ["run", "--locked", "--project", REPOSITORY_ROOT, ...arguments_], {
    cwd,
    encoding: "utf8",
    env: environment,
    timeout: 30_000,
  });
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

async function startControlledExperiment(projectRoot: string): Promise<ControlledExperiment> {
  const script = join(projectRoot, "e2e_live_run.py");
  const acceptedReady = join(projectRoot, ".scopecat/e2e-accepted-ready");
  const releaseAccepted = join(projectRoot, ".scopecat/e2e-release-accepted");
  const runningReady = join(projectRoot, ".scopecat/e2e-running-ready");
  const releaseRunning = join(projectRoot, ".scopecat/e2e-release-running");
  const measurementReady = join(projectRoot, ".scopecat/e2e-measurement-ready");
  const releaseMeasurement = join(projectRoot, ".scopecat/e2e-release-measurement");
  await writeFile(script, CONTROLLED_EXPERIMENT_SOURCE, "utf8");

  const environment = { ...process.env };
  delete environment.SCOPECAT_DAEMON_URL;
  const child = spawn("uv", ["run", "--locked", "--project", REPOSITORY_ROOT, "python", script], {
    cwd: projectRoot,
    env: environment,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout?.setEncoding("utf8");
  child.stderr?.setEncoding("utf8");
  child.stdout?.on("data", (chunk: string) => {
    stdout += chunk;
  });
  child.stderr?.on("data", (chunk: string) => {
    stderr += chunk;
  });
  const completion = new Promise<ProcessCompletion>((resolveCompletion) => {
    child.once("error", (error) => {
      stderr += `\n${error.message}`;
    });
    child.once("close", (code, signal) => {
      resolveCompletion({ code, signal, stdout, stderr });
    });
  });
  return {
    acceptedReady,
    releaseAccepted,
    runningReady,
    releaseRunning,
    measurementReady,
    releaseMeasurement,
    child,
    completion,
  };
}

async function waitForMarker(path: string, experiment: ControlledExperiment): Promise<string> {
  await expect
    .poll(
      async () => {
        const marker = await readFile(path, "utf8").catch(() => "");
        const earlyExit = await processResultWithin(experiment, 0);
        if (earlyExit !== undefined) {
          expectProcessOk(earlyExit);
          throw new Error(`controlled experiment exited before ${path}`);
        }
        return marker.trim();
      },
      { message: `waiting for controlled experiment marker ${path}` },
    )
    .not.toBe("");
  return (await readFile(path, "utf8")).trim();
}

function expectProcessOk(completion: ProcessCompletion): void {
  expect(
    completion.code,
    [
      `controlled experiment exited with code ${completion.code}`,
      completion.signal && `signal: ${completion.signal}`,
      completion.stdout,
      completion.stderr,
    ]
      .filter(Boolean)
      .join("\n"),
  ).toBe(0);
  expect(completion.stdout).toContain("'status': 'completed'");
}

async function finishControlledExperiment(experiment: ControlledExperiment): Promise<void> {
  await Promise.all([
    writeFile(experiment.releaseAccepted, "", "utf8"),
    writeFile(experiment.releaseRunning, "", "utf8"),
    writeFile(experiment.releaseMeasurement, "", "utf8"),
  ]);
  if ((await processResultWithin(experiment, 5_000)) === undefined) {
    experiment.child.kill("SIGTERM");
    await experiment.completion;
  }
}

async function processResultWithin(
  experiment: ControlledExperiment,
  timeoutMs: number,
): Promise<ProcessCompletion | undefined> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      experiment.completion,
      new Promise<undefined>((resolveTimeout) => {
        timer = setTimeout(() => resolveTimeout(undefined), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

async function stopAndRemoveProject(projectRoot: string): Promise<void> {
  const stopped = runUv(["scopecat", "stop", projectRoot], projectRoot, true);
  if (stopped.error || stopped.status !== 0) {
    const daemonLog = await readFile(join(projectRoot, ".scopecat/daemon.log"), "utf8").catch(
      () => "",
    );
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
