"use client";

import { FolderKanbanIcon, SearchIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { useProject } from "@/components/project-provider";
import { NAV_SECTIONS, SETTINGS_ITEM } from "@/components/shell/nav-items";
import { Button, cn } from "@ai-search-growth-os/ui";

/**
 * Cmd/Ctrl-K palette: jump to any page, switch projects. No new
 * dependencies — a small accessible overlay (role=dialog, focus to the
 * input, Escape/backdrop to close, arrows + Enter to pick).
 */

interface Entry {
  kind: "page" | "project";
  id: string;
  label: string;
  hint: string;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" }>;
  run: () => void;
}

export function CommandPalette() {
  const router = useRouter();
  const { projects, current, select } = useProject();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);

  // Opening always starts from a clean slate; closing happens on pick,
  // Escape, backdrop, or the shortcut again — no state-syncing effects.
  const openPalette = React.useCallback(() => {
    setQuery("");
    setActive(0);
    setOpen(true);
  }, []);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => {
          if (!v) {
            setQuery("");
            setActive(0);
          }
          return !v;
        });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // DOM-only effect: focus the input once the dialog is in the tree.
  React.useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open]);

  const entries = React.useMemo<Entry[]>(() => {
    const pages: Entry[] = [];
    for (const section of NAV_SECTIONS) {
      for (const item of section.items) {
        pages.push({
          kind: "page",
          id: item.href,
          label: item.label,
          hint: section.label ?? "Workspace",
          icon: item.icon,
          run: () => router.push(item.href),
        });
      }
    }
    pages.push({
      kind: "page",
      id: SETTINGS_ITEM.href,
      label: SETTINGS_ITEM.label,
      hint: "Workspace",
      icon: SETTINGS_ITEM.icon,
      run: () => router.push(SETTINGS_ITEM.href),
    });
    const projectEntries: Entry[] = projects.map((p) => ({
      kind: "project",
      id: p.id,
      label: p.name,
      hint: p.id === current?.id ? "Project · selected" : "Switch project",
      icon: FolderKanbanIcon,
      run: () => select(p.id),
    }));
    return [...pages, ...projectEntries];
  }, [projects, current?.id, router, select]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? entries.filter((e) => `${e.label} ${e.hint}`.toLowerCase().includes(q))
    : entries;
  const activeIndex = Math.min(active, Math.max(filtered.length - 1, 0));

  function pick(entry: Entry) {
    setOpen(false);
    entry.run();
  }

  function onInputKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((v) => Math.min(v + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((v) => Math.max(v - 1, 0));
    } else if (e.key === "Enter" && filtered[activeIndex]) {
      e.preventDefault();
      pick(filtered[activeIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  // Keep the active option visible while arrowing.
  React.useEffect(() => {
    listRef.current
      ?.querySelector(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="text-muted-foreground hidden gap-2 font-normal md:inline-flex"
        onClick={openPalette}
      >
        <SearchIcon className="size-3.5" aria-hidden="true" />
        Go to…
        <kbd className="bg-muted text-muted-foreground rounded border px-1 font-mono text-[10px]">
          ⌘K
        </kbd>
      </Button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            className="bg-popover text-popover-foreground w-full max-w-lg overflow-hidden rounded-xl border shadow-lg"
          >
            <div className="flex items-center gap-2 border-b px-3">
              <SearchIcon className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
              <input
                ref={inputRef}
                role="combobox"
                aria-expanded="true"
                aria-controls="command-palette-list"
                aria-activedescendant={
                  filtered[activeIndex] ? `cp-${filtered[activeIndex].kind}-${activeIndex}` : undefined
                }
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                onKeyDown={onInputKey}
                placeholder="Jump to a page or project…"
                className="placeholder:text-muted-foreground h-11 w-full bg-transparent text-sm outline-none"
              />
            </div>
            <div
              id="command-palette-list"
              role="listbox"
              aria-label="Destinations"
              ref={listRef}
              className="max-h-[50vh] overflow-y-auto p-1.5"
            >
              {filtered.length === 0 ? (
                <p className="text-muted-foreground px-2.5 py-4 text-sm">No matches.</p>
              ) : (
                filtered.map((entry, i) => {
                  const Icon = entry.icon;
                  return (
                    <button
                      key={`${entry.kind}:${entry.id}`}
                      type="button"
                      id={`cp-${entry.kind}-${i}`}
                      data-index={i}
                      role="option"
                      aria-selected={i === activeIndex}
                      onMouseEnter={() => setActive(i)}
                      onClick={() => pick(entry)}
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm",
                        i === activeIndex && "bg-accent",
                      )}
                    >
                      <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
                      <span className="min-w-0 flex-1 truncate">{entry.label}</span>
                      <span className="text-muted-foreground shrink-0 text-xs">{entry.hint}</span>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
