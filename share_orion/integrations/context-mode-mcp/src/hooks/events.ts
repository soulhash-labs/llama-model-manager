import { chunkMarkdownByHeadings } from "../utils/chunker";
import { indexDocument } from "../db/index";
import type { SqlBackend } from "../db/adapter";

export interface HookPayload {
  project_hash: string;
  session_id: string;
  category: string;
  payload: unknown;
}

export function emitHookEvent(db: SqlBackend, payload: HookPayload): void {
  try {
    db.execute(
      `INSERT INTO events(project_hash, session_id, category, payload_json, created_at)
       VALUES(:project_hash, :session_id, :category, :payload_json, :created_at)`,
      {
        project_hash: payload.project_hash,
        session_id: payload.session_id,
        category: payload.category,
        payload_json: JSON.stringify(payload.payload || {}),
        created_at: new Date().toISOString(),
      },
    );
  } catch {
    // soft-fail
  }
}

function escapeText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function compactSessionSnapshotXml(db: SqlBackend, projectHash: string, sessionId: string): string {
  const rows = db.all<{ category: string; payload_json: string; created_at: string }>(
    `SELECT category, payload_json, created_at FROM events WHERE project_hash = :project_hash AND session_id = :session_id ORDER BY rowid DESC LIMIT 24`,
    { project_hash: projectHash, session_id: sessionId },
  );

  const eventXml = rows
    .map(
      (row) => `<event type="${escapeText(row.category)}" at="${escapeText(row.created_at)}">${escapeText(row.payload_json || "")}</event>`,
    )
    .join("");

  const xml = `<session id="${escapeText(sessionId)}"><events>${eventXml}</events></session>`;
  return xml.length > 2048 ? `${xml.slice(0, 2035)}...</session>` : xml;
}

export function indexCompactSnapshot(db: SqlBackend, projectHash: string, sessionId: string) {
  const xml = compactSessionSnapshotXml(db, projectHash, sessionId);
  const chunks = chunkMarkdownByHeadings(`<resume>${xml}</resume>`);
  const markdown = chunks.map((chunk) => `## ${chunk.title}\n\n${chunk.markdown}`).join("\n\n");

  return indexDocument(db, {
    projectHash,
    source: "events",
    title: `compact-${sessionId}`,
    uri: `ctx://session/${sessionId}`,
    markdown,
    tags: ["events", "precompact"],
  });
}
