"use client";

import { CheckCircle2Icon, CircleIcon, XIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { useOrganization } from "@/components/organization-provider";
import { useProject } from "@/components/project-provider";
import { api } from "@/lib/api";
import { Button, Card, CardContent, cn } from "@ai-search-growth-os/ui";

/**
 * First-run checklist on the workspace home. Every checkmark is derived
 * from data that actually exists (a crawl job, an audit, a prompt set, a
 * computed visibility score, a second member) — never from "the user
 * clicked through this step". Hides itself once everything is done;
 * dismissible earlier (a per-browser convenience, wrapped in try/catch).
 */

const DISMISS_KEY = "asg:getting-started-dismissed";

interface Step {
  key: string;
  label: string;
  description: string;
  href: string;
  done: boolean;
}

interface Signals {
  projectId: string;
  crawled: boolean;
  audited: boolean;
  prompts: boolean;
  measured: boolean;
  team: boolean;
}

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

export function GettingStarted() {
  const { current: project } = useProject();
  const { current: org } = useOrganization();
  const projectId = project?.id ?? null;
  const orgId = org?.id ?? null;

  const [signals, setSignals] = React.useState<Signals | null>(null);
  const [dismissed, setDismissed] = React.useState(readDismissed);

  React.useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    const settle = Promise.allSettled([
      api.crawl.list(projectId, 1),
      api.seo.listAudits(projectId, 1),
      api.prompts.listSets(projectId),
      api.visibility.overview(projectId, "30d"),
      orgId ? api.organizations.members(orgId) : Promise.resolve([]),
    ]);
    settle.then(([crawls, audits, sets, overview, members]) => {
      if (cancelled) return;
      // A failed call counts as "not done yet" — never as a crash.
      const total = (r: PromiseSettledResult<unknown>): number =>
        r.status === "fulfilled" ? ((r.value as { total?: number }).total ?? 0) : 0;
      setSignals({
        projectId,
        crawled: total(crawls) > 0,
        audited: total(audits) > 0,
        prompts: total(sets) > 0,
        measured:
          overview.status === "fulfilled" &&
          (overview.value as { current?: { score: number | null } }).current?.score != null,
        team:
          members.status === "fulfilled" && (members.value as unknown[]).length > 1,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, orgId]);

  if (dismissed) return null;

  const data = signals?.projectId === projectId ? signals : null;
  // Never flash a wrong count: with a project selected, wait for the real
  // signals before rendering anything.
  if (projectId && !data) return null;
  const steps: Step[] = [
    {
      key: "project",
      label: "Create a project",
      description: "One brand, one website.",
      href: "/app/projects",
      done: projectId != null,
    },
    {
      key: "crawl",
      label: "Crawl your website",
      description: "Fetch the pages AI engines see.",
      href: "/app/geo",
      done: data?.crawled ?? false,
    },
    {
      key: "audit",
      label: "Run a website audit",
      description: "Find what holds AI visibility back.",
      href: "/app/geo",
      done: data?.audited ?? false,
    },
    {
      key: "prompts",
      label: "Create your prompts",
      description: "The buyer questions to measure.",
      href: "/app/ai-visibility/prompts",
      done: data?.prompts ?? false,
    },
    {
      key: "measure",
      label: "Measure AI visibility",
      description: "Run the prompts against AI engines.",
      href: "/app/ai-visibility",
      done: data?.measured ?? false,
    },
    {
      key: "team",
      label: "Invite your team",
      description: "Work on it together.",
      href: "/app/settings",
      done: data?.team ?? false,
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  // All done (measured with real data): the card has served its purpose.
  if (projectId && data && doneCount === steps.length) return null;

  function dismiss() {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* per-browser convenience only */
    }
  }

  return (
    <Card className="mt-4 py-5">
      <CardContent className="px-5">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
            Getting started · {doneCount} of {steps.length}
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground -mr-2 h-7 px-2"
            onClick={dismiss}
          >
            <XIcon className="size-3.5" aria-hidden="true" />
            Dismiss
          </Button>
        </div>
        <ol className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
          {steps.map((step) => (
            <li key={step.key}>
              <Link
                href={step.href}
                className={cn(
                  "hover:bg-accent flex items-start gap-2 rounded-md px-2 py-2 text-sm transition-colors",
                  step.done && "opacity-70",
                )}
              >
                {step.done ? (
                  <CheckCircle2Icon
                    className="text-success mt-0.5 size-4 shrink-0"
                    aria-hidden="true"
                  />
                ) : (
                  <CircleIcon
                    className="text-muted-foreground mt-0.5 size-4 shrink-0"
                    aria-hidden="true"
                  />
                )}
                <span className="min-w-0">
                  <span className={cn("font-medium", step.done && "line-through")}>
                    {step.label}
                  </span>
                  <span className="text-muted-foreground block text-xs">{step.description}</span>
                  <span className="sr-only">{step.done ? " — done" : " — not done yet"}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
