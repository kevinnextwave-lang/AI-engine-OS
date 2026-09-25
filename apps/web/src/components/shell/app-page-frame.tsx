"use client";

import * as React from "react";

import { MockNotice } from "@/components/geo/data-source-badge";
import { LoadError } from "@/components/shell/load-error";
import { PageHeader } from "@/components/shell/page-header";
import type { DataSource } from "@/lib/geo/types";

/**
 * THE page chrome: header (title, description, toolbar), the mock-data
 * notice, and the load-error branch. The domain frames (visibility,
 * intelligence, section) delegate here and contribute only what genuinely
 * differs between them — their empty-state semantics — via `gate`.
 */
export function AppPageFrame({
  title,
  description,
  tools,
  source,
  mockReason,
  error,
  errorWhat,
  onRetry,
  gate,
  children,
}: {
  title: string;
  description: string;
  /** Header toolbar (project select, provenance badge, window pills…). */
  tools?: React.ReactNode;
  /** When set, a MockNotice explains mock provenance under the header. */
  source?: DataSource;
  mockReason?: string | null;
  error?: string | null;
  /** Names what failed in the error box, e.g. "AI visibility data". */
  errorWhat?: string;
  onRetry?: () => void;
  /** Domain pre-empt: rendered INSTEAD of children when non-null
   * (a project gate, a no-measurements empty state, …). */
  gate?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <>
      <PageHeader title={title} description={description}>
        {tools}
      </PageHeader>
      {source && <MockNotice source={source} reason={mockReason ?? null} />}
      {error != null && onRetry ? (
        <LoadError what={errorWhat ?? title.toLowerCase()} message={error} onRetry={onRetry} />
      ) : (
        (gate ?? children)
      )}
    </>
  );
}
