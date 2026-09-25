"use client";

import { ArrowRightIcon, CheckIcon, FolderKanbanIcon } from "lucide-react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { useOrganization } from "@/components/organization-provider";
import { ProjectProvider, useProject } from "@/components/project-provider";
import { PageHeader } from "@/components/shell/page-header";
import {
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  Skeleton,
  cn,
} from "@ai-search-growth-os/ui";

/**
 * The workspace home. One question drives the layout: "where do I continue
 * working?" — so the current project and its two product entry points
 * dominate, the project list is one click away, and organization context
 * stays quiet at the bottom. Everything shown comes from data the app
 * already loads (auth, organization and project providers).
 */
export default function OverviewPage() {
  return (
    <ProjectProvider>
      <OverviewInner />
    </ProjectProvider>
  );
}

function OverviewInner() {
  const { user } = useAuth();
  const { current: org, organizations, loading: orgLoading, error: orgError } = useOrganization();
  const { projects, current, loading: projectsLoading, select } = useProject();
  const loading = orgLoading || projectsLoading;

  return (
    <>
      <PageHeader
        title={`Welcome${user?.full_name ? `, ${user.full_name}` : ""}`}
        description="Pick up where you left off: measure how AI engines see your brand, then fix what holds it back."
      />

      {orgError && <p className="text-destructive mb-4 text-sm">{orgError}</p>}

      {loading ? (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <Card className="py-5">
            <CardContent className="flex flex-col gap-3 px-5">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-7 w-56" />
              <Skeleton className="h-4 w-40" />
              <div className="mt-2 flex gap-2">
                <Skeleton className="h-9 w-40" />
                <Skeleton className="h-9 w-40" />
              </div>
            </CardContent>
          </Card>
          <Card className="py-5">
            <CardContent className="flex flex-col gap-3 px-5">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-full" />
            </CardContent>
          </Card>
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={FolderKanbanIcon}
          title="Create your first project"
          description="A project is one brand and website. Once it exists you can generate prompts, collect AI answers and audit the site — everything in the sidebar works on the selected project."
        >
          <Button asChild>
            <Link href="/app/projects">New project</Link>
          </Button>
        </EmptyState>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[2fr_1fr]">
          {/* The dominant thing: the project you're working on, and the two
              places work happens. */}
          <Card className="py-5">
            <CardContent className="px-5">
              <p className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
                Current project
              </p>
              {current ? (
                <>
                  <p className="mt-1.5 text-xl font-semibold tracking-tight">{current.name}</p>
                  <p className="text-muted-foreground mt-0.5 text-sm">
                    {current.primary_domain?.url ?? "No website configured"}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button asChild>
                      <Link href="/app/ai-visibility">
                        Open AI Visibility
                        <ArrowRightIcon aria-hidden="true" />
                      </Link>
                    </Button>
                    <Button asChild variant="outline">
                      <Link href="/app/geo">Website overview</Link>
                    </Button>
                  </div>
                </>
              ) : (
                <p className="text-muted-foreground mt-2 text-sm">
                  Select a project below to start working.
                </p>
              )}
            </CardContent>
          </Card>

          {/* One click to any other project; managing them stays on /app/projects. */}
          <Card className="py-5">
            <CardContent className="px-5">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-muted-foreground text-[11px] font-medium tracking-wider uppercase">
                  Your projects
                </p>
                <Link href="/app/projects" className="text-primary text-xs font-medium hover:underline">
                  Manage
                </Link>
              </div>
              <ul className="mt-2 flex flex-col">
                {projects.map((p) => {
                  const active = p.id === current?.id;
                  return (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => select(p.id)}
                        aria-pressed={active}
                        className={cn(
                          "hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                          active && "font-medium",
                        )}
                      >
                        <span className="min-w-0 truncate">{p.name}</span>
                        <span className="text-muted-foreground min-w-0 truncate text-xs">
                          {p.primary_domain?.url?.replace(/^https?:\/\//, "") ?? ""}
                        </span>
                        {active && <CheckIcon className="text-primary ml-auto size-4 shrink-0" aria-hidden="true" />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Organization context: present, quiet. */}
      {!loading && org && (
        <p className="text-muted-foreground mt-6 text-xs">
          Organization: <span className="text-foreground font-medium">{org.name}</span>{" "}
          <Badge variant="outline" className="ml-1 capitalize">{org.role}</Badge>
          {organizations.length > 1 && (
            <span> · one of {organizations.length} you belong to — switch in the sidebar</span>
          )}
        </p>
      )}
    </>
  );
}
