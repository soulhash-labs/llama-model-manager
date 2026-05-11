import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import type { SqlBackend } from "./adapter";

export interface DbCapabilities {
  backend: "better-sqlite3" | "node:sqlite" | "bun:sqlite" | "none";
  fts5: boolean;
  trigram: boolean;
  warnings: string[];
}

export function ensureDbDirectory(dbPath: string): void {
  mkdirSync(dirname(dbPath), { recursive: true });
}

export function tableExists(db: SqlBackend, name: string): boolean {
  const row = db.get<{ c: number }>(
    `SELECT COUNT(*) as c FROM sqlite_master WHERE type='table' AND name = :name`,
    { name },
  );
  return Number(row?.c || 0) > 0;
}

function safeExecute(db: SqlBackend, sql: string): boolean;
function safeExecute(db: SqlBackend, sql: string, warnLabel: string): boolean;
function safeExecute(db: SqlBackend, sql: string, warnLabel?: string): boolean {
  try {
    db.execute(sql);
    return true;
  } catch (err) {
    if (warnLabel) {
      const msg = err instanceof Error ? err.message : String(err);
      process.stderr.write(`[MCP-DB-WARN] ${warnLabel}: ${msg}\n`);
    }
    return false;
  }
}

/** Silently add a column to a table — no-op if column already exists. */
function addColumnSilent(db: SqlBackend, sql: string): void {
  try { db.execute(sql); } catch { /* column already exists */ }
}

export function initSchema(db: SqlBackend): DbCapabilities {
  ensureDbDirectory(db.dbPath);
  const warnings: string[] = [];

  const coreTables = ["meta", "docs", "chunks", "events", "runs"];
  for (const table of coreTables) {
    if (!safeExecute(db, `CREATE TABLE IF NOT EXISTS ${getTableDef(table)}`, `create table ${table}`)) {
      warnings.push(`failed to create table: ${table}`);
    }
  }

  // Add incremental indexing columns to docs table (migration for existing databases).
  addColumnSilent(db, `ALTER TABLE docs ADD COLUMN mtime TEXT`);
  addColumnSilent(db, `ALTER TABLE docs ADD COLUMN content_hash TEXT`);

  const indexes = [
    ["idx_chunks_doc", "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)"],
    ["idx_events_project", "CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_hash, created_at DESC)"],
    ["idx_events_session", "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at DESC)"],
    ["idx_runs_tool", "CREATE INDEX IF NOT EXISTS idx_runs_tool ON runs(tool, created_at DESC)"],
  ];
  for (const [label, sql] of indexes) {
    if (!safeExecute(db, sql, `create index ${label}`)) {
      warnings.push(`failed to create index: ${label}`);
    }
  }

  let fts5 = false;
  let trigram = false;

  if (safeExecute(db, "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, h2_title, content_md)")) {
    fts5 = true;
  } else {
    warnings.push("FTS5 extension unavailable — search will fall back to substring matching (slower, no ranking)");
  }

  if (fts5 && safeExecute(db, `CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_trigram USING fts5(chunk_id UNINDEXED, h2_title, content_md, tokenize='trigram')`, "create trigram FTS")) {
    trigram = true;
  } else if (fts5) {
    warnings.push("Trigram tokenizer unavailable — fuzzy typo tolerance disabled");
  }

  try {
    db.execute(`INSERT OR REPLACE INTO meta(k,v) VALUES('backend', :v)`, { v: db.kind });
    db.execute(`INSERT OR REPLACE INTO meta(k,v) VALUES('fts5', :v)`, { v: String(fts5) });
    db.execute(`INSERT OR REPLACE INTO meta(k,v) VALUES('trigram', :v)`, { v: String(trigram) });
  } catch {
    warnings.push("failed to write capability metadata");
  }

  return { backend: db.kind, fts5, trigram, warnings };
}

function getTableDef(name: string): string {
  switch (name) {
    case "meta":
      return `meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)`;
    case "docs":
      return `docs (doc_id TEXT PRIMARY KEY, project_hash TEXT, source TEXT, uri TEXT, title TEXT, tags_json TEXT, mtime TEXT, content_hash TEXT, created_at TEXT)`;
    case "chunks":
      return `chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, h2_title TEXT, content_md TEXT, created_at TEXT, FOREIGN KEY (doc_id) REFERENCES docs(doc_id) ON DELETE CASCADE)`;
    case "events":
      return `events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, project_hash TEXT, session_id TEXT, category TEXT, payload_json TEXT, created_at TEXT)`;
    case "runs":
      return `runs (run_id TEXT PRIMARY KEY, tool TEXT, created_at TEXT, raw_bytes INT, returned_bytes INT, indexed_bytes INT, duration_ms INT, ok INT, meta_json TEXT)`;
    default:
      throw new Error(`unknown table: ${name}`);
  }
}

export function getMeta(db: SqlBackend, key: string): string | undefined {
  const row = db.get<{ v: string }>(`SELECT v FROM meta WHERE k = :k`, { k: key });
  return row?.v;
}
