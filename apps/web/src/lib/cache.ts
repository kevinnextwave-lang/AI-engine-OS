"use client";

/**
 * Session-scoped stale-while-revalidate cache for the heavy project-scoped
 * loaders (GEO, visibility, intelligence).
 *
 * Contract:
 * - A remount (navigating between pages of a section) renders the cached
 *   snapshot instantly — no skeleton flash — and only refetches when the
 *   entry is older than its TTL, so section-internal navigation stops
 *   re-downloading everything.
 * - Explicit refresh() and mutations bypass/refresh the cache, so acting
 *   on data never shows stale results.
 * - The cache lives in module memory only: a full page load starts clean,
 *   nothing is persisted, and provenance (api vs mock) is cached along
 *   with the data so the MockNotice stays truthful.
 */

interface Entry {
  value: unknown;
  at: number;
}

const store = new Map<string, Entry>();

/** How long a snapshot may be served without a background refetch. */
export const CACHE_TTL_MS = 60_000;

export function readCache<T>(key: string): { value: T; ageMs: number } | null {
  const e = store.get(key);
  if (!e) return null;
  return { value: e.value as T, ageMs: Date.now() - e.at };
}

export function writeCache<T>(key: string, value: T): void {
  store.set(key, { value, at: Date.now() });
}

/** Drop every entry for a project (used after mutations that change many
 * datasets at once, e.g. running a new audit). */
export function invalidateProject(projectId: string): void {
  for (const key of store.keys()) {
    if (key.includes(projectId)) store.delete(key);
  }
}
