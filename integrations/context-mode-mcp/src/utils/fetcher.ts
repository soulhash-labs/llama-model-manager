import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import createWindow from "domino";
import TurndownService from "turndown";

const turndown = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced", bulletListMarker: "-" });

interface CachedFetch {
  status: number;
  headers: Record<string, string>;
  body: string;
  fetched_at: string;
}

export interface FetchResult {
  markdown: string;
  from_cache: boolean;
  status: number;
  bytes: number;
}

function cachePath(cacheDir: string, url: string): string {
  const key = createHash("sha256").update(url).digest("hex");
  return join(cacheDir, `${key}.json`);
}

function fromHtml(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("<")) return raw;
  const window = createWindow(trimmed);
  const body = window.document?.body?.innerHTML || trimmed;
  return turndown.turndown(body);
}

export async function fetchAndCache(url: string, cacheDir: string, force = false): Promise<FetchResult> {
  const path = cachePath(cacheDir, url);
  await mkdir(dirname(path), { recursive: true });

  if (!force && existsSync(path)) {
    try {
      const cached = JSON.parse(await readFile(path, "utf8")) as CachedFetch;
      return {
        markdown: fromHtml(cached.body),
        from_cache: true,
        status: cached.status,
        bytes: Buffer.byteLength(cached.body, "utf8"),
      };
    } catch {
      // fallback to network
    }
  }

  const response = await fetch(url);
  const body = await response.text();
  const cached: CachedFetch = {
    status: response.status,
    headers: Object.fromEntries(response.headers.entries()),
    body,
    fetched_at: new Date().toISOString(),
  };

  await writeFile(path, JSON.stringify(cached));
  return {
    markdown: fromHtml(body),
    from_cache: false,
    status: response.status,
    bytes: Buffer.byteLength(body, "utf8"),
  };
}
