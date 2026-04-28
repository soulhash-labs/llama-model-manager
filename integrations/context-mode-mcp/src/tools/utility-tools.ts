import { createReadStream, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { dirname, extname, resolve } from "node:path";
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import type { SqlBackend } from "../db/adapter";
import { beginRunMeta, finalizeRun, toolError, type ToolErrorLike } from "./shared";
import { getChunkRows, indexDocument, getDbCapabilities, purgeProject, safeDeleteDbFile } from "../db/index";
import { searchChunks } from "../db/search";
import { initSchema } from "../db/schema";
import { fetchAndCache } from "../utils/fetcher";
import { clampBytes, toISO } from "../utils/timing";
import { loadSecurityPolicy, ContextPaths, isCommandAllowed } from "../utils/types";
import { runInSandbox } from "../sandbox/runner";
import {
  CtxBatchRequest,
  CtxIndexRequest,
  CtxSearchRequest,
  CtxFetchIndexRequest,
  CtxStatsRequest,
  CtxPurgeRequest,
  CtxDashboardOpenRequest,
  CtxUpgradeRequest,
  ToolError,
} from "../schemas/context-tools";

type BatchItem = CtxBatchRequest["items"][number];

const DASHBOARD_DIR = resolve(process.cwd(), "dashboard", "dist");
let dashboardServer: ReturnType<typeof createServer> | null = null;
let dashboardAddress: { host: string; port: number } | null = null;

function detectRuntime(command: string): { available: boolean; path?: string; version?: string } {
  try {
    const result = spawnSync(command, ["--version"], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    const raw = result.stdout?.toString() || result.stderr?.toString() || "";
    return { available: result.status === 0, path: command, version: raw.trim().split("\n")[0] || undefined };
  } catch {
    return { available: false };
  }
}

function inlineDecision(rawText: string, intent?: string) {
  const bytes = Buffer.byteLength(rawText || "", "utf8");
  if (bytes > 50_000) return { indexed: true, disposition: "indexed" as const };
  if (intent && intent.trim() && bytes > 5_000) return { indexed: true, disposition: "indexed" as const };
  return { indexed: false, disposition: "inline" as const };
}

function rowSnippets(rows: Array<{ chunk_id: string; h2_title: string; content_md: string }>) {
  return rows.slice(0, 4).map((row, idx) => ({
    chunk_id: row.chunk_id,
    title: row.h2_title || `chunk-${idx + 1}`,
    snippet: row.content_md.slice(0, 180),
    score: 1,
  }));
}

function requestBytesFromArgs(...args: string[]): number {
  return args.reduce((acc, next) => acc + Buffer.byteLength(next || "", "utf8"), 0);
}

function fileSizeBytes(dir: string): number {
  let total = 0;
  for (const item of readdirSync(dir, { withFileTypes: true })) {
    const p = `${dir}/${item.name}`;
    if (item.isDirectory()) total += fileSizeBytes(p);
    else total += statSync(p).size;
  }
  return total;
}

export async function handleBatchTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxBatchRequest;
  requestId?: string;
  startTime: number;
}) {
  const run = beginRunMeta(params.context, "ctx_batch");
  const security = loadSecurityPolicy(params.context.project_root);

  const outputItems: Array<{
    kind: "shell" | "search";
    ok: boolean;
    stdout?: string;
    snippets: Array<{ chunk_id: string; title: string; snippet: string; score?: number }>;
    index?: { doc_id: string; chunk_ids: string[]; source: "execute" | "execute_file" | "index" | "fetch" | "events"; uri?: string; title?: string };
    meta?: {
      project_hash: string;
      workdir: string;
      timeout_ms: number;
      exit_code: number | null;
      timed_out: boolean;
      killed: boolean;
      pid: number | null;
      stdout_bytes: number;
      returned_bytes: number;
      fs_bytes_written: number;
      net_bytes: null;
      duration_ms: number;
      indexed: boolean;
      disposition: "inline" | "indexed";
    };
    error?: ToolErrorLike;
  }> = [];

  let rawBytes = 0;
  let returnedBytes = 0;
  let indexedBytes = 0;

  for (const item of params.request.items) {
    if (item.kind === "search") {
      const search = searchChunks(params.db, item.query, Math.min(50, item.limit || 10));
      const payload = {
        kind: "search" as const,
        ok: true,
        snippets: search.rows.slice(0, 4).map((row) => ({
          chunk_id: row.chunk_id,
          title: row.title,
          snippet: row.snippet,
          score: row.score,
        })),
      };
      outputItems.push(payload);
      rawBytes += requestBytesFromArgs(item.query);
      returnedBytes += JSON.stringify(payload).length;
      continue;
    }

    const command = item.command;
    const commandCheck = isCommandAllowed(command, security);
    if (!commandCheck.allowed) {
      const denied = {
        kind: "shell" as const,
        ok: false,
        stdout: "",
        snippets: [] as Array<{ chunk_id: string; title: string; snippet: string; score?: number }> ,
        error: toolError("DENIED", commandCheck.reason || "command denied", { command }),
      };
      outputItems.push(denied);
      rawBytes += requestBytesFromArgs(command);
      returnedBytes += JSON.stringify(denied).length;
      continue;
    }

    const execution = await runInSandbox({
      language: "shell",
      code: command,
      args: [],
      env: {},
      timeout_ms: item.timeout_ms || 30_000,
      security,
    });

    const policy = inlineDecision(execution.output.stdout, item.intent);
    let index;
    let snippets: Array<{ chunk_id: string; title: string; snippet: string; score?: number }> = [];
    let returned = execution.output.stdout;
    let returnedBytesItem = clampBytes(Buffer.byteLength(returned, "utf8"));
    let indexedBytesItem = 0;

    if (!execution.output.timed_out && !execution.error && policy.indexed) {
      try {
        const doc = indexDocument(params.db, {
          projectHash: params.context.project_hash,
          source: "execute",
          title: `batch:${command.slice(0, 64)}`,
          uri: "shell",
          markdown: execution.output.stdout || "(no output)",
          tags: ["batch", "shell"],
        });

        const rows = getChunkRows(params.db, doc.chunk_ids);
        snippets = rowSnippets(rows);
        index = {
          doc_id: doc.doc_id,
          chunk_ids: doc.chunk_ids,
          source: doc.source,
          uri: doc.uri,
          title: doc.title,
        };

        returned = "";
        returnedBytesItem = clampBytes(JSON.stringify({ snippets }).length);
        indexedBytesItem = Buffer.byteLength(execution.output.stdout || "", "utf8");
      } catch {
        // soft-fail to inline output
      }
    }

    const shellRun = {
      kind: "shell" as const,
      ok: !execution.output.timed_out && !execution.error,
      stdout: policy.indexed ? undefined : returned,
      snippets,
      ...(index ? { index } : {}),
      meta: {
        project_hash: params.context.project_hash,
        workdir: execution.output.workdir,
        timeout_ms: item.timeout_ms || 30_000,
        exit_code: execution.output.exit_code,
        timed_out: execution.output.timed_out,
        killed: execution.output.killed,
        pid: execution.output.pid,
        stdout_bytes: clampBytes(Buffer.byteLength(execution.output.stdout || "", "utf8")),
        returned_bytes: returnedBytesItem,
        fs_bytes_written: clampBytes(execution.output.fs_bytes_written),
        net_bytes: null,
        duration_ms: execution.output.duration_ms,
        indexed: policy.indexed,
        disposition: policy.disposition,
      },
      ...(execution.error ? { error: { code: execution.error.code, message: execution.error.message, details: execution.error.details } } : {}),
    };

    outputItems.push(shellRun);

    rawBytes += requestBytesFromArgs(command);
    returnedBytes += returnedBytesItem;
    indexedBytes += indexedBytesItem;
  }

  const hasFailure = outputItems.some((row) => !row.ok);
  finalizeRun(params.db, run, {
    raw_bytes: rawBytes,
    returned_bytes: returnedBytes,
    indexed_bytes: indexedBytes,
    duration_ms: Date.now() - params.startTime,
    ok: !hasFailure,
    meta: { count: params.request.items.length },
  });

  return {
    ok: !hasFailure,
    tool: "ctx_batch" as const,
    request_id: params.requestId,
    results: outputItems,
  };
}

export async function handleIndexTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxIndexRequest;
  requestId?: string;
}) {
  const run = beginRunMeta(params.context, "ctx_index");
  const markdown = params.request.markdown || "";
  const doc = indexDocument(params.db, {
    projectHash: params.context.project_hash,
    source: "index",
    title: params.request.title,
    uri: params.request.uri,
    markdown,
    tags: params.request.tags,
  });

  const chunks = getChunkRows(params.db, doc.chunk_ids);
  const markdownBytes = Buffer.byteLength(markdown, "utf8");

  finalizeRun(params.db, run, {
    raw_bytes: markdownBytes,
    returned_bytes: JSON.stringify({ chunks: chunks.length }).length,
    indexed_bytes: markdownBytes,
    duration_ms: 0,
    ok: true,
    meta: { chunks: chunks.length, doc_id: doc.doc_id },
  });

  return {
    ok: true,
    tool: "ctx_index" as const,
    request_id: params.requestId,
    index: {
      doc_id: doc.doc_id,
      chunk_ids: doc.chunk_ids,
      source: doc.source,
      uri: doc.uri,
      title: doc.title,
    },
    chunks_indexed: doc.chunk_ids.length,
    meta: {
      project_hash: params.context.project_hash,
      markdown_bytes: markdownBytes,
      created_at: toISO(),
    },
  };
}

export async function handleSearchTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxSearchRequest;
  requestId?: string;
}) {
  const run = beginRunMeta(params.context, "ctx_search");
  const start = Date.now();
  const search = searchChunks(params.db, params.request.query, params.request.limit || 10);

  finalizeRun(params.db, run, {
    raw_bytes: Buffer.byteLength(params.request.query, "utf8"),
    returned_bytes: JSON.stringify(search.rows).length,
    indexed_bytes: 0,
    duration_ms: Date.now() - start,
    ok: true,
    meta: { strategy: search.strategy, degraded: search.degraded },
  });

  return {
    ok: true,
    tool: "ctx_search" as const,
    request_id: params.requestId,
    query: params.request.query,
    results: search.rows,
    meta: {
      project_hash: params.context.project_hash,
      strategy: search.strategy,
      degraded: search.degraded,
      suggestions: search.degraded ? ((search.debug.suggestions as string[]) ?? []) : [],
    },
    ...(params.request.include_debug ? { debug: search.debug } : {}),
  };
}

export async function handleFetchIndexTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxFetchIndexRequest;
  requestId?: string;
}) {
  const run = beginRunMeta(params.context, "ctx_fetch_index");
  const started = Date.now();

  const fetched = await fetchAndCache(params.request.url, params.context.cache_dir, !!params.request.force);
  const markdown = fetched.markdown || "";
  const _policy = inlineDecision(markdown, params.request.intent);

  const doc = indexDocument(params.db, {
    projectHash: params.context.project_hash,
    source: "fetch",
    title: params.request.title || `fetch:${params.request.url}`,
    uri: params.request.url,
    markdown: markdown || "(empty)",
    tags: ["fetch", params.request.url],
  });

  const rows = getChunkRows(params.db, doc.chunk_ids);
  const snippets = rowSnippets(rows);

  finalizeRun(params.db, run, {
    raw_bytes: fetched.bytes,
    returned_bytes: JSON.stringify({ snippets }).length,
    indexed_bytes: fetched.bytes,
    duration_ms: Date.now() - started,
    ok: fetched.status >= 200 && fetched.status < 300,
    meta: { url: params.request.url, from_cache: fetched.from_cache },
  });

  const ok = fetched.status >= 200 && fetched.status < 300;
  return {
    ok,
    tool: "ctx_fetch_index" as const,
    request_id: params.requestId,
    index: {
      doc_id: doc.doc_id,
      chunk_ids: doc.chunk_ids,
      source: doc.source,
      uri: doc.uri,
      title: doc.title,
    },
    snippets,
    meta: {
      project_hash: params.context.project_hash,
      fetched_at: toISO(),
      from_cache: fetched.from_cache,
      http_status: fetched.status,
      markdown_bytes: Buffer.byteLength(markdown, "utf8"),
    },
    ...(ok ? {} : { error: { code: "FETCH_FAILED", message: `HTTP ${fetched.status}` as string } }),
  };
}

export async function handleStatsTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxStatsRequest;
  requestId?: string;
  startTime: number;
}) {
  const run = beginRunMeta(params.context, "ctx_stats");
  const now = new Date();
  const window = params.request.window || "session";

  const since =
    window === "session"
      ? toISO(new Date(params.startTime))
      : window === "24h"
        ? toISO(new Date(now.getTime() - 24 * 60 * 60 * 1000))
        : window === "7d"
          ? toISO(new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000))
          : "1970-01-01T00:00:00.000Z";

  const where = window === "all" ? "1=1" : "created_at >= :since";
  const totals = params.db.get<{
    raw_bytes_total: number;
    returned_bytes_total: number;
    indexed_bytes_total: number;
  }>(
    `SELECT COALESCE(SUM(raw_bytes),0) as raw_bytes_total,
            COALESCE(SUM(returned_bytes),0) as returned_bytes_total,
            COALESCE(SUM(indexed_bytes),0) as indexed_bytes_total
       FROM runs WHERE ${where}`,
    window === "all" ? {} : { since },
  );

  const byToolRows = params.db.all<{
    tool: string;
    calls: number;
    raw_bytes: number;
    returned_bytes: number;
    indexed_bytes: number;
  }>(
    `SELECT tool,
            COUNT(*) as calls,
            COALESCE(SUM(raw_bytes),0) as raw_bytes,
            COALESCE(SUM(returned_bytes),0) as returned_bytes,
            COALESCE(SUM(indexed_bytes),0) as indexed_bytes
       FROM runs
      WHERE ${where}
      GROUP BY tool`,
    window === "all" ? {} : { since },
  );

  const by_tool: Record<string, { calls: number; raw_bytes: number; returned_bytes: number; indexed_bytes: number }> = {};
  for (const row of byToolRows) {
    by_tool[row.tool] = {
      calls: Number(row.calls || 0),
      raw_bytes: Number(row.raw_bytes || 0),
      returned_bytes: Number(row.returned_bytes || 0),
      indexed_bytes: Number(row.indexed_bytes || 0),
    };
  }

  const raw = Number(totals?.raw_bytes_total || 0);
  const returned = Number(totals?.returned_bytes_total || 0);
  const indexed = Number(totals?.indexed_bytes_total || 0);

  const reduction_ratio = raw > 0 ? clampBytes(returned) / clampBytes(raw) : 0;
  const reduction_percent = raw > 0 ? Number(((1 - reduction_ratio) * 100).toFixed(2)) : 0;

  finalizeRun(params.db, run, {
    raw_bytes: raw,
    returned_bytes: returned,
    indexed_bytes: indexed,
    duration_ms: Date.now() - params.startTime,
    ok: true,
    meta: { window },
  });

  return {
    ok: true,
    tool: "ctx_stats" as const,
    request_id: params.requestId,
    meta: {
      project_hash: params.context.project_hash,
      db_path: params.context.db_path,
      uptime_ms: Date.now() - params.startTime,
    },
    savings: {
      raw_bytes_total: raw,
      returned_bytes_total: returned,
      indexed_bytes_total: indexed,
      reduction_ratio,
      reduction_percent,
    },
    by_tool,
  };
}

export async function handleDoctorTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  security: ReturnType<typeof loadSecurityPolicy>;
  lifecycle: { parentPid: number | null; active: boolean; lastCheckAt: string | null };
  requestId?: string;
}) {
  const capabilities = getDbCapabilities(params.db);
  const run = beginRunMeta(params.context, "ctx_doctor");
  finalizeRun(params.db, run, {
    raw_bytes: 0,
    returned_bytes: 0,
    indexed_bytes: 0,
    duration_ms: 0,
    ok: true,
    meta: { tool: "doctor" },
  });

  return {
    ok: true,
    tool: "ctx_doctor" as const,
    request_id: params.requestId,
    meta: {
      project_root: params.context.project_root,
      project_hash: params.context.project_hash,
      db_path: params.context.db_path,
      cache_dir: params.context.cache_dir,
    },
    runtimes: {
      node: detectRuntime("node"),
      bun: detectRuntime("bun"),
      python: detectRuntime("python3"),
      shell: detectRuntime("/bin/bash"),
      go: detectRuntime("go"),
      rust: detectRuntime("rustc"),
    },
    sqlite: {
      backend: capabilities.backend,
      fts5: capabilities.fts5,
      trigram: capabilities.trigram,
      degraded: capabilities.degraded,
    },
    security: {
      deny_bash_patterns: params.security.denyBashPatterns,
      deny_path_patterns: params.security.denyPathPatterns,
      allowlist_loaded: params.security.allowlistLoaded,
      denylist_loaded: params.security.denylistLoaded,
    },
    lifecycle_guard: {
      parent_pid: params.lifecycle.parentPid,
      active: params.lifecycle.active,
      last_check_at: params.lifecycle.lastCheckAt,
    },
  };
}

export async function handleUpgradeTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxUpgradeRequest;
  requestId?: string;
}) {
  const started = Date.now();
  const run = beginRunMeta(params.context, "ctx_upgrade");
  const actions: string[] = [];
  const durationMs = () => Date.now() - started;

  if (!params.request.confirm) {
    return {
      ok: false,
      tool: "ctx_upgrade" as const,
      request_id: params.requestId,
      actions,
      meta: {
        project_hash: params.context.project_hash,
        duration_ms: 0,
      },
      error: toolError("DENIED", "confirm=false blocks upgrade"),
    };
  }

  if (params.request.rebuild) {
    actions.push("rebuild schema");
    try {
      // re-open and initialize to migrate schema
      initSchema(params.db);
    } catch {
      finalizeRun(params.db, run, {
        raw_bytes: 0,
        returned_bytes: 0,
        indexed_bytes: 0,
        duration_ms: durationMs(),
        ok: false,
        meta: { actions },
      });
      return {
        ok: false,
        tool: "ctx_upgrade" as const,
        request_id: params.requestId,
        actions,
        meta: {
          project_hash: params.context.project_hash,
          duration_ms: durationMs(),
        },
        error: toolError("DB_UNAVAILABLE", "schema rebuild failed"),
      };
    }
  }

  if (params.request.reconfigure) {
    actions.push("reconfigure cache directories");
    try {
      const hadCache = existsSync(params.context.cache_dir);
      mkdirSync(params.context.cache_dir, { recursive: true });
      if (!hadCache && existsSync(params.context.cache_dir)) {
        actions.push("created cache directories");
      }
    } catch {
      finalizeRun(params.db, run, {
        raw_bytes: 0,
        returned_bytes: 0,
        indexed_bytes: 0,
        duration_ms: durationMs(),
        ok: false,
        meta: { actions },
      });
      return {
        ok: false,
        tool: "ctx_upgrade" as const,
        request_id: params.requestId,
        actions,
        meta: {
          project_hash: params.context.project_hash,
          duration_ms: durationMs(),
        },
        error: toolError("INTERNAL", "cache reconfiguration failed"),
      };
    }
  }

  if (actions.length === 0) {
    actions.push("noop");
  }

  finalizeRun(params.db, run, {
    raw_bytes: 0,
    returned_bytes: 0,
    indexed_bytes: 0,
    duration_ms: durationMs(),
    ok: true,
    meta: { actions },
  });

  return {
    ok: true,
    tool: "ctx_upgrade" as const,
    request_id: params.requestId,
    actions,
    meta: {
      project_hash: params.context.project_hash,
      duration_ms: durationMs(),
    },
  };
}

export async function handlePurgeTool(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxPurgeRequest;
  requestId?: string;
}) {
  const started = Date.now();

  if (!params.request.confirm) {
    return {
      ok: false,
      tool: "ctx_purge" as const,
      request_id: params.requestId,
      meta: {
        project_hash: params.context.project_hash,
        deleted_docs: 0,
        deleted_chunks: 0,
        deleted_events: 0,
        cache_bytes_freed: 0,
      },
      error: toolError("DENIED", "confirm=true required"),
    };
  }

  const run = beginRunMeta(params.context, "ctx_purge");
  let counts: { deleted_docs: number; deleted_chunks: number; deleted_events: number };
  try {
    counts = purgeProject(params.db, params.context.project_hash);
  } catch (error) {
    return {
      ok: false,
      tool: "ctx_purge" as const,
      request_id: params.requestId,
      meta: {
        project_hash: params.context.project_hash,
        deleted_docs: 0,
        deleted_chunks: 0,
        deleted_events: 0,
        cache_bytes_freed: 0,
      },
      error: toolError("DB_UNAVAILABLE", "purge query failed", {
        message: error instanceof Error ? error.message : String(error),
      }),
    };
  }

  let cacheBytes = 0;
  if (existsSync(params.context.cache_dir)) {
    try {
      cacheBytes = fileSizeBytes(params.context.cache_dir);
      rmSync(params.context.cache_dir, { recursive: true, force: true });
      mkdirSync(dirname(params.context.cache_dir), { recursive: true });
    } catch {
      // noop
    }
  }

  finalizeRun(params.db, run, {
    raw_bytes: 0,
    returned_bytes: 0,
    indexed_bytes: 0,
    duration_ms: Date.now() - started,
    ok: true,
    meta: {
      deleted_docs: counts.deleted_docs,
      deleted_chunks: counts.deleted_chunks,
      deleted_events: counts.deleted_events,
    },
  });

  if (params.request.delete_db) {
    try {
      params.db.close();
      safeDeleteDbFile(params.context.db_path);
    } catch {
      // noop
    }
  }

  return {
    ok: true,
    tool: "ctx_purge" as const,
    request_id: params.requestId,
    meta: {
      project_hash: params.context.project_hash,
      deleted_docs: counts.deleted_docs,
      deleted_chunks: counts.deleted_chunks,
      deleted_events: counts.deleted_events,
      cache_bytes_freed: cacheBytes,
    },
  };
}

export async function handleDashboardOpenTool(params: {
  context: ContextPaths;
  request: CtxDashboardOpenRequest;
  requestId?: string;
}) {
  const port = params.request.port || 4747;
  const host = params.request.host || "127.0.0.1";

  if (dashboardAddress && dashboardAddress.host === host && dashboardAddress.port === port) {
    return {
      ok: true,
      tool: "ctx_dashboard_open" as const,
      request_id: params.requestId,
      url: `http://${host}:${port}`,
      meta: { host, port, started: false },
    };
  }

  if (!existsSync(DASHBOARD_DIR)) {
    return {
      ok: false,
      tool: "ctx_dashboard_open" as const,
      request_id: params.requestId,
      url: "",
      meta: { host, port, started: false },
      error: toolError("INTERNAL", "dashboard not built"),
    };
  }

  const indexFile = resolve(DASHBOARD_DIR, "index.html");
  if (!existsSync(indexFile)) {
    return {
      ok: false,
      tool: "ctx_dashboard_open" as const,
      request_id: params.requestId,
      url: "",
      meta: { host, port, started: false },
      error: toolError("INTERNAL", "dashboard index not found"),
    };
  }

  if (dashboardServer) {
    dashboardServer.close();
    dashboardServer = null;
  }

  const typeFor = (pathname: string) => {
    const ext = extname(pathname || "").toLowerCase();
    if (ext === ".css") return "text/css; charset=utf-8";
    if (ext === ".js" || ext === ".mjs") return "application/javascript; charset=utf-8";
    if (ext === ".json") return "application/json; charset=utf-8";
    if (ext === ".svg") return "image/svg+xml";
    if (ext === ".png") return "image/png";
    return "text/html; charset=utf-8";
  };

  dashboardServer = createServer((request: IncomingMessage, response: ServerResponse) => {
    const rawPath = request.url?.split("?")[0] || "/";
    const filePath = resolve(DASHBOARD_DIR, `.${rawPath === "/" ? "/index.html" : rawPath}`);
    if (!filePath.startsWith(DASHBOARD_DIR)) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }

    if (!existsSync(filePath)) {
      response.writeHead(404, { "Content-Type": "text/plain" });
      response.end("not found");
      return;
    }

    response.writeHead(200, { "Content-Type": typeFor(filePath) });
    createReadStream(filePath).pipe(response);
  });

  await new Promise<void>((resolve, reject) => {
    dashboardServer!.listen(port, host, (error?: Error) => {
      if (error) reject(error);
      else resolve();
    });
  });

  dashboardAddress = { host, port };
  return {
    ok: true,
    tool: "ctx_dashboard_open" as const,
    request_id: params.requestId,
    url: `http://${host}:${port}`,
    meta: {
      host,
      port,
      started: true,
    },
  };
}
