"use client";

import { SearchIcon, XIcon } from "lucide-react";
import * as React from "react";

import { IssueDrawer } from "@/components/geo/issue-drawer";
import { IssueTable } from "@/components/geo/issue-table";
import { SEVERITY_LABEL, STATUS_LABEL } from "@/lib/geo/labels";
import { applyFilters, sortIssues } from "@/lib/geo/mappers";
import type { GeoIssue, IssueFilters, SortDirection, SortKey } from "@/lib/geo/types";
import type { ObservationStatus, Severity } from "@ai-search-growth-os/types";
import { Button, Input, Label, NativeSelect } from "@ai-search-growth-os/ui";

const DEFAULT_FILTERS: IssueFilters = { severity: "all", category: "all", status: "all", origin: "all", query: "" };
const PAGE_SIZE = 25;

/**
 * Search + filter bar, sortable paginated table, bulk triage, detail drawer.
 * Filtering/sorting is delegated to lib/geo/mappers; this component only
 * holds UI state. Bulk actions apply only to issues that support status
 * updates (technical SEO observations).
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
  /** Compact embed (overview): caps rows, hides filters/pagination/bulk. */
  limit?: number;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const [filters, setFilters] = React.useState<IssueFilters>({ ...DEFAULT_FILTERS, ...initialFilters });
  const [sortKey, setSortKey] = React.useState<SortKey>("severity");
  const [sortDir, setSortDir] = React.useState<SortDirection>("asc");
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(0);
  const [selectedIds, setSelectedIds] = React.useState<ReadonlySet<string>>(new Set());
  const [bulkBusy, setBulkBusy] = React.useState(false);

  const categories = React.useMemo(
    () => [...new Map(issues.map((i) => [i.categoryKey, i.category])).entries()].sort((a, b) => a[1].localeCompare(b[1])),
    [issues],
  );
  const filtered = React.useMemo(
    () => sortIssues(applyFilters(issues, filters), sortKey, sortDir),
    [issues, filters, sortKey, sortDir],
  );
  const pageCount = limit ? 1 : Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visible = React.useMemo(() => {
    if (limit) return filtered.slice(0, limit);
    return filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);
  }, [filtered, limit, safePage]);
  const open = issues.find((i) => i.id === openId) ?? null;
  const selected = React.useMemo(
    () => issues.filter((i) => selectedIds.has(i.id) && i.canUpdateStatus),
    [issues, selectedIds],
  );

  const onSort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };
  const set = <K extends keyof IssueFilters>(key: K, value: IssueFilters[K]) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(0);
  };
  const toggle = (issue: GeoIssue) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(issue.id)) next.delete(issue.id);
      else next.add(issue.id);
      return next;
    });
  const toggleAll = (triageable: GeoIssue[]) =>
    setSelectedIds((prev) => {
      const all = triageable.every((i) => prev.has(i.id));
      const next = new Set(prev);
      for (const i of triageable) {
        if (all) next.delete(i.id);
        else next.add(i.id);
      }
      return next;
    });

  const bulkSet = async (status: ObservationStatus) => {
    setBulkBusy(true);
    try {
      for (const issue of selected) {
        await onUpdateStatus(issue, status);
      }
      setSelectedIds(new Set());
    } finally {
      setBulkBusy(false);
    }
  };

  const bulkEnabled = showFilters && !limit;

  return (
    <div className="flex flex-col gap-3">
      {showFilters && (
        <div className="grid gap-3 sm:grid-cols-2 lg:flex lg:flex-wrap lg:items-end">
          <div className="flex flex-col gap-1">
            <Label htmlFor="f-query" className="text-xs">Search</Label>
            <div className="relative">
              <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" aria-hidden="true" />
              <Input
                id="f-query"
                value={filters.query}
                onChange={(e) => set("query", e.target.value)}
                placeholder="Search issues…"
                className="pl-8 lg:w-56"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="f-severity" className="text-xs">Severity</Label>
            <NativeSelect id="f-severity" className="lg:w-36" value={filters.severity} onChange={(e) => set("severity", e.target.value as Severity | "all")}>
              <option value="all">All severities</option>
              {(Object.keys(SEVERITY_LABEL) as Severity[]).map((s) => (
                <option key={s} value={s}>{SEVERITY_LABEL[s]}</option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="f-category" className="text-xs">Category</Label>
            <NativeSelect id="f-category" className="lg:w-44" value={filters.category} onChange={(e) => set("category", e.target.value)}>
              <option value="all">All categories</option>
              {categories.map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="f-status" className="text-xs">Status</Label>
            <NativeSelect id="f-status" className="lg:w-32" value={filters.status} onChange={(e) => set("status", e.target.value as ObservationStatus | "all")}>
              <option value="all">All statuses</option>
              {(Object.keys(STATUS_LABEL) as ObservationStatus[]).map((s) => (
                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
              ))}
            </NativeSelect>
          </div>
          {showOrigin && (
            <div className="flex flex-col gap-1">
              <Label htmlFor="f-origin" className="text-xs">Source</Label>
              <NativeSelect id="f-origin" className="lg:w-36" value={filters.origin} onChange={(e) => set("origin", e.target.value as IssueFilters["origin"])}>
                <option value="all">All audits</option>
                <option value="technical_seo">Technical SEO</option>
                <option value="ai_readiness">AI readiness</option>
              </NativeSelect>
            </div>
          )}
          <p className="text-muted-foreground text-xs lg:ml-auto lg:pb-2.5">
            {loading ? "" : `${filtered.length} of ${issues.length} observations`}
          </p>
        </div>
      )}

      {bulkEnabled && selected.length > 0 && (
        <div className="bg-muted/60 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2">
          <p className="text-sm font-medium">
            {selected.length} issue{selected.length === 1 ? "" : "s"} selected
          </p>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant="outline" disabled={bulkBusy || busy} onClick={() => void bulkSet("resolved")}>
              {bulkBusy ? "Updating…" : "Mark resolved"}
            </Button>
            <Button size="sm" variant="outline" disabled={bulkBusy || busy} onClick={() => void bulkSet("ignored")}>
              Ignore
            </Button>
            <Button size="sm" variant="outline" disabled={bulkBusy || busy} onClick={() => void bulkSet("open")}>
              Reopen
            </Button>
            <Button size="sm" variant="ghost" disabled={bulkBusy} onClick={() => setSelectedIds(new Set())} aria-label="Clear selection">
              <XIcon aria-hidden="true" />
            </Button>
          </div>
        </div>
      )}

      <IssueTable
        issues={visible}
        loading={loading}
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={onSort}
        onOpen={(i) => setOpenId(i.id)}
        selectable={bulkEnabled}
        selected={selectedIds}
        onToggle={toggle}
        onToggleAll={toggleAll}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
      />

      {!limit && !loading && pageCount > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-muted-foreground text-xs tabular-nums">
            {safePage * PAGE_SIZE + 1}–{Math.min((safePage + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
          </p>
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
              Previous
            </Button>
            <Button size="sm" variant="outline" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}>
              Next
            </Button>
          </div>
        </div>
      )}

      <IssueDrawer issue={open} onClose={() => setOpenId(null)} onUpdateStatus={onUpdateStatus} busy={busy} />
    </div>
  );
}
