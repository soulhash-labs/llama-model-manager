import { randomBytes } from "node:crypto";
import { existsSync, rmSync } from "node:fs";
import { chunkMarkdownByHeadings } from "../utils/chunker";
import { toISO } from "../utils/timing";
import { tableExists } from "./schema";
import type { SqlBackend } from "./adapter";

export interface IndexInput {
  projectHash: string;
  source: "execute" | "execute_file" | "index" | "fetch" | "events";
  uri?: string;
  title: string;
  markdown: string;
  tags?: string[];
}

export interface IndexResult {
  doc_id: string;
  chunk_ids: string[];
  source: "execute" | "execute_file" | "index" | "fetch" | "events";
  uri?: string;
  title?: string;
}

function chunkId(prefix: string, index: number): string {
  return `${prefix}_${String(index).padStart(4, "0")}`;
}

function toChunks(markdown: string, fallbackTitle: string) {
  const chunks = chunkMarkdownByHeadings(markdown);
  if (chunks.length > 0) return chunks;
  return [{ title: fallbackTitle, markdown }];
}

function insertFts(db: SqlBackend, table: string, chunkIdValue: string, h2Title: string, content: string) {
  if (!tableExists(db, table)) return;
  try {
    db.execute(`INSERT INTO ${table}(chunk_id, h2_title, content_md) VALUES(:chunk_id, :h2_title, :content_md)`, {
      chunk_id: chunkIdValue,
      h2_title: h2Title,
      content_md: content,
    });
  } catch {
    // best-effort: continue when FTS unavailable or read-only.
  }
}

function placeHolders(count: number): string {
  return Array.from({ length: count }, () => "?").join(",");
}

export function indexDocument(db: SqlBackend, input: IndexInput): IndexResult {
  const docId = `doc_${randomBytes(8).toString("hex")}`;
  const now = toISO();
  const chunks = toChunks(input.markdown || "", input.title || "Indexed document");

  db.execute(
    `INSERT INTO docs(doc_id, project_hash, source, uri, title, tags_json, created_at)
     VALUES(:doc_id, :project_hash, :source, :uri, :title, :tags_json, :created_at)`,
    {
      doc_id: docId,
      project_hash: input.projectHash,
      source: input.source,
      uri: input.uri || "",
      title: input.title,
      tags_json: JSON.stringify(input.tags || []),
      created_at: now,
    },
  );

  const chunkIds: string[] = [];
  chunks.forEach((chunk, idx) => {
    const body = (chunk.markdown || "").trim();
    if (!body) return;

    const chunkIdValue = chunkId(docId, idx + 1);
    const title = chunk.title || input.title;

    db.execute(
      `INSERT INTO chunks(chunk_id, doc_id, h2_title, content_md, created_at)
       VALUES(:chunk_id, :doc_id, :h2_title, :content_md, :created_at)`,
      {
        chunk_id: chunkIdValue,
        doc_id: docId,
        h2_title: title,
        content_md: body,
        created_at: now,
      },
    );

    insertFts(db, "chunks_fts", chunkIdValue, title, body);
    insertFts(db, "chunks_fts_trigram", chunkIdValue, title, body);
    chunkIds.push(chunkIdValue);
  });

  return {
    doc_id: docId,
    chunk_ids: chunkIds,
    source: input.source,
    uri: input.uri,
    title: input.title,
  };
}

export function getChunkRows(db: SqlBackend, chunkIds: string[]): Array<{ chunk_id: string; doc_id: string; h2_title: string; content_md: string }>{
  if (!chunkIds.length) return [];
  const rows = db.all<{
    chunk_id: string;
    doc_id: string;
    h2_title: string;
    content_md: string;
  }>(`SELECT chunk_id, doc_id, h2_title, content_md FROM chunks WHERE chunk_id IN (${placeHolders(chunkIds.length)})`, chunkIds);
  return rows;
}

export function purgeProject(db: SqlBackend, projectHash: string) {
  const docRows = db.all<{ doc_id: string }>(`SELECT doc_id FROM docs WHERE project_hash = :project_hash`, {
    project_hash: projectHash,
  });

  const docIds = docRows.map((row) => row.doc_id);
  const deleted: { deleted_docs: number; deleted_chunks: number; deleted_events: number } = {
    deleted_docs: docRows.length,
    deleted_chunks: 0,
    deleted_events: 0,
  };

  if (docIds.length > 0) {
    const chunkRows = db.all<{ chunk_id: string }>(
      `SELECT chunk_id FROM chunks WHERE doc_id IN (${placeHolders(docIds.length)})`,
      docIds,
    );
    const chunkIds = chunkRows.map((row) => row.chunk_id);
    deleted.deleted_chunks = chunkIds.length;

    if (tableExists(db, "chunks_fts")) {
      if (chunkIds.length > 0) {
        db.execute(`DELETE FROM chunks_fts WHERE chunk_id IN (${placeHolders(chunkIds.length)})`, chunkIds);
      }
    }
    if (tableExists(db, "chunks_fts_trigram")) {
      if (chunkIds.length > 0) {
        db.execute(`DELETE FROM chunks_fts_trigram WHERE chunk_id IN (${placeHolders(chunkIds.length)})`, chunkIds);
      }
    }

    if (chunkIds.length > 0) {
      db.execute(`DELETE FROM chunks WHERE chunk_id IN (${placeHolders(chunkIds.length)})`, chunkIds);
    }

    db.execute(`DELETE FROM docs WHERE doc_id IN (${placeHolders(docIds.length)})`, docIds);
  }

  const eventsDeleted = db.get<{ c: number }>(`SELECT COUNT(*) as c FROM events WHERE project_hash = :project_hash`, {
    project_hash: projectHash,
  });
  deleted.deleted_events = Number(eventsDeleted?.c || 0);

  db.execute(`DELETE FROM events WHERE project_hash = :project_hash`, {
    project_hash: projectHash,
  });
  db.execute(`DELETE FROM runs WHERE tool LIKE 'ctx_%'`);

  return deleted;
}

export function recordRun(
  db: SqlBackend,
  run: {
    run_id: string;
    tool: string;
    created_at: string;
    raw_bytes: number;
    returned_bytes: number;
    indexed_bytes: number;
    duration_ms: number;
    ok: boolean;
    meta_json: string;
  },
) {
  db.execute(
    `INSERT INTO runs(run_id, tool, created_at, raw_bytes, returned_bytes, indexed_bytes, duration_ms, ok, meta_json)
     VALUES(:run_id, :tool, :created_at, :raw_bytes, :returned_bytes, :indexed_bytes, :duration_ms, :ok, :meta_json)`,
    {
      run_id: run.run_id,
      tool: run.tool,
      created_at: run.created_at,
      raw_bytes: run.raw_bytes,
      returned_bytes: run.returned_bytes,
      indexed_bytes: run.indexed_bytes,
      duration_ms: run.duration_ms,
      ok: run.ok ? 1 : 0,
      meta_json: run.meta_json,
    },
  );
}

export function recordEvent(db: SqlBackend, projectHash: string, sessionId: string, category: string, payload: unknown) {
  db.execute(
    `INSERT INTO events(project_hash, session_id, category, payload_json, created_at)
     VALUES(:project_hash, :session_id, :category, :payload_json, :created_at)`,
    {
      project_hash: projectHash,
      session_id: sessionId,
      category,
      payload_json: JSON.stringify(payload || {}),
      created_at: toISO(),
    },
  );
}

export function getDbCapabilities(db: SqlBackend): {
  backend: "better-sqlite3" | "node:sqlite" | "bun:sqlite" | "none";
  fts5: boolean;
  trigram: boolean;
  degraded: boolean;
} {
  let fts5 = false;
  let trigram = false;

  try {
    fts5 = tableExists(db, "chunks_fts");
    if (fts5) trigram = tableExists(db, "chunks_fts_trigram");
  } catch {
    fts5 = false;
    trigram = false;
  }

  return {
    backend: db.kind,
    fts5,
    trigram,
    degraded: db.kind === "none" || !fts5,
  };
}

export function safeDeleteDbFile(path: string): void {
  if (existsSync(path)) {
    rmSync(path, { force: true });
  }
}
