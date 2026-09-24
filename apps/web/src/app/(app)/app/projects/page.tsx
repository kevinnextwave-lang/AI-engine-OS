"use client";

import { CheckIcon, FolderKanbanIcon, XIcon } from "lucide-react";
import * as React from "react";

import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/shell/page-header";
import { api } from "@/lib/api";
import type { Competitor, Project } from "@ai-search-growth-os/types";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Skeleton } from "@ai-search-growth-os/ui";

// Same key the section providers read, so "Use this project" selects it app-wide.
const STORAGE_KEY = "asg:current-project";

function readSelectedId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function CompetitorManager({ project }: { project: Project }) {
  const [competitors, setCompetitors] = React.useState<Competitor[] | null>(null);
  const [name, setName] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    api.projects.competitors
      .list(project.id)
      .then(setCompetitors)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load competitors"),
      );
  }, [project.id]);

  React.useEffect(() => {
    load();
  }, [load]);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Please enter the competitor's name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.projects.competitors.add(project.id, { name: trimmedName, website_url: url.trim() });
      setName("");
      setUrl("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add competitor");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (competitorId: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.projects.competitors.remove(project.id, competitorId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove competitor");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <p className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Competitors</p>
      {error && <p className="text-destructive text-xs">{error}</p>}
      {!competitors && !error && <Skeleton className="h-8 w-full" />}
      {competitors && competitors.length === 0 && (
        <p className="text-muted-foreground text-sm">None yet — add the brands AI answers compare you with.</p>
      )}
      {competitors && competitors.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {competitors.map((c) => (
            <li key={c.id}>
              <Badge variant="secondary" className="gap-1.5 pr-1">
                {c.name}
                <button
                  type="button"
                  aria-label={`Remove ${c.name}`}
                  onClick={() => void remove(c.id)}
                  disabled={busy}
                  className="hover:text-destructive rounded p-0.5"
                >
                  <XIcon className="size-3" aria-hidden="true" />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      )}
      <form className="flex flex-wrap gap-2" onSubmit={(e) => void add(e)}>
        <Input
          aria-label="Competitor name"
          placeholder="Name, e.g. QuickBooks"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          className="h-8 w-40 text-sm"
        />
        <Input
          aria-label="Competitor website"
          placeholder="https://quickbooks.intuit.com"
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          className="h-8 w-64 text-sm"
        />
        <Button type="submit" size="sm" variant="outline" disabled={busy} className="h-8">
          {busy ? "…" : "Add"}
        </Button>
      </form>
    </div>
  );
}

export default function ProjectsPage() {
  const { current: organization, loading: orgLoading, error: orgError } = useOrganization();
  // Keyed by organization so a slow response for org A can never overwrite
  // org B's list after a switch.
  const [loaded, setLoaded] = React.useState<{ orgId: string; items: Project[] } | null>(null);
  const projects = organization && loaded?.orgId === organization.id ? loaded.items : null;
  const [error, setError] = React.useState<string | null>(null);
  // SSR-safe read of the stored selection; select() overrides it for this render.
  const storedId = React.useSyncExternalStore(
    React.useCallback(() => () => {}, []),
    readSelectedId,
    () => null,
  );
  const [overrideId, setOverrideId] = React.useState<string | null>(null);
  const chosenId = overrideId ?? storedId;
  const [showForm, setShowForm] = React.useState(false);
  const [name, setName] = React.useState("");
  const [website, setWebsite] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    if (!organization) return;
    const orgId = organization.id;
    api.projects
      .list(orgId)
      .then((res) => {
        setLoaded({ orgId, items: res.items });
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load projects"),
      );
  }, [organization]);

  React.useEffect(() => {
    load();
  }, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!organization) return;
    const trimmedName = name.trim();
    if (trimmedName.length < 2) {
      // The browser's minLength check passes for whitespace-only input.
      setFormError("Please enter a project name (at least 2 characters).");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const project = await api.projects.create({
        name: trimmedName,
        website_url: website.trim(),
        organization_id: organization.id,
      });
      setName("");
      setWebsite("");
      setShowForm(false);
      select(project.id);
      load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not create the project");
    } finally {
      setBusy(false);
    }
  };

  const select = (id: string) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* selection still applies for this page */
    }
    setOverrideId(id);
  };

  return (
    <>
      <PageHeader
        title="Projects"
        description={
          organization
            ? `Brands and websites tracked by ${organization.name}.`
            : "Brands and websites you track."
        }
      >
        <Button onClick={() => setShowForm((s) => !s)} disabled={!organization}>
          {showForm ? "Cancel" : "New project"}
        </Button>
      </PageHeader>

      {showForm && (
        <form onSubmit={(e) => void create(e)} className="mb-6 flex flex-col gap-3 rounded-xl border p-4">
          <p className="font-medium">Create a project</p>
          <div className="flex flex-wrap gap-3">
            <Input
              aria-label="Project name"
              placeholder="Brand name, e.g. QuickTract"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              minLength={2}
              className="w-64"
            />
            <Input
              aria-label="Website URL"
              placeholder="https://www.quicktract.com"
              type="url"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
              required
              className="w-80"
            />
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create project"}
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">
            The website becomes the project&apos;s primary domain — crawls and audits stay within it.
          </p>
          {formError && <p className="text-destructive text-sm">{formError}</p>}
        </form>
      )}

      {(error ?? orgError) && <p className="text-destructive mb-4 text-sm">{error ?? orgError}</p>}
      {!orgLoading && !organization && !orgError && (
        <p className="text-muted-foreground text-sm">
          You don&apos;t belong to an organization yet, so there is nothing to show here.
        </p>
      )}
      {!projects && !error && !orgError && (orgLoading || organization) && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      )}
      {projects && projects.length === 0 && !showForm && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
          <FolderKanbanIcon className="text-muted-foreground mb-3 size-8" aria-hidden="true" />
          <p className="font-medium">No projects yet</p>
          <p className="text-muted-foreground mt-1 max-w-sm text-sm">
            A project groups one brand&apos;s domains, competitors and tracked prompts. Create your
            first one to unlock crawls, audits and AI visibility.
          </p>
          <Button className="mt-4" onClick={() => setShowForm(true)}>
            New project
          </Button>
        </div>
      )}
      <div className="flex flex-col gap-4">
        {/* Sections fall back to the first project when nothing (valid) is
            stored; mirror that here so the badge matches what pages use. */}
        {projects?.map((p, index) => {
          const isActive =
            chosenId != null && projects.some((x) => x.id === chosenId)
              ? p.id === chosenId
              : index === 0;
          return (
          <Card key={p.id}>
            <CardHeader className="pb-3">
              <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
                <span className="flex items-center gap-2">
                  {p.name}
                  {p.primary_domain && (
                    <span className="text-muted-foreground text-sm font-normal">
                      {p.primary_domain.hostname}
                    </span>
                  )}
                </span>
                {isActive ? (
                  <Badge variant="success" className="gap-1">
                    <CheckIcon className="size-3" aria-hidden="true" /> Active project
                  </Badge>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => select(p.id)}>
                    Use this project
                  </Button>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <CompetitorManager project={p} />
            </CardContent>
          </Card>
          );
        })}
      </div>
    </>
  );
}
