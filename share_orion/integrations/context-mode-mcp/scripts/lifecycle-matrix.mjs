import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { resolve } from "node:path";
import process from "node:process";

const ROOT_OVERRIDE = process.env.CTX_PROJECT_ROOT || resolve(process.cwd(), "..");
const DIST_PATH = resolve(process.cwd(), "dist", "index.js");

const steps = [];
const transport = new StdioClientTransport({
  command: "node",
  args: [DIST_PATH],
  env: {
    ...Object.fromEntries(
      Object.entries(process.env).map(([key, value]) => [key, String(value ?? "")]),
    ),
    CTX_PROJECT_ROOT: ROOT_OVERRIDE,
  },
});

const client = new Client(
  { name: "context-mode-mcp-lifecycle-matrix", version: "0.0.1" },
  { capabilities: { tools: {} } },
);

function record(name, ok, details = {}) {
  steps.push({ name, ok, ...details });
}

function normalizePayload(response) {
  if (response?.structuredContent) return response.structuredContent;
  if (response?.content?.[0]?.type === "text") {
    try {
      return JSON.parse(response.content[0].text || "{}");
    } catch {
      return { ok: false, error: { code: "INTERNAL", message: "non-json response content" } };
    }
  }
  return response || {};
}

async function callTool(name, args = {}) {
  const response = await client.callTool({ name, arguments: args });
  const payload = normalizePayload(response);
  if (typeof payload.ok === "undefined") {
    payload.ok = !payload.error;
  }
  payload.tool = payload.tool || name;
  return payload;
}

function failUnless(condition, stepName, payload, message) {
  const ok = Boolean(condition);
  record(stepName, ok, { error: payload?.error, message, payload });
  if (!ok) {
    throw new Error(message || `${stepName} failed`);
  }
}

async function run() {
  let exitCode = 0;

  try {
    await client.connect(transport);
    record("connect", true);

    const doctor = await callTool("ctx_doctor", {});
    failUnless(doctor?.ok === true, "ctx_doctor", doctor, "ctx_doctor did not return ok");

    const execute = await callTool("ctx_execute", {
      language: "python",
      code: "print('matrix-lifecycle')",
      title: "lifecycle matrix",
      args: [],
      timeout_ms: 5000,
    });
    failUnless(execute?.ok === true && execute.meta?.disposition === "inline", "ctx_execute", execute, "ctx_execute inline path failed");

    const upgradeDenied = await callTool("ctx_upgrade", { confirm: false });
    failUnless(Boolean(upgradeDenied?.error?.code), "ctx_upgrade_confirm_denied", upgradeDenied, "ctx_upgrade did not enforce confirm gate");

    const upgrade = await callTool("ctx_upgrade", { confirm: true, rebuild: true, reconfigure: true });
    failUnless(upgrade?.ok === true, "ctx_upgrade", upgrade, "ctx_upgrade confirm=true failed");

    const purgeDenied = await callTool("ctx_purge", { confirm: false, delete_db: false });
    failUnless(Boolean(purgeDenied?.error?.code), "ctx_purge_confirm_denied", purgeDenied, "ctx_purge did not enforce confirm gate");

    const index = await callTool("ctx_index", {
      markdown: "# Heading\n\n## Alpha\nIndexed by lifecycle matrix.",
      title: "ctx-lifecycle-matrix",
      uri: "/tmp/ctx-lifecycle-matrix.md",
      tags: ["lifecycle", "matrix"],
    });
    failUnless(index?.ok === true && index.chunks_indexed >= 1, "ctx_index", index, "ctx_index did not produce indexed chunks");

    const search = await callTool("ctx_search", { query: "Alpha", limit: 5, include_debug: false });
    failUnless(search?.ok === true && search.results?.length >= 1, "ctx_search", search, "ctx_search did not return results");

    const purge = await callTool("ctx_purge", { confirm: true, delete_db: false });
    failUnless(purge?.ok === true, "ctx_purge", purge, "ctx_purge confirm=true failed");

    const report = {
      project_hash: doctor?.meta?.project_hash,
      db_path: doctor?.meta?.db_path,
      backend: doctor?.sqlite?.backend || "unknown",
      fts5: Boolean(doctor?.sqlite?.fts5),
      trigram: Boolean(doctor?.sqlite?.trigram),
      purge_deleted: {
        docs: purge?.meta?.deleted_docs ?? 0,
        chunks: purge?.meta?.deleted_chunks ?? 0,
        events: purge?.meta?.deleted_events ?? 0,
      },
    };

    record("lifecycle_matrix", true, report);
    console.log("context-mode-mcp lifecycle matrix: PASS");
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    record("lifecycle_matrix", false, {
      message: error instanceof Error ? error.message : String(error),
    });
    console.error("context-mode-mcp lifecycle matrix: FAIL");
    exitCode = 1;
  } finally {
    try {
      await client.close();
    } catch {
      // ignore
    }
    const failures = steps.filter((step) => !step.ok);
    if (failures.length > 0) {
      console.log("Steps with failures:");
      for (const failure of failures) {
        console.log(`- ${failure.name}: ${failure.message || failure.error?.message || "failed"}`);
      }
      exitCode = 1;
    }

    if (exitCode === 0) {
      console.log("All lifecycle checks passed.");
      return;
    }
    process.exit(exitCode);
  }
}

run();
