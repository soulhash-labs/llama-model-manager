import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative, sep } from "node:path";
import { shaHex } from "../utils/types";
import { indexDocument } from "../db/index";
import type { SqlBackend } from "../db/adapter";

// Files and directories to skip during project scan.
const SKIP_DIRS = new Set([
  "node_modules",
  ".git",
  "dist",
  "build",
  "out",
  ".next",
  ".nuxt",
  ".cache",
  "__pycache__",
  ".venv",
  "vendor",
  ".cargo",
  "target",
  "coverage",
  ".turbo",
]);

const SKIP_EXTS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
  ".woff", ".woff2", ".ttf", ".eot",
  ".map", ".lock", ".gz", ".zip", ".tar", ".tgz",
  ".wasm", ".exe", ".dll", ".so", ".dylib",
  ".db", ".sqlite", ".sqlite3",
]);

// Priority file extensions that get indexed first.
const INDEX_EXTENSIONS = new Map<string, string>([
  // Documentation
  [".md", "markdown"],
  [".mdx", "markdown"],
  [".txt", "text"],
  [".rst", "markdown"],
  // Code
  [".ts", "typescript"],
  [".tsx", "typescript-react"],
  [".js", "javascript"],
  [".jsx", "javascript-react"],
  [".py", "python"],
  [".go", "go"],
  [".rs", "rust"],
  [".rb", "ruby"],
  [".php", "php"],
  [".java", "java"],
  [".c", "c"],
  [".cpp", "cpp"],
  [".h", "c-header"],
  [".swift", "swift"],
  [".kt", "kotlin"],
  [".scala", "scala"],
  // Config
  [".json", "json"],
  [".yaml", "yaml"],
  [".yml", "yaml"],
  [".toml", "toml"],
  [".ini", "ini"],
  [".cfg", "config"],
  // Shell
  [".sh", "shell"],
  [".bash", "shell"],
  [".zsh", "shell"],
  [".fish", "shell"],
]);

const MAX_FILE_SIZE = 50_000; // 50KB per file
const MAX_FILES = 80; // Cap total indexed files per scan

interface ScanResult {
  indexed: number;
  skipped: number;
  errors: number;
  totalBytes: number;
  durationMs: number;
}

function shouldSkipDir(name: string): boolean {
  return SKIP_DIRS.has(name) || name.startsWith(".");
}

function walkDirectory(root: string, maxFiles: number): string[] {
  const files: string[] = [];
  const queue: string[] = [root];

  while (queue.length > 0 && files.length < maxFiles * 2) {
    const dir = queue.shift()!;
    let entries: Array<{ name: string; path: string; isDir: boolean }>;

    try {
      entries = readdirSync(dir, { withFileTypes: true }).map((e) => ({
        name: e.name,
        path: join(dir, e.name),
        isDir: e.isDirectory(),
      }));
    } catch {
      continue;
    }

    for (const entry of entries) {
      if (entry.isDir) {
        if (!shouldSkipDir(entry.name)) {
          queue.push(entry.path);
        }
        continue;
      }

      const ext = extname(entry.name).toLowerCase();
      if (SKIP_EXTS.has(ext)) continue;
      if (!INDEX_EXTENSIONS.has(ext)) continue;

      files.push(entry.path);
      if (files.length >= maxFiles * 2) break;
    }
  }

  return files;
}

function wrapCodeAsMarkdown(filePath: string, content: string, lang: string): string {
  const relPath = relative(process.cwd(), filePath).replace(/\\/g, "/");
  const lines = content.split(/\r?\n/);

  // Group lines into sections split by top-level declarations.
  // Each section becomes a ##-prefixed markdown block with a fenced code region,
  // so the heading-aware chunker can produce meaningful chunks.
  const sections: { heading: string; lines: string[] }[] = [];
  let currentLines: string[] = [];
  let currentHeading = `## File: ${relPath}`;

  function flushSection() {
    if (currentLines.length > 0) {
      sections.push({ heading: currentHeading, lines: currentLines });
      currentLines = [];
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();
    const isDeclaration =
      trimmed.startsWith("export ") ||
      trimmed.startsWith("export default ") ||
      trimmed.startsWith("export function ") ||
      trimmed.startsWith("export class ") ||
      trimmed.startsWith("export interface ") ||
      trimmed.startsWith("export type ") ||
      trimmed.startsWith("export const ") ||
      trimmed.startsWith("export async function ") ||
      trimmed.startsWith("export interface ") ||
      trimmed.startsWith("class ") ||
      trimmed.startsWith("interface ") ||
      trimmed.startsWith("type ") ||
      trimmed.startsWith("function ") ||
      trimmed.startsWith("async function ") ||
      trimmed.startsWith("const ") ||
      trimmed.startsWith("let ") ||
      trimmed.startsWith("def ") ||
      trimmed.startsWith("async def ") ||
      trimmed.startsWith("struct ") ||
      trimmed.startsWith("enum ") ||
      trimmed.startsWith("pub fn ") ||
      trimmed.startsWith("pub struct ") ||
      trimmed.startsWith("pub trait ") ||
      trimmed.startsWith("pub enum ") ||
      trimmed.startsWith("fn ") ||
      trimmed.startsWith("impl ") ||
      trimmed.startsWith("func ") ||
      trimmed.startsWith("var ") ||
      (trimmed.startsWith("import ") && trimmed.includes("from "));

    if (isDeclaration && currentLines.length > 0) {
      flushSection();
      // Create a heading from the declaration
      const heading = trimmed
        .replace(/^(export |export default |pub |async )?/, "")
        .replace(/\s*\{?\s*$/, "")
        .replace(/\s*\(.*\)\s*:.*$/, "")
        .replace(/\s*=>.*$/, "");
      currentHeading = `## ${heading || relPath}`;
    }

    currentLines.push(line);
  }

  flushSection();

  // Build markdown output: each section gets its heading + fenced code
  return sections
    .map((s) => `${s.heading}\n\n\`\`\`${lang}\n${s.lines.join("\n")}\n\`\`\``)
    .join("\n\n");
}

export function scanAndIndexProject(db: SqlBackend, projectRoot: string, projectHash: string): ScanResult {
  const started = Date.now();
  const result: ScanResult = { indexed: 0, skipped: 0, errors: 0, totalBytes: 0, durationMs: 0 };

  const files = walkDirectory(projectRoot, MAX_FILES);

  // Sort by extension priority: markdown first, then code, then config.
  const priority = (path: string): number => {
    const ext = extname(path).toLowerCase();
    if (ext === ".md" || ext === ".mdx") return 0;
    if (ext === ".ts" || ext === ".tsx") return 1;
    if (ext === ".py") return 2;
    return 3;
  };
  files.sort((a, b) => priority(a) - priority(b));

  let indexedCount = 0;
  let skippedUnchanged = 0;

  for (const filePath of files) {
    if (indexedCount >= MAX_FILES) break;

    let stat;
    try {
      stat = statSync(filePath);
    } catch {
      result.errors++;
      continue;
    }

    // Skip files that are too large
    if (stat.size > MAX_FILE_SIZE) {
      result.skipped++;
      continue;
    }

    // Skip empty files
    if (stat.size === 0) {
      result.skipped++;
      continue;
    }

    const ext = extname(filePath).toLowerCase();
    const lang = INDEX_EXTENSIONS.get(ext);
    if (!lang) {
      result.skipped++;
      continue;
    }

    let content: string;
    try {
      content = readFileSync(filePath, "utf8");
    } catch {
      result.errors++;
      continue;
    }

    if (!content.trim()) {
      result.skipped++;
      continue;
    }

    const relPath = relative(projectRoot, filePath).replace(/\\/g, "/");
    const title = relPath;
    const docId = `proj_${shaHex(filePath).slice(0, 16)}`;
    const contentHash = shaHex(content);
    const mtime = stat.mtime.toISOString();

    const markdown = lang === "markdown" || lang === "text"
      ? content
      : wrapCodeAsMarkdown(filePath, content, lang);

    try {
      const indexResult = indexDocument(db, {
        projectHash,
        source: "index",
        title,
        uri: `file://${filePath}`,
        markdown,
        tags: ["project-scan", lang, relPath.split(sep)[0] || "root"],
        docId,
        mtime,
        contentHash,
      });

      // indexDocument returns updated=false for unchanged files (incremental skip).
      if (indexResult.updated) {
        indexedCount++;
        result.totalBytes += Buffer.byteLength(markdown, "utf8");
      } else {
        skippedUnchanged++;
      }
    } catch {
      result.errors++;
    }
  }

  result.indexed = indexedCount;
  result.skipped += skippedUnchanged;
  result.durationMs = Date.now() - started;
  return result;
}
