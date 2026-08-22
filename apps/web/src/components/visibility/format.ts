import type { MetricUnit } from "@/lib/visibility/types";

export function fmtValue(value: number | null, unit: MetricUnit): string {
  if (value == null) return "–";
  if (unit === "percent") return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
  if (unit === "position") return `#${value.toFixed(1)}`;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function fmtChange(change: number | null, unit: MetricUnit): string {
  if (change == null) return "–";
  const sign = change > 0 ? "+" : "";
  const n = Number.isInteger(change) ? String(change) : change.toFixed(1);
  return unit === "percent" ? `${sign}${n} pts` : `${sign}${n}`;
}

export function fmtDateTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "–";
}

export function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "–";
}
