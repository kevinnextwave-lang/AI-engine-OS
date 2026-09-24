"use client";

import * as React from "react";

/**
 * Renders an evidence payload (arbitrary JSON the engines attach to insights,
 * alerts, gaps, findings and proposed actions) as readable key/value rows.
 * Values are shown verbatim — evidence is never editorialised in the UI.
 */
export function EvidenceList({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence).filter(([, v]) => v !== null && v !== undefined);
  if (entries.length === 0) return <p className="text-muted-foreground text-sm">No evidence recorded.</p>;
  return (
    <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {entries.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt className="text-muted-foreground break-words">{k.replaceAll("_", " ")}</dt>
          <dd className="min-w-0 break-words tabular-nums">{formatValue(v)}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function formatValue(v: unknown): React.ReactNode {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x === "string" || typeof x === "number"))
      return v.length ? v.join(", ") : "—";
    return <Json value={v} />;
  }
  if (v && typeof v === "object") return <Json value={v} />;
  return String(v);
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="bg-muted/50 max-h-48 overflow-auto rounded-md p-2 text-xs whitespace-pre-wrap">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function DrawerSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{title}</h3>
      {children}
    </section>
  );
}
