import { z } from "zod";

export const Bytes = z.number().int().nonnegative();
export const Ms = z.number().int().nonnegative();
export const ISO = z.string().datetime({ offset: true }).or(z.string());

export const ToolError = z.object({
  code: z.enum([
    "INVALID_INPUT",
    "DENIED",
    "TIMEOUT",
    "NOT_FOUND",
    "FETCH_FAILED",
    "EXEC_FAILED",
    "DB_UNAVAILABLE",
    "FTS_UNAVAILABLE",
    "INTERNAL",
    "DEGRADED",
  ]),
  message: z.string().min(1),
  details: z.record(z.any()).optional(),
}).strict();

export const ExecLanguage = z.enum([
  "node",
  "bun",
  "python",
  "shell",
  "ruby",
  "go",
  "rust",
  "php",
  "perl",
  "r",
  "elixir",
]);

export const OutputDisposition = z.enum(["inline", "indexed"]);

export const Snippet = z.object({
  chunk_id: z.string().min(1),
  title: z.string().min(1),
  snippet: z.string().min(1),
  score: z.number().optional(),
}).strict();

export const IndexRef = z.object({
  doc_id: z.string().min(1),
  chunk_ids: z.array(z.string().min(1)).default([]),
  source: z.enum(["execute", "execute_file", "index", "fetch", "events"]).optional(),
  uri: z.string().optional(),
  title: z.string().optional(),
}).strict();

export const SandboxMeta = z.object({
  project_hash: z.string().min(8),
  workdir: z.string().min(1),
  timeout_ms: Ms,
  exit_code: z.number().int().nullable(),
  timed_out: z.boolean(),
  killed: z.boolean(),
  pid: z.number().int().nullable(),
  stdout_bytes: Bytes,
  returned_bytes: Bytes,
  fs_bytes_written: Bytes,
  net_bytes: Bytes.nullable(),
  duration_ms: Ms,
  indexed: z.boolean(),
  disposition: OutputDisposition,
}).strict();

export const CtxExecuteRequest = z.object({
  language: ExecLanguage,
  code: z.string().min(1),
  args: z.array(z.string()).default([]),
  env: z.record(z.string()).default({}),
  timeout_ms: Ms.default(30_000),
  intent: z.string().min(1).optional(),
  title: z.string().min(1).optional(),
}).strict();

export const CtxExecuteResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_execute"),
  request_id: z.string().optional(),
  stdout: z.string().optional(),
  snippets: z.array(Snippet).default([]),
  index: IndexRef.optional(),
  meta: SandboxMeta,
  error: ToolError.optional(),
}).strict();

export const CtxExecuteFileRequest = z.object({
  language: ExecLanguage,
  file_path: z.string().min(1),
  args: z.array(z.string()).default([]),
  env: z.record(z.string()).default({}),
  timeout_ms: Ms.default(30_000),
  intent: z.string().min(1).optional(),
  title: z.string().min(1).optional(),
}).strict();

export const CtxExecuteFileResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_execute_file"),
  request_id: z.string().optional(),
  stdout: z.string().optional(),
  snippets: z.array(Snippet).default([]),
  index: IndexRef.optional(),
  meta: SandboxMeta,
  error: ToolError.optional(),
}).strict();

const BatchShell = z.object({
  kind: z.literal("shell"),
  command: z.string().min(1),
  timeout_ms: Ms.optional(),
  intent: z.string().min(1).optional(),
}).strict();

const BatchSearch = z.object({
  kind: z.literal("search"),
  query: z.string().min(1),
  limit: z.number().int().min(1).max(50).default(10),
}).strict();

export const CtxBatchRequest = z.object({
  items: z.array(z.union([BatchShell, BatchSearch])).min(1).max(50),
}).strict();

export const BatchItemResult = z.object({
  kind: z.enum(["shell", "search"]),
  ok: z.boolean(),
  stdout: z.string().optional(),
  snippets: z.array(Snippet).default([]),
  index: IndexRef.optional(),
  meta: SandboxMeta.optional(),
  error: ToolError.optional(),
}).strict();

export const CtxBatchResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_batch"),
  request_id: z.string().optional(),
  results: z.array(BatchItemResult),
  error: ToolError.optional(),
}).strict();

export const CtxIndexRequest = z.object({
  markdown: z.string().min(1),
  title: z.string().min(1).default("Indexed markdown"),
  uri: z.string().optional(),
  tags: z.array(z.string().min(1)).default([]),
}).strict();

export const CtxIndexResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_index"),
  request_id: z.string().optional(),
  index: IndexRef,
  chunks_indexed: z.number().int().nonnegative(),
  meta: z.object({
    project_hash: z.string().min(8),
    markdown_bytes: Bytes,
    created_at: ISO,
  }).strict(),
  error: ToolError.optional(),
}).strict();

const SearchResult = z.object({
  rank: z.number().int().min(1),
  chunk_id: z.string().min(1),
  doc_id: z.string().min(1),
  title: z.string().min(1),
  snippet: z.string().min(1),
  score: z.number(),
  uri: z.string().optional(),
}).strict();

export const CtxSearchRequest = z.object({
  query: z.string().min(1),
  limit: z.number().int().min(1).max(50).default(10),
  include_debug: z.boolean().default(false),
}).strict();

export const CtxSearchResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_search"),
  request_id: z.string().optional(),
  query: z.string(),
  results: z.array(SearchResult),
  meta: z.object({
    project_hash: z.string().min(8),
    strategy: z.enum(["fts_porter", "fts_trigram", "rrf", "substring"]),
    degraded: z.boolean(),
    suggestions: z.array(z.string()).default([]),
  }).strict(),
  debug: z.record(z.any()).optional(),
  error: ToolError.optional(),
}).strict();

export const CtxFetchIndexRequest = z.object({
  url: z.string().url(),
  force: z.boolean().default(false),
  title: z.string().min(1).optional(),
  intent: z.string().min(1).optional(),
}).strict();

export const CtxFetchIndexResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_fetch_index"),
  request_id: z.string().optional(),
  index: IndexRef,
  snippets: z.array(Snippet).default([]),
  meta: z.object({
    project_hash: z.string().min(8),
    fetched_at: ISO,
    from_cache: z.boolean(),
    http_status: z.number().int().optional(),
    markdown_bytes: Bytes,
  }).strict(),
  error: ToolError.optional(),
}).strict();

export const CtxStatsRequest = z.object({
  window: z.enum(["session", "24h", "7d", "all"]).default("session"),
}).strict();

export const CtxStatsResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_stats"),
  request_id: z.string().optional(),
  meta: z.object({
    project_hash: z.string().min(8),
    db_path: z.string().min(1),
    uptime_ms: Ms,
  }).strict(),
  savings: z.object({
    raw_bytes_total: Bytes,
    returned_bytes_total: Bytes,
    indexed_bytes_total: Bytes,
    reduction_ratio: z.number().min(0).max(1),
    reduction_percent: z.number().min(0).max(100),
  }).strict(),
  by_tool: z.record(z.object({
    calls: z.number().int().nonnegative(),
    raw_bytes: Bytes,
    returned_bytes: Bytes,
    indexed_bytes: Bytes,
  }).strict()),
  error: ToolError.optional(),
}).strict();

export const CtxDoctorRequest = z.object({}).strict();

export const CtxDoctorResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_doctor"),
  request_id: z.string().optional(),
  meta: z.object({
    project_root: z.string().min(1),
    project_hash: z.string().min(8),
    db_path: z.string().min(1),
    cache_dir: z.string().min(1),
  }).strict(),
  runtimes: z.record(z.object({
    available: z.boolean(),
    path: z.string().optional(),
    version: z.string().optional(),
  }).strict()),
  sqlite: z.object({
    backend: z.enum(["better-sqlite3", "node:sqlite", "bun:sqlite", "none"]),
    fts5: z.boolean(),
    trigram: z.boolean(),
    degraded: z.boolean(),
    warnings: z.array(z.string()).default([]),
  }).strict(),
  security: z.object({
    deny_bash_patterns: z.array(z.string()).default([]),
    deny_path_patterns: z.array(z.string()).default([]),
    allowlist_loaded: z.boolean(),
    denylist_loaded: z.boolean(),
  }).strict(),
  lifecycle_guard: z.object({
    parent_pid: z.number().int().nullable(),
    active: z.boolean(),
    last_check_at: ISO.optional(),
  }).strict(),
  error: ToolError.optional(),
}).strict();

export const CtxUpgradeRequest = z.object({
  rebuild: z.boolean().default(true),
  reconfigure: z.boolean().default(false),
  confirm: z.boolean().default(false),
}).strict();

export const CtxUpgradeResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_upgrade"),
  request_id: z.string().optional(),
  actions: z.array(z.string()).default([]),
  meta: z.object({
    project_hash: z.string().min(8),
    duration_ms: Ms,
  }).strict(),
  error: ToolError.optional(),
}).strict();

export const CtxPurgeRequest = z.object({
  confirm: z.boolean(),
  delete_db: z.boolean().default(false),
}).strict();

export const CtxPurgeResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_purge"),
  request_id: z.string().optional(),
  meta: z.object({
    project_hash: z.string().min(8),
    deleted_docs: z.number().int().nonnegative(),
    deleted_chunks: z.number().int().nonnegative(),
    deleted_events: z.number().int().nonnegative(),
    cache_bytes_freed: Bytes,
  }).strict(),
  error: ToolError.optional(),
}).strict();

export const CtxDashboardOpenRequest = z.object({
  port: z.number().int().min(1024).max(65535).default(4747),
  host: z.string().default("127.0.0.1"),
}).strict();

export const CtxDashboardOpenResponse = z.object({
  ok: z.boolean(),
  tool: z.literal("ctx_dashboard_open"),
  request_id: z.string().optional(),
  url: z.string().url(),
  meta: z.object({
    host: z.string(),
    port: z.number().int(),
    started: z.boolean(),
  }).strict(),
  error: ToolError.optional(),
}).strict();

export const ToolRegistry = {
  ctx_execute: "ctx_execute",
  ctx_execute_file: "ctx_execute_file",
  ctx_batch: "ctx_batch",
  ctx_index: "ctx_index",
  ctx_search: "ctx_search",
  ctx_fetch_index: "ctx_fetch_index",
  ctx_stats: "ctx_stats",
  ctx_doctor: "ctx_doctor",
  ctx_upgrade: "ctx_upgrade",
  ctx_purge: "ctx_purge",
  ctx_dashboard_open: "ctx_dashboard_open",
} as const;

export type ToolError = z.infer<typeof ToolError>;
export type Snippet = z.infer<typeof Snippet>;
export type IndexRef = z.infer<typeof IndexRef>;
export type SandboxMeta = z.infer<typeof SandboxMeta>;
export type CtxExecuteRequest = z.infer<typeof CtxExecuteRequest>;
export type CtxExecuteFileRequest = z.infer<typeof CtxExecuteFileRequest>;
export type CtxBatchRequest = z.infer<typeof CtxBatchRequest>;
export type CtxIndexRequest = z.infer<typeof CtxIndexRequest>;
export type CtxSearchRequest = z.infer<typeof CtxSearchRequest>;
export type CtxFetchIndexRequest = z.infer<typeof CtxFetchIndexRequest>;
export type CtxStatsRequest = z.infer<typeof CtxStatsRequest>;
export type CtxDoctorRequest = z.infer<typeof CtxDoctorRequest>;
export type CtxUpgradeRequest = z.infer<typeof CtxUpgradeRequest>;
export type CtxPurgeRequest = z.infer<typeof CtxPurgeRequest>;
export type CtxDashboardOpenRequest = z.infer<typeof CtxDashboardOpenRequest>;
