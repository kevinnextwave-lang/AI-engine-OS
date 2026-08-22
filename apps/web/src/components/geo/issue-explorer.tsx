"use client";

import * as React from "react";

import { IssueDrawer } from "@/components/geo/issue-drawer";
import { IssueTable } from "@/components/geo/issue-table";
import { SEVERITY_LABEL, STATUS_LABEL } from "@/lib/geo/labels";
import { applyFilters, sortIssues } from "@/lib/geo/mappers";
import type { GeoIssue, IssueFilters, SortDirection, SortKey } from "@/lib/geo/types";
import type { ObservationStatus, Severity } from "@ai-search-growth-os/types";
import { Label, NativeSelect } from "@ai-search-growth-os/ui";

const DEFAULT_FILTERS: IssueFilters = { severity: "all", category: "all", status: "all", origin: "all" };

/**
 * Filter bar + sortable table + detail drawer. Filtering/sorting is delegated
 * to lib/geo/mappers; this component only holds UI state.
 */
export function IssueExplorer({
  issues,
  loading,
  busy,
  onUpdateStatus,
  showFilters = true,
  showOrigin = true,
  initialFilters,
  limit,
  emptyTitle,
  emptyDescription,
}: {
  issues: GeoIssue[];
  loading: boolean;
  busy: boolean;
  onUpdateStatus: (issue: GeoIssue, status: ObservationStatus, note?: string) => Promise<void>;
  showFilters?: boolean;
  showOrigin?: boolean;
  initialFilters?: Partial<IssueFilters>;
  limit?: number;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const [filters, setFilters] = React.useState<IssueFilters>({ ...DEFAULT_FILTERS, ...initialFilters });
  const [sortKey, setSortKey] = React.useState<SortKey>("severity");
  const [sortDir, setSortDir] = React.useState<SortDirection>("asc");
  const [openId, setOpenId] = React.useState<string | null>(null);

  const categories = React.useMemo(
    () => [...new Map(issues.map((i) => [i.categoryKey, i.category])).entries()].sort((a, b) => a[1].localeCompare(b[1])),
    [issues],
  );
  const visible = React.useMemo(() => {
    const rows = sortIssues(applyFilters(issues, filters), sortKey, sortDir);
    return limit ? rows.slice(0, limit) : rows;
  }, [issues, filters, sortKey, sortDir, limit]);
  const open = issues.find((i) => i.id === openId) ?? null;

  const onSort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };
  const set = <K extends keyof IssueFilters>(key: K, value: IssueFilters[K]) =>
    setFilters((f) => ({ ...f, [key]: value }));

  return (
    <div className="flex flex-col gap-3">
      {showFilters && (
        <div className="grid gap-3 sm:grid-cols-2 lg:flex lg:flex-wrap lg:items-end">
          <div className="flex flex-col gap-1">
            <Label htmlFor="f-severity" className="text-xs">Severity</Label>
            <NativeSelect id="f-severity" className="lg:w-40" value={filters.severity} onChange={(e) => set("severity", e.target.value as Severity | "all")}>
              <option value="all">All severities</option>
              {(Object.keys(SEVERITY_LABEL) as Severity[]).map((s) => (
                <option key={s} value={s}>{SEVERITY_LABEL[s]}</option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="f-category" className="text-xs">Category</Label>
            <NativeSelect id="f-category" className="lg:w-48" value={filters.category} onChange={(e) => set("category", e.target.value)}>
              <option value="all">All categories</option>
              {categories.map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="f-status" className="text-xs">Status</Label>
            <NativeSelect id="f-status" className="lg:w-36" value={filters.status} onChange={(e) => set("status", e.target.value as ObservationStatus | "all")}>
              <option value="all">All statuses</option>
              {(Object.keys(STATUS_LABEL) as ObservationStatus[]).map((s) => (
                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
              ))}
            </NativeSelect>
          </div>
          {showOrigin && (
            <div className="flex flex-col gap-1">
              <Label htmlFor="f-origin" className="text-xs">Source</Label>
              <NativeSelect id="f-origin" className="lg:w-40" value={filters.origin} onChange={(e) => set("origin", e.target.value as IssueFilters["origin"])}>
                <option value="all">All audits</option>
                <option value="technical_seo">Technical SEO</option>
                <option value="ai_readiness">AI readiness</option>
              </NativeSelect>
            </div>
          )}
          <p className="text-muted-foreground text-xs lg:ml-auto lg:pb-2">
            {loading ? "" : `${visible.length} of ${issues.length} observations`}
          </p>
        </div>
      )}
      <IssueTable issues={visible} loading={loading} sortKey={sortKey} sortDir={sortDir} onSort={onSort} onOpen={(i) => setOpenId(i.id)} emptyTitle={emptyTitle} emptyDescription={emptyDescription} />
      <IssueDrawer issue={open} onClose={() => setOpenId(null)} onUpdateStatus={onUpdateStatus} busy={busy} />
    </div>
  );
}
