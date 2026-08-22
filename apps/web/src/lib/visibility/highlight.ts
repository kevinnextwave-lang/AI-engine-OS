/**
 * Splits a response into segments so the UI can highlight brand mentions,
 * competitors, citations and claims. Pure.
 *
 * Claims are sentences, so they form an outer layer; brand, competitor and
 * citation markers are applied inside (and outside) claim spans. Among inner
 * markers the longest match wins an overlap (a URL beats the brand name it
 * contains), then the kind order brand > competitor > citation.
 */

export type HighlightKind = "brand" | "competitor" | "citation" | "claim";

export interface Marker {
  kind: HighlightKind;
  /** Text to find (case-insensitive, all occurrences). */
  text: string;
  /** Tooltip. */
  title?: string;
}

export interface Segment {
  text: string;
  kind: HighlightKind | null;
  title?: string;
  /** Inner segments of a claim span. */
  children?: Segment[];
}

interface Hit {
  start: number;
  end: number;
  kind: HighlightKind;
  title?: string;
}

const INNER_PRIORITY: HighlightKind[] = ["brand", "competitor", "citation", "claim"];

function findAll(text: string, markers: Marker[]): Hit[] {
  const lower = text.toLowerCase();
  const hits: Hit[] = [];
  for (const m of markers) {
    const needle = m.text.trim().toLowerCase();
    if (needle.length < 2) continue;
    let from = 0;
    while (from < lower.length) {
      const i = lower.indexOf(needle, from);
      if (i < 0) break;
      hits.push({ start: i, end: i + needle.length, kind: m.kind, title: m.title });
      from = i + needle.length;
    }
  }
  return hits;
}

function nonOverlapping(hits: Hit[]): Hit[] {
  const sorted = [...hits].sort(
    (a, b) => b.end - b.start - (a.end - a.start) || INNER_PRIORITY.indexOf(a.kind) - INNER_PRIORITY.indexOf(b.kind) || a.start - b.start,
  );
  const kept: Hit[] = [];
  for (const h of sorted) {
    if (kept.every((k) => h.end <= k.start || h.start >= k.end)) kept.push(h);
  }
  return kept.sort((a, b) => a.start - b.start);
}

function split(text: string, hits: Hit[], inner?: (piece: string) => Segment[]): Segment[] {
  const out: Segment[] = [];
  let cursor = 0;
  const plain = (piece: string) => (inner ? out.push(...inner(piece)) : out.push({ text: piece, kind: null }));
  for (const h of hits) {
    if (h.start > cursor) plain(text.slice(cursor, h.start));
    const piece = text.slice(h.start, h.end);
    out.push({ text: piece, kind: h.kind, title: h.title, children: inner ? inner(piece) : undefined });
    cursor = h.end;
  }
  if (cursor < text.length) plain(text.slice(cursor));
  return out;
}

export function highlight(text: string, markers: Marker[]): Segment[] {
  const innerMarkers = markers.filter((m) => m.kind !== "claim");
  const claimMarkers = markers.filter((m) => m.kind === "claim");
  const innerOf = (piece: string) => split(piece, nonOverlapping(findAll(piece, innerMarkers)));
  return split(text, nonOverlapping(findAll(text, claimMarkers)), innerOf);
}
