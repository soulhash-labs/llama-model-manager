import { getDbCapabilities } from "./index";
import type { SqlBackend } from "./adapter";

export interface SearchDoc {
  rank: number;
  chunk_id: string;
  doc_id: string;
  title: string;
  snippet: string;
  score: number;
  uri?: string;
}

interface RankedChunk {
  chunk_id: string;
  doc_id: string;
  h2_title: string;
  uri: string | null;
  content_md: string;
  score: number;
}

const RRF_K = 60;

function tokenize(query: string): string[] {
  return query
    .toLowerCase()
    .replace(/[^a-z0-9_\s]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 12);
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function snippetFromContent(content: string, query: string, maxLen = 220): string {
  const terms = tokenize(query);
  const hay = (content || "").toLowerCase();
  let best = -1;

  for (const term of terms) {
    const idx = hay.indexOf(term);
    if (idx >= 0 && (best < 0 || idx < best)) best = idx;
  }

  const start = best >= 0 ? Math.max(0, best - 55) : 0;
  const raw = (content || "").slice(start, start + maxLen);
  return raw.trim() || (content || "").slice(0, maxLen).trim();
}

function proximityBoost(content: string, terms: string[]): number {
  if (terms.length < 2) return 0;

  const lower = content.toLowerCase();
  const positions: number[][] = terms.map((term) => {
    const out: number[] = [];
    let cursor = 0;
    while (true) {
      const idx = lower.indexOf(term, cursor);
      if (idx < 0) break;
      out.push(idx);
      cursor = idx + term.length;
    }
    return out;
  });

  const anchors = positions[0] ?? [];
  if (!anchors.length) return 0;

  let best = Number.MAX_SAFE_INTEGER;
  for (const anchor of anchors) {
    let maxDistance = 0;
    let found = true;

    for (let i = 1; i < positions.length; i += 1) {
      const next = positions[i];
      let bestDelta = Number.MAX_SAFE_INTEGER;
      for (const p of next) {
        const delta = Math.abs(p - anchor);
        if (delta < bestDelta) bestDelta = delta;
      }
      if (bestDelta === Number.MAX_SAFE_INTEGER) {
        found = false;
        break;
      }
      maxDistance = Math.max(maxDistance, bestDelta);
    }

    if (found) best = Math.min(best, maxDistance);
  }

  if (best === Number.MAX_SAFE_INTEGER) return 0;
  return clamp01(1 - Math.min(1, best / 400));
}

function mergeRRF(porter: RankedChunk[], trigram: RankedChunk[]): Map<string, number> {
  const scores = new Map<string, number>();
  porter.forEach((row, idx) => {
    scores.set(row.chunk_id, (scores.get(row.chunk_id) ?? 0) + 1 / (RRF_K + idx + 1));
  });
  trigram.forEach((row, idx) => {
    scores.set(row.chunk_id, (scores.get(row.chunk_id) ?? 0) + 1 / (RRF_K + idx + 1));
  });
  return scores;
}

function levenshtein(a: string, b: string): number {
  const matrix = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i += 1) matrix[i][0] = i;
  for (let j = 0; j <= b.length; j += 1) matrix[0][j] = j;

  for (let i = 1; i <= a.length; i += 1) {
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      matrix[i][j] = Math.min(matrix[i - 1][j] + 1, matrix[i][j - 1] + 1, matrix[i - 1][j - 1] + cost);
    }
  }

  return matrix[a.length][b.length];
}

function typoSuggestions(db: SqlBackend, terms: string[]): string[] {
  if (!terms.length) return [];
  const rows = db.all<{ h2_title: string }>(`SELECT h2_title FROM chunks ORDER BY rowid DESC LIMIT 400`);
  const vocab = new Set<string>();
  for (const row of rows) {
    for (const token of tokenize(row.h2_title || "")) vocab.add(token);
  }

  const suggestions: string[] = [];
  for (const term of terms) {
    let bestWord = "";
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const candidate of vocab) {
      const distance = levenshtein(term, candidate);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestWord = candidate;
      }
    }
    if (bestWord && bestDistance <= 2) suggestions.push(bestWord);
  }

  return suggestions.slice(0, 5);
}

function substringFallback(
  db: SqlBackend,
  query: string,
  terms: string[],
  safeLimit: number,
  debug: Record<string, unknown>,
): { strategy: string; degraded: boolean; rows: SearchDoc[]; debug: Record<string, unknown> } {
  const like = `%${query.toLowerCase()}%`;
  const rows = db.all<{
    chunk_id: string;
    doc_id: string;
    h2_title: string;
    content_md: string;
    uri: string | null;
  }>(
    `SELECT c.chunk_id, c.doc_id, c.h2_title, c.content_md, d.uri
     FROM chunks c
     LEFT JOIN docs d ON d.doc_id = c.doc_id
     WHERE lower(c.content_md) LIKE :like OR lower(c.h2_title) LIKE :like
     LIMIT :limit`,
    { like, limit: safeLimit * 3 },
  );

  const scored = rows.map((row, idx) => {
    const lower = (row.content_md || "").toLowerCase();
    let score = 0;
    for (const token of terms) {
      let from = 0;
      while (from >= 0) {
        const found = lower.indexOf(token, from);
        if (found < 0) break;
        score += 1;
        from = found + token.length;
      }
    }
    score += proximityBoost(row.content_md, terms) - idx / 1_000;
    return {
      rank: 0,
      chunk_id: row.chunk_id,
      doc_id: row.doc_id,
      title: row.h2_title || "chunk",
      uri: row.uri || undefined,
      snippet: snippetFromContent(row.content_md, query),
      score,
    } as SearchDoc;
  });

  scored.sort((a, b) => b.score - a.score);
  const ranked = scored.slice(0, safeLimit).map((row, idx) => ({ ...row, rank: idx + 1 }));

  return {
    strategy: "substring_fallback",
    degraded: true,
    rows: ranked,
    debug: {
      ...debug,
      fallback: true,
      suggestions: typoSuggestions(db, terms),
    },
  };
}

export function searchChunks(
  db: SqlBackend,
  query: string,
  limit = 10,
): {
  strategy: "fts_porter" | "fts_trigram" | "rrf" | "substring" | "substring_fallback";
  degraded: boolean;
  rows: SearchDoc[];
  debug: Record<string, unknown>;
} {
  const safeLimit = Math.max(1, Math.min(50, Math.floor(limit)));
  const terms = tokenize(query);
  const caps = getDbCapabilities(db);

  const debug: Record<string, unknown> = {
    terms,
    degraded: caps.degraded,
  };

  if (!query.trim()) {
    return {
      strategy: caps.fts5 ? (caps.trigram ? "rrf" : "fts_porter") : "substring",
      degraded: caps.degraded,
      rows: [],
      debug,
    };
  }

  if (caps.fts5) {
    const ftsQuery = `${query.trim()}`;

    const porterRows = db.all<{
      chunk_id: string;
      doc_id: string;
      h2_title: string;
      content_md: string;
      uri: string | null;
      bm: number;
    }>(
      `SELECT c.chunk_id, c.doc_id, c.h2_title, c.content_md, d.uri,
              bm25(chunks_fts) as bm
       FROM chunks_fts f
       JOIN chunks c ON c.chunk_id = f.chunk_id
       JOIN docs d ON d.doc_id = c.doc_id
       WHERE chunks_fts MATCH :query
       LIMIT :limit`,
      { query: ftsQuery, limit: safeLimit * 3 },
    );

    const porter: RankedChunk[] = porterRows.map((row, idx) => ({
      chunk_id: row.chunk_id,
      doc_id: row.doc_id,
      h2_title: row.h2_title,
      uri: row.uri,
      content_md: row.content_md,
      score: -Number(row.bm) + 1 / (idx + 1),
    }));

    let trigramRows: RankedChunk[] = [];
    if (caps.trigram) {
      const trigRows = db.all<{
        chunk_id: string;
        doc_id: string;
        h2_title: string;
        content_md: string;
        uri: string | null;
        bm: number;
      }>(
        `SELECT c.chunk_id, c.doc_id, c.h2_title, c.content_md, d.uri,
                bm25(chunks_fts_trigram) as bm
         FROM chunks_fts_trigram f
         JOIN chunks c ON c.chunk_id = f.chunk_id
         JOIN docs d ON d.doc_id = c.doc_id
         WHERE chunks_fts_trigram MATCH :query
         LIMIT :limit`,
        { query: ftsQuery, limit: safeLimit * 3 },
      );

      trigramRows = trigRows.map((row, idx) => ({
        chunk_id: row.chunk_id,
        doc_id: row.doc_id,
        h2_title: row.h2_title,
        uri: row.uri,
        content_md: row.content_md,
        score: -Number(row.bm) + 1 / (idx + 1),
      }));
    }

    let merged = new Map<string, number>();
    if (caps.trigram) {
      merged = mergeRRF(porter, trigramRows);
    }

    const union = new Map<string, RankedChunk>();
    for (const row of [...porter, ...trigramRows]) {
      union.set(row.chunk_id, row);
    }

    const rows: SearchDoc[] = [];
    for (const [, row] of union) {
      const baseScore = caps.trigram ? (merged.get(row.chunk_id) ?? row.score) : row.score;
      const proximity = proximityBoost(row.content_md, terms);
      rows.push({
        rank: 0,
        chunk_id: row.chunk_id,
        doc_id: row.doc_id,
        title: row.h2_title,
        uri: row.uri || undefined,
        snippet: snippetFromContent(row.content_md, query),
        score: baseScore + proximity,
      });
    }

    rows.sort((a, b) => b.score - a.score);
    const ranked = rows.slice(0, safeLimit).map((row, idx) => ({ ...row, rank: idx + 1 }));

    // FTS zero-hit fallback: if FTS returned nothing, try substring
    if (ranked.length === 0 && terms.length > 0) {
      console.log("[SEARCH] FTS5 returned 0 hits → substring fallback");
      return substringFallback(db, query, terms, safeLimit, debug);
    }

    return {
      strategy: caps.trigram ? "rrf" : "fts_porter",
      degraded: false,
      rows: ranked,
      debug: {
        ...debug,
        counts: {
          porter: porter.length,
          trigram: trigramRows.length,
        },
      },
    };
  }

  // No FTS available: raw substring search
  const like = `%${query.toLowerCase()}%`;
  const rows = db.all<{
    chunk_id: string;
    doc_id: string;
    h2_title: string;
    content_md: string;
    uri: string | null;
  }>(
    `SELECT c.chunk_id, c.doc_id, c.h2_title, c.content_md, d.uri
     FROM chunks c
     LEFT JOIN docs d ON d.doc_id = c.doc_id
     WHERE lower(c.content_md) LIKE :like OR lower(c.h2_title) LIKE :like
     LIMIT :limit`,
    { like, limit: safeLimit * 3 },
  );

  const scored = rows.map((row, idx) => {
    const lower = (row.content_md || "").toLowerCase();
    let score = 0;
    for (const token of terms) {
      let from = 0;
      while (from >= 0) {
        const found = lower.indexOf(token, from);
        if (found < 0) break;
        score += 1;
        from = found + token.length;
      }
    }
    score += proximityBoost(row.content_md, terms) - idx / 1_000;
    return {
      rank: 0,
      chunk_id: row.chunk_id,
      doc_id: row.doc_id,
      title: row.h2_title || "chunk",
      uri: row.uri || undefined,
      snippet: snippetFromContent(row.content_md, query),
      score,
    } as SearchDoc;
  });

  scored.sort((a, b) => b.score - a.score);
  const ranked = scored.slice(0, safeLimit).map((row, idx) => ({ ...row, rank: idx + 1 }));

  return {
    strategy: "substring",
    degraded: true,
    rows: ranked,
    debug: {
      ...debug,
      suggestions: typoSuggestions(db, terms),
    },
  };
}
