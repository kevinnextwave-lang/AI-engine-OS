"use client";

import { ChevronDownIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { NAV_SECTIONS, isActive, sectionActive, type NavItem } from "@/components/shell/nav-items";
import { cn } from "@ai-search-growth-os/ui";

/**
 * Persisted section-collapse state, exposed through useSyncExternalStore so it
 * is hydration-safe: the server (and first client render) sees "nothing
 * collapsed", then the stored state applies. Storage failures (private mode)
 * simply mean the state doesn't persist.
 */
const COLLAPSE_KEY = "nav-collapsed-sections";
const NONE: string[] = [];
let cache: { raw: string | null; value: string[] } | null = null;
const listeners = new Set<() => void>();

function getCollapsed(): string[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(COLLAPSE_KEY);
  } catch {
    return cache?.value ?? NONE;
  }
  if (cache && cache.raw === raw) return cache.value;
  let value = NONE;
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) value = parsed.filter((v): v is string => typeof v === "string");
  } catch {
    value = NONE;
  }
  cache = { raw, value };
  return value;
}

function setCollapsed(next: string[]) {
  const raw = JSON.stringify(next);
  try {
    window.localStorage.setItem(COLLAPSE_KEY, raw);
  } catch {
    // Not persistable; still update in-memory state for this page.
  }
  cache = { raw, value: next };
  listeners.forEach((cb) => cb());
}

function subscribeCollapsed(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

export function NavLink({ item, active, onNavigate }: { item: NavItem; active: boolean; onNavigate?: () => void }) {
  const ref = React.useRef<HTMLAnchorElement>(null);
  // Keep the current page's item visible when landing deep in a long nav.
  // Scrolled manually (not scrollIntoView) so the browser's sequential-focus
  // starting point stays at the top of the page — otherwise the first Tab
  // would skip the "Skip to main content" link and start mid-sidebar.
  React.useEffect(() => {
    const el = ref.current;
    if (!active || !el) return;
    const scroller = el.closest<HTMLElement>(".overflow-y-auto");
    if (!scroller) return;
    const er = el.getBoundingClientRect();
    const sr = scroller.getBoundingClientRect();
    if (er.top < sr.top) scroller.scrollTop += er.top - sr.top;
    else if (er.bottom > sr.bottom) scroller.scrollTop += er.bottom - sr.bottom;
  }, [active]);
  return (
    <Link
      ref={ref}
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
          : "text-sidebar-foreground/75 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
      )}
    >
      <item.icon
        className={cn("size-4 shrink-0", active ? "" : "text-sidebar-foreground/50")}
        aria-hidden="true"
      />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

/**
 * Grouped, collapsible primary navigation.
 *
 * - Sections are product areas (see nav-items.ts); collapse state persists per
 *   browser and a section is always shown open while it contains the current
 *   page, so the active item can never be hidden.
 * - Visually quiet by design: neutral text, one soft accent tint for the
 *   active item, no colors beyond the sidebar tokens.
 */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const collapsed = React.useSyncExternalStore(subscribeCollapsed, getCollapsed, () => NONE);

  function toggle(label: string) {
    const next = collapsed.includes(label) ? collapsed.filter((l) => l !== label) : [...collapsed, label];
    setCollapsed(next);
  }

  return (
    <nav aria-label="Primary" className="flex flex-col px-3 py-2">
      {NAV_SECTIONS.map((section, i) => {
        const containsCurrent = sectionActive(pathname, section);
        const open = !section.label || !collapsed.includes(section.label) || containsCurrent;
        return (
          <div key={section.label ?? "workspace"} className={cn("flex flex-col gap-px", i > 0 && "mt-5")}>
            {section.label && (
              <button
                type="button"
                onClick={() => toggle(section.label!)}
                aria-expanded={open}
                className={cn(
                  "group/section mb-1 flex h-6 w-full items-center justify-between rounded px-2.5 text-[11px] font-medium tracking-wider uppercase transition-colors",
                  // ≥4.5:1 on the sidebar background (11px text needs AA small-text contrast)
                  "text-sidebar-foreground/70 hover:text-sidebar-foreground/90",
                )}
              >
                {section.label}
                <ChevronDownIcon
                  className={cn(
                    "size-3.5 opacity-0 transition-[transform,opacity] group-hover/section:opacity-100",
                    !open && "-rotate-90 opacity-100",
                  )}
                  aria-hidden="true"
                />
              </button>
            )}
            {/* Animated collapse: the grid-rows trick transitions height
                without measuring it. Items stay mounted; `inert` keeps the
                hidden links out of the tab order and the a11y tree. */}
            <div
              className={cn(
                "grid transition-[grid-template-rows] duration-200 ease-out",
                open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
              )}
              inert={!open}
            >
              <div className="flex flex-col gap-px overflow-hidden">
                {section.items.map((item) => (
                  <NavLink key={item.href} item={item} active={isActive(pathname, item)} onNavigate={onNavigate} />
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </nav>
  );
}
