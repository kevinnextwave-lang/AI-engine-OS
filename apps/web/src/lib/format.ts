/**
 * The app's ONE set of date/time formatters. Domain modules
 * (components/visibility/format.ts, lib/geo/mappers.ts) re-export from here
 * so every screen prints timestamps the same way.
 *
 * Conventions:
 * - Missing values render as "–" (en dash) everywhere — never "n/a".
 * - Timestamps carry no seconds; they must fit a table cell untruncated.
 */

/** "Sep 22, 2026, 6:00 AM" */
export function fmtDateTime(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "–";
}

/** "Sep 22" — for chart axes and compact contexts within the current year.
 * Accepts an ISO string or an epoch-ms number (chart tick values). */
export function fmtDate(value: string | number | null): string {
  return value != null && value !== ""
    ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : "–";
}

/** "Sep 22, 2026" — when the day matters but the time doesn't. */
export function fmtDateFull(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : "–";
}

/** "12 min ago" / "3 h ago" / "2 d ago"; `emptyLabel` covers never-run cases. */
export function relativeTime(iso: string | null, emptyLabel = "not yet run"): string {
  if (!iso) return emptyLabel;
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}
