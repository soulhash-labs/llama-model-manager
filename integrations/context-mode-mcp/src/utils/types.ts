import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { createHash, randomBytes } from "node:crypto";
import path from "node:path";

export type ToolErrorCode =
  | "INVALID_INPUT"
  | "DENIED"
  | "TIMEOUT"
  | "NOT_FOUND"
  | "FETCH_FAILED"
  | "EXEC_FAILED"
  | "DB_UNAVAILABLE"
  | "FTS_UNAVAILABLE"
  | "INTERNAL"
  | "DEGRADED";

export interface ToolErrorLike {
  code: ToolErrorCode;
  message: string;
  details?: Record<string, unknown>;
}

export interface ContextPaths {
  project_root: string;
  project_hash: string;
  db_path: string;
  cache_dir: string;
  session_id: string;
}

export function newRequestId(): string {
  return randomBytes(8).toString("hex");
}

export function shaHex(input: string): string {
  return createHash("sha256").update(input).digest("hex");
}

export function resolveProjectRoot(): string {
  const override = process.env.CTX_PROJECT_ROOT;
  try {
    return realpathSync(override || process.cwd());
  } catch {
    return override ? override : process.cwd();
  }
}

export function resolveSessionContext(): ContextPaths {
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
    session_id,
  };
}

export interface SecurityPolicy {
  allowlistPatterns: string[];
  denylistPatterns: string[];
  denyBashPatterns: string[];
  denyPathPatterns: string[];
  allowlistLoaded: boolean;
  denylistLoaded: boolean;
}

const DEFAULT_DENY_BASH = [
  "\\b(shutdown|reboot|poweroff|halt)\\b",
  "\\bmkfs\\b",
  "\\bdd\\s",
  "\\brm\\s+-rf",
  "\\bchmod\\s+(-R)?\\s*777",
  "\\bchown\\s",
  "\\biptables\\b",
  "\\buserdel\\b",
  "\\buseradd\\b",
  "\\bpasswd\\b",
];

const DEFAULT_DENY_PATH = [
  "^/etc/",
  "^/usr/bin/",
  "^/usr/sbin/",
  "^/boot/",
  "^/proc/",
  "^/sys/",
  "^/root/",
];

function readList(filePath?: string): string[] {
  if (!filePath) return [];
  try {
    const raw = readFileSync(filePath, "utf8");
    return raw
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && !line.startsWith("#"));
  } catch {
    return [];
  }
}

export function loadSecurityPolicy(projectRoot: string): SecurityPolicy {
  const allowlistFile = path.join(projectRoot, "ALLOWLIST.md");
  const denylistFile = path.join(projectRoot, "DENYLIST.md");

  const allowlistPatterns = readList(allowlistFile);
  const denylistPatterns = readList(denylistFile);

  return {
    allowlistPatterns,
    denylistPatterns,
    denyBashPatterns: [...DEFAULT_DENY_BASH],
    denyPathPatterns: [...DEFAULT_DENY_PATH],
    allowlistLoaded: allowlistPatterns.length > 0,
    denylistLoaded: denylistPatterns.length > 0,
  };
}

function matchAny(patterns: string[], target: string): boolean {
  return patterns.some((pattern) => {
    try {
      const re = new RegExp(pattern, "i");
      return re.test(target);
    } catch {
      return target.includes(pattern);
    }
  });
}

export function isCommandAllowed(command: string, security: SecurityPolicy): { allowed: boolean; reason?: string } {
  if (security.allowlistPatterns.length > 0 && !matchAny(security.allowlistPatterns, command)) {
    return { allowed: false, reason: "command not in allowlist" };
  }

  if (security.denylistPatterns.length > 0 && matchAny(security.denylistPatterns, command)) {
    return { allowed: false, reason: "command matched denylist" };
  }

  if (security.denyBashPatterns.length > 0 && matchAny(security.denyBashPatterns, command)) {
    return { allowed: false, reason: "command matched deny pattern" };
  }

  return { allowed: true };
}

export function isPathAllowed(filePath: string, security: SecurityPolicy): { allowed: boolean; reason?: string } {
  if (matchAny(security.denyPathPatterns, filePath)) {
    return { allowed: false, reason: "path denied by policy" };
  }

  if (security.allowlistPatterns.length > 0 && !matchAny(security.allowlistPatterns, filePath)) {
    return { allowed: false, reason: "path not in allowlist" };
  }

  return { allowed: true };
}
