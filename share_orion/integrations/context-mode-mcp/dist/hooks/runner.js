#!/usr/bin/env node

// src/hooks/runner.ts
import { readFileSync as readFileSync2 } from "node:fs";
import { randomBytes as randomBytes3 } from "node:crypto";

// src/db/adapter.ts
import { createRequire } from "node:module";
function isNamedParams(params) {
  return Boolean(params) && !Array.isArray(params);
}
function paramValues(params) {
  if (!params || Array.isArray(params)) return params ? params : [];
  return Object.values(params);
}
async function openBetterSqlite(dbPath) {
  try {
    const req = createRequire(import.meta.url);
    const sqlite = req("better-sqlite3");
    const DatabaseCtor = sqlite?.Database ?? sqlite?.default?.Database ?? sqlite?.default ?? sqlite;
    if (typeof DatabaseCtor !== "function") return null;
    if (!DatabaseCtor) return null;
    const db = new DatabaseCtor(dbPath);
    const execute = (sql, params = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) {
        statement.run(params);
      } else {
        statement.run(...paramValues(params));
      }
    };
    const all = (sql, params = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.all(params);
      return statement.all(...paramValues(params));
    };
    const get = (sql, params = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.get(params);
      return statement.get(...paramValues(params));
    };
    return {
      kind: "better-sqlite3",
      dbPath,
      execute,
      all,
      get,
      close() {
        db.close();
      }
    };
  } catch {
    return null;
  }
}
async function openNodeSqlite(dbPath) {
  try {
    const sqlite = await import("node:sqlite");
    const DatabaseSync = sqlite.DatabaseSync;
    if (!DatabaseSync) return null;
    const db = new DatabaseSync(dbPath);
    const execute = (sql, params = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) statement.run(params);
      else statement.run(...paramValues(params));
    };
    const all = (sql, params = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.all(params);
      return statement.all(...paramValues(params));
    };
    const get = (sql, params = []) => {
      const statement = db.prepare(sql);
      if (isNamedParams(params)) return statement.get(params);
      return statement.get(...paramValues(params));
    };
    return {
      kind: "node:sqlite",
      dbPath,
      execute,
      all,
      get,
      close() {
        db.close();
      }
    };
  } catch {
    return null;
  }
}
async function openBunSqlite(dbPath) {
  try {
    const sqlite = await import("bun:sqlite");
    const DatabaseCtor = sqlite.Database;
    if (!DatabaseCtor) return null;
    const db = new DatabaseCtor(dbPath, { create: true });
    const execute = (sql, params = []) => {
      const statement = db.query(sql);
      if (isNamedParams(params)) statement.run(params);
      else statement.run(...paramValues(params));
    };
    const all = (sql, params = []) => {
      const statement = db.query(sql);
      if (isNamedParams(params)) return statement.all(params);
      return statement.all(...paramValues(params));
    };
    const get = (sql, params = []) => {
      const statement = db.query(sql);
      if (isNamedParams(params)) return statement.get(params);
      return statement.get(...paramValues(params));
    };
    return {
      kind: "bun:sqlite",
      dbPath,
      execute,
      all,
      get,
      close() {
        db.close();
      }
    };
  } catch {
    return null;
  }
}
function openFallbackBackend(dbPath) {
  return {
    kind: "none",
    dbPath,
    execute() {
      throw new Error("No sqlite backend available");
    },
    all() {
      throw new Error("No sqlite backend available");
    },
    get() {
      throw new Error("No sqlite backend available");
    },
    close() {
    }
  };
}
async function openSqlBackend(dbPath) {
  const better = await openBetterSqlite(dbPath);
  if (better) return better;
  const node = await openNodeSqlite(dbPath);
  if (node) return node;
  const bun = await openBunSqlite(dbPath);
  if (bun) return bun;
  return openFallbackBackend(dbPath);
}

// src/db/schema.ts
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
function ensureDbDirectory(dbPath) {
  mkdirSync(dirname(dbPath), { recursive: true });
}
function tableExists(db, name) {
  const row = db.get(
    `SELECT COUNT(*) as c FROM sqlite_master WHERE type='table' AND name = :name`,
    { name }
  );
  return Number(row?.c || 0) > 0;
}
function safeExecute(db, sql, warnLabel) {
  try {
    db.execute(sql);
    return true;
  } catch (err) {
    if (warnLabel) {
      const msg = err instanceof Error ? err.message : String(err);
      process.stderr.write(`[MCP-DB-WARN] ${warnLabel}: ${msg}
`);
    }
    return false;
  }
}
function addColumnSilent(db, sql) {
  try {
    db.execute(sql);
  } catch {
  }
}
function initSchema(db) {
  ensureDbDirectory(db.dbPath);
  const warnings = [];
  const coreTables = ["meta", "docs", "chunks", "events", "runs"];
  for (const table of coreTables) {
    if (!safeExecute(db, `CREATE TABLE IF NOT EXISTS ${getTableDef(table)}`, `create table ${table}`)) {
      warnings.push(`failed to create table: ${table}`);
    }
  }
  addColumnSilent(db, `ALTER TABLE docs ADD COLUMN mtime TEXT`);
  addColumnSilent(db, `ALTER TABLE docs ADD COLUMN content_hash TEXT`);
  const indexes = [
    ["idx_chunks_doc", "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)"],
    ["idx_events_project", "CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_hash, created_at DESC)"],
    ["idx_events_session", "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at DESC)"],
    ["idx_runs_tool", "CREATE INDEX IF NOT EXISTS idx_runs_tool ON runs(tool, created_at DESC)"]
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
    warnings.push("FTS5 extension unavailable \u2014 search will fall back to substring matching (slower, no ranking)");
  }
  if (fts5 && safeExecute(db, `CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_trigram USING fts5(chunk_id UNINDEXED, h2_title, content_md, tokenize='trigram')`, "create trigram FTS")) {
    trigram = true;
  } else if (fts5) {
    warnings.push("Trigram tokenizer unavailable \u2014 fuzzy typo tolerance disabled");
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
function getTableDef(name) {
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

// src/utils/chunker.ts
var MAX_CHUNK_CHARS = 12e3;
function isCodeFence(line) {
  return /^\s*```/.test(line);
}
function splitSections(lines, headingPrefix) {
  const sections = [];
  let current = [];
  let inFence = false;
  for (const line of lines) {
    const fence = isCodeFence(line);
    if (fence) inFence = !inFence;
    const isHeading = !inFence && line.startsWith(headingPrefix);
    if (isHeading && current.length > 0) {
      sections.push(current);
      current = [line];
      continue;
    }
    if (current.length === 0) {
      current.push(line);
      continue;
    }
    current.push(line);
  }
  if (current.length > 0) sections.push(current);
  return sections;
}
function splitLargeSection(lines, h2Title) {
  const raw = lines.join("\n").trim();
  if (raw.length <= MAX_CHUNK_CHARS) {
    return [{ title: h2Title, markdown: raw }];
  }
  const chunks = [];
  const h3Segments = splitSections(lines, "### ");
  if (h3Segments.length === 1) {
    let current = [];
    let currentSize = 0;
    let part = 1;
    for (const line of lines) {
      if (currentSize + line.length + 1 > MAX_CHUNK_CHARS && current.length > 0) {
        chunks.push({ title: `${h2Title} (part ${part})`, markdown: current.join("\n").trim() });
        current = [line];
        currentSize = line.length;
        part += 1;
      } else {
        current.push(line);
        currentSize += line.length + 1;
      }
    }
    if (current.length) {
      chunks.push({ title: `${h2Title} (part ${part})`, markdown: current.join("\n").trim() });
    }
    return chunks;
  }
  for (const segment of h3Segments) {
    if (segment.length === 0) continue;
    const titleLine = segment[0];
    const subTitle = titleLine.replace(/^###\s+/, "");
    const normalized = segment.join("\n").trim();
    if (normalized.length <= MAX_CHUNK_CHARS) {
      chunks.push({ title: `${h2Title} \xBB ${subTitle}`, markdown: normalized });
      continue;
    }
    let current = [];
    let currentSize = 0;
    let part = 1;
    for (const line of segment) {
      if (currentSize + line.length + 1 > MAX_CHUNK_CHARS && current.length > 0) {
        chunks.push({ title: `${h2Title} \xBB ${subTitle} (part ${part})`, markdown: current.join("\n").trim() });
        current = [line];
        currentSize = line.length;
        part += 1;
      } else {
        current.push(line);
        currentSize += line.length + 1;
      }
    }
    if (current.length) {
      chunks.push({ title: `${h2Title} \xBB ${subTitle} (part ${part})`, markdown: current.join("\n").trim() });
    }
  }
  return chunks;
}
function chunkMarkdownByHeadings(markdown) {
  const trimmed = (markdown || "").trim();
  if (!trimmed) return [];
  const lines = trimmed.split(/\r?\n/);
  const h2Sections = splitSections(lines, "## ");
  const chunks = [];
  for (const section of h2Sections) {
    if (!section.length) continue;
    const titleLine = section.find((line) => line.startsWith("## ")) || "## Untitled";
    const h2Title = titleLine.replace(/^##\s+/, "");
    chunks.push(...splitLargeSection(section, h2Title));
  }
  return chunks;
}

// src/db/index.ts
import { randomBytes } from "node:crypto";

// src/utils/timing.ts
function toISO(value = /* @__PURE__ */ new Date()) {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "number") return new Date(value).toISOString();
  return new Date(value).toISOString();
}

// src/db/index.ts
function chunkId(prefix, index) {
  return `${prefix}_${String(index).padStart(4, "0")}`;
}
function toChunks(markdown, fallbackTitle) {
  const chunks = chunkMarkdownByHeadings(markdown);
  if (chunks.length > 0) return chunks;
  return [{ title: fallbackTitle, markdown }];
}
function insertFts(db, table, chunkIdValue, h2Title, content) {
  if (!tableExists(db, table)) return;
  try {
    db.execute(`INSERT INTO ${table}(chunk_id, h2_title, content_md) VALUES(:chunk_id, :h2_title, :content_md)`, {
      chunk_id: chunkIdValue,
      h2_title: h2Title,
      content_md: content
    });
  } catch {
  }
}
function indexDocument(db, input) {
  const now = toISO();
  const chunks = toChunks(input.markdown || "", input.title || "Indexed document");
  const docId = input.docId || `doc_${randomBytes(8).toString("hex")}`;
  if (input.docId && input.contentHash) {
    const existing = db.get(
      `SELECT content_hash FROM docs WHERE doc_id = :doc_id`,
      { doc_id: input.docId }
    );
    if (existing && existing.content_hash === input.contentHash) {
      const existingChunks = db.all(
        `SELECT chunk_id FROM chunks WHERE doc_id = :doc_id`,
        { doc_id: input.docId }
      );
      return {
        doc_id: input.docId,
        chunk_ids: existingChunks.map((r) => r.chunk_id),
        source: input.source,
        uri: input.uri,
        title: input.title,
        updated: false
      };
    }
  }
  if (input.docId) {
    const oldChunks = db.all(
      `SELECT chunk_id FROM chunks WHERE doc_id = :doc_id`,
      { doc_id: input.docId }
    );
    for (const chunk of oldChunks) {
      try {
        db.execute(`DELETE FROM chunks_fts WHERE chunk_id = :id`, { id: chunk.chunk_id });
      } catch {
      }
      try {
        db.execute(`DELETE FROM chunks_fts_trigram WHERE chunk_id = :id`, { id: chunk.chunk_id });
      } catch {
      }
    }
    db.execute(`DELETE FROM chunks WHERE doc_id = :doc_id`, { doc_id: input.docId });
    db.execute(`DELETE FROM docs WHERE doc_id = :doc_id`, { doc_id: input.docId });
  }
  db.execute(
    `INSERT INTO docs(doc_id, project_hash, source, uri, title, tags_json, mtime, content_hash, created_at)
     VALUES(:doc_id, :project_hash, :source, :uri, :title, :tags_json, :mtime, :content_hash, :created_at)`,
    {
      doc_id: docId,
      project_hash: input.projectHash,
      source: input.source,
      uri: input.uri || "",
      title: input.title,
      tags_json: JSON.stringify(input.tags || []),
      mtime: input.mtime || "",
      content_hash: input.contentHash || "",
      created_at: now
    }
  );
  const chunkIds = [];
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
        created_at: now
      }
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
    updated: true
  };
}

// src/hooks/events.ts
function emitHookEvent(db, payload) {
  try {
    db.execute(
      `INSERT INTO events(project_hash, session_id, category, payload_json, created_at)
       VALUES(:project_hash, :session_id, :category, :payload_json, :created_at)`,
      {
        project_hash: payload.project_hash,
        session_id: payload.session_id,
        category: payload.category,
        payload_json: JSON.stringify(payload.payload || {}),
        created_at: (/* @__PURE__ */ new Date()).toISOString()
      }
    );
  } catch {
  }
}
function escapeText(value) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function compactSessionSnapshotXml(db, projectHash, sessionId) {
  const rows = db.all(
    `SELECT category, payload_json, created_at FROM events WHERE project_hash = :project_hash AND session_id = :session_id ORDER BY rowid DESC LIMIT 24`,
    { project_hash: projectHash, session_id: sessionId }
  );
  const eventXml = rows.map(
    (row) => `<event type="${escapeText(row.category)}" at="${escapeText(row.created_at)}">${escapeText(row.payload_json || "")}</event>`
  ).join("");
  const xml = `<session id="${escapeText(sessionId)}"><events>${eventXml}</events></session>`;
  return xml.length > 2048 ? `${xml.slice(0, 2035)}...</session>` : xml;
}
function indexCompactSnapshot(db, projectHash, sessionId) {
  const xml = compactSessionSnapshotXml(db, projectHash, sessionId);
  const chunks = chunkMarkdownByHeadings(`<resume>${xml}</resume>`);
  const markdown = chunks.map((chunk) => `## ${chunk.title}

${chunk.markdown}`).join("\n\n");
  return indexDocument(db, {
    projectHash,
    source: "events",
    title: `compact-${sessionId}`,
    uri: `ctx://session/${sessionId}`,
    markdown,
    tags: ["events", "precompact"]
  });
}

// src/utils/types.ts
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { createHash, randomBytes as randomBytes2 } from "node:crypto";
import path from "node:path";
function shaHex(input) {
  return createHash("sha256").update(input).digest("hex");
}
function resolveProjectRoot() {
  const override = process.env.CTX_PROJECT_ROOT;
  try {
    return realpathSync(override || process.cwd());
  } catch {
    return override ? override : process.cwd();
  }
}
function resolveSessionContext() {
  const project_root = resolveProjectRoot();
  const project_hash = shaHex(project_root).slice(0, 16);
  const base = path.join(homedir(), ".claude", "context-mode");
  const db_path = path.join(base, "sessions", `${project_hash}.db`);
  const cache_dir = path.join(base, "cache", project_hash);
  const session_file = path.join(base, "session-id.txt");
  let session_id = `session_${process.pid}`;
  try {
    if (existsSync(session_file)) {
      const raw = readFileSync(session_file, "utf8").trim();
      if (raw) session_id = raw;
    }
  } catch {
    session_id = `session_${process.pid}`;
  }
  return {
    project_root,
    project_hash,
    db_path,
    cache_dir,
    session_id
  };
}

// src/hooks/runner.ts
function parseArgs(argv) {
  const out = { category: "session_start" };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--category") out.category = argv[i + 1] || out.category;
    if (arg === "--project-root") out.projectRoot = argv[i + 1];
    if (arg === "--session-id") out.sessionId = argv[i + 1];
  }
  return out;
}
function readPayload() {
  try {
    const raw = readFileSync2(0, "utf8");
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}
async function main() {
  const args = parseArgs(process.argv.slice(2));
  const context = resolveSessionContext();
  if (args.projectRoot) {
    context.project_root = args.projectRoot;
    context.project_hash = context.project_hash;
  }
  let db = await openSqlBackend(context.db_path);
  try {
    initSchema(db);
  } catch {
    return;
  }
  const payload = readPayload();
  const sessionId = args.sessionId || context.session_id || `session-${randomBytes3(8).toString("hex")}`;
  if (["pre_tool_use", "post_tool_use", "session_start", "tool-result"].includes(args.category)) {
    emitHookEvent(db, {
      project_hash: context.project_hash,
      session_id: sessionId,
      category: args.category,
      payload
    });
  }
  if (args.category === "pre_compact") {
    try {
      const doc = indexCompactSnapshot(db, context.project_hash, sessionId);
      emitHookEvent(db, {
        project_hash: context.project_hash,
        session_id: sessionId,
        category: "pre_compact",
        payload: { snapshot_doc: doc.doc_id, chunk_count: doc.chunk_ids.length }
      });
    } catch {
    }
  }
  db.close();
}
main().catch(() => {
});
