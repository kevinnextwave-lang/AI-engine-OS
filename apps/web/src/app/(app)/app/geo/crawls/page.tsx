"use client";

import * as React from "react";

import { DataTable, StatusBadge, label } from "@/components/section/primitives";
import { SectionFrame, Toolbar } from "@/components/section/section-frame";
import { useProjectResource } from "@/components/section/use-project-resource";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { CrawlJob, CrawlJobListResponse, CrawlUrlListResponse } from "@ai-search-growth-os/types";
import {
  Button,
  Input,
  NativeSelect,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@ai-search-growth-os/ui";

const ACTIVE = new Set(["queued", "running"]);

function fmtDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function CrawlDrawer({ job, onClose, onChanged }: { job: CrawlJob | null; onClose: () => void; onChanged: () => void }) {
  return (
    <Sheet open={job !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-3xl">
        {job && <CrawlDrawerBody key={job.id} initial={job} onChanged={onChanged} />}
      </SheetContent>
    </Sheet>
  );
}

function CrawlDrawerBody({ initial, onChanged }: { initial: CrawlJob; onChanged: () => void }) {
  const [job, setJob] = React.useState<CrawlJob>(initial);
  const [pages, setPages] = React.useState<CrawlUrlListResponse | null>(null);
  const [urlStatus, setUrlStatus] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  // Monotonic token: a slow response from an earlier load (previous filter,
  // or a poll tick) must never overwrite a newer one.
  const loadSeq = React.useRef(0);
  const load = React.useCallback(() => {
    const seq = ++loadSeq.current;
    Promise.all([api.crawl.get(initial.id), api.crawl.pages(initial.id, { status: urlStatus || undefined })])
      .then(([j, p]) => {
        if (seq !== loadSeq.current) return;
        setJob(j);
        setPages(p);
        setError(null);
      })
      .catch((err: unknown) => {
        if (seq !== loadSeq.current) return;
        setError(err instanceof Error ? err.message : "Could not load crawl");
      });
  }, [initial.id, urlStatus]);

  React.useEffect(() => {
    load();
  }, [load]);

  React.useEffect(() => {
    if (!ACTIVE.has(job.status)) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [job.status, load]);

  const cancel = async () => {
    setBusy(true);
    try {
      const j = await api.crawl.cancel(job.id);
      setJob(j);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">
          <span className="truncate">{job.root_url}</span>
          <StatusBadge value={job.status} />
        </SheetTitle>
        <SheetDescription>
          {label(job.crawl_type)} crawl · {job.pages_crawled} crawled / {job.pages_discovered} discovered ·{" "}
          {job.pages_failed} failed · {job.pages_skipped} skipped · {fmtDuration(job.duration_seconds)}
        </SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-4 px-4 pb-6">
        {error && <p className="text-destructive text-sm">{error}</p>}
        {job.error_message && <p className="text-destructive text-sm">{job.error_message}</p>}
        {ACTIVE.has(job.status) && (
          <Button size="sm" variant="outline" onClick={() => void cancel()} disabled={busy} className="self-start">
            Cancel crawl
          </Button>
        )}
        <div className="flex items-center gap-2">
          <NativeSelect aria-label="URL status" value={urlStatus} onChange={(e) => setUrlStatus(e.target.value)} className="w-40">
            <option value="">All URLs</option>
            {["crawled", "failed", "skipped", "queued", "crawling", "discovered"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </NativeSelect>
          {pages && <span className="text-muted-foreground text-xs">{pages.total} URLs</span>}
        </div>
        {!pages && !error && <Skeleton className="h-40 w-full" />}
        {pages && (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>URL</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>HTTP</TableHead>
                  <TableHead>Depth</TableHead>
                  <TableHead>Outcome</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pages.items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-muted-foreground py-8 text-center text-sm">
                      No URLs with this status.
                    </TableCell>
                  </TableRow>
                ) : (
                  pages.items.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell className="max-w-md">
                        <p className="truncate font-medium" title={u.url}>
                          {u.url}
                        </p>
                        {u.page?.title && <p className="text-muted-foreground truncate text-xs">{u.page.title}</p>}
                      </TableCell>
                      <TableCell>
                        <StatusBadge value={u.status} />
                      </TableCell>
                      <TableCell className="tabular-nums">{u.http_status ?? "—"}</TableCell>
                      <TableCell className="tabular-nums">{u.depth}</TableCell>
                      <TableCell className="text-muted-foreground max-w-xs truncate text-xs" title={u.error_message ?? undefined}>
                        {u.error_message ?? (u.page?.word_count != null ? `${u.page.word_count} words` : "—")}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </>
  );
}

export default function CrawlsPage() {
  const res = useProjectResource<CrawlJobListResponse>(
    React.useCallback((pid) => api.crawl.list(pid, 50), []),
    { pollMs: 4000, isActive: (d) => d.items.some((j) => ACTIVE.has(j.status)) },
  );
  const [maxPages, setMaxPages] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<CrawlJob | null>(null);
  const d = res.data;

  const start = async () => {
    if (!res.projectId) return;
    setBusy(true);
    setNotice(null);
    try {
      // The input is outside a <form>, so its min=1 is never enforced by the
      // browser; clamp to a sane integer before sending.
      const pages = Math.floor(Number(maxPages));
      const job = await api.crawl.start(res.projectId, {
        crawl_type: "full",
        ...(Number.isFinite(pages) && pages >= 1 ? { max_pages: pages } : {}),
      });
      setOpen(job);
      res.refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not start the crawl");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionFrame
      title="Crawls"
      description="Safe, polite crawls of your own site: robots.txt respected, internal HTML pages only, per-host rate limits, an identifiable crawler user-agent, and hard protection against private addresses. Crawled pages feed the SEO, entity and agent analyses."
      projectId={res.projectId}
      projectLoading={res.projectLoading}
      error={res.error}
      onRetry={res.refresh}
      tools={
        <>
          <Input
            aria-label="Max pages"
            type="number"
            min={1}
            placeholder="Max pages (plan default)"
            value={maxPages}
            onChange={(e) => setMaxPages(e.target.value)}
            className="w-44"
          />
          <Button onClick={() => void start()} disabled={!res.projectId || busy}>
            {busy ? "Starting…" : "Start crawl"}
          </Button>
        </>
      }
    >
      {notice && <p className="text-destructive mb-3 text-sm">{notice}</p>}
      <Toolbar>
        <span className="text-muted-foreground text-xs">
          One crawl runs at a time per project; limits are capped by your plan.
        </span>
      </Toolbar>
      <DataTable
        head={["Root URL", "Type", "Status", "Crawled", "Failed", "Skipped", "Duration", "Started"]}
        loading={res.loading}
        empty={d && d.items.length === 0 ? "No crawls yet — start one to build your website intelligence." : null}
      >
        {(d?.items ?? []).map((j) => (
          <TableRow key={j.id} className="cursor-pointer" onClick={() => setOpen(j)}>
            <TableCell className="max-w-sm truncate font-medium" title={j.root_url}>
              {j.root_url}
            </TableCell>
            <TableCell className="text-sm">{label(j.crawl_type)}</TableCell>
            <TableCell>
              <StatusBadge value={j.status} />
            </TableCell>
            <TableCell className="tabular-nums">
              {j.pages_crawled}/{j.pages_discovered}
            </TableCell>
            <TableCell className="tabular-nums">{j.pages_failed}</TableCell>
            <TableCell className="tabular-nums">{j.pages_skipped}</TableCell>
            <TableCell className="tabular-nums">{fmtDuration(j.duration_seconds)}</TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {j.started_at ? fmtDateTime(j.started_at) : fmtDateTime(j.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </DataTable>
      <CrawlDrawer job={open} onClose={() => setOpen(null)} onChanged={res.refresh} />
    </SectionFrame>
  );
}
