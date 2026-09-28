"use client";

/**
 * Manage public share links for the current project. The raw URL is shown
 * exactly once, at creation (the server stores only a hash) — the drawer
 * says so instead of pretending it could show it again later.
 */

import { Share2Icon } from "lucide-react";
import * as React from "react";

import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { ShareLink } from "@ai-search-growth-os/types";
import {
  Button,
  Input,
  Label,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@ai-search-growth-os/ui";

export function ShareDrawer({ projectId }: { projectId: string }) {
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [links, setLinks] = React.useState<ShareLink[]>([]);
  const [label, setLabel] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [freshUrl, setFreshUrl] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  const openDrawer = () => {
    setOpen(true);
    setLoading(true);
    setError(null);
    setFreshUrl(null);
    setCopied(false);
    api.shareLinks
      .list(projectId)
      .then(setLinks)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load share links."),
      )
      .finally(() => setLoading(false));
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    setFreshUrl(null);
    setCopied(false);
    try {
      const created = await api.shareLinks.create(projectId, {
        label: label.trim() || null,
      });
      setLabel("");
      setFreshUrl(`${window.location.origin}${created.url_path}`);
      setLinks((prev) => [created, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the link.");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (linkId: string) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.shareLinks.revoke(linkId);
      setLinks((prev) => prev.map((l) => (l.id === linkId ? updated : l)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke the link.");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!freshUrl) return;
    try {
      await navigator.clipboard.writeText(freshUrl);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const active = links.filter((l) => l.revoked_at === null);
  const revoked = links.filter((l) => l.revoked_at !== null);

  return (
    <>
      <Button variant="outline" size="sm" onClick={openDrawer}>
        <Share2Icon aria-hidden="true" />
        Share
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Share this report</SheetTitle>
            <SheetDescription>
              Create a read-only public link to this project&rsquo;s visibility report —
              scores, engines, and trend, never your prompts. Anyone with the link can view
              it until you revoke it.
            </SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-4 px-4 pb-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="share-label">Label (optional)</Label>
              <div className="flex gap-2">
                <Input
                  id="share-label"
                  value={label}
                  maxLength={100}
                  placeholder="e.g. Client monthly report"
                  onChange={(e) => setLabel(e.target.value)}
                />
                <Button size="sm" disabled={busy} onClick={() => void create()}>
                  Create link
                </Button>
              </div>
            </div>
            {freshUrl && (
              <div className="border-primary/40 bg-primary/5 flex flex-col gap-2 rounded-md border p-3">
                <p className="text-sm font-medium">Link created — copy it now.</p>
                <p className="text-muted-foreground text-xs">
                  For security only a hash is stored, so this URL cannot be shown again.
                </p>
                <div className="flex items-center gap-2">
                  <Input readOnly value={freshUrl} className="font-mono text-xs" />
                  <Button size="sm" variant="outline" onClick={() => void copy()}>
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
              </div>
            )}
            {error && (
              <p role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}
            <Separator />
            {loading ? (
              <p className="text-muted-foreground text-sm">Loading…</p>
            ) : links.length === 0 ? (
              <p className="text-muted-foreground text-sm">No share links yet.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {active.map((l) => (
                  <li
                    key={l.id}
                    className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium">{l.label ?? "Untitled link"}</p>
                      <p className="text-muted-foreground text-xs">
                        Created {fmtDateTime(l.created_at)}
                        {l.last_accessed_at
                          ? ` · last viewed ${fmtDateTime(l.last_accessed_at)}`
                          : " · never viewed"}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void revoke(l.id)}
                    >
                      Revoke
                    </Button>
                  </li>
                ))}
                {revoked.length > 0 && (
                  <li className="text-muted-foreground text-xs">
                    {revoked.length} revoked link{revoked.length !== 1 ? "s" : ""} (URLs are
                    dead).
                  </li>
                )}
              </ul>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
