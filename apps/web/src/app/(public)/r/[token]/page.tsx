"use client";

/**
 * Public read-only visibility report, served by a tokenized share link.
 * No auth, no app chrome. Follows the product's honesty rules: a score
 * without sample is "not enough data", never 0, and the page names the
 * window and generation time of every number it shows.
 */

import { useParams } from "next/navigation";
import * as React from "react";

import { api, ApiError } from "@/lib/api";
import type { PublicReport } from "@ai-search-growth-os/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@ai-search-growth-os/ui";

type State =
  | { kind: "loading" }
  | { kind: "done"; report: PublicReport }
  | { kind: "gone" }
  | { kind: "failed"; message: string };

function fmtScore(score: number | null | undefined): string {
  return score == null ? "–" : `${Math.round(score)}`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function TrendLine({ series }: { series: PublicReport["series"] }) {
  const points = series
    .map((p) => ({ score: typeof p.score === "number" ? p.score : null }))
    .filter((p): p is { score: number } => p.score !== null);
  if (points.length < 2) return null;
  const w = 560;
  const h = 80;
  const max = Math.max(...points.map((p) => p.score), 1);
  const min = Math.min(...points.map((p) => p.score), 0);
  const span = max - min || 1;
  const coords = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * (w - 8) + 4;
      const y = h - 6 - ((p.score - min) / span) * (h - 12);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label="Visibility score trend over the last 90 days"
      className="h-20 w-full"
    >
      <polyline
        points={coords}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="text-primary"
      />
    </svg>
  );
}

export default function PublicReportPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token;
  const [state, setState] = React.useState<State>({ kind: "loading" });

  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api.public
      .report(token)
      .then((report) => !cancelled && setState({ kind: "done", report }))
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setState({ kind: "gone" });
        else
          setState({
            kind: "failed",
            message: err instanceof Error ? err.message : "Could not load this report.",
          });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (state.kind === "loading") {
    return <p className="text-muted-foreground text-sm">Loading report…</p>;
  }
  if (state.kind === "gone") {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>This report link is no longer available</CardTitle>
          <CardDescription>
            It may have been revoked by the team that shared it. Ask them for a fresh link.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }
  if (state.kind === "failed") {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Could not load this report</CardTitle>
          <CardDescription>{state.message}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const { report } = state;
  const current = report.overview.current;
  const previous = report.overview.previous;
  const trend = report.overview.trend;
  const noData = current.score == null;
  return (
    <div className="flex w-full max-w-2xl flex-col gap-4 pb-10">
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">{report.project_name}</CardTitle>
          <CardDescription>
            AI search visibility, last 30 days · generated {fmtDate(report.generated_at)}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {noData ? (
            <p className="text-muted-foreground text-sm">
              Not enough collected responses in this window to report a score.
            </p>
          ) : (
            <div className="flex items-baseline gap-3">
              <span className="text-5xl font-semibold tabular-nums">
                {fmtScore(current.score)}
              </span>
              <span className="text-muted-foreground text-sm">/ 100 visibility score</span>
              {trend && previous.score != null && trend !== "flat" && (
                <span className="text-sm">
                  {trend === "up" ? "▲" : "▼"} from {fmtScore(previous.score)} the prior 30 days
                </span>
              )}
            </div>
          )}
          <p className="text-muted-foreground mt-2 text-xs">
            Based on {current.data_quality?.sample_size ?? 0} AI responses collected in the
            window.
          </p>
        </CardContent>
      </Card>

      {report.series.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">90-day trend</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendLine series={report.series} />
          </CardContent>
        </Card>
      )}

      {report.engines.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">By AI engine</CardTitle>
            <CardDescription>Score and sample per engine in the last 30 days.</CardDescription>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted-foreground border-b text-left text-xs uppercase">
                  <th className="py-1.5 pr-2 font-medium">Engine</th>
                  <th className="py-1.5 pr-2 font-medium">Score</th>
                  <th className="py-1.5 font-medium">Responses</th>
                </tr>
              </thead>
              <tbody>
                {report.engines.map((e) => (
                  <tr key={e.provider} className="border-b last:border-0">
                    <td className="py-1.5 pr-2 capitalize">{e.provider}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{fmtScore(e.score)}</td>
                    <td className="py-1.5 tabular-nums">{e.data_quality?.sample_size ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      <p className="text-muted-foreground text-center text-xs">
        Shared read-only report · numbers are measured from real AI engine responses, never
        estimated.
      </p>
    </div>
  );
}
