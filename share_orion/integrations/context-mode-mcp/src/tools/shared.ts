import { isUnavailableBackend, type SqlBackend } from "../db/adapter";
import { toISO, newRequestIdIfMissing } from "../utils/timing";
import { recordRun } from "../db/index";
import type { ContextPaths } from "../utils/types";

export interface ToolErrorLike {
  code: "INVALID_INPUT" | "DENIED" | "TIMEOUT" | "NOT_FOUND" | "FETCH_FAILED" | "EXEC_FAILED" | "DB_UNAVAILABLE" | "FTS_UNAVAILABLE" | "INTERNAL" | "DEGRADED";
  message: string;
  details?: Record<string, unknown>;
}

export function toolError(code: ToolErrorLike["code"], message: string, details?: Record<string, unknown>): ToolErrorLike {
  return { code, message, details };
}

export interface RunMeta {
  run_id: string;
  tool: string;
  createdAt: string;
  startAt: number;
  project_hash: string;
}

export function beginRunMeta(context: ContextPaths, tool: string): RunMeta {
  return {
    run_id: newRequestIdIfMissing(),
    tool,
    createdAt: toISO(),
    startAt: Date.now(),
    project_hash: context.project_hash,
  };
}

export function finalizeRun(
  db: SqlBackend,
  run: RunMeta,
  payload: {
    raw_bytes: number;
    returned_bytes: number;
    indexed_bytes: number;
    duration_ms: number;
    ok: boolean;
    meta: Record<string, unknown>;
  },
): void {
  if (isUnavailableBackend(db)) return;
  try {
    recordRun(db, {
      run_id: run.run_id,
      tool: run.tool,
      created_at: run.createdAt,
      raw_bytes: Number(payload.raw_bytes || 0),
      returned_bytes: Number(payload.returned_bytes || 0),
      indexed_bytes: Number(payload.indexed_bytes || 0),
      duration_ms: Number(payload.duration_ms || 0),
      ok: Boolean(payload.ok),
      meta_json: JSON.stringify(payload.meta || {}),
    });
  } catch {
    // soft-fail
  }
}
