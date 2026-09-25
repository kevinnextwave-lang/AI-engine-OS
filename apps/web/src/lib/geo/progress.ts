/**
 * Live progress models for the GEO pipeline, built ONLY from what the
 * backend reports (crawl job counters, audit statuses — refreshed by the
 * 5-second poll in use-geo-data). Nothing here advances a step or invents a
 * percentage; a phase whose status the backend doesn't expose (e.g. entity
 * analysis, which has no status endpoint) simply is not listed.
 */

import type { AiReadinessAuditDetail, CrawlJob, SeoAudit } from "@ai-search-growth-os/types";
import type { ProgressStep } from "@ai-search-growth-os/ui";

export interface LiveProgress {
  title: string;
  steps: ProgressStep[];
  note: string;
}

function auditStep(label: string, status: string | null | undefined): ProgressStep | null {
  switch (status) {
    case "queued":
      return { label, status: "pending" };
    case "running":
      return { label, status: "active" };
    case "completed":
      return { label, status: "done" };
    case "failed":
      return { label, status: "failed" };
    default:
      return null;
  }
}

/**
 * Progress card for the Website Audit area. Returns null when nothing is
 * running — the card only exists while the backend reports activity.
 */
export function geoLiveProgress(
  job: CrawlJob | null,
  seoAudit: SeoAudit | null,
  readiness: AiReadinessAuditDetail | null,
): LiveProgress | null {
  const crawlActive = job?.status === "queued" || job?.status === "running";
  const seoActive = seoAudit?.status === "queued" || seoAudit?.status === "running";
  const readinessActive = readiness?.status === "queued" || readiness?.status === "running";

  if (crawlActive) {
    const counts = [
      `${job.pages_crawled} crawled`,
      `${job.pages_discovered} discovered`,
      ...(job.pages_failed > 0 ? [`${job.pages_failed} failed`] : []),
    ].join(" · ");
    return {
      title: "Crawling website",
      steps: [
        job.status === "queued"
          ? { label: "Waiting for a crawler worker", status: "active" }
          : { label: "Fetching and parsing pages", status: "active", detail: counts },
      ],
      note: "Counts come from the crawler and refresh automatically every few seconds.",
    };
  }

  if (seoActive || readinessActive) {
    const steps = [
      auditStep("Technical SEO audit", seoAudit?.status),
      auditStep("AI readiness audit", readiness?.status),
    ].filter((s): s is ProgressStep => s !== null);
    if (steps.length === 0) return null;
    return {
      title: "Running GEO audit",
      steps,
      note: "Statuses come from the audit jobs and refresh automatically; results appear when each audit completes.",
    };
  }

  return null;
}
