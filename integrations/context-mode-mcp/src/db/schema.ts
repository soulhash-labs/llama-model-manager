import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import type { SqlBackend } from "./adapter";

export interface DbCapabilities {
  backend: "better-sqlite3" | "node:sqlite" | "bun:sqlite" | "none";
  fts5: boolean;
  trigram: boolean;
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

function safeExecute(db: SqlBackend, sql: string) {
  try {
    db.execute(sql);
    return true;
  } catch {
    return false;
  }
}

export function initSchema(db: SqlBackend): DbCapabilities {
  ensureDbDirectory(db.dbPath);

  safeExecute(
    db,
    `CREATE TABLE IF NOT EXISTS meta (
      k TEXT PRIMARY KEY,
      v TEXT NOT NULL
    )`,
  );
  safeExecute(
    db,
    `CREATE TABLE IF NOT EXISTS docs (
      doc_id TEXT PRIMARY KEY,
      project_hash TEXT,
      source TEXT,
      uri TEXT,
      title TEXT,
      tags_json TEXT,
      created_at TEXT
    )`,
  );
  safeExecute(
    db,
    `CREATE TABLE IF NOT EXISTS chunks (
      chunk_id TEXT PRIMARY KEY,
      doc_id TEXT NOT NULL,
      h2_title TEXT,
      content_md TEXT,
      created_at TEXT,
      FOREIGN KEY (doc_id) REFERENCES docs(doc_id) ON DELETE CASCADE
    )`,
  );
  safeExecute(
    db,
    `CREATE TABLE IF NOT EXISTS events (
      event_id INTEGER PRIMARY KEY AUTOINCREMENT,
      project_hash TEXT,
      session_id TEXT,
      category TEXT,
      payload_json TEXT,
      created_at TEXT
    )`,
  );
  safeExecute(
    db,
    `CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY,
      tool TEXT,
      created_at TEXT,
      raw_bytes INT,
      returned_bytes INT,
      indexed_bytes INT,
      duration_ms INT,
      ok INT,
      meta_json TEXT
    )`,
  );

  safeExecute(db, `CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)`);
  safeExecute(db, `CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_hash, created_at DESC)`);
  safeExecute(db, `CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at DESC)`);
  safeExecute(db, `CREATE INDEX IF NOT EXISTS idx_runs_tool ON runs(tool, created_at DESC)`);

  let fts5 = false;
  let trigram = false;

  if (safeExecute(db, "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, h2_title, content_md)")) {
    fts5 = true;
  }

  if (fts5 && safeExecute(db, `CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_trigram USING fts5(chunk_id UNINDEXED, h2_title, content_md, tokenize='trigram')`)) {
    trigram = true;
  }

  try {
    db.execute(`INSERT OR REPLACE INTO meta(k,v) VALUES('backend', :v)`, { v: db.kind });
    db.execute(`INSERT OR REPLACE INTO meta(k,v) VALUES('fts5', :v)`, { v: String(fts5) });
    db.execute(`INSERT OR REPLACE INTO meta(k,v) VALUES('trigram', :v)`, { v: String(trigram) });
  } catch {
    // best-effort
  }

  return { backend: db.kind, fts5, trigram };
}

export function getMeta(db: SqlBackend, key: string): string | undefined {
  const row = db.get<{ v: string }>(`SELECT v FROM meta WHERE k = :k`, { k: key });
  return row?.v;
}
