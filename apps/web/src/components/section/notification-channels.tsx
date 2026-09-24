"use client";

import * as React from "react";

import { StatusBadge } from "@/components/section/primitives";
import { fmtDateTime } from "@/components/visibility/format";
import { api } from "@/lib/api";
import type { NotificationChannel } from "@ai-search-growth-os/types";
import {
  Button,
  Input,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  Skeleton,
} from "@ai-search-growth-os/ui";

/**
 * Webhook notification channel management for a project's competitive alerts.
 * Secrets are write-only: the API never returns them, so the UI only ever
 * shows whether one is set.
 */
export function NotificationChannelsSheet({
  projectId,
  open,
  onClose,
}: {
  projectId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [channels, setChannels] = React.useState<NotificationChannel[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [name, setName] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [secret, setSecret] = React.useState("");

  const load = React.useCallback(() => {
    if (!projectId) return;
    api.notificationChannels
      .list(projectId)
      .then((r) => {
        setChannels(r.items);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load channels"),
      );
  }, [projectId]);

  React.useEffect(() => {
    if (open) load();
  }, [open, load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const add = () =>
    act(async () => {
      if (!projectId) return;
      // Browser minLength checks pass for padded input; validate the trimmed
      // values the API will actually receive.
      if (name.trim().length < 2) throw new Error("Please enter a channel name (at least 2 characters).");
      if (secret.trim() && secret.trim().length < 8) throw new Error("The signing secret must be at least 8 characters.");
      await api.notificationChannels.create(projectId, {
        name: name.trim(),
        url: url.trim(),
        ...(secret.trim() ? { secret: secret.trim() } : {}),
      });
      setName("");
      setUrl("");
      setSecret("");
    });

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>Notification channels</SheetTitle>
          <SheetDescription>
            New competitive alerts are POSTed as JSON to each enabled webhook. Endpoints must be
            public HTTP(S); deliveries are signed (X-ASG-Signature) when a secret is set.
          </SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-5 px-4 pb-6">
          {error && <p className="text-destructive text-sm">{error}</p>}
          <form
            className="flex flex-col gap-2 rounded-lg border p-3"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <p className="text-sm font-medium">Add a webhook</p>
            <Input aria-label="Channel name" placeholder="Name, e.g. Ops Slack relay" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
            <Input aria-label="Webhook URL" placeholder="https://hooks.example.com/asg" value={url} onChange={(e) => setUrl(e.target.value)} required type="url" />
            <Input aria-label="Signing secret" placeholder="Signing secret (optional, min 8 chars)" value={secret} onChange={(e) => setSecret(e.target.value)} type="password" minLength={8} />
            <Button type="submit" size="sm" disabled={busy || !projectId} className="self-start">
              {busy ? "Saving…" : "Add channel"}
            </Button>
          </form>
          {!channels && !error && <Skeleton className="h-24 w-full" />}
          {channels && channels.length === 0 && (
            <p className="text-muted-foreground text-sm">No channels yet — alerts stay in the app only.</p>
          )}
          {channels?.map((c) => (
            <div key={c.id} className="flex flex-col gap-1.5 rounded-lg border p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium">{c.name}</p>
                <span className="flex items-center gap-1.5">
                  {c.has_secret && <StatusBadge value="signed" className="bg-muted text-muted-foreground" />}
                  <StatusBadge value={c.enabled ? "enabled" : "disabled"} />
                </span>
              </div>
              <p className="text-muted-foreground truncate" title={c.url}>
                {c.url}
              </p>
              {c.last_delivery_at && (
                <p className="text-muted-foreground text-xs">
                  Last delivery {fmtDateTime(c.last_delivery_at)} —{" "}
                  <span className={c.last_delivery_status === "failed" ? "text-destructive" : ""}>
                    {c.last_delivery_status}
                    {c.last_delivery_error ? `: ${c.last_delivery_error}` : ""}
                  </span>
                </p>
              )}
              <div className="mt-1 flex gap-1.5">
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => api.notificationChannels.test(c.id))}>
                  Send test
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void act(() => api.notificationChannels.update(c.id, { enabled: !c.enabled }))}
                >
                  {c.enabled ? "Disable" : "Enable"}
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => api.notificationChannels.remove(c.id))}>
                  Delete
                </Button>
              </div>
            </div>
          ))}
          <p className="text-muted-foreground text-xs">
            Internal hosts and private addresses are rejected, and every delivery re-checks the
            target with DNS resolution before connecting. A test delivery updates the channel&apos;s
            last-delivery status within a few seconds.
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
