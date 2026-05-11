import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { randomBytes } from "node:crypto";
import type { SqlBackend } from "../db/adapter";
import { clampBytes, toISO } from "../utils/timing";
import { beginRunMeta, finalizeRun, toolError, type ToolErrorLike } from "./shared";
import { getChunkRows, indexDocument } from "../db/index";
import { runInSandbox, type ExecutionInput, type ToolErrorLike as RunnerError } from "../sandbox/runner";
import { isCommandAllowed, isPathAllowed, loadSecurityPolicy, type ContextPaths, type ToolErrorCode } from "../utils/types";
import { CtxExecuteRequest, CtxExecuteFileRequest, type Snippet } from "../schemas/context-tools";

interface ExecPolicy {
  indexed: boolean;
  disposition: "inline" | "indexed";
}

function indexPolicy(stdout: string, intent?: string): ExecPolicy {
  const bytes = Buffer.byteLength(stdout || "", "utf8");
  if (bytes > 50_000) return { indexed: true, disposition: "indexed" };
  if (intent && intent.trim() && bytes > 5_000) return { indexed: true, disposition: "indexed" };
  return { indexed: false, disposition: "inline" };
}

function mkSnippets(rows: Array<{ chunk_id: string; h2_title: string; content_md: string }>): Snippet[] {
  return rows.slice(0, 4).map((row, idx) => ({
    chunk_id: row.chunk_id,
    title: row.h2_title || `chunk-${idx + 1}`,
    snippet: row.content_md.slice(0, 220),
    score: 1,
  }));
}

function asToolError(err: RunnerError | unknown): ToolErrorLike {
  if (err && typeof err === "object" && "code" in err && "message" in err) {
    const candidate = err as { code: ToolErrorCode; message: string; details?: Record<string, unknown> };
    return {
      code: candidate.code,
      message: candidate.message,
      details: candidate.details,
    };
  }
  return { code: "INTERNAL", message: err instanceof Error ? err.message : String(err) };
}

async function executeAndIndex(params: {
  db: SqlBackend;
  context: ContextPaths;
  tool: "ctx_execute" | "ctx_execute_file";
  source: "execute" | "execute_file";
  title: string;
  input: {
    language: string;
    args: string[];
    env: Record<string, string>;
    timeout_ms: number;
    intent?: string;
    code?: string;
    filePath?: string;
  };
  requestId?: string;
}) {
  const run = beginRunMeta(params.context, params.tool);
  const security = loadSecurityPolicy(params.context.project_root);

  const executionInput: ExecutionInput = {
    language: params.input.language,
    code: params.input.code,
    filePath: params.input.filePath,
    args: params.input.args || [],
    env: params.input.env || {},
    timeout_ms: params.input.timeout_ms || 30_000,
    security,
  };

  const execution = await runInSandbox(executionInput);
  const policy = indexPolicy(execution.output.stdout, params.input.intent);

  let snippets: Snippet[] = [];
  let index: {
    doc_id: string;
    chunk_ids: string[];
    source: "execute" | "execute_file" | "index" | "fetch" | "events";
    uri?: string;
    title?: string;
  } | undefined;

  let error: ToolErrorLike | undefined;
  if (execution.error) {
    error = {
      code: execution.error.code,
      message: execution.error.message,
      details: execution.error.details,
    };
  }

  let returned = execution.output.stdout;
  let returnedBytes = Buffer.byteLength(returned, "utf8");
  let indexedBytes = 0;

  if (policy.indexed && !execution.output.timed_out && !error) {
    try {
      const doc = indexDocument(params.db, {
        projectHash: params.context.project_hash,
        source: params.source,
        uri: params.input.filePath,
        title: params.title,
        markdown: execution.output.stdout || "(no output)",
        tags: [params.source, params.input.language],
      });
      index = {
        doc_id: doc.doc_id,
        chunk_ids: doc.chunk_ids,
        source: doc.source,
        uri: doc.uri,
        title: doc.title,
      };

      const rows = getChunkRows(params.db, doc.chunk_ids);
      snippets = mkSnippets(rows);

      returned = "";
      returnedBytes = clampBytes(Buffer.byteLength(JSON.stringify({ snippets, index }), "utf8"));
      indexedBytes = Buffer.byteLength(execution.output.stdout || "", "utf8");
    } catch (idxErr) {
      // Indexing failed — revert to inline so output isn't lost.
      policy.indexed = false;
      policy.disposition = "inline";
      error = error ?? {
        code: "DB_UNAVAILABLE",
        message: idxErr instanceof Error ? idxErr.message : "index backend unavailable",
      };
      returned = execution.output.stdout;
      returnedBytes = Buffer.byteLength(returned, "utf8");
    }
  }

  const meta = {
    project_hash: params.context.project_hash,
    workdir: execution.output.workdir,
    timeout_ms: params.input.timeout_ms || 30_000,
    exit_code: execution.output.exit_code,
    timed_out: execution.output.timed_out,
    killed: execution.output.killed,
    pid: execution.output.pid,
    stdout_bytes: clampBytes(Buffer.byteLength(execution.output.stdout || "", "utf8")),
    returned_bytes: returnedBytes,
    fs_bytes_written: clampBytes(execution.output.fs_bytes_written),
    net_bytes: null,
    duration_ms: execution.output.duration_ms,
    indexed: policy.indexed,
    disposition: policy.disposition,
  };

  const ok = !execution.output.timed_out && !error;
  finalizeRun(params.db, run, {
    raw_bytes: Buffer.byteLength(params.input.code || params.input.filePath || "", "utf8") + Buffer.byteLength(execution.output.stdout || "", "utf8") + Buffer.byteLength(execution.output.stderr || "", "utf8"),
    returned_bytes: returnedBytes,
    indexed_bytes: indexedBytes,
    duration_ms: execution.output.duration_ms,
    ok,
    meta: { ...meta, request_id: params.requestId },
  });

  const response = {
    ok,
    tool: params.tool,
    request_id: params.requestId,
    ...(policy.indexed && !error ? {} : { stdout: returned }),
    snippets,
    ...(index ? { index } : {}),
    meta,
    ...(error ? { error } : {}),
  };

  return response;
}

export async function handleExecute(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxExecuteRequest;
  requestId?: string;
}) {
  const security = loadSecurityPolicy(params.context.project_root);

  if (!existsSync(params.context.project_root)) {
    return {
      ok: false,
      tool: "ctx_execute" as const,
      request_id: params.requestId,
      meta: {
        project_hash: params.context.project_hash,
        workdir: "",
        timeout_ms: params.request.timeout_ms || 30_000,
        exit_code: null,
        timed_out: false,
        killed: false,
        pid: null,
        stdout_bytes: 0,
        returned_bytes: 0,
        fs_bytes_written: 0,
        net_bytes: null,
        duration_ms: 0,
        indexed: false,
        disposition: "inline",
      },
      error: toolError("INVALID_INPUT", "project root missing or inaccessible"),
    };
  }

  // Security checks apply to ALL languages — not just shell.
  // Non-shell languages can still execute dangerous operations (os.system, etc.)
  // so deny patterns must always be enforced.
  const commandCheck = isCommandAllowed(params.request.code, security);
  if (!commandCheck.allowed) {
    return {
      ok: false,
      tool: "ctx_execute" as const,
      request_id: params.requestId,
      meta: {
        project_hash: params.context.project_hash,
        workdir: "",
        timeout_ms: params.request.timeout_ms || 30_000,
        exit_code: null,
        timed_out: false,
        killed: false,
        pid: null,
        stdout_bytes: 0,
        returned_bytes: 0,
        fs_bytes_written: 0,
        net_bytes: null,
        duration_ms: 0,
        indexed: false,
        disposition: "inline",
      },
      error: toolError("DENIED", commandCheck.reason || "command denied"),
    };
  }

  const safeTitle = params.request.title || `execute-${randomBytes(4).toString("hex")}`;
  return executeAndIndex({
    db: params.db,
    context: params.context,
    tool: "ctx_execute",
    source: "execute",
    title: safeTitle,
    input: {
      language: params.request.language,
      args: params.request.args,
      env: params.request.env,
      timeout_ms: params.request.timeout_ms,
      intent: params.request.intent,
      code: params.request.code,
    },
    requestId: params.requestId,
  });
}

export async function handleExecuteFile(params: {
  db: SqlBackend;
  context: ContextPaths;
  request: CtxExecuteFileRequest;
  requestId?: string;
}) {
  const security = loadSecurityPolicy(params.context.project_root);

  if (!existsSync(params.request.file_path)) {
    return {
      ok: false,
      tool: "ctx_execute_file" as const,
      request_id: params.requestId,
      meta: {
        project_hash: params.context.project_hash,
        workdir: "",
        timeout_ms: params.request.timeout_ms || 30_000,
        exit_code: null,
        timed_out: false,
        killed: false,
        pid: null,
        stdout_bytes: 0,
        returned_bytes: 0,
        fs_bytes_written: 0,
        net_bytes: null,
        duration_ms: 0,
        indexed: false,
        disposition: "inline",
      },
      error: toolError("NOT_FOUND", "file not found", { file_path: params.request.file_path }),
    };
  }

  const pathDecision = isPathAllowed(resolve(params.request.file_path), security);
  if (!pathDecision.allowed) {
    return {
      ok: false,
      tool: "ctx_execute_file" as const,
      request_id: params.requestId,
      meta: {
        project_hash: params.context.project_hash,
        workdir: "",
        timeout_ms: params.request.timeout_ms || 30_000,
        exit_code: null,
        timed_out: false,
        killed: false,
        pid: null,
        stdout_bytes: 0,
        returned_bytes: 0,
        fs_bytes_written: 0,
        net_bytes: null,
        duration_ms: 0,
        indexed: false,
        disposition: "inline",
      },
      error: toolError("DENIED", pathDecision.reason || "path denied", { path: params.request.file_path }),
    };
  }

  const safeTitle = params.request.title || `file:${resolve(params.request.file_path)}`;
  const code = readFileSync(resolve(params.request.file_path), "utf8");

  return executeAndIndex({
    db: params.db,
    context: params.context,
    tool: "ctx_execute_file",
    source: "execute_file",
    title: safeTitle,
    input: {
      language: params.request.language,
      filePath: resolve(params.request.file_path),
      args: params.request.args,
      env: params.request.env,
      timeout_ms: params.request.timeout_ms,
      intent: params.request.intent,
      code,
    },
    requestId: params.requestId,
  });
}
