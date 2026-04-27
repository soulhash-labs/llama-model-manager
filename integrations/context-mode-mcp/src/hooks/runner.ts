#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { openSqlBackend } from "../db/adapter";
import { initSchema } from "../db/schema";
import { emitHookEvent, indexCompactSnapshot } from "./events";
import { loadSecurityPolicy, resolveSessionContext } from "../utils/types";

interface CliArgs {
  category: string;
  projectRoot?: string;
  sessionId?: string;
}

function parseArgs(argv: string[]): CliArgs {
  const out: CliArgs = { category: "session_start" };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--category") out.category = argv[i + 1] || out.category;
    if (arg === "--project-root") out.projectRoot = argv[i + 1];
    if (arg === "--session-id") out.sessionId = argv[i + 1];
  }
  return out;
}

function readPayload(): unknown {
  try {
    const raw = readFileSync(0, "utf8");
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
    context.project_hash = context.project_hash; // stable
  }

  let db = await openSqlBackend(context.db_path);
  try {
    initSchema(db);
  } catch {
    return;
  }

  const payload = readPayload();
  const sessionId = args.sessionId || context.session_id || `session-${randomBytes(8).toString("hex")}`;

  if (["pre_tool_use", "post_tool_use", "session_start", "tool-result"].includes(args.category)) {
    emitHookEvent(db, {
      project_hash: context.project_hash,
      session_id: sessionId,
      category: args.category,
      payload,
    });
  }

  if (args.category === "pre_compact") {
    try {
      const doc = indexCompactSnapshot(db, context.project_hash, sessionId);
      emitHookEvent(db, {
        project_hash: context.project_hash,
        session_id: sessionId,
        category: "pre_compact",
        payload: { snapshot_doc: doc.doc_id, chunk_count: doc.chunk_ids.length },
      });
    } catch {
      // soft-fail
    }
  }

  db.close();
}

main().catch(() => {
  // hooks are intentionally soft-fail and should not block caller processes
});
