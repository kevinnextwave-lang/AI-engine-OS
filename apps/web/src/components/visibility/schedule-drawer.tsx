"use client";

/**
 * Recurring collection schedule for the project's runnable prompt set.
 * The server owns all the rules (plan cadences, provider validation, cost
 * controls at fire time); this drawer edits the row and repeats the server's
 * answer honestly — including the saved schedule's last_error, which is how
 * a user learns why last night's collection didn't happen.
 */

import { CalendarClockIcon } from "lucide-react";
import * as React from "react";

import { fmtDateTime } from "@/components/visibility/format";
import { api, ApiError } from "@/lib/api";
import type { PromptSchedule, ScheduleCadence } from "@ai-search-growth-os/types";
import {
  Button,
  Label,
  NativeSelect,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@ai-search-growth-os/ui";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

type FormState = {
  cadence: ScheduleCadence;
  weekday: number;
  hourUtc: number;
  providers: string[];
};

const DEFAULT_FORM: FormState = { cadence: "weekly", weekday: 0, hourUtc: 6, providers: [] };

function formFrom(schedule: PromptSchedule): FormState {
  return {
    cadence: schedule.cadence,
    weekday: schedule.weekday ?? 0,
    hourUtc: schedule.hour_utc,
    providers: schedule.providers,
  };
}

export function ScheduleDrawer({
  promptSetId,
  configuredProviders,
}: {
  promptSetId: string;
  /** Provider keys the deployment has credentials for. */
  configuredProviders: string[];
}) {
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [schedule, setSchedule] = React.useState<PromptSchedule | null>(null);
  const [form, setForm] = React.useState<FormState>(DEFAULT_FORM);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const openDrawer = () => {
    // Reset at the event, then load the current schedule (404 = none yet).
    setOpen(true);
    setLoading(true);
    setError(null);
    setNotice(null);
    setSchedule(null);
    setForm({ ...DEFAULT_FORM, providers: configuredProviders });
    api.prompts
      .getSchedule(promptSetId)
      .then((existing) => {
        setSchedule(existing);
        setForm(formFrom(existing));
      })
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 404)) {
          setError(err instanceof Error ? err.message : "Could not load the schedule.");
        }
      })
      .finally(() => setLoading(false));
  };

  const toggleProvider = (key: string) => {
    setForm((f) => ({
      ...f,
      providers: f.providers.includes(key)
        ? f.providers.filter((p) => p !== key)
        : [...f.providers, key],
    }));
  };

  const save = async (isActive: boolean) => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await api.prompts.saveSchedule(promptSetId, {
        cadence: form.cadence,
        hour_utc: form.hourUtc,
        weekday: form.cadence === "weekly" ? form.weekday : null,
        providers: form.providers,
        is_active: isActive,
      });
      setSchedule(saved);
      setForm(formFrom(saved));
      setNotice(
        saved.is_active
          ? `Saved. Next collection: ${fmtDateTime(saved.next_run_at)}.`
          : "Saved as paused — no collections will run.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the schedule.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.prompts.deleteSchedule(promptSetId);
      setSchedule(null);
      setForm({ ...DEFAULT_FORM, providers: configuredProviders });
      setNotice("Schedule removed. Collections are manual again.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the schedule.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Button variant="outline" size="sm" onClick={openDrawer}>
        <CalendarClockIcon aria-hidden="true" />
        Schedule
        {schedule?.is_active ? <span className="sr-only"> (on)</span> : null}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Scheduled collections</SheetTitle>
            <SheetDescription>
              Run this project&rsquo;s prompt set automatically so visibility scores stay
              current. Times are UTC; scheduled runs follow the same plan limits as manual
              ones.
            </SheetDescription>
          </SheetHeader>
          {loading ? (
            <p className="text-muted-foreground px-4 text-sm">Loading…</p>
          ) : (
            <div className="flex flex-col gap-4 px-4 pb-4">
              {schedule && (
                <div className="text-muted-foreground flex flex-col gap-1 text-sm">
                  <p>
                    Status:{" "}
                    <span className="text-foreground font-medium">
                      {schedule.is_active ? "on" : "paused"}
                    </span>
                    {schedule.is_active && <> · next run {fmtDateTime(schedule.next_run_at)}</>}
                  </p>
                  {schedule.last_run_at && <p>Last run {fmtDateTime(schedule.last_run_at)}.</p>}
                  {schedule.last_error && (
                    <p
                      role="status"
                      className="border-caution/40 bg-caution/10 text-foreground rounded-md border px-2 py-1"
                    >
                      Last attempt: {schedule.last_error}
                    </p>
                  )}
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="schedule-cadence">Frequency</Label>
                <NativeSelect
                  id="schedule-cadence"
                  value={form.cadence}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, cadence: e.target.value as ScheduleCadence }))
                  }
                >
                  <option value="weekly">Weekly</option>
                  <option value="daily">Daily</option>
                </NativeSelect>
              </div>
              {form.cadence === "weekly" && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="schedule-weekday">Day</Label>
                  <NativeSelect
                    id="schedule-weekday"
                    value={form.weekday}
                    onChange={(e) => setForm((f) => ({ ...f, weekday: Number(e.target.value) }))}
                  >
                    {WEEKDAYS.map((d, i) => (
                      <option key={d} value={i}>
                        {d}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="schedule-hour">Time (UTC)</Label>
                <NativeSelect
                  id="schedule-hour"
                  value={form.hourUtc}
                  onChange={(e) => setForm((f) => ({ ...f, hourUtc: Number(e.target.value) }))}
                >
                  {Array.from({ length: 24 }, (_, h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, "0")}:00
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm leading-none font-medium">AI engines</legend>
                {configuredProviders.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    No AI providers are configured on this deployment.
                  </p>
                ) : (
                  configuredProviders.map((key) => (
                    <label key={key} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="accent-primary size-4"
                        checked={form.providers.includes(key)}
                        onChange={() => toggleProvider(key)}
                      />
                      <span className="capitalize">{key}</span>
                    </label>
                  ))
                )}
              </fieldset>
              {error && (
                <p role="alert" className="text-destructive text-sm">
                  {error}
                </p>
              )}
              {notice && !error && (
                <p role="status" className="text-muted-foreground text-sm">
                  {notice}
                </p>
              )}
              <Separator />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  disabled={saving || form.providers.length === 0}
                  onClick={() => void save(true)}
                >
                  {saving ? "Saving…" : schedule ? "Save changes" : "Turn on"}
                </Button>
                {schedule?.is_active && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={saving}
                    onClick={() => void save(false)}
                  >
                    Pause
                  </Button>
                )}
                {schedule && (
                  <Button size="sm" variant="ghost" disabled={saving} onClick={() => void remove()}>
                    Remove
                  </Button>
                )}
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
