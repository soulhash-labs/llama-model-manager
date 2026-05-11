const MAX_CHUNK_CHARS = 12000;

export interface ParsedChunk {
  title: string;
  markdown: string;
}

function isCodeFence(line: string): boolean {
  return /^\s*```/.test(line);
}

function splitSections(lines: string[], headingPrefix: string): string[][] {
  const sections: string[][] = [];
  let current: string[] = [];
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

function splitLargeSection(lines: string[], h2Title: string): ParsedChunk[] {
  const raw = lines.join("\n").trim();
  if (raw.length <= MAX_CHUNK_CHARS) {
    return [{ title: h2Title, markdown: raw }];
  }

  const chunks: ParsedChunk[] = [];
  const h3Segments = splitSections(lines, "### ");

  if (h3Segments.length === 1) {
    let current: string[] = [];
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
      chunks.push({ title: `${h2Title} » ${subTitle}`, markdown: normalized });
      continue;
    }

    let current: string[] = [];
    let currentSize = 0;
    let part = 1;

    for (const line of segment) {
      if (currentSize + line.length + 1 > MAX_CHUNK_CHARS && current.length > 0) {
        chunks.push({ title: `${h2Title} » ${subTitle} (part ${part})`, markdown: current.join("\n").trim() });
        current = [line];
        currentSize = line.length;
        part += 1;
      } else {
        current.push(line);
        currentSize += line.length + 1;
      }
    }

    if (current.length) {
      chunks.push({ title: `${h2Title} » ${subTitle} (part ${part})`, markdown: current.join("\n").trim() });
    }
  }

  return chunks;
}

export function chunkMarkdownByHeadings(markdown: string): ParsedChunk[] {
  const trimmed = (markdown || "").trim();
  if (!trimmed) return [];

  const lines = trimmed.split(/\r?\n/);
  const h2Sections = splitSections(lines, "## ");

  const chunks: ParsedChunk[] = [];
  for (const section of h2Sections) {
    if (!section.length) continue;
    const titleLine = section.find((line) => line.startsWith("## ")) || "## Untitled";
    const h2Title = titleLine.replace(/^##\s+/, "");
    chunks.push(...splitLargeSection(section, h2Title));
  }

  return chunks;
}
